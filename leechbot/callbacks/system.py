# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
All inline keyboard callback query handlers.

Each callback category is handled by a dedicated async function
for clarity, testability, and maintainability.
"""

import logging

from pyrogram import types
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from leechbot import app
from leechbot.utility.variables import BOT, MSG, BotTimes, Paths
from leechbot.utility.helper import send_settings, sysINFO, sysINFO_full, status_keyboard
import uikit
import config

logger = logging.getLogger(__name__)



from .common import safe_answer

# =============================================================================
# System Info Refresh
# =============================================================================
def _strip_sysinfo(text: str) -> str:
    """Strip existing system info block from message text."""
    for separator in ("<b>─── System ───</b>", "<b>📊 System</b>", "<b>📊 System Info (Detailed)</b>"):
        idx = text.find(separator)
        if idx != -1:
            return text[:idx].rstrip()
    return text

async def _handle_sys_refresh(client, callback_query):
    """Refresh system info display."""
    original_text = callback_query.message.text or callback_query.message.caption or ""
    new_text = _strip_sysinfo(original_text) + sysINFO()
    try:
        if callback_query.message.photo:
            await callback_query.message.edit_caption(
                caption=new_text,
                reply_markup=status_keyboard(),
            )
        else:
            await callback_query.message.edit_text(
                text=new_text,
                link_preview_options=types.LinkPreviewOptions(is_disabled=True),
                reply_markup=status_keyboard(),
            )
        await safe_answer(callback_query, "Refreshed ✓")
    except Exception as e:
        logger.debug("Sys refresh error: %s", e)
        await safe_answer(callback_query, "No changes", show_alert=False)

async def _handle_sys_stats(client, callback_query):
    """Show detailed system stats."""
    original_text = callback_query.message.text or callback_query.message.caption or ""
    new_text = _strip_sysinfo(original_text) + sysINFO_full()
    try:
        if callback_query.message.photo:
            # captions can't carry rich markup — use the classic block
            await callback_query.message.edit_caption(
                caption=_strip_sysinfo(original_text) + sysINFO(),
                reply_markup=status_keyboard(),
            )
        else:
            await uikit.edit_where(
                client, callback_query.message.chat.id, callback_query.message.id,
                new_text,
                reply_markup=status_keyboard(),
            )
        await safe_answer(callback_query, "Detailed stats ✓")
    except Exception as e:
        logger.debug("Sys stats error: %s", e)
        await safe_answer(callback_query, "No changes", show_alert=False)


