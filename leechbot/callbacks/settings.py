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
import logging

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from leechbot.utility.variables import BOT, Paths
from leechbot.utility.helper import send_settings
import config

logger = logging.getLogger(__name__)



from .common import safe_answer

# =============================================================================
# Video Settings
# =============================================================================
async def _handle_video_settings(client, callback_query):
    """Show video settings submenu."""
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✂️ Split", callback_data="split-true"),
            InlineKeyboardButton("Zip 🗜️", callback_data="split-false"),
        ],
        [
            InlineKeyboardButton("🔄 Convert", callback_data="convert-true"),
            InlineKeyboardButton("Skip ⏭️", callback_data="convert-false"),
        ],
        [
            InlineKeyboardButton("🎬 Mp4", callback_data="mp4"),
            InlineKeyboardButton("Mkv 📼", callback_data="mkv"),
        ],
        [
            InlineKeyboardButton("👍 High Quality", callback_data="q-High"),
            InlineKeyboardButton("Low Quality 👎", callback_data="q-Low"),
        ],
        [InlineKeyboardButton("❰ Back", callback_data="back")],
    ])

    await callback_query.message.edit_text(
        f"<b>⚙️ Video Settings</b>\n\n"
        f"• 🔄 <b>Convert:</b> <code>{BOT.Setting.convert_video}</code>\n"
        f"• ✂️ <b>Split:</b> <code>{BOT.Setting.split_video}</code>\n"
        f"• 🎬 <b>Format:</b> <code>{BOT.Options.video_out}</code>\n"
        f"• 🔴 <b>Quality:</b> <code>{BOT.Setting.convert_quality}</code>",
        reply_markup=keyboard,
    )
    await safe_answer(callback_query)

# =============================================================================
# Caption Settings
# =============================================================================
async def _handle_caption_settings(client, callback_query):
    """Show caption style submenu."""
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Monospace", callback_data="code-Monospace"),
            InlineKeyboardButton("Bold", callback_data="b-Bold"),
        ],
        [
            InlineKeyboardButton("Italic", callback_data="i-Italic"),
            InlineKeyboardButton("Underline", callback_data="u-Underlined"),
        ],
        [InlineKeyboardButton("Regular", callback_data="p-Regular")],
        [InlineKeyboardButton("❰ Back", callback_data="back")],
    ])

    await callback_query.message.edit_text(
        "<b>📝 Caption Font Style</b>\n\n"
        "<code>Monospace</code>\n"
        "Regular\n"
        "<b>Bold</b>\n"
        "<i>Italic</i>\n"
        "<u>Underline</u>",
        reply_markup=keyboard,
    )
    await safe_answer(callback_query)

# =============================================================================
# Thumbnail Settings
# =============================================================================
async def _handle_thumb_settings(client, callback_query):
    """Show thumbnail settings submenu."""
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Delete Thumbnail", callback_data="del-thumb")],
        [InlineKeyboardButton("❰ Back", callback_data="back")],
    ])

    thmb_status = "✅ Set" if BOT.Setting.thumbnail else "🚫 None"
    await callback_query.message.edit_text(
        f"<b>🖼️ Thumbnail Settings</b>\n\n"
        f"<b>Status:</b> {thmb_status}\n\n"
        f"💡 Send an image to set as thumbnail.",
        reply_markup=keyboard,
    )
    await safe_answer(callback_query)

async def _handle_delete_thumb(client, callback_query):
    """Delete the stored thumbnail."""
    if BOT.Setting.thumbnail and os.path.exists(Paths.THMB_PATH):
        try:
            os.remove(Paths.THMB_PATH)
        except OSError as e:
            logger.warning("Failed to delete thumbnail: %s", e)
    BOT.Setting.thumbnail = False
    await send_settings(client, callback_query.message, callback_query.message.id, False)
    await safe_answer(callback_query, "Thumbnail deleted ✓")

# =============================================================================
# Auto-Delete Menu
# =============================================================================
async def _handle_autodelete_menu(client, callback_query):
    """Show auto-delete settings submenu."""
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"✅ Auto-Delete: {'ON' if BOT.Setting.auto_delete else 'OFF'}",
                callback_data="toggle_autodelete",
            )
        ],
        [InlineKeyboardButton("⏱️ Set Delay", callback_data="set_autodelete_delay")],
        [InlineKeyboardButton("❰ Back", callback_data="back")],
    ])
    await callback_query.message.edit_text(
        f"<b>⏳ Auto-Delete Messages</b>\n\n"
        f"<b>Status:</b> {'Enabled' if BOT.Setting.auto_delete else 'Disabled'}\n"
        f"<b>Delay:</b> {BOT.Setting.auto_delete_delay} seconds\n\n"
        f"When enabled, bot messages will be auto-deleted after the delay.",
        reply_markup=keyboard,
    )
    await safe_answer(callback_query)

# =============================================================================
# Photo Mode Menu
# =============================================================================
async def _handle_photo_mode_menu(client, callback_query):
    """Show photo upload mode submenu."""
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    current = BOT.Setting.photo_mode
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{'✅ ' if current == 'Group' else ''}📦 Group (batch of 10)",
            callback_data="photo-group",
        )],
        [InlineKeyboardButton(
            f"{'✅ ' if current == 'Single' else ''}📷 Single (one by one)",
            callback_data="photo-single",
        )],
        [InlineKeyboardButton("❰ Back", callback_data="back")],
    ])
    await callback_query.message.edit_text(
        f"<b>📸 Photo Upload Mode</b>\n\n"
        f"<b>Current:</b> <code>{current}</code>\n\n"
        f"📦 <b>Group</b> — Send photos in batches of 10 (faster)\n"
        f"📷 <b>Single</b> — Send each photo individually\n\n"
        f"💡 Group mode uses Telegram media groups (max 10).",
        reply_markup=keyboard,
    )
    await safe_answer(callback_query)

# =============================================================================
# Screenshot Settings Menu
# =============================================================================
async def _handle_screenshot_menu(client, callback_query):
    """Show auto-screenshot settings submenu."""
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    status = "✅ ON" if BOT.Setting.auto_screenshot else "❌ OFF"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"📸 Auto-SS: {'ON' if BOT.Setting.auto_screenshot else 'OFF'}",
                callback_data="toggle_autoss",
            )
        ],
        [
            InlineKeyboardButton("➖", callback_data="ss-count-minus"),
            InlineKeyboardButton(f"Count: {BOT.Setting.screenshot_count}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data="ss-count-plus"),
        ],
        [InlineKeyboardButton("💬 Watermark", callback_data="set_ss_watermark")],
        [InlineKeyboardButton("❰ Back", callback_data="back")],
    ])
    await callback_query.message.edit_text(
        f"<b>📸 Auto-Screenshot Settings</b>\n\n"
        f"<b>Status:</b> {status}\n"
        f"<b>Count:</b> {BOT.Setting.screenshot_count}\n"
        f"<b>Watermark:</b> <code>{BOT.Setting.screenshot_watermark or 'None'}</code>\n\n"
        f"💡 Screenshots are taken after video upload completes.\n"
        f"Extracted from local file (no re-download).\n"
        f"Sent as batch to dump channel.",
        reply_markup=keyboard,
    )
    await safe_answer(callback_query)

