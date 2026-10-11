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
import time
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import VERSION

logger = logging.getLogger(__name__)

user_manga = {}          # user_id -> state dict
_busy = set()            # user_ids with a download running
TMP = Path("/tmp/animedl/manga")

PAGE_SIZE = 10           # chapters per page


def _search_state(user_id):
    return (user_manga.get(user_id) or {}).get("results") or []


# ─────────────────────────────────────────────
#  /manga — search
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("manga"))
async def manga_search_cmd(client: Client, message):
    query = (message.text or "").split(None, 1)[1].strip() if len((message.text or "").split()) > 1 else ""
    if not query:
        return await message.reply(
            "<blockquote>📖 <b>ᴍᴀɴɢᴀ ꜱᴇᴀʀᴄʜ</b>\n\n"
            "ᴜꜱᴀɢᴇ: <code>/manga solo leveling</code>\n\n"
            "ꜱᴏᴜʀᴄᴇꜱ: ᴍᴀɴɢᴀᴅᴇx · ᴄᴏᴍɪᴄᴋ · ᴀꜱᴜʀᴀ ꜱᴄᴀɴꜱ\n"
            "ᴏᴜᴛᴘᴜᴛ: 📄 ᴘᴅꜰ ᴏʀ 📚 ᴄʙᴢ ᴘᴇʀ ᴄʜᴀᴘᴛᴇʀ</blockquote>",
            parse_mode=ParseMode.HTML)

    status = await message.reply(
        f"<blockquote>🔎 ꜱᴇᴀʀᴄʜɪɴɢ <b>{query[:40]}</b> ᴏɴ ᴍᴀɴɢᴀᴅᴇx · ᴄᴏᴍɪᴄᴋ · ᴀꜱᴜʀᴀ…</blockquote>",
        parse_mode=ParseMode.HTML)

    def _work():
        from manga_sources import search_all
        return search_all(query)

    try:
        results, tried = await asyncio.get_event_loop().run_in_executor(None, _work)
    except Exception as e:
        return await status.edit_text(
            f"<blockquote>❌ ꜱᴇᴀʀᴄʜ ꜰᴀɪʟᴇᴅ: {e}</blockquote>", parse_mode=ParseMode.HTML)

    user_manga[message.from_user.id] = {
        "query": query, "results": results, "mangas": {}, "chapters": {},
    }
    if not results:
        tried_line = " · ".join(
            f"{n}:{o}" for n, o in tried) if tried else "no sources"
        return await status.edit_text(
            f"<blockquote>❌ ɴᴏ ᴍᴀɴɢᴀ ꜰᴏᴜɴᴅ ꜰᴏʀ <b>{query[:40]}</b>\n"
            f"<i>{tried_line}</i></blockquote>", parse_mode=ParseMode.HTML)

    buttons, row = [], []
    for i, r in enumerate(results[:12]):
        label = f"📖 {r.title[:38]}"
        row.append(InlineKeyboardButton(label, callback_data=f"mgp_{r.provider}_{i}"))
        if len(row) == 1:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ", callback_data="mgx")])

    health = " · ".join(
        f"{p.capitalize()} {('✅' if isinstance(o, int) and o else '⚠️')}" for p, o in tried)
    await status.edit_text(
        f"<blockquote>📖 <b>ᴍᴀɴɢᴀ ꜰᴏᴜɴᴅ ({len(results)}):</b>\n{health}</blockquote>",
        reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)


# ─────────────────────────────────────────────
#  series picked → chapters
# ─────────────────────────────────────────────
@Client.on_callback_query(filters.regex(r"^mgp_([a-z]+)_(\d+)$"))
async def on_manga_pick(client: Client, cq):
    user_id = cq.from_user.id
    state = user_manga.get(user_id)
    if not state:
        return await cq.answer("❌ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ — /manga ᴀɢᴀɪɴ.", show_alert=True)
    pid, idx = cq.pattern.group(1), int(cq.pattern.group(2))
    results = state.get("results") or []
    if idx >= len(results):
        return await cq.answer("❌ ꜱᴛᴀʟᴇ ʟɪɴᴋ.", show_alert=True)
    manga = results[idx]

    await cq.answer("📚 ʟᴏᴀᴅɪɴɢ ᴄʜᴀᴘᴛᴇʀꜱ…")
    try:
        await cq.edit_message_caption(
            caption=f"<blockquote>📚 ʟᴏᴀᴅɪɴɢ ᴄʜᴀᴘᴛᴇʀꜱ ᴏꜰ <b>{manga.title[:40]}</b>…</blockquote>",
            parse_mode=ParseMode.HTML)
    except Exception:
        pass

    def _work():
        from manga_sources import get_provider
        prov = get_provider(pid)
        if pid == "mangadex":
            return prov, prov.chapters(manga.id)
        if pid == "asura":
            return prov, prov.chapters(manga.url)
        return prov, prov.chapters(manga.id)   # comick: slug

    try:
        prov, chapters = await asyncio.get_event_loop().run_in_executor(None, _work)
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
    for j, ch in enumerate(chunk):
        label = f"📑 Ch {ch.number}" + (f" · {ch.title[:22]}" if ch.title else "")
        fmt = "cbz"
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

    text = (f"<blockquote>📚 <b>{manga.title[:40]}</b>\n"
            f"ᴄʜᴀᴘᴛᴇʀꜱ: {len(chapters)} · ᴛᴀᴘ ᴀ ᴄʜᴀᴘᴛᴇʀ → 📄 ᴘᴅꜰ / 📚 ᴄʙᴢ</blockquote>")
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
    await _render_chapters(cq, user_id, cq.pattern.group(1), int(cq.pattern.group(2)))


@Client.on_callback_query(filters.regex(r"^mgi_"))
async def on_manga_info(client: Client, cq):
    await cq.answer("📄 = ᴘᴅꜰ · 📚 = ᴄʙᴢ", show_alert=False)


@Client.on_callback_query(filters.regex("^mgback$"))
async def on_manga_back(client: Client, cq):
    state = user_manga.get(cq.from_user.id)
    if not state:
        return await cq.answer("❌ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ.", show_alert=True)
    await cq.answer()
    results = state.get("results") or []
    buttons = []
    for i, r in enumerate(results[:12]):
        buttons.append([InlineKeyboardButton(
            f"📖 {r.title[:38]}", callback_data=f"mgp_{r.provider}_{i}")])
    buttons.append([InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ", callback_data="mgx")])
    try:
        await cq.edit_message_caption(
            caption=f"<blockquote>📖 <b>ᴍᴀɴɢᴀ ꜰᴏᴜɴᴅ ({len(results)}):</b></blockquote>",
            reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
    except MessageNotModified:
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

    key, page, j, fmt = (cq.pattern.group(1), int(cq.pattern.group(2)),
                         int(cq.pattern.group(3)), cq.pattern.group(4))
    chapters = (state.get("chapters") or {}).get(key) or []
    manga = (state.get("mangas") or {}).get(key)
    idx = page * PAGE_SIZE + j
    if idx >= len(chapters) or manga is None:
        return await cq.answer("❌ ꜱᴛᴀʟᴇ ʟɪɴᴋ.", show_alert=True)
    chapter = chapters[idx]

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
        from manga_sources import get_provider as _gp  # noqa: F401
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

        caption = (f"<blockquote>📖 <b>{manga.title[:50]}</b>\n"
                   f"ᴄʜᴀᴘᴛᴇʀ {chapter.number}"
                   + (f" — {chapter.title[:40]}" if chapter.title else "")
                   + f"\n{len(paths)} ᴘᴀɢᴇꜱ · {fmt.upper()} · ᴀɴɪᴍᴇᴅʟ ᴠ{VERSION}</blockquote>")
        await client.send_document(
            cq.message.chat.id, document=str(out_path),
            file_name=Path(out_path).name,
            caption=caption, parse_mode=ParseMode.HTML)
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
