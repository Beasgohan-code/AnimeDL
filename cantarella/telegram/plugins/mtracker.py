# ============================================================================
#  AnimeDL MangaTracker — chapter subscriptions
#  /msubscribe /msubs /munsub /mcheck /minterval /mchannel /mexport /mimport
# ============================================================================
#  Rebuilt natively on the AnimeDL manga engine (the vendored sources/scrapers
#  layer). Polling/notification approach follows the UX of
#  auto-manga-chapter-update-bot + Manhwa-Bot; every line here is AnimeDL's
#  own — no upstream code, no upstream credits. Features:
#    • follow a series → periodic newest-chapter check (same engine)
#    • photo update cards (series cover + one-tap download)
#    • per-user check interval (/minterval) and optional update channel
#      where new chapters also get posted (/mchannel)
#    • /mexport · /mimport — follows backup as a JSON document
#    • provider responses are cached (MANGA_CACHE_TTL, default 10 min)
# ============================================================================

import asyncio
import json
import logging
import os
import time

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from cantarella.telegram.decorators import check_ban
from config import VERSION

logger = logging.getLogger(__name__)

_sub_state = {}          # uid -> {"results": [...]} for msb_ picks


def _interval_minutes() -> int:
    try:
        return max(5, int(os.getenv("MANGA_CHECK_MINUTES", "30") or "30"))
    except ValueError:
        return 30


async def _user_interval(uid: int) -> int:
    """per-user check interval (minutes) — default = operator env value."""
    try:
        from cantarella.core.database import db
        v = await db.get_user_setting(uid, "minterval", None)
        if v:
            return max(5, min(720, int(v)))
    except Exception:
        pass
    return _interval_minutes()


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
    def _work():
        from manga_sources import get_provider
        return get_provider(sub["provider"]).chapters(_sub_arg(sub))
    loop = asyncio.get_event_loop()
    chs = await loop.run_in_executor(None, _work)
    return chs[0] if chs else None


async def check_subs(uid: int = None) -> list:
    """Check follows (one user or everyone). Returns [(sub, chapter)] pairs
    newer than the stored last chapter (DB already updated). One dead
    source never kills the scan."""
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
    """(caption, markup) for a set of (sub, chapter) updates; wires the
    existing /manga chapter pipeline via mgp_ buttons."""
    from cantarella.telegram.plugins.manga import _badge
    results, lines = [], []
    for sub, ch in updates:
        results.append(_result_for(sub))
        i = len(results) - 1
        lines.append(
            f"📖 <b>{(sub.get('title') or '?')[:40]}</b> — "
            f"ᴄʜᴀᴘᴛᴇʀ <b>{ch.number}</b>"
            + (f" · {ch.title[:24]}" if ch.title else "")
            + f"  <i>{_badge(sub['provider'])}</i>")
    caption = (f"<blockquote>{header}</blockquote>\n"
               + "\n".join(f"<blockquote expandable>{l}</blockquote>"
                           for l in lines)
               + f"\n<i>ᴛᴀᴘ → ᴄʜᴀᴘᴛᴇʀꜱ → 📄/📚 · ᴀɴɪᴍᴇᴅʟ ᴠ{VERSION}</i>")
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
    return caption, InlineKeyboardMarkup(buttons)


async def deliver_updates(dest, uid: int, updates: list, header: str):
    """Send update card(s): photo card when a cover exists, text fallback.
    `dest` is anything with .reply_photo/.edit_text/.send_message style
    helpers — resolved via small adapters below."""
    caption, markup = _update_card(uid, updates, header)
    cover = next((s.get("cover") for s, _ in updates if s.get("cover")), "")
    # 1) reply-style target (a status Message)
    if hasattr(dest, "reply_photo"):
        if cover:
            try:
                m = await dest.reply_photo(cover, caption=caption,
                                           reply_markup=markup,
                                           parse_mode=ParseMode.HTML)
                return m
            except Exception:
                pass
        try:
            return await dest.reply_text(caption, reply_markup=markup,
                                         parse_mode=ParseMode.HTML)
        except Exception:
            return None
    # 2) client-style target (background loop → send_message)
    if hasattr(dest, "send_message"):
        if cover:
            try:
                return await dest.send_photo(uid, cover, caption=caption,
                                             reply_markup=markup,
                                             parse_mode=ParseMode.HTML)
            except Exception:
                pass
        try:
            return await dest.send_message(uid, caption, reply_markup=markup,
                                           parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.info("notify %s failed: %s", uid, e)
    return None


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
    import re as _re
    m = _re.match(r"^msb_([a-z]+)_(\d+)$", cq.data or "")
    if not m:
        return await cq.answer()
    pid, idx = m.group(1), int(m.group(2))
    st = _sub_state.get(uid) or {}
    results = st.get("results") or []
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
    interval = await _user_interval(uid)
    text = (f"<blockquote>🔔 <b>ꜰᴏʟʟᴏᴡɪɴɢ {title[:40]}</b></blockquote>\n"
            f"<blockquote>{r.cover and '🖼 '}"
            f"ʟᴀᴛᴇꜱᴛ ᴋɴᴏᴡɴ: ᴄʜ {saved.get('last_chapter') or '?'}\n"
            f"ʏᴏᴜ'ʟʟ ɢᴇᴛ ᴀ ᴘɪɴɢ + ᴏɴᴇ-ᴛᴀᴘ ᴅᴏᴡɴʟᴏᴀᴅ ᴡʜᴇɴ ɴᴇᴡᴇʀ ᴄʜᴀᴘᴛᴇʀꜱ ᴅʀᴏᴘ"
            f" (ᴇᴠᴇʀʏ {interval} ᴍɪɴ · /minterval ᴛᴏ ᴄʜᴀɴɢᴇ)</blockquote>")
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
    interval = await _user_interval(uid)
    try:
        chan = await db.get_user_setting(uid, "mchannel", None)
    except Exception:
        chan = None
    if not subs:
        return await message.reply(
            "<blockquote>📭 ʏᴏᴜ'ʀᴇ ɴᴏᴛ ꜰᴏʟʟᴏᴡɪɴɢ ᴀɴʏᴛʜɪɴɢ ʏᴇᴛ — /msubscribe ꜱᴏʟᴏ leveling</blockquote>",
            parse_mode=ParseMode.HTML)
    from cantarella.telegram.plugins.manga import _badge
    lines = [f"🔔 <b>{s.get('title', '?')[:36]}</b> — ʟᴀꜱᴛ ᴄʜ "
             f"{s.get('last_chapter') or '?'} <i>{_badge(s['provider'])}</i>"
             f" <code>/munsub {s['_id']}</code>"
             for s in subs[:20]]
    text = (f"<blockquote>📚 <b>ʏᴏᴜʀ ꜰᴏʟʟᴏᴡꜱ ({len(subs)})</b> · ᴄʜᴇᴄᴋ ᴇᴠᴇʀʏ "
            f"{interval} ᴍɪɴ · ᴄʜᴀɴɴᴇʟ: {('<code>' + str(chan) + '</code>') if chan else 'ᴏꜰꜰ'}</blockquote>\n"
            + "\n".join(f"<blockquote>{l}</blockquote>" for l in lines)
            + "\n<i>/mcheck ꜰᴏʀᴄᴇ ꜱᴄᴀɴ · /mexport ʙᴀᴄᴋᴜᴘ · /minterval · /mchannel</i>")
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
    await status.edit_text(f"<blockquote>🔔 {len(updates)} ꜱᴇʀɪᴇꜱ ᴜᴘᴅᴀᴛᴇᴅ!</blockquote>",
                           parse_mode=ParseMode.HTML)
    await deliver_updates(message, uid, updates, "🔔 ɴᴇᴡ ᴄʜᴀᴘᴛᴇʀꜱ:")


# ─────────────────────────────────────────────
#  /minterval · /mchannel — per-user tracker settings
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("minterval"))
@check_ban
async def minterval_cmd(client: Client, message):
    uid = message.from_user.id
    parts = (message.text or "").split()
    from cantarella.core.database import db
    if len(parts) < 2:
        cur = await _user_interval(uid)
        return await message.reply(
            f"<blockquote>⏱ ʏᴏᴜʀ ɪɴᴛᴇʀᴠᴀʟ: <b>{cur} ᴍɪɴ</b>\n"
            f"ᴜꜱᴀɢᴇ: <code>/minterval 15</code> (5–720 ᴍɪɴ)</blockquote>",
            parse_mode=ParseMode.HTML)
    try:
        v = max(5, min(720, int(parts[1])))
    except ValueError:
        return await message.reply(
            "<blockquote>❌ ɢɪᴠᴇ ᴀ ɴᴜᴍʙᴇʀ: <code>/minterval 15</code></blockquote>",
            parse_mode=ParseMode.HTML)
    await db.set_user_setting(uid, "minterval", v)
    await message.reply(
        f"<blockquote>⏱ ᴄʜᴇᴄᴋ ɪɴᴛᴇʀᴠᴀʟ ꜱᴇᴛ: <b>{v} ᴍɪɴ</b></blockquote>",
        parse_mode=ParseMode.HTML)


@Client.on_message(filters.private & filters.command("mchannel"))
@check_ban
async def mchannel_cmd(client: Client, message):
    uid = message.from_user.id
    parts = (message.text or "").split()
    from cantarella.core.database import db
    if len(parts) < 2 or parts[1].lower() == "off":
        await db.set_user_setting(uid, "mchannel", None)
        return await message.reply(
            "<blockquote>📵 ᴜᴘᴅᴀᴛᴇ ᴄʜᴀɴɴᴇʟ ᴏꜰꜰ — ᴘɪɴɢꜱ ᴄᴏᴍᴇ ʜᴇʀᴇ.</blockquote>",
            parse_mode=ParseMode.HTML)
    raw = parts[1]
    try:
        chat_id = int(raw)
    except ValueError:
        chat_id = None
    if chat_id is None and raw.lstrip("@").isidentifier():
        chat_id = raw                      # @username form
    else:
        try:
            chat_id = int(raw)
        except ValueError:
            return await message.reply(
                "<blockquote>❌ ɢɪᴠᴇ ᴀ ᴄʜᴀɴɴᴇʟ ɪᴅ ᴏʀ @ᴜꜱᴇʀɴᴀᴍᴇ: <code>/mchannel -1001234</code></blockquote>",
                parse_mode=ParseMode.HTML)
    # verify the bot can post there
    try:
        chat = await client.get_chat(chat_id)
        await client.send_message(chat.id, "<blockquote>🔔 ᴀɴɪᴍᴇᴅʟ ᴄʜᴀᴘᴛᴇʀ ᴛʀᴀᴄᴋᴇʀ ᴡɪʟʟ ᴘᴏꜱᴛ ɴᴇᴡ ᴄʜᴀᴘᴛᴇʀꜱ ʜᴇʀᴇ.</blockquote>",
                                  parse_mode=ParseMode.HTML)
    except Exception as e:
        return await message.reply(
            f"<blockquote>❌ ᴄᴀɴ'ᴛ ᴘᴏꜱᴛ ᴛʜᴇʀᴇ ({str(e)[:80]}).\n"
            f"ᴀᴅᴅ ᴍᴇ ᴀꜱ ᴀᴅᴍɪɴ ᴡɪᴛʜ ᴘᴏꜱᴛ ʀɪɢʜᴛꜱ ꜰɪʀꜱᴛ.</blockquote>",
            parse_mode=ParseMode.HTML)
    await db.set_user_setting(uid, "mchannel", chat.id if hasattr(chat, "id") else chat_id)
    await message.reply(
        "<blockquote>🔔 ᴜᴘᴅᴀᴛᴇ ᴄʜᴀɴɴᴇʟ ꜱᴇᴛ! ɴᴇᴡ ᴄʜᴀᴘᴛᴇʀ 괄ᴀʀᴅꜱ ᴡɪʟʟ ᴀʟꜱᴏ ᴀᴘᴘᴇᴀʀ ᴛʜᴇʀᴇ. (/mchannel ᴏꜰꜰ)</blockquote>",
        parse_mode=ParseMode.HTML)


# ─────────────────────────────────────────────
#  /mexport · /mimport — follows backup (JSON doc)
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("mexport"))
@check_ban
async def mexport_cmd(client: Client, message):
    uid = message.from_user.id
    from cantarella.core.database import db
    subs = await db.get_manga_subs(uid)
    if not subs:
        return await message.reply(
            "<blockquote>📭 ɴᴏᴛʜɪɴɢ ᴛᴏ ᴇxᴘᴏʀᴛ — /msubscribe ꜰɪʀꜱᴛ.</blockquote>",
            parse_mode=ParseMode.HTML)
    payload = {"animedl_msubs": 1, "subs": [
        {k: s.get(k) for k in ("provider", "series_id", "title",
                               "cover", "url", "last_chapter")}
        for s in subs]}
    import io
    doc = io.BytesIO(json.dumps(payload, indent=1).encode())
    doc.name = "animedl_msubs.json"
    await message.reply_document(doc,
        caption=f"<blockquote>📤 {len(subs)} ꜰᴏʟʟᴏᴡꜱ ᴇxᴘᴏʀᴛᴇᴅ — ʀᴇᴘʟʏ ᴛᴏ ᴛʜɪꜱ ꜰɪʟᴇ ᴡɪᴛʜ /mimport ᴛᴏ ʀᴇꜱᴛᴏʀᴇ.</blockquote>",
        parse_mode=ParseMode.HTML)


@Client.on_message(filters.private & filters.command("mimport"))
@check_ban
async def mimport_cmd(client: Client, message):
    uid = message.from_user.id
    if not (message.reply_to_message and message.reply_to_message.document):
        return await message.reply(
            "<blockquote>ʀᴇᴘʟʏ ᴛᴏ ʏᴏᴜʀ /mexport ꜰɪʟᴇ ᴡɪᴛʜ <code>/mimport</code>.</blockquote>",
            parse_mode=ParseMode.HTML)
    path = None
    try:
        path = await message.reply_to_message.download()
        data = json.loads(open(path, "rb").read())
    except Exception as e:
        return await message.reply(
            f"<blockquote>❌ ʙᴀᴅ ꜰɪʟᴇ: {str(e)[:80]}</blockquote>",
            parse_mode=ParseMode.HTML)
    finally:
        import os as _os
        try:
            path and _os.remove(path)
        except Exception:
            pass
    if not isinstance(data, dict) or not data.get("animedl_msubs"):
        return await message.reply(
            "<blockquote>❌ ᴛʜᴀᴛ'ꜱ ɴᴏᴛ ᴀɴ ᴀɴɪᴍᴇᴅʟ ꜰᴏʟʟᴏᴡꜱ ʙᴀᴄᴋᴜᴘ.</blockquote>",
            parse_mode=ParseMode.HTML)
    from cantarella.core.database import db
    added = dup = 0
    for s in (data.get("subs") or [])[:100]:
        if not s.get("provider") or not s.get("series_id"):
            continue
        saved = await db.add_manga_sub(
            uid=uid, provider=s["provider"], series_id=s["series_id"],
            title=s.get("title") or "?", cover=s.get("cover") or "",
            url=s.get("url") or "",
            last_chapter=s.get("last_chapter") or "0")
        if saved and not saved.get("added"):   # existing doc → duplicate
            dup += 1
        else:
            added += 1
    await message.reply(
        f"<blockquote>📥 ɪᴍᴘᴏʀᴛᴇᴅ: +{added} ɴᴇᴡ · {dup} ᴀʟʀᴇᴀᴅʏ ꜰᴏʟʟᴏᴡᴇᴅ — /msubs</blockquote>",
        parse_mode=ParseMode.HTML)


# ─────────────────────────────────────────────
#  background loop (started from main.py)
# ─────────────────────────────────────────────
async def sub_check_loop(app):
    """Periodic follow-scan; respects each user's /minterval and mirrors
    update cards into their /mchannel when set."""
    await asyncio.sleep(90)                    # let the bot settle
    from cantarella.core.database import db
    while True:
        try:
            subs = await db.get_manga_subs()   # everyone
            by_uid = {}
            for s in subs:
                by_uid.setdefault(s.get("uid"), []).append(s)
            now = int(time.time())
            for uid, u_subs in by_uid.items():
                interval = await _user_interval(uid)
                try:
                    last = int(await db.get_user_setting(uid, "last_scan", 0) or 0)
                except Exception:
                    last = 0
                if now - last < interval * 60:
                    continue                   # not due yet
                try:
                    await db.set_user_setting(uid, "last_scan", now)
                    updates = await check_subs(uid)
                except Exception as e:         # noqa: BLE001
                    logger.info("sub loop user %s failed: %s", uid, e)
                    continue
                if not updates:
                    continue
                header = f"🔔 {len(updates)} ꜰᴏʟʟᴏᴡᴇᴅ ꜱᴇʀɪᴇꜱ ᴊᴜꜱᴛ ᴜᴘᴅᴀᴛᴇᴅ!"
                await deliver_updates(app, uid, updates, header)
                # optional update channel
                try:
                    chan = await db.get_user_setting(uid, "mchannel", None)
                    if chan:
                        cap, mk = _update_card(uid, updates, header)
                        target = int(chan) if str(chan).lstrip("-").isdigit() else chan
                        try:
                            await app.send_photo(
                                target, next((s.get("cover") for s, _ in updates
                                              if s.get("cover")), ""),
                                caption=cap, reply_markup=mk) if any(
                                s.get("cover") for s, _ in updates) else \
                                await app.send_message(target, cap,
                                                       reply_markup=mk,
                                                       parse_mode=ParseMode.HTML)
                        except Exception as e:  # noqa: BLE001 — can't post
                            logger.info("channel %s post failed: %s", chan, e)
                except Exception:
                    pass
                await asyncio.sleep(2)
        except Exception as e:                 # noqa: BLE001 — never die
            logger.warning("sub_check_loop cycle failed: %s", e)
        await asyncio.sleep(min(15, _interval_minutes()) * 60)
