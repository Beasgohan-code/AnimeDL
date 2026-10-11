# AnimeDL — anime-engine settings callbacks (Cantarella core).
# Merged-repo behaviour: all toggles re-render the ONE unified settings
# panel (leechbot.utility.helper.send_settings) so /settings, /manage and
# every toggle button stay on the same menu.
# =============================================================================

import logging

from pyrogram import Client, filters

from cantarella.core.database import db
from config import OWNER_ID

logger = logging.getLogger(__name__)


async def _authorized(callback_query) -> bool:
    if callback_query.from_user.id == OWNER_ID:
        return True
    return await db.is_admin(callback_query.from_user.id)


async def _rerender_unified(client, callback_query):
    """Re-open the unified settings panel on the current message."""
    try:
        from leechbot.utility.helper import send_settings
        await send_settings(client, callback_query.message,
                            callback_query.message.id, False)
    except Exception as e:
        logger.error("Unified settings re-render failed: %s", e)


@Client.on_callback_query(filters.regex("^toggle_ongoing$"))
async def on_toggle_ongoing(client: Client, callback_query):
    if not await _authorized(callback_query):
        return await callback_query.answer("❌ You are not authorized to use this.", show_alert=True)

    current = await db.get_user_setting(0, "ongoing_enabled", False)
    new_status = not current
    await db.set_user_setting(0, "ongoing_enabled", new_status)

    await _rerender_unified(client, callback_query)
    await callback_query.answer(
        f"📡 Ongoing auto-download {'ᴇɴᴀʙʟᴇᴅ' if new_status else 'ᴅɪsᴀʙʟᴇᴅ'}!",
        show_alert=True,
    )


@Client.on_callback_query(filters.regex("^toggle_dm_copy$"))
async def on_toggle_dm_copy(client: Client, callback_query):
    if not await _authorized(callback_query):
        return await callback_query.answer("❌ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.", show_alert=True)
    current = await db.get_user_setting(0, "dm_copy", False)
    new_status = not current
    await db.set_user_setting(0, "dm_copy", new_status)
    await callback_query.answer(f"📨 DM copy: {'ON' if new_status else 'OFF'}")
    await _rerender_unified(client, callback_query)


@Client.on_callback_query(filters.regex("^toggle_mapping_mode$"))
async def on_toggle_mapping_mode(client: Client, callback_query):
    if not await _authorized(callback_query):
        return await callback_query.answer("❌ You are not authorized to use this.", show_alert=True)

    current = await db.get_user_setting(0, "mapping_batch_mode", True)
    new_status = not current
    await db.set_user_setting(0, "mapping_batch_mode", new_status)

    await _rerender_unified(client, callback_query)
    await callback_query.answer(
        f"🔗 Mapping mode set to {'ʙᴀᴛᴄʜ' if new_status else 'ꜱɪɴɢʟᴇ'}!",
        show_alert=True,
    )


@Client.on_callback_query(filters.regex("^toggle_active_source$"))
async def on_toggle_active_source(client: Client, callback_query):
    if not await _authorized(callback_query):
        return await callback_query.answer("❌ You are not authorized to use this.", show_alert=True)

    from anime_sources.base import SOURCE_CYCLE, SOURCE_NAMES

    current = await db.get_user_setting(0, "active_source", "animetsu")
    try:
        idx = SOURCE_CYCLE.index(current)
    except ValueError:
        idx = -1
    new_source = SOURCE_CYCLE[(idx + 1) % len(SOURCE_CYCLE)]
    await db.set_user_setting(0, "active_source", new_source)

    await _rerender_unified(client, callback_query)
    await callback_query.answer(
        f"🌐 Source → {SOURCE_NAMES.get(new_source, new_source)}",
        show_alert=True,
    )
