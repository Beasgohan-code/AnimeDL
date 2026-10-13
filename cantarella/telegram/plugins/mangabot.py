# ============================================================================
#  AnimeDL MangaBot — the manga-repo command suite, inside AnimeDL
# ============================================================================
#  Ported from the reference manga bots (commands that AnimeDL did NOT already
#  have — no duplicates of /manga /settings /queue(leech) /broadcast /admins …):
#
#    /msearch <source> <query>   per-source search (Manga-Bot's per-plugin UX)
#    /minfo <query>              manga details card (Manhwa-Bot /info)
#    /mqueue                     your running manga jobs (Manhwa-Bot /queue)
#    /mclean                     cancel my manga job + wipe my session
#                                (Manhwa-Bot /clean · /clean_queue)
#    /mrefresh                   re-download the last chapter fresh
#                                (Manga-Bot /refresh)
#    /mpost <query>              shareable cover post (AUTO-BOT /makepost)
#
#  Plus already-shipped: /manga (all-source search) · /mrandom (dice) ·
#  /usettings · /premium — the whole manga bot in one bot.
# ============================================================================

import asyncio
import logging
import time
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.enums import ParseMode

import uikit
from config import VERSION, OWNER_ID
from cantarella.telegram.decorators import check_ban

from cantarella.telegram.plugins.manga import (
    user_manga, _busy, TMP,
    _premium_ok, _default_fmt, _badge,
)

logger = logging.getLogger(__name__)

import manga_sources as _MS
_SFW = tuple(_MS.SEARCH_ORDER)                 # 37 SFW sources (repo scrapers first)
_NSFW = tuple(_MS.NSFW_IDS)                    # 18+: manhwaclan · manga18fx · manhwa18


def _src_line() -> str:
    return " · ".join(_SFW)


# ─────────────────────────────────────────────
#  /msearch <source> <query> — per-source search
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("msearch"))
@check_ban
async def msearch_cmd(client: Client, message):
    parts = (message.text or "").split(None, 2)
    if len(parts) < 2:
        return await message.reply(
            "<blockquote>🔎 <b>ᴘᴇʀ-ꜱᴏᴜʀᴄᴇ ꜱᴇᴀʀᴄʜ</b></blockquote>\n"
            "<blockquote>ᴜꜱᴀɢᴇ: <code>/msearch mangadex one piece</code>\n\n"
            f"ꜱᴏᴜʀᴄᴇꜱ:\n{_src_line()}\n"
            "🔞 ᴘʀᴇᴍɪᴜᴍ: " + " · ".join(_NSFW) + "</blockquote>",
            parse_mode=ParseMode.HTML)
    pid = parts[1].lower().lstrip("/").strip()
    if len(parts) < 3 or not parts[2].strip():
        return await message.reply(
            f"<blockquote>❌ ɢɪᴠᴇ ᴀ Qᴜᴇʀʏ: <code>/msearch {pid} one piece</code></blockquote>",
            parse_mode=ParseMode.HTML)
    query = parts[2].strip()
    uid = message.from_user.id

    from manga_sources import PROVIDER_NAMES
    if pid not in PROVIDER_NAMES:
        return await message.reply(
            f"<blockquote>❌ ᴜɴᴋɴᴏᴡɴ ꜱᴏᴜʀᴄᴇ <code>{pid[:16]}</code>\n"
            f"ᴛʀʏ: {_src_line()}</blockquote>", parse_mode=ParseMode.HTML)
    if pid in _NSFW:
        from manga_sources.nsfw import nsfw_enabled
        if not nsfw_enabled() or not await _premium_ok(uid):
            return await message.reply(
                "<blockquote>🔒 ᴛʜᴀᴛ 18+ ꜱᴏᴜʀᴄᴇ ɴᴇᴇᴅꜱ 💎 ᴘʀᴇᴍɪᴜᴍ (+ ᴏᴘᴇʀᴀᴛᴏʀ ᴇɴᴀʙʟᴇ) — /premium</blockquote>",
                parse_mode=ParseMode.HTML)

    status = await message.reply(
        f"<blockquote>🔎 ꜱᴇᴀʀᴄʜɪɴɢ <b>{query[:36]}</b> ᴏɴ <b>{_badge(pid)}</b>…</blockquote>",
        parse_mode=ParseMode.HTML)

    def _work():
        from manga_sources import get_provider
        return get_provider(pid).search(query)[:8]

    try:
        found = await asyncio.get_event_loop().run_in_executor(None, _work)
    except Exception as e:
        return await status.edit_text(
            f"<blockquote>❌ {_badge(pid)} ꜰᴀɪʟᴇᴅ: {str(e)[:120]}</blockquote>",
            parse_mode=ParseMode.HTML)

    user_manga[uid] = {"query": query, "results": found, "mangas": {},
                       "chapters": {}, "pref_fmt": await _default_fmt(uid),
                       "tried": [(pid, len(found))]}
    if not found:
        return await status.edit_text(
            f"<blockquote>❌ ɴᴏᴛʜɪɴɢ ᴏɴ <b>{_badge(pid)}</b> ꜰᴏʀ <b>{query[:36]}</b></blockquote>",
            parse_mode=ParseMode.HTML)
    from cantarella.telegram.plugins.manga import _render_results
    await _render_results(status, uid, 0)


# ─────────────────────────────────────────────
#  /minfo <query> — details card
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("minfo"))
@check_ban
async def minfo_cmd(client: Client, message):
    parts = (message.text or "").split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        return await message.reply(
            "<blockquote>Usage: <code>/minfo one piece</code></blockquote>",
            parse_mode=ParseMode.HTML)
    query = parts[1].strip()
    status = await message.reply(
        "<blockquote>ℹ️ ʟᴏᴏᴋɪɴɢ ɪᴛ ᴜᴘ…</blockquote>", parse_mode=ParseMode.HTML)

    def _work():
        from manga_sources import get_provider
        return get_provider("mangadex").info(query)

    try:
        d = await asyncio.get_event_loop().run_in_executor(None, _work)
    except Exception as e:
        return await status.edit_text(
            f"<blockquote>❌ ɪɴꜰᴏ ꜰᴀɪʟᴇᴅ: {str(e)[:120]}</blockquote>",
            parse_mode=ParseMode.HTML)
    r = d["result"]
    tags = " · ".join(d["tags"]) or "—"
    desc = (d["description"] or "").strip()
    if len(desc) > 350:
        desc = desc[:350].rsplit(" ", 1)[0] + "…"
    text = (
        "<blockquote>ℹ️ <b>" + r.title[:60] + "</b> <i>· " + _badge(r.provider)
        + "</i></blockquote>\n"
        "<blockquote><b>ꜱᴛᴀᴛᴜꜱ:</b> " + d["status"] + " · <b>ʏᴇᴀʀ:</b> "
        + str(d["year"]) + "\n<b>ɢᴇɴʀᴇꜱ:</b> " + tags + "</blockquote>\n"
        "<blockquote expandable>" + (desc or "ɴᴏ ᴅᴇꜱᴄʀɪᴘᴛɪᴏɴ") + "</blockquote>\n"
        f"<i>ᴅᴏᴡɴʟᴏᴀᴅ → /manga {query[:24]} · ᴅᴇᴛᴀɪʟꜱ via ᴀɴɪᴍᴇᴅʟ ᴠ{VERSION}</i>")
    try:
        await status.delete()
    except Exception:
        pass
    if r.cover:
        try:
            return await message.reply_photo(
                r.cover, caption=text, parse_mode=ParseMode.HTML)
        except Exception:
            pass
    await message.reply(text, parse_mode=ParseMode.HTML)


# ─────────────────────────────────────────────
#  /mqueue — your manga jobs
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("mqueue"))
@check_ban
async def mqueue_cmd(client: Client, message):
    uid = message.from_user.id
    rows = []
    if uid in _busy:
        st = user_manga.get(uid) or {}
        last = st.get("last_dl") or {}
        rows.append(f"⬇️ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ: <b>{(st.get('query') or '?')[:28]}</b>"
                    + (f" — ᴄʜ {last['chapter'].number}"
                       if last.get("chapter") else ""))
    st = user_manga.get(uid)
    if st and st.get("chapters"):
        total = sum(len(v) for v in st["chapters"].values())
        rows.append(f"📚 ꜱᴇꜱꜱɪᴏɴ: <b>{(st.get('query') or '?')[:28]}</b> — "
                    f"{len(st.get('results') or [])} ꜱᴇʀɪᴇꜱ · {total} ᴄʜᴀᴘᴛᴇʀꜱ ʟᴏᴀᴅᴇᴅ")
    if st and st.get("last_dl"):
        last = st["last_dl"]
        rows.append(f"✅ ʟᴀꜱᴛ: <b>{last['title'][:28]}</b> ᴄʜ "
                    f"{last['chapter'].number} · {last['fmt'].upper()} "
                    f"({ _badge(last['provider'])}) — /mrefresh ᴛᴏ ʀᴇ-ɢᴇᴛ")
    if not rows:
        return await message.reply(
            "<blockquote>📭 ɴᴏ ᴍᴀɴɢᴀ ᴊᴏʙꜱ. /manga ᴛᴏ ꜱᴛᴀʀᴛ ᴏɴᴇ.</blockquote>",
            parse_mode=ParseMode.HTML)
    text = ("<blockquote>🧾 <b>ʏᴏᴜʀ ᴍᴀɴɢᴀ Qᴜᴇᴜᴇ</b></blockquote>\n"
            + "\n".join(f"<blockquote>{r}</blockquote>" for r in rows))
    await message.reply(text, parse_mode=ParseMode.HTML)


# ─────────────────────────────────────────────
#  /mclean — cancel my job + wipe my session
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("mclean"))
@check_ban
async def mclean_cmd(client: Client, message):
    uid = message.from_user.id
    if uid in _busy:
        return await message.reply(
            "<blockquote>⏳ ᴀ ᴄʜᴀᴘᴛᴇʀ ɪꜱ ꜱᴛɪʟʟ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ — /mclean ᴀɢᴀɪɴ ᴀꜰᴛᴇʀ ɪᴛ ғɪɴɪꜱʜᴇꜱ.</blockquote>",
            parse_mode=ParseMode.HTML)
    had = user_manga.pop(uid, None) is not None
    import shutil
    wiped = 0
    try:
        for d in TMP.glob(f"{uid}_*"):
            shutil.rmtree(d, ignore_errors=True)
            wiped += 1
    except Exception:
        pass
    await message.reply(
        "<blockquote>🧹 ꜱᴇꜱꜱɪᴏɴ ᴄʟᴇᴀɴᴇᴅ — " + ("ꜱᴛᴀᴛᴇ + " if had else "")
        + f"{wiped} ᴛᴇᴍᴘ ᴅɪʀ(ꜱ) ʀᴇᴍᴏᴠᴇᴅ.</blockquote>",
        parse_mode=ParseMode.HTML)


# ─────────────────────────────────────────────
#  /mrefresh — re-download the last chapter (fresh fetch)
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("mrefresh"))
@check_ban
async def mrefresh_cmd(client: Client, message):
    uid = message.from_user.id
    st = user_manga.get(uid) or {}
    last = st.get("last_dl")
    if not last:
        return await message.reply(
            "<blockquote>❌ ɴᴏ ᴘʀᴇᴠɪᴏᴜꜱ ᴄʜᴀᴘᴛᴇʀ ɪɴ ᴛʜɪꜱ ꜱᴇꜱꜱɪᴏɴ — ᴅᴏᴡɴʟᴏᴀᴅ ᴏɴᴇ ᴠɪᴀ /manga ꜰɪʀꜱᴛ.</blockquote>",
            parse_mode=ParseMode.HTML)
    if uid in _busy:
        return await message.reply(
            "<blockquote>⏳ ᴀʟʀᴇᴀᴅʏ ᴡᴏʀᴋɪɴɢ ᴏɴ ꜱᴏᴍᴇᴛʜɪɴɢ.</blockquote>",
            parse_mode=ParseMode.HTML)
    chapter, fmt, title = last["chapter"], last["fmt"], last["title"]
    pid = last["provider"]
    _busy.add(uid)
    status = await message.reply(
        f"<blockquote>🔄 ʀᴇ-ꜰᴇᴛᴄʜɪɴɢ <b>{title[:30]}</b> ᴄʜ {chapter.number} (ꜰʀᴇꜱʜ)…</blockquote>",
        parse_mode=ParseMode.HTML)
    try:
        loop = asyncio.get_event_loop()
        t0 = time.time()

        def _pages():
            from manga_sources import get_provider
            return get_provider(pid).images(chapter)

        urls, referer = await loop.run_in_executor(None, _pages)
        from manga_sources.base import fetch_images
        workdir = TMP / f"{uid}_r{int(time.time())}"
        paths = await loop.run_in_executor(
            None, lambda: fetch_images(urls, workdir, referer=referer))
        if not paths:
            raise RuntimeError("no pages downloaded")
        from manga_sources import build_output, sanitize

        def _build():
            return build_output(paths, fmt,
                                workdir / sanitize(f"{title} - Ch {chapter.number}"))

        out_path = await loop.run_in_executor(None, _build)
        cap = (f"<blockquote>🔄 <b>{title[:50]}</b>\nᴄʜᴀᴘᴛᴇʀ {chapter.number}"
               f" · {len(paths)} ᴘᴀɢᴇꜱ · {fmt.upper()} · ᴀɴɪᴍᴇᴅʟ ᴠ{VERSION}</blockquote>")
        await client.send_document(message.chat.id, document=str(out_path),
                                   file_name=Path(out_path).name,
                                   caption=cap, parse_mode=ParseMode.HTML)
        await status.edit_text(
            f"<blockquote>✅ ʀᴇꜰʀᴇꜱʜᴇᴅ ⚡ {round(time.time()-t0)}s</blockquote>",
            parse_mode=ParseMode.HTML)
    except Exception as e:
        await status.edit_text(
            f"<blockquote>❌ ʀᴇꜰʀᴇꜱʜ ꜰᴀɪʟᴇᴅ: {str(e)[:140]}</blockquote>",
            parse_mode=ParseMode.HTML)
    finally:
        _busy.discard(uid)
        try:
            import shutil
            for d in TMP.glob(f"{uid}_r*"):
                shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


# ─────────────────────────────────────────────
#  /mpost <query> — shareable cover post
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("mpost"))
@check_ban
async def mpost_cmd(client: Client, message):
    parts = (message.text or "").split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        return await message.reply(
            "<blockquote>Usage: <code>/mpost solo leveling</code></blockquote>",
            parse_mode=ParseMode.HTML)
    query = parts[1].strip()
    status = await message.reply(
        "<blockquote>🖼 ᴍᴀᴋɪɴɢ ʏᴏᴜʀ ᴘᴏꜱᴛ…</blockquote>", parse_mode=ParseMode.HTML)

    def _work():
        from manga_sources import get_provider
        return get_provider("mangadex").info(query)

    try:
        d = await asyncio.get_event_loop().run_in_executor(None, _work)
    except Exception as e:
        return await status.edit_text(
            f"<blockquote>❌ ᴘᴏꜱᴛ ꜰᴀɪʟᴇᴅ: {str(e)[:120]}</blockquote>",
            parse_mode=ParseMode.HTML)
    r = d["result"]
    cap = (f"<blockquote>📖 <b>{r.title[:60]}</b></blockquote>\n"
           f"<blockquote>{d['status'].title()} · {d['year']} · "
           f"{' · '.join(d['tags'][:4])}\n"
           f"ꜱᴇᴀʀᴄʜ ɪᴛ ɪɴ-ʙᴏᴛ: /manga {query[:22]} — ᴀɴɪᴍᴇᴅʟ 📺</blockquote>")
    try:
        await status.delete()
    except Exception:
        pass
    if r.cover:
        try:
            return await message.reply_photo(r.cover, caption=cap,
                                             parse_mode=ParseMode.HTML)
        except Exception:
            pass
    await message.reply(cap, parse_mode=ParseMode.HTML)
