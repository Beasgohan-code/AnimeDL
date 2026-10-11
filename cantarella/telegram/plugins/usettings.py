# ============================================================================
#  AnimeDL — user preferences (/usettings) + premium status (/premium)
# ============================================================================
#  • /usettings → per-user menu:
#      📖 default manga format (PDF / CBZ — pre-selects the /manga download)
#      🔞 18+ sources ON/OFF  (💎 premium only; NSFW is never on by default)
#  • /premium → shows premium status, expiry and what it unlocks.
#  Settings persist in Mongo (user_settings collection) via core Database.
# ============================================================================

import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from cantarella.telegram.decorators import check_ban
from config import VERSION

logger = logging.getLogger(__name__)


async def _load_prefs(user_id: int) -> dict:
    """(format, show_nsfw, is_premium, until) — tolerant to mongo hiccups."""
    fmt, show_nsfw, prem, until = "pdf", False, False, ""
    try:
        from cantarella.core.database import db
        fmt = await db.get_user_setting(user_id, "manga_format", "pdf") or "pdf"
        show_nsfw = bool(await db.get_user_setting(user_id, "show_nsfw", False))
        prem = await db.is_premium(user_id)
        if prem:
            until = await db.premium_until(user_id)
    except Exception as e:
        logger.info("usettings: db unavailable (%s)", e)
    return {"fmt": "cbz" if fmt == "cbz" else "pdf", "nsfw": show_nsfw,
            "premium": prem, "until": until}


def _settings_markup(prefs: dict) -> InlineKeyboardMarkup:
    fmt_icon = "📚 ᴄʙᴢ" if prefs["fmt"] == "cbz" else "📄 ᴘᴅꜰ"
    other = "pdf" if prefs["fmt"] == "cbz" else "cbz"
    other_icon = "📄 ᴘᴅꜰ" if other == "pdf" else "📚 ᴄʙᴢ"
    nsfw_lbl = "🔞 18+ ꜱᴏᴜʀᴄᴇꜱ: ᴏɴ" if prefs["nsfw"] else "🔞 18+ ꜱᴏᴜʀᴄᴇꜱ: ᴏꜰꜰ"
    rows = [
        [InlineKeyboardButton(
            f"📖 ᴍᴀɴɢᴀ ꜰᴏʀᴍᴀᴛ: {fmt_icon} (ᴛᴀᴘ → {other_icon})",
            callback_data=f"us_fmt_{other}")],
    ]
    if prefs["premium"]:
        rows.append([InlineKeyboardButton(nsfw_lbl, callback_data="us_nsfw")])
    else:
        rows.append([InlineKeyboardButton(
            "🔒 18+ ꜱᴏᴜʀᴄᴇꜱ — 💎 ᴘʀᴇᴍɪᴜᴍ ᴏɴʟʏ", callback_data="us_premupsell")])
    rows.append([InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ", callback_data="us_close")])
    return InlineKeyboardMarkup(rows)


def _settings_text(prefs: dict) -> str:
    fmt_lbl = "ᴄʙᴢ" if prefs["fmt"] == "cbz" else "ᴘᴅꜰ"
    prem_line = (f"💎 ᴘʀᴇᴍɪᴜᴍ: ᴀᴄᴛɪᴠᴇ ᴜɴᴛɪʟ <b>{prefs['until'][:10]}</b>"
                 if prefs["premium"] else
                 "💎 ᴘʀᴇᴍɪᴜᴍ: ɴᴏᴛ ᴀᴄᴛɪᴠᴇ — /premium ꜰᴏʀ ɪɴꜰᴏ")
    return (f"<blockquote>⚙️ <b>ʏᴏᴜʀ ꜱᴇᴛᴛɪɴɢꜱ</b> · ᴀɴɪᴍᴇᴅʟ ᴠ{VERSION}</blockquote>\n"
            f"<blockquote>📖 ᴍᴀɴɢᴀ ꜰᴏʀᴍᴀᴛ: <b>{fmt_lbl}</b>\n"
            f"🔞 18+ ꜱᴏᴜʀᴄᴇꜱ: <b>{'ᴏɴ' if prefs['nsfw'] else 'ᴏꜰꜰ'}</b>\n"
            f"{prem_line}</blockquote>\n"
            "<i>ᴛᴀᴘ ᴀɴ ᴏᴘᴛɪᴏɴ ᴛᴏ ᴄʜᴀɴɢᴇ ɪᴛ.</i>")


@Client.on_message(filters.private & filters.command("usettings"))
@check_ban
async def usettings_cmd(client: Client, message):
    prefs = await _load_prefs(message.from_user.id)
    await message.reply(_settings_text(prefs),
                        reply_markup=_settings_markup(prefs),
                        parse_mode=ParseMode.HTML)


@Client.on_message(filters.private & filters.command("premium"))
@check_ban
async def premium_cmd(client: Client, message):
    prefs = await _load_prefs(message.from_user.id)
    if prefs["premium"]:
        text = (f"<blockquote>💎 <b>ᴘʀᴇᴍɪᴜᴍ ᴀᴄᴛɪᴠᴇ</b></blockquote>\n"
                f"<blockquote>✦ ᴠᴀʟɪᴅ ᴜɴᴛɪʟ: <b>{prefs['until'][:10]}</b>\n"
                f"✦ ᴜɴʟᴏᴄᴋꜱ: 🔞 18+ ᴍᴀɴɢᴀ/ᴍᴀɴʜᴡᴀ ꜱᴏᴜʀᴄᴇꜱ ɪɴ /manga\n"
                f"✦ ᴍᴀɴᴀɢᴇ ɪᴛ: /usettings → 🔞 ᴛᴏɢɢʟᴇ</blockquote>")
    else:
        text = (f"<blockquote>💎 <b>ᴀɴɪᴍᴇᴅʟ ᴘʀᴇᴍɪᴜᴍ</b></blockquote>\n"
                f"<blockquote>✦ ᴜɴʟᴏᴄᴋꜱ 🔞 18+ ᴍᴀɴɢᴀ/ᴍᴀɴʜᴡᴀ ꜱᴏᴜʀᴄᴇꜱ (ᴍᴀɴʜᴡᴀᴄʟᴀɴ · ᴍᴀɴɢᴀ18 · ᴍᴏʀᴇ)\n"
                f"✦ ᴀꜱᴋ ᴛʜᴇ ʙᴏᴛ ᴏᴡɴᴇʀ ᴛᴏ ᴀᴄᴛɪᴠᴀᴛᴇ ɪᴛ ꜰᴏʀ ʏᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ\n"
                f"✦ ʏᴏᴜʀ ɪᴅ: <code>{message.from_user.id}</code> — ꜱᴇɴᴅ ɪᴛ ᴛᴏ ᴛʜᴇ ᴏᴡɴᴇʀ</blockquote>")
    await message.reply(text, parse_mode=ParseMode.HTML)


@Client.on_callback_query(filters.regex(r"^us_fmt_(pdf|cbz)$"))
async def on_us_fmt(client: Client, cq):
    fmt = cq.pattern.group(1)
    try:
        from cantarella.core.database import db
        await db.set_user_setting(cq.from_user.id, "manga_format", fmt)
    except Exception as e:
        logger.info("usettings fmt save failed: %s", e)
    prefs = await _load_prefs(cq.from_user.id)
    await cq.answer(f"📖 ᴅᴇꜰᴀᴜʟᴛ: {fmt.upper()}")
    try:
        await cq.message.edit_text(_settings_text(prefs),
                                   reply_markup=_settings_markup(prefs),
                                   parse_mode=ParseMode.HTML)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^us_nsfw$"))
async def on_us_nsfw(client: Client, cq):
    prefs = await _load_prefs(cq.from_user.id)
    if not prefs["premium"]:
        return await cq.answer(
            "💎 18+ ꜱᴏᴜʀᴄᴇꜱ ɴᴇᴇᴅ ᴘʀᴇᴍɪᴜᴍ — /premium ꜰᴏʀ ɪɴꜰᴏ.", show_alert=True)
    new_val = not prefs["nsfw"]
    try:
        from cantarella.core.database import db
        await db.set_user_setting(cq.from_user.id, "show_nsfw", new_val)
    except Exception as e:
        logger.info("usettings nsfw save failed: %s", e)
    prefs = await _load_prefs(cq.from_user.id)
    await cq.answer("🔞 18+ ꜱᴏᴜʀᴄᴇꜱ: " + ("ᴏɴ" if new_val else "ᴏꜰꜰ"))
    try:
        await cq.message.edit_text(_settings_text(prefs),
                                   reply_markup=_settings_markup(prefs),
                                   parse_mode=ParseMode.HTML)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^us_premupsell$"))
async def on_us_premupsell(client: Client, cq):
    await cq.answer(
        "💎 18+ ꜱᴏᴜʀᴄᴇꜱ ᴀʀᴇ ᴘʀᴇᴍɪᴜᴍ-ᴏɴʟʏ — /premium ꜰᴏʀ ɪɴꜰᴏ.", show_alert=True)


@Client.on_callback_query(filters.regex(r"^us_close$"))
async def on_us_close(client: Client, cq):
    try:
        await cq.message.delete()
    except Exception:
        pass
    await cq.answer()
