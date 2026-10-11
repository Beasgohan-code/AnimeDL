# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
All inline keyboard callback query handlers.

Each callback category is handled by a dedicated async function
for clarity, testability, and maintainability.
"""

import os
import sys
import logging
from datetime import datetime
from asyncio import get_running_loop

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from leechbot import app, OWNER
from leechbot.utility.variables import BOT, MSG, BotTimes, Paths
from leechbot.utility.handler import cancelTask
from leechbot.utility.helper import send_settings, sysINFO, sysINFO_full, status_keyboard
import config
from pyrogram import types

logger = logging.getLogger(__name__)



from .common import safe_answer

# =============================================================================
# Upload Type Selection
# =============================================================================
async def _handle_upload_type(client, callback_query, data: str):
    """Handle upload type selection (normal/zip/unzip/undzip)."""
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from leechbot.utility.task_manager import taskScheduler

    # Bail if bot is shutting down — the dispatcher drains pending callbacks
    # before app.stop() completes, and starting a long task here will be
    # cancelled mid-flight (noisy CancelledError traceback).
    if BOT.State.shutting_down:
        logger.warning(
            "Callback %s ignored: bot is shutting down",
            data,
        )
        try:
            await safe_answer(callback_query, "⏳ Bot is shutting down, try again later.", show_alert=True)
        except Exception:
            pass
        return

    BOT.Mode.type = data
    await callback_query.message.delete()
    if callback_query.message.reply_to_message_id:
        await app.delete_messages(
            chat_id=callback_query.message.chat.id,
            message_ids=callback_query.message.reply_to_message_id,
        )

    type_labels = {
        "normal": "📄 Regular",
        "zip": "🗜️ Compress",
        "unzip": "📂 Extract",
        "undzip": "🔄 Unzip+Zip",
    }

    MSG.status_msg = await app.send_message(
        chat_id=OWNER,
        text=f"<b>🚀 Starting {type_labels.get(data, data)} Upload...</b>\n\nPlease wait while I prepare your download",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🚫 Cancel", callback_data="cancel")]]
        ),
        link_preview_options=types.LinkPreviewOptions(is_disabled=True)
    )

    BOT.State.task_going = True
    BOT.State.started = False
    BotTimes.start_time = datetime.now()

    event_loop = get_running_loop()
    BOT.TASK = event_loop.create_task(taskScheduler())
    try:
        await BOT.TASK
    finally:
        BOT.State.task_going = False

# =============================================================================
# YTDL Confirmation
# =============================================================================
async def _handle_ytdl_confirm(client, callback_query, data: str):
    """Handle YT-DLP mode confirmation."""
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from leechbot.utility.task_manager import taskScheduler

    BOT.Mode.ytdl = data == "ytdl-true"
    await callback_query.message.delete()
    await app.delete_messages(
        chat_id=callback_query.message.chat.id,
        message_ids=callback_query.message.reply_to_message_id,
    )

    MSG.status_msg = await app.send_message(
        chat_id=OWNER,
        text="<b>🚀 Initializing YT-DLP Download...</b>\n\nPlease wait while I prepare your download",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🚫 Cancel", callback_data="cancel")]]
        ),
        link_preview_options=types.LinkPreviewOptions(is_disabled=True)
    )

    BOT.State.task_going = True
    BOT.State.started = False
    BotTimes.start_time = datetime.now()

    event_loop = get_running_loop()
    BOT.TASK = event_loop.create_task(taskScheduler())
    try:
        await BOT.TASK
    finally:
        BOT.State.task_going = False

