# ============================================================================
#  AnimeDL Manga Engine — Telegram front-end (/manga)
# ============================================================================
#  /manga <query> → aggregated search (MangaDex · Comick · Asura)
#    → 📖 pick series → chapter pages (newest first)
#    → 📄 PDF / 📚 CBZ → pages fetched (live progress) → document sent here.
#
#  Output files carry the AnimeDL caption; the engine itself was rebuilt from
#  three reference bots and hardened (per-image retry, bounded memory PDFs,
#  STORED-entries CBZ, per-provider error tolerance).
# ============================================================================

import asyncio
import logging
import re
import time
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import uikit
from config import VERSION
from cantarella.telegram.decorators import check_ban

logger = logging.getLogger(__name__)

user_manga = {}          # user_id -> state dict
_busy = set()            # user_ids with a download running
TMP = Path("/tmp/animedl/manga")

PAGE_SIZE = 10           # chapters per page


def _search_state(user_id):
    return (user_manga.get(user_id) or {}).get("results") or []


async def _premium_ok(user_id: int) -> bool:
    """💎 premium check — tolerant when mongo is unreachable."""
    try:
        from cantarella.core.database import db
        return bool(await db.is_premium(user_id))
    except Exception:
        return False


async def _nsfw_allowed(user_id: int) -> bool:
    """18+ sources need: operator env ON + user premium + user opted in."""
    try:
        from manga_sources.nsfw import nsfw_enabled
        if not nsfw_enabled():
            return False
    except Exception:
        return False
    if not await _premium_ok(user_id):
        return False
    try:
        from cantarella.core.database import db
        return bool(await db.get_user_setting(user_id, "show_nsfw", False))
    except Exception:
        return False


async def _default_fmt(user_id: int) -> str:
    try:
        from cantarella.core.database import db
        fmt = await db.get_user_setting(user_id, "manga_format", "pdf")
        return "cbz" if fmt == "cbz" else "pdf"
    except Exception:
        return "pdf"


# short provider badges for buttons / captions (richgram-style chips)
_BADGES = {
    "mangadex": "ᴍᴅx", "comick": "ᴄᴋ", "asura": "ᴀꜱ", "weebcentral": "ᴡᴄ",
    "mgeko": "ᴍɢ", "manhuafast": "ᴍꜰ", "manhuaplus": "ᴍᴘ", "templetoons": "ᴛᴛ",
    "mangakakalot": "ᴍᴋ", "mangasee": "ᴍꜱ", "mangabuddy": "ᴍʙ", "ninemanga": "ɴᴍ",
    "manhwaclan": "18ᴄ", "manga18fx": "18x", "manhwa18": "18",
}
RES_PAGE = 8               # series results per page


def _badge(pid: str) -> str:
    return _BADGES.get(pid, pid[:3])


async def _render_results(msg, user_id: int, page: int = 0):
    """Series result card — uikit bar + per-source chips + numbered buttons."""
    state = user_manga.get(user_id) or {}
    results = state.get("results") or []
    tried = state.get("tried") or []
    pages = max(1, (len(results) + RES_PAGE - 1) // RES_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = results[page * RES_PAGE:(page + 1) * RES_PAGE]

    online = sum(1 for _, o in tried if isinstance(o, int) and o)
    chips = " · ".join(
        f"{_badge(p)} {o if isinstance(o, int) and o else '⚠️'}"
        for p, o in tried)
    text = (
        "<blockquote>📖 <b>ᴍᴀɴɢᴀ ꜰᴏᴜɴᴅ</b> — “" + (state.get("query") or "")[:32]
        + "” · " + str(len(results)) + " ʀᴇꜱᴜʟᴛꜱ</blockquote>" + "\n"
        "<blockquote expandable>🟢 ꜱᴏᴜʀᴄᴇꜱ: <b>" + str(online) + "/"
        + str(len(tried)) + "</b> ᴀɴꜱᴡᴇʀᴇᴅ\n"
        "<code>" + uikit.bar(100.0 * online / max(1, len(tried)), 12)
        + "</code>\n" + chips + "</blockquote>" + "\n"
        "<i>ᴛᴀᴘ ᴀ ꜱᴇʀɪᴇꜱ → ᴄʜᴀᴘᴛᴇʀꜱ · ᴘᴀɢᴇ " + str(page + 1) + "/"
        + str(pages) + "</i>")

    buttons = []
    for j, r in enumerate(chunk):
        idx = page * RES_PAGE + j
        label = f"{idx + 1}· {r.title[:28]}  {_badge(r.provider)}"
        buttons.append([InlineKeyboardButton(
            label, callback_data=f"mgp_{r.provider}_{idx}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"mgsl_{page - 1}"))
    nav.append(InlineKeyboardButton(
        f"▼ {page + 1}/{pages}", callback_data="mgnoop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"mgsl_{page + 1}"))
    buttons.append(nav)
    buttons.append([
        InlineKeyboardButton("🔄 ɴᴇᴡ ꜱᴇᴀʀᴄʜ", callback_data="mgnew"),
        InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ", callback_data="mgx"),
    ])
    markup = InlineKeyboardMarkup(buttons)
    try:
        await msg.edit_message_caption(caption=text, reply_markup=markup,
                                       parse_mode=ParseMode.HTML)
    except MessageNotModified:
        pass
    except Exception:
        try:
            await msg.edit_text(text, reply_markup=markup,
                                parse_mode=ParseMode.HTML)
        except MessageNotModified:
            pass
        except Exception:
            pass


# ─────────────────────────────────────────────
#  /manga — search
# ─────────────────────────────────────────────
class _MsgView:
    """Adapts a plain Message to the edit surface the renderers expect."""

    def __init__(self, m):
        self.message = m

    async def edit_message_caption(self, caption=None, reply_markup=None, **k):
        try:
            return await self.message.edit_text(caption, reply_markup=reply_markup, **k)
        except MessageNotModified:
            raise
        except Exception:
            return None

    async def edit_message_text(self, text=None, reply_markup=None, **k):
        return await self.message.edit_text(text, reply_markup=reply_markup, **k)


@Client.on_message(filters.private & filters.command("mrandom"))
@check_ban
async def mrandom_cmd(client: Client, message):
    """One random SFW series, straight to its chapters."""
    uid = message.from_user.id
    if uid in _busy:
        return await message.reply(
            "<blockquote>⏳ ꜰɪɴɪꜱʜ ʏᴏᴜʀ ᴄᴜʀʀᴇɴᴛ ᴄʜᴀᴘᴛᴇʀ ꜰɪʀꜱᴛ.</blockquote>",
            parse_mode=ParseMode.HTML)
    status = await message.reply(
        "<blockquote>🎲 ᴘɪᴄᴋɪɴɢ ᴀ ʀᴀɴᴅᴏᴍ ꜱᴇʀɪᴇꜱ ꜰᴏʀ ʏᴏᴜ…</blockquote>",
        parse_mode=ParseMode.HTML)

    def _pick():
        from manga_sources import get_provider
        return get_provider("mangadex").random_sfw()

    try:
        manga = await asyncio.get_event_loop().run_in_executor(None, _pick)
    except Exception as e:
        return await _safe_edit(status, "<blockquote>❌ ᴘɪᴄᴋ ꜰᴀɪʟᴇᴅ: "
                                + str(e)[:140] + "</blockquote>")

    key = "mangadex_0"
    user_manga[uid] = {"query": "🎲 random", "results": [manga],
                       "mangas": {key: manga}, "chapters": {},
                       "pref_fmt": await _default_fmt(uid),
                       "tried": [("mangadex", 1)]}
    await _safe_edit(status, "<blockquote>🎲 <b>" + manga.title[:40]
                     + "</b> — ʟᴏᴀᴅɪɴɢ ᴄʜᴀᴘᴛᴇʀꜱ…</blockquote>")

    def _ch():
        from manga_sources import get_provider
        return get_provider("mangadex").chapters(manga.id)

    try:
        chapters = await asyncio.get_event_loop().run_in_executor(None, _ch)
    except Exception as e:
        user_manga.pop(uid, None)
        return await _safe_edit(status, "<blockquote>❌ ᴄʜᴀᴘᴛᴇʀꜱ ꜰᴀɪʟᴇᴅ: "
                                + str(e)[:140] + "</blockquote>")
    if not chapters:
        user_manga.pop(uid, None)
        return await _safe_edit(status,
            "<blockquote>❌ ɴᴏ ᴇɴɢʟɪꜱʜ ᴄʜᴀᴘᴛᴇʀꜱ — ʀᴏʟʟ ᴀɢᴀɪɴ: /mrandom</blockquote>")
    user_manga[uid]["chapters"][key] = chapters
    await _render_chapters(_MsgView(status), uid, key, 0)


@Client.on_message(filters.private & filters.command("manga"))
@check_ban
async def manga_search_cmd(client: Client, message):
    uid = message.from_user.id
    query = (message.text or "").split(None, 1)[1].strip() if len((message.text or "").split()) > 1 else ""
    if not query:
        return await message.reply(
            "<blockquote>📖 <b>ᴍᴀɴɢᴀ ꜱᴇᴀʀᴄʜ</b>\n\n"
            "ᴜꜱᴀɢᴇ: <code>/manga solo leveling</code>\n\n"
            "ꜱᴏᴜʀᴄᴇꜱ: ᴍᴀɴɢᴀᴅᴇx · ᴄᴏᴍɪᴄᴋ · ᴀꜱᴜʀᴀ · ᴡᴇᴇʙᴄᴇɴᴛʀᴀʟ · ᴍɢᴇᴋᴏ + 7 ᴍᴏʀᴇ\n"
            "🎲 /mrandom — ꜱᴜʀᴘʀɪꜱᴇ ꜱᴇʀɪᴇꜱ · ᴏᴜᴛᴘᴜᴛ: 📄 ᴘᴅꜰ / 📚 ᴄʙᴢ</blockquote>",
            parse_mode=ParseMode.HTML)

    include_nsfw = await _nsfw_allowed(uid)
    pref_fmt = await _default_fmt(uid)
    status = await message.reply(
        f"<blockquote>🔎 ꜱᴇᴀʀᴄʜɪɴɢ <b>{query[:40]}</b> ᴏɴ 12 ꜱᴏᴜʀᴄᴇꜱ"
        + (" + 🔞" if include_nsfw else "") + "…</blockquote>",
        parse_mode=ParseMode.HTML)

    def _work():
        from manga_sources import search_all
        return search_all(query, nsfw=include_nsfw)

    try:
        results, tried = await asyncio.get_event_loop().run_in_executor(None, _work)
    except Exception as e:
        return await status.edit_text(
            f"<blockquote>❌ ꜱᴇᴀʀᴄʜ ꜰᴀɪʟᴇᴅ: {e}</blockquote>", parse_mode=ParseMode.HTML)

    user_manga[message.from_user.id] = {
        "query": query, "results": results, "mangas": {}, "chapters": {},
        "pref_fmt": pref_fmt, "tried": tried,
    }
    if not results:
        online = sum(1 for _, o in tried if isinstance(o, int) and o)
        chips = " · ".join(
            f"{_badge(p)} {o if isinstance(o, int) and o else '⚠️'}"
            for p, o in tried)
        return await status.edit_text(
            f"<blockquote>❌ ɴᴏ ᴍᴀɴɢᴀ ꜰᴏᴜɴᴅ ꜰᴏʀ <b>{query[:40]}</b></blockquote>\n"
            f"<blockquote expandable>🟢 {online}/{len(tried)} ꜱᴏᴜʀᴄᴇꜱ ᴀɴꜱᴡᴇʀᴇᴅ\n{chips}\n"
            f"ᴛʀʏ ᴀɴᴏᴛʜᴇʀ ᴛɪᴛʟᴇ ᴏʀ /manga ᴀɢᴀɪɴ</blockquote>",
            parse_mode=ParseMode.HTML)

    await _render_results(status, message.from_user.id, 0)


# ─────────────────────────────────────────────
#  series picked → chapters
# ─────────────────────────────────────────────
@Client.on_callback_query(filters.regex(r"^mgp_([a-z]+)_(\d+)$"))
async def on_manga_pick(client: Client, cq):
    user_id = cq.from_user.id
    state = user_manga.get(user_id)
    if not state:
        return await cq.answer("❌ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ — /manga ᴀɢᴀɪɴ.", show_alert=True)
    _m = re.match(r"^mgp_([a-z]+)_(\d+)$", cq.data or "")
    if not _m:
        return await cq.answer()
    pid, idx = _m.group(1), int(_m.group(2))
    results = state.get("results") or []
    if idx >= len(results):
        return await cq.answer("❌ ꜱᴛᴀʟᴇ ʟɪɴᴋ.", show_alert=True)
    manga = results[idx]
    from manga_sources import NSFW_IDS
    if manga.provider in NSFW_IDS and not await _premium_ok(user_id):
        return await cq.answer(
            "🔒 18+ ꜱᴏᴜʀᴄᴇ — 💎 ᴘʀᴇᴍɪᴜᴍ ʀᴇǫᴜɪʀᴇᴅ (/premium).", show_alert=True)

    await cq.answer("📚 ʟᴏᴀᴅɪɴɢ ᴄʜᴀᴘᴛᴇʀꜱ…")
    try:
        await cq.edit_message_caption(
            caption=f"<blockquote>📚 ʟᴏᴀᴅɪɴɢ ᴄʜᴀᴘᴛᴇʀꜱ ᴏꜰ <b>{manga.title[:40]}</b>…</blockquote>",
            parse_mode=ParseMode.HTML)
    except Exception:
        pass

    def _work():
        from manga_sources import get_provider, CHAPTERS_ARG
        prov = get_provider(pid)
        arg = getattr(manga, CHAPTERS_ARG.get(pid, "id"))
        return prov.chapters(arg)

    try:
        chapters = await asyncio.get_event_loop().run_in_executor(None, _work)
    except Exception as e:
        return await cq.edit_message_caption(
            f"<blockquote>❌ ᴄʜᴀᴘᴛᴇʀ ʟɪꜱᴛ ꜰᴀɪʟᴇᴅ: {e}</blockquote>",
            parse_mode=ParseMode.HTML)
    if not chapters:
        return await cq.edit_message_caption(
            "<blockquote>❌ ɴᴏ ᴄʜᴀᴘᴛᴇʀꜱ ꜰᴏᴜɴᴅ ᴏɴ ᴛʜɪꜱ ꜱᴏᴜʀᴄᴇ.</blockquote>",
            parse_mode=ParseMode.HTML)

    key = f"{pid}_{idx}"
    state["mangas"][key] = manga
    state["chapters"][key] = chapters
    await _render_chapters(cq, user_id, key, 0)


async def _render_chapters(cq, user_id, key, page):
    state = user_manga[user_id]
    chapters = state["chapters"][key]
    manga = state["mangas"][key]
    pages = max(1, (len(chapters) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = chapters[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    buttons = []
    pref = state.get("pref_fmt")
    for j, ch in enumerate(chunk):
        label = f"📑 Ch {ch.number}" + (f" · {ch.title[:22]}" if ch.title else "")
        if pref in ("pdf", "cbz"):
            alt = "pdf" if pref == "cbz" else "cbz"
            buttons.append([
                InlineKeyboardButton(label[:52], callback_data=f"mgi_{key}_{page}_{j}"),
                InlineKeyboardButton(f"⬇️ {pref.upper()}", callback_data=f"mgd_{key}_{page}_{j}_{pref}"),
                InlineKeyboardButton("📄" if alt == "pdf" else "📚", callback_data=f"mgd_{key}_{page}_{j}_{alt}"),
            ])
        else:
            buttons.append([
                InlineKeyboardButton(label[:52], callback_data=f"mgi_{key}_{page}_{j}"),
                InlineKeyboardButton("📄", callback_data=f"mgd_{key}_{page}_{j}_pdf"),
                InlineKeyboardButton("📚", callback_data=f"mgd_{key}_{page}_{j}_cbz"),
            ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"mgc_{key}_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data="mgnoop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"mgc_{key}_{page+1}"))
    buttons.append(nav)
    buttons.append([
        InlineKeyboardButton("🔙 ꜱᴇᴀʀᴄʜ", callback_data="mgback"),
        InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ", callback_data="mgx"),
    ])

    text = (f"<blockquote>📚 <b>{manga.title[:40]}</b> "
            f"<i>· {_badge(key.split('_', 1)[0])}</i>\n"
            f"ᴄʜᴀᴘᴛᴇʀꜱ: {len(chapters)} · ᴛᴀᴘ ᴀ ᴄʜᴀᴘᴛᴇʀ → ⬇️ ᴘᴅꜰ / ᴄʙᴢ</blockquote>")
    try:
        await cq.edit_message_caption(caption=text,
                                      reply_markup=InlineKeyboardMarkup(buttons),
                                      parse_mode=ParseMode.HTML)
    except MessageNotModified:
        pass
    except Exception:
        try:
            await cq.edit_message_text(text,
                                       reply_markup=InlineKeyboardMarkup(buttons),
                                       parse_mode=ParseMode.HTML)
        except MessageNotModified:
            pass


@Client.on_callback_query(filters.regex(r"^mgc_(.+)_(\d+)$"))
async def on_manga_chpage(client: Client, cq):
    user_id = cq.from_user.id
    if user_id not in user_manga:
        return await cq.answer("❌ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ.", show_alert=True)
    await cq.answer()
    _m = re.match(r"^mgc_(.+)_(\d+)$", cq.data or "")
    if not _m:
        return await cq.answer()
    await _render_chapters(cq, user_id, _m.group(1), int(_m.group(2)))


@Client.on_callback_query(filters.regex(r"^mgi_"))
async def on_manga_info(client: Client, cq):
    await cq.answer("📄 = ᴘᴅꜰ · 📚 = ᴄʙᴢ", show_alert=False)


@Client.on_callback_query(filters.regex("^mgback$"))
async def on_manga_back(client: Client, cq):
    state = user_manga.get(cq.from_user.id)
    if not state:
        return await cq.answer("❌ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ.", show_alert=True)
    await cq.answer()
    await _render_results(cq.message, cq.from_user.id,
                          state.get("res_page", 0))


@Client.on_callback_query(filters.regex(r"^mgsl_(\d+)$"))
async def on_manga_respage(client: Client, cq):
    state = user_manga.get(cq.from_user.id)
    if not state:
        return await cq.answer("❌ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ.", show_alert=True)
    await cq.answer()
    _m = re.match(r"^mgsl_(\d+)$", cq.data or "")
    if not _m:
        return await cq.answer()
    state["res_page"] = int(_m.group(1))
    await _render_results(cq.message, cq.from_user.id, state["res_page"])


@Client.on_callback_query(filters.regex("^mgnew$"))
async def on_manga_newsearch(client: Client, cq):
    await cq.answer()
    try:
        await cq.message.delete()
    except Exception:
        pass
    try:
        await client.send_message(
            cq.from_user.id,
            "<blockquote>🔎 ꜱᴇɴᴅ: <code>/manga &lt;ᴛɪᴛʟᴇ&gt;</code>\n"
            "ᴇxᴀᴍᴘʟᴇ: <code>/manga one piece</code> · <code>/mrandom</code> 🎲</blockquote>",
            parse_mode=ParseMode.HTML)
    except Exception:
        pass


@Client.on_callback_query(filters.regex("^mgnoop$"))
async def on_manga_noop(client: Client, cq):
    await cq.answer()


@Client.on_callback_query(filters.regex("^mgx$"))
async def on_manga_close(client: Client, cq):
    user_manga.pop(cq.from_user.id, None)
    try:
        await cq.message.delete()
    except Exception:
        pass


# ─────────────────────────────────────────────
#  chapter → PDF / CBZ → upload
# ─────────────────────────────────────────────
@Client.on_callback_query(filters.regex(r"^mgd_(.+)_(\d+)_(\d+)_(pdf|cbz)$"))
async def on_manga_download(client: Client, cq):
    user_id = cq.from_user.id
    state = user_manga.get(user_id)
    if not state:
        return await cq.answer("❌ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ — /manga ᴀɢᴀɪɴ.", show_alert=True)
    if user_id in _busy:
        return await cq.answer("⏳ ᴏɴᴇ ᴄʜᴀᴘᴛᴇʀ ᴀᴛ ᴀ ᴛɪᴍᴇ — ꜱᴛɪʟʟ ᴡᴏʀᴋɪɴɢ…", show_alert=True)

    _m = re.match(r"^mgd_(.+)_(\d+)_(\d+)_(pdf|cbz)$", cq.data or "")
    if not _m:
        return await cq.answer()
    key, page, j, fmt = (_m.group(1), int(_m.group(2)),
                         int(_m.group(3)), _m.group(4))
    chapters = (state.get("chapters") or {}).get(key) or []
    manga = (state.get("mangas") or {}).get(key)
    idx = page * PAGE_SIZE + j
    if idx >= len(chapters) or manga is None:
        return await cq.answer("❌ ꜱᴛᴀʟᴇ ʟɪɴᴋ.", show_alert=True)
    chapter = chapters[idx]
    from manga_sources import NSFW_IDS
    if manga.provider in NSFW_IDS and not await _premium_ok(user_id):
        return await cq.answer(
            "🔒 18+ ꜱᴏᴜʀᴄᴇ — 💎 ᴘʀᴇᴍɪᴜᴍ ʀᴇǫᴜɪʀᴇᴅ (/premium).", show_alert=True)

    await cq.answer(f"⬇️ ꜰᴇᴛᴄʜɪɴɢ ᴄʜ {chapter.number}…")
    _busy.add(user_id)
    status = None
    try:
        status = await cq.message.reply(
            f"<blockquote>⬇️ <b>{manga.title[:36]}</b> — ᴄʜ {chapter.number}\n"
            f"ꜰᴇᴛᴄʜɪɴɢ ᴘᴀɢᴇꜱ…</blockquote>", parse_mode=ParseMode.HTML)
        loop = asyncio.get_event_loop()
        t0 = time.time()

        def _pages():
            from manga_sources import get_provider
            prov = get_provider(key.split("_", 1)[0])
            return prov.images(chapter)

        urls, referer = await loop.run_in_executor(None, _pages)
        await status.edit_text(
            f"<blockquote>⬇️ {len(urls)} ᴘᴀɢᴇꜱ ꜰᴏᴜɴᴅ — ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ…</blockquote>",
            parse_mode=ParseMode.HTML)

        def _dl_progress(done_n, total):
            if done_n % 5 == 0 or done_n == total:
                asyncio.get_event_loop().call_soon_threadsafe(
                    lambda: asyncio.create_task(_safe_edit(
                        status,
                        f"<blockquote>⬇️ <b>{manga.title[:30]}</b> — ᴄʜ {chapter.number}\n"
                        f"ᴘᴀɢᴇꜱ: {done_n}/{total}</blockquote>")))
        from manga_sources.base import fetch_images
        workdir = TMP / f"{user_id}_{int(time.time())}"
        paths = await loop.run_in_executor(
            None, lambda: fetch_images(urls, workdir, progress=_dl_progress,
                                       referer=referer))
        if not paths:
            raise RuntimeError("no pages downloaded (CDN blocked?)")

        await status.edit_text(
            f"<blockquote>🛠 ᴍᴀᴋɪɴɢ {fmt.upper()} ({len(paths)} ᴘᴀɢᴇꜱ)…</blockquote>",
            parse_mode=ParseMode.HTML)

        def _build():
            from manga_sources import build_output, sanitize
            out_base = workdir / sanitize(
                f"{manga.title} - Ch {chapter.number}")
            return build_output(paths, fmt, out_base)

        out_path = await loop.run_in_executor(None, _build)
        await status.edit_text(
            f"<blockquote>📤 ᴜᴘʟᴏᴀᴅɪɴɢ {out_path.stat().st_size/1048576:.1f} ᴍʙ…</blockquote>",
            parse_mode=ParseMode.HTML)

        caption = (f"<blockquote>📖 <b>{manga.title[:50]}</b> "
                   f"<i>· {_badge(key.split('_', 1)[0])}</i>\n"
                   f"ᴄʜᴀᴘᴛᴇʀ {chapter.number}"
                   + (f" — {chapter.title[:40]}" if chapter.title else "")
                   + f"\n{len(paths)} ᴘᴀɢᴇꜱ · {fmt.upper()} · ᴀɴɪᴍᴇᴅʟ ᴠ{VERSION}</blockquote>")
        await client.send_document(
            cq.message.chat.id, document=str(out_path),
            file_name=Path(out_path).name,
            caption=caption, parse_mode=ParseMode.HTML)
        state["last_dl"] = {"provider": key.split("_", 1)[0],
                            "title": manga.title,
                            "chapter": chapter, "fmt": fmt}
        await status.edit_text(
            f"<blockquote>✅ ᴄʜ {chapter.number} ᴅᴇʟɪᴠᴇʀᴇᴅ ⚡ {round(time.time()-t0)}s</blockquote>",
            parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.info("manga download failed: %s", e)
        try:
            if status:
                await status.edit_text(
                    f"<blockquote>❌ ᴅᴏᴡɴʟᴏᴀᴅ ꜰᴀɪʟᴇᴅ: {str(e)[:160]}</blockquote>",
                    parse_mode=ParseMode.HTML)
        except Exception:
            pass
    finally:
        _busy.discard(user_id)
        try:
            import shutil
            for d in TMP.glob(f"{user_id}_*"):
                shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


async def _safe_edit(msg, text):
    try:
        await msg.edit_text(text, parse_mode=ParseMode.HTML)
    except MessageNotModified:
        pass
    except Exception:
        pass
