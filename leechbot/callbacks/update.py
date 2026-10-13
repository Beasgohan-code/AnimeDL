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

logger = logging.getLogger(__name__)



from .common import safe_answer

# =============================================================================
# Do Update
# =============================================================================
async def _handle_do_update(client, callback_query):
    """Handle the update action."""
    from leechbot.updater import perform_update

    await callback_query.message.edit_text("<b>🔄 Updating... Please wait.</b>")
    await safe_answer(callback_query, "Updating...")

    result = perform_update()

    if result["success"]:
        await callback_query.message.edit_text(
            f"<b>✅ Update Complete!</b>\n\n"
            f"<b>New commit:</b> <code>{result['new_commit']}</code>\n\n"
            f"⚠️ <b>Restart required.</b> Bot will restart automatically.\n\n"
            f"{result['message'][:1000]}"
        )
        logger.info("Restarting after update...")
        try:
            os.execv(sys.executable, [sys.executable, "-m", "leechbot"])
        except Exception as e:
            logger.error("Restart failed: %s", e)
            await callback_query.message.edit_text(
                f"<b>✅ Update Complete!</b>\n\n"
                f"<b>New commit:</b> <code>{result['new_commit']}</code>\n\n"
                f"⚠️ <b>Auto-restart failed.</b> Please restart manually.\n"
                f"<code>python3 -m leechbot</code>"
            )
    else:
        await callback_query.message.edit_text(
            f"<b>❌ Update Failed</b>\n\n<code>{result['message'][:500]}</code>"
        )

