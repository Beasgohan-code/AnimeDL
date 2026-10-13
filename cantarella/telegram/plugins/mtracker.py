# ============================================================================
#  AnimeDL MangaTracker — chapter subscriptions (/msubscribe /msubs /munsub)
# ============================================================================
#  Rebuilt natively on the AnimeDL manga engine. The polling/notification
#  approach (follow a series → periodic newest-chapter check → announce with
#  a one-tap download) follows the UX of auto-manga-chapter-update-bot and
#  Manhwa-Bot; every line here is AnimeDL's own — no upstream code, no
#  upstream credits. Checks reuse the SAME 15-provider engine as /manga.
#
#    /msubscribe <query>   follow a series (pick from search results)
#    /msubs                your follows + last known chapter
#    /munsub <id|all>      unfollow
#    /mcheck               check all follows right now
#
#  Poll interval: MANGA_CHECK_MINUTES env (default 30, min 5).
# ============================================================================

import asyncio
import logging
import os
import time

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from cantarella.telegram.decorators import check_ban
from config import VERSION

logger = logging.getLogger(__name__)

_sub_state = {}          # uid -> {"results": [...]} for msb_ picks & updates


def _interval_minutes() -> int:
    try:
        return max(5, int(os.getenv("MANGA_CHECK_MINUTES", "30") or "30"))
    except ValueError:
        return 30


def _sub_arg(sub: dict) -> str:
    """the value chapters() consumes for this provider (same engine rules)."""
    from manga_sources import CHAPTERS_ARG
    attr = CHAPTERS_ARG.get(sub["provider"], "id")
    return sub.get(attr) or sub.get("series_id") or ""


def _result_for(sub: dict):
    from manga_sources import MangaSearchResult
    return MangaSearchResult(
        provider=sub["provider"], id=sub.get("series_id") or "",
        title=sub.get("title") or "?", cover=sub.get("cover") or "",
        url=sub.get("url") or "")


async def _newest_chapter(sub: dict):
    """newest chapter of a followed series via the shared engine."""
    def _work():
        from manga_sources import get_provider
        return get_provider(sub["provider"]).chapters(_sub_arg(sub))
    loop = asyncio.get_event_loop()
    chs = await loop.run_in_executor(None, _work)
    return chs[0] if chs else None


async def check_subs(uid: int = None) -> list:
    """Check follows (one user or everyone). Returns
    [(sub, chapter)] pairs that are NEWER than the stored last chapter
    (DB already updated). One dead source never kills the scan."""
    from cantarella.core.database import db
    subs = await db.get_manga_subs(uid)
    updates = []
    for sub in subs[:40]:                     # bounded per cycle
        try:
            ch = await _newest_chapter(sub)
        except Exception as e:                # noqa: BLE001 — skip dead source
            logger.info("sub check failed (%s %s): %s",
                        sub.get("provider"), sub.get("title"), e)
            continue
        if ch is None:
            continue
        try:
            new_n, old_n = float(ch.number), float(sub.get("last_chapter") or 0)
        except ValueError:
            continue
        if new_n > old_n:
            await db.update_manga_sub(
                sub["_id"], last_chapter=ch.number, last_title=ch.title or "")
            updates.append((sub, ch))
        await asyncio.sleep(0.4)              # gentle on sources
    return updates


def _update_card(uid: int, updates: list, header: str) -> tuple:
    """(text, markup) for a set of (sub, chapter) updates; wires the existing
    /manga chapter pipeline via mgp_ buttons."""
    from manga_sources import PROVIDER_NAMES
    from cantarella.telegram.plugins.manga import _badge
    results = []
    lines = []
    for sub, ch in updates:
        results.append(_result_for(sub))
        i = len(results) - 1
        lines.append(
            f"📖 <b>{(sub.get('title') or '?')[:40]}</b> — "
            f"ᴄʜᴀᴘᴛᴇʀ <b>{ch.number}</b>"
            + (f" · {ch.title[:24]}" if ch.title else "")
            + f"  <i>{_badge(sub['provider'])}</i>")
    text = (f"<blockquote>{header}</blockquote>\n"
            + "\n".join(f"<blockquote expandable>{l}</blockquote>"
                        for l in lines)
            + f"\n<i>ᴛᴀᴘ ᴀ ꜱᴇʀɪᴇꜱ → ᴄʜᴀᴘᴛᴇʀꜱ → 📄/📚 · ᴀɴɪᴍᴇᴅʟ ᴠ{VERSION}</i>")
    buttons = []
    for i, r in enumerate(results):
        buttons.append([InlineKeyboardButton(
            f"⬇️ {(r.title or '?')[:24]} ᴄʜ {updates[i][1].number}",
            callback_data=f"mgp_{r.provider}_{i}")])
    buttons.append([InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ", callback_data="mgx")])
    from cantarella.telegram.plugins.manga import user_manga
    st = user_manga.setdefault(uid, {"query": "🔔 updates", "results": [],
                                     "mangas": {}, "chapters": {},
                                     "tried": []})
    st["results"] = results
    return text, InlineKeyboardMarkup(buttons)


# ─────────────────────────────────────────────
#  /msubscribe — follow a series
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("msubscribe"))
@check_ban
async def msubscribe_cmd(client: Client, message):
    parts = (message.text or "").split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        return await message.reply(
            "<blockquote>🔔 <b>ꜰᴏʟʟᴏᴡ ᴀ ꜱᴇʀɪᴇꜱ</b></blockquote>\n"
            "<blockquote>ᴜꜱᴀɢᴇ: <code>/msubscribe solo leveling</code>\n"
            "ɢᴇᴛ ᴘɪɴɢᴇᴅ ᴡɪᴛʜ ᴀ ᴏɴᴇ-ᴛᴀᴘ ᴅᴏᴡɴʟᴏᴀᴅ ᴡʜᴇɴ ɴᴇᴡ ᴄʜᴀᴘᴛᴇʀꜱ ᴅʀᴏᴘ.</blockquote>",
            parse_mode=ParseMode.HTML)
    query = parts[1].strip()
    uid = message.from_user.id
    status = await message.reply(
        f"<blockquote>🔎 ꜱᴇᴀʀᴄʜɪɴɢ <b>{query[:36]}</b> — ᴘɪᴄᴋ ᴡʜᴀᴛ ᴛᴏ ꜰᴏʟʟᴏᴡ…</blockquote>",
        parse_mode=ParseMode.HTML)

    def _work():
        from manga_sources import search_all
        return search_all(query)[:8]

    try:
        results, tried = await asyncio.get_event_loop().run_in_executor(None, _work)
    except Exception as e:
        return await status.edit_text(
            f"<blockquote>❌ ꜱᴇᴀʀᴄʜ ꜰᴀɪʟᴇᴅ: {str(e)[:120]}</blockquote>",
            parse_mode=ParseMode.HTML)
    if not results:
        return await status.edit_text(
            f"<blockquote>❌ ɴᴏᴛʜɪɴɢ ꜰᴏᴜɴᴅ ꜰᴏʀ <b>{query[:36]}</b></blockquote>",
            parse_mode=ParseMode.HTML)
    _sub_state[uid] = {"results": results}
    buttons = []
    from cantarella.telegram.plugins.manga import _badge
    for i, r in enumerate(results[:8]):
        buttons.append([InlineKeyboardButton(
            f"🔔 {r.title[:30]}  {_badge(r.provider)}",
            callback_data=f"msb_{r.provider}_{i}")])
    buttons.append([InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ", callback_data="mgx")])
    await status.edit_text(
        f"<blockquote>🔔 <b>ꜰᴏʟʟᴏᴡ ᴡʜɪᴄʜ ꜱᴇʀɪᴇꜱ?</b> ({len(results)} ғᴏʀ "
        f"“{query[:28]}”)</blockquote>",
        reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)


@Client.on_callback_query(filters.regex(r"^msb_([a-z]+)_(\d+)$"))
async def on_msub_pick(client: Client, cq):
    uid = cq.from_user.id
    st = _sub_state.get(uid) or {}
    results = st.get("results") or []
    import re as _re
    m = _re.match(r"^msb_([a-z]+)_(\d+)$", cq.data or "")
    if not m:
        return await cq.answer()
    pid, idx = m.group(1), int(m.group(2))
    if idx >= len(results):
        return await cq.answer("❌ ꜱᴛᴀʟᴇ ʟɪɴᴋ — /msubscribe ᴀɢᴀɪɴ.", show_alert=True)
    r = results[idx]
    await cq.answer("🔔 ꜰᴏʟʟᴏᴡɪɴɢ…")
    sub = {"uid": uid, "provider": r.provider,
           "series_id": r.id, "title": r.title,
           "cover": r.cover, "url": r.url, "last_chapter": "0"}
    try:
        ch = await _newest_chapter(sub)
    except Exception as e:
        return await _safe_edit_msg(cq.message,
                                    f"❌ ᴄᴀɴ'ᴛ ʀᴇᴀᴅ ᴛʜᴀᴛ ꜱᴏᴜʀᴄᴇ: {str(e)[:100]}")
    if ch is not None:
        sub["last_chapter"] = ch.number
    from cantarella.core.database import db
    saved = await db.add_manga_sub(**sub)
    title = saved.get("title") or r.title
    text = (f"<blockquote>🔔 <b>ꜰᴏʟʟᴏᴡɪɴɢ {title[:40]}</b></blockquote>\n"
            f"<blockquote>{_badge(r.provider)} · ʟᴀᴛᴇꜱᴛ ᴋɴᴏᴡɴ: "
            f"ᴄʜ {saved.get('last_chapter') or '?'}\n"
            f"ʏᴏᴜ'ʟʟ ɢᴇᴛ ᴀ ᴘɪɴɢ + ᴏɴᴇ-ᴛᴀᴘ ᴅᴏᴡɴʟᴏᴀᴅ ᴡʜᴇɴ ɴᴇᴡᴇʀ ᴄʜᴀᴘᴛᴇʀꜱ ᴅʀᴏᴘ"
            f" (ᴇᴠᴇʀʏ {_interval_minutes()} ᴍɪɴ)</blockquote>")
    try:
        await cq.message.edit_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        pass


async def _safe_edit_msg(msg, text):
    try:
        await msg.edit_text("<blockquote>" + text + "</blockquote>",
                            parse_mode=ParseMode.HTML)
    except Exception:
        pass


# ─────────────────────────────────────────────
#  /msubs · /munsub · /mcheck
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("msubs"))
@check_ban
async def msubs_cmd(client: Client, message):
    uid = message.from_user.id
    from cantarella.core.database import db
    subs = await db.get_manga_subs(uid)
    if not subs:
        return await message.reply(
            "<blockquote>📭 ʏᴏᴜ'ʀᴇ ɴᴏᴛ ꜰᴏʟʟᴏᴡɪɴɢ ᴀɴʏᴛʜɪɴɢ ʏᴇᴛ — /msubscribe ꜱᴏʟᴏ leveling</blockquote>",
            parse_mode=ParseMode.HTML)
    from cantarella.telegram.plugins.manga import _badge
    lines = [f"🔔 <b>{s.get('title', '?')[:36]}</b> — ʟᴀꜱᴛ ᴄʜ "
             f"{s.get('last_chapter') or '?'} <i>{_badge(s['provider'])}</i>"
             f" <code>/munsub {s['_id']}</code>"
             for s in subs[:20]]
    text = (f"<blockquote>📚 <b>ʏᴏᴜʀ ꜰᴏʟʟᴏᴡꜱ ({len(subs)})</b> · ᴄʜᴇᴄᴋᴇᴅ ᴇᴠᴇʀʏ "
            f"{_interval_minutes()} ᴍɪɴ</blockquote>\n"
            + "\n".join(f"<blockquote>{l}</blockquote>" for l in lines)
            + "\n<i>/mcheck — ꜰᴏʀᴄᴇ ᴀ ꜱᴄᴀɴ ɴᴏᴡ</i>")
    await message.reply(text, parse_mode=ParseMode.HTML)


@Client.on_message(filters.private & filters.command("munsub"))
@check_ban
async def munsub_cmd(client: Client, message):
    uid = message.from_user.id
    parts = (message.text or "").split()
    from cantarella.core.database import db
    if len(parts) >= 2 and parts[1].lower() == "all":
        n = await db.del_manga_subs_all(uid)
        return await message.reply(
            f"<blockquote>🧹 ᴜɴꜰᴏʟʟᴏᴡᴇᴅ ᴀʟʟ ({n}).</blockquote>",
            parse_mode=ParseMode.HTML)
    if len(parts) >= 2:
        ok = await db.del_manga_sub(uid, " ".join(parts[1:]))
        if ok:
            return await message.reply(
                "<blockquote>🕊 ᴜɴꜰᴏʟʟᴏᴡᴇᴅ. /msubs ꜰᴏʀ ᴡʜᴀᴛ'ꜱ ʟᴇғᴛ.</blockquote>",
                parse_mode=ParseMode.HTML)
        return await message.reply(
            "<blockquote>❌ ɴᴏ ꜰᴏʟʟᴏᴡ ᴡɪᴛʜ ᴛʜᴀᴛ ɪᴅ — ꜱᴇᴇ /msubs.</blockquote>",
            parse_mode=ParseMode.HTML)
    return await message.reply(
        "<blockquote>ᴜꜱᴀɢᴇ: <code>/munsub &lt;id&gt;</code> (ꜰʀᴏᴍ /msubs) · <code>/munsub all</code></blockquote>",
        parse_mode=ParseMode.HTML)


@Client.on_message(filters.private & filters.command("mcheck"))
@check_ban
async def mcheck_cmd(client: Client, message):
    uid = message.from_user.id
    status = await message.reply(
        "<blockquote>🔄 ꜱᴄᴀɴɴɪɴɢ ʏᴏᴜʀ ꜰᴏʟʟᴏᴡꜱ…</blockquote>",
        parse_mode=ParseMode.HTML)
    try:
        updates = await check_subs(uid)
    except Exception as e:
        return await status.edit_text(
            f"<blockquote>❌ ꜱᴄᴀɴ ꜰᴀɪʟᴇᴅ: {str(e)[:120]}</blockquote>",
            parse_mode=ParseMode.HTML)
    if not updates:
        return await status.edit_text(
            "<blockquote>✅ ᴀʟʟ ᴄᴀᴜɢʜᴛ ᴜᴘ — ɴᴏ ɴᴇᴡ ᴄʜᴀᴘᴛᴇʀꜱ.</blockquote>",
            parse_mode=ParseMode.HTML)
    text, markup = _update_card(uid, updates,
                                f"🔔 {len(updates)} ꜱᴇʀɪᴇꜱ ᴜᴘᴅᴀᴛᴇᴅ!")
    try:
        await status.edit_text(text, reply_markup=markup,
                               parse_mode=ParseMode.HTML)
    except Exception:
        pass


# ─────────────────────────────────────────────
#  background loop (started from main.py)
# ─────────────────────────────────────────────
async def sub_check_loop(app):
    """Periodic follow-scan for every user; announces new chapters in DM."""
    await asyncio.sleep(90)                    # let the bot settle
    from cantarella.core.database import db
    while True:
        try:
            subs = await db.get_manga_subs()   # everyone
            by_uid = {}
            for s in subs:
                by_uid.setdefault(s.get("uid"), []).append(s)
            for uid, u_subs in by_uid.items():
                try:
                    updates = await check_subs(uid)
                except Exception as e:         # noqa: BLE001
                    logger.info("sub loop user %s failed: %s", uid, e)
                    continue
                if not updates:
                    continue
                try:
                    text, markup = _update_card(
                        uid, updates,
                        f"🔔 {len(updates)} ꜰᴏʟʟᴏᴡᴇᴅ ꜱᴇʀɪᴇꜱ ᴊᴜꜱᴛ ᴜᴘᴅᴀᴛᴇᴅ!")
                    await app.send_message(uid, text, reply_markup=markup,
                                           parse_mode=ParseMode.HTML)
                except Exception as e:         # noqa: BLE001 — user blocked bot
                    logger.info("notify %s failed: %s", uid, e)
                await asyncio.sleep(2)
        except Exception as e:                 # noqa: BLE001 — never die
            logger.warning("sub_check_loop cycle failed: %s", e)
        await asyncio.sleep(_interval_minutes() * 60)
