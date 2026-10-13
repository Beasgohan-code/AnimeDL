import config
# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
About and Start navigation callbacks with photo support.
"""

import logging

from pyrogram import types
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from leechbot import app

logger = logging.getLogger(__name__)

from .common import safe_answer

try:
    from ..commands.start_help import _get_random_photo
except ImportError:
    from leechbot.commands.start_help import _get_random_photo


# =============================================================================
# About
# =============================================================================
ABOUT_TEXT = """<b>ℹ️ About AnimeDL</b>

<b>Version:</b> <code>{version}</code>
<b>Build:</b> {build_date}

<b>🤖 Bot:</b> AnimeDL
<b>📂 GitHub:</b> <a href="https://github.com/Beasgohan-code/AnimeDL">AnimeDL</a>
<b>📜 License:</b> MIT

<b>📊 Stats:</b>
• Supports <b>2000+</b> download sources
• <b>Kurigram</b> (Pyrogram fork) + asyncio

<b>🛠 Features:</b>
• Telegram, Google Drive, direct-URL, YouTube, galleries
• Video conversion, archive extract, custom thumbnails
• Per-task settings, queue, bandwidth control

<b>⚖️ Disclaimer:</b>
This bot is for personal use only. Respect copyright
laws in your jurisdiction. The developer is not
responsible for misuse."""


async def _handle_about(client, callback_query):
    """Show the About card with random photo."""
    import config

    text = ABOUT_TEXT.format(
        version=config.VERSION,
        build_date=config.BUILD_DATE,
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📖 Help", callback_data="help_all_0"),
            InlineKeyboardButton("⚙️ Settings", callback_data="settings_menu"),
        ],
        [
            InlineKeyboardButton("📂 GitHub", url="https://github.com/Beasgohan-code/AnimeDL"),
            InlineKeyboardButton("💬 Support", url=config.SUPPORT_CONTACT),
        ],
        [InlineKeyboardButton("⟵ Back", callback_data="start_back")],
    ])

    photo = _get_random_photo()
    if photo:
        try:
            await callback_query.message.edit_media(
                InputMediaPhoto(photo, caption=text),
                reply_markup=keyboard,
            )
            await safe_answer(callback_query)
            return
        except Exception:
            pass
    try:
        await callback_query.message.edit_text(
            text=text,
            reply_markup=keyboard,
            link_preview_options=types.LinkPreviewOptions(is_disabled=True),
        )
        await safe_answer(callback_query)
    except Exception as e:
        logger.debug("About edit failed: %s", e)
        await safe_answer(callback_query, "No changes", show_alert=False)


async def _handle_start_back(client, callback_query):
    """Re-show the /start welcome message in place."""
    from leechbot.commands.start_help import _send_welcome

    try:
        await _send_welcome(client, callback_query.message, edit=True)
        await safe_answer(callback_query, "Welcome ✓")
    except Exception as e:
        logger.debug("Start back failed: %s", e)
        await safe_answer(callback_query, "Use /start", show_alert=False)
