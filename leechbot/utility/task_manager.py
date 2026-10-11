# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================

"""
Task scheduler and orchestrator for download/upload workflows.
"""

import pytz
import shutil
import random
import logging
from time import time
from datetime import datetime
from pyrogram import types

import config
from asyncio import sleep
from os import makedirs, path as ospath
from leechbot import OWNER, app, DUMP_ID
from leechbot.downloader.manager import calDownSize, get_d_name, downloadManager
from leechbot.utility.helper import getSize, applyCustomName, keyboard, sysINFO, is_google_drive, is_ytdl_link, is_mega, is_terabox, is_torrent
from leechbot.utility.handler import Leech, Unzip_Handler, Zip_Handler, SendLogs, cancelTask
from leechbot.utility.variables import BOT, MSG, BotTimes, Messages, Paths, Transfer, TaskError, BotStats

logger = logging.getLogger(__name__)


# =============================================================================
# Task Starter
# =============================================================================
async def task_starter(message, text: str):
    """
    Initiate a new task.

    Args:
        message: Telegram message object
        text: instruction text to send

    Returns:
        message: request message object
    """
    from leechbot.utility.variables import BOT

    await message.delete()
    BOT.State.started = True

    if not BOT.State.task_going:
        src_request_msg = await message.reply_text(text)
        return src_request_msg
    else:
        msg = await message.reply_text("<b>⏳ I'm Already Working! Please Wait...</b>")
        await sleep(15)
        await msg.delete()
        return None


# =============================================================================
# Main Task Scheduler
# =============================================================================
async def taskScheduler():
    """
    Main task scheduler that orchestrates the entire download/upload workflow.
    """
    from leechbot.utility.variables import BOT, MSG, BotTimes, Messages, Paths, Transfer, TaskError

    # Bail if bot is shutting down — see __main__.py:startup() and
    # callbacks.py:_handle_upload_type for the full shutdown flow.
    # This is a defensive check: _handle_upload_type should already have
    # prevented this call, but in case it was bypassed (e.g. via
    # task_starter for queued messages), we bail here too.
    if BOT.State.shutting_down:
        logger.warning("taskScheduler bailing: bot is shutting down")
        return

    # Determine task type
    is_dualzip = BOT.Mode.type == "undzip"
    is_unzip = BOT.Mode.type == "unzip"
    is_zip = BOT.Mode.type == "zip"
    is_dir = BOT.Mode.mode == "dir-leech"
    is_gallery = BOT.Mode.gallery

    # Reset messages
    Messages.download_name = ""
    Messages.task_msg = "<b>🎯 Task Mode:</b> "
    mode_label = "Gallery" if is_gallery else BOT.Mode.mode.capitalize()
    Messages.dump_task = Messages.task_msg + f"<code>{BOT.Mode.type.capitalize()} {mode_label} as {BOT.Setting.stream_upload}</code>\n\n<b>🔗 Sources:</b>"

    # Reset transfer state
    Paths.down_path = str(config.DOWNLOADS_PATH)
    Transfer.sent_file = []
    Transfer.sent_file_names = []
    Transfer.down_bytes = [0, 0]
    Transfer.up_bytes = [0, 0]
    Transfer.total_down_size = 0
    Messages.download_name = ""
    Messages.task_msg = ""
    Messages.status_head = "<b>📥 Downloading</b>\n"

    # Handle directory leech
    if is_dir:
        if not ospath.exists(BOT.SOURCE[0]):
            TaskError.state = True
            TaskError.text = "Directory path does not exist"
            logger.error(TaskError.text)
            return

        if not ospath.exists(Paths.temp_dirleech_path):
            makedirs(Paths.temp_dirleech_path)

        Messages.dump_task += f"\n\n📁 `{BOT.SOURCE[0]}`"
        Transfer.total_down_size = getSize(BOT.SOURCE[0])
        Messages.download_name = ospath.basename(BOT.SOURCE[0])

    else:  # URL list
        for link in BOT.SOURCE:
            if is_google_drive(link):
                icon = "♻️"
            elif is_torrent(link):
                icon = "🧲"
                Messages.caution_msg = "\n\n⚠️ <b>Torrents Are Restricted In Some Environments</b>"
            elif is_ytdl_link(link):
                icon = "🏮"
            elif is_terabox(link):
                icon = "🍑"
            elif is_mega(link):
                icon = "💾"
            else:
                icon = "🔗"

            code_link = f"\n\n{icon} `{link}`"

            if len(Messages.dump_task + code_link) >= 4096:
                await MSG.sent_msg.reply_text(Messages.dump_task)
                Messages.dump_task = code_link
            else:
                Messages.dump_task += code_link

    # Add timestamp
    cdt = datetime.now(pytz.timezone("Asia/Kolkata"))
    dt = cdt.strftime(" %d-%m-%Y")
    Messages.dump_task += f"\n\n<b>📅 Date:</b> <code>{dt}</code>"

    # Create working directories
    if ospath.exists(Paths.WORK_PATH):
        shutil.rmtree(Paths.WORK_PATH, ignore_errors=True)
        makedirs(Paths.down_path)
    else:
        makedirs(Paths.WORK_PATH)
        makedirs(Paths.down_path)

    Messages.link_p = str(DUMP_ID)[4:]

    # Pick random hero image from assets/images/
    try:
        import glob as _glob
        images = _glob.glob(ospath.join(Paths.ASSETS_IMAGES, "*.jpg")) + \
                 _glob.glob(ospath.join(Paths.ASSETS_IMAGES, "*.png")) + \
                 _glob.glob(ospath.join(Paths.ASSETS_IMAGES, "*.webp"))
        if images:
            Paths.HERO_IMAGE = random.choice(images)
            Paths.DEFAULT_HERO = images[0]
        else:
            logger.warning("No hero images found in %s", Paths.ASSETS_IMAGES)
    except Exception:
        pass

    # Send task log
    MSG.sent_msg = await app.send_message(chat_id=DUMP_ID, text=Messages.dump_task, link_preview_options=types.LinkPreviewOptions(is_disabled=True))
    Messages.src_link = f"https://t.me/c/{Messages.link_p}/{MSG.sent_msg.id}"
    Messages.task_msg += f"[{BOT.Mode.type.capitalize()} {mode_label} as {BOT.Setting.stream_upload}]({Messages.src_link})\n\n"

    # Update status message
    await MSG.status_msg.delete()
    img = Paths.THMB_PATH if ospath.exists(Paths.THMB_PATH) else Paths.HERO_IMAGE
    logger.info("Status image: %s (exists: %s)", img, ospath.exists(img) if img else False)
    caption = Messages.task_msg + Messages.status_head + "\n📝 Initializing..." + sysINFO()

    if img and ospath.exists(img):
        try:
            MSG.status_msg = await app.send_photo(
                chat_id=OWNER,
                photo=img,
                caption=caption,
                reply_markup=keyboard()
            )
        except Exception as e:
            logger.error("send_photo failed: %s — falling back to text", e)
            MSG.status_msg = await app.send_message(
                chat_id=OWNER,
                text=caption,
                reply_markup=keyboard(),
                link_preview_options=types.LinkPreviewOptions(is_disabled=True)
            )
    else:
        MSG.status_msg = await app.send_message(
            chat_id=OWNER,
            text=caption,
            reply_markup=keyboard(),
            link_preview_options=types.LinkPreviewOptions(is_disabled=True)
        )

    # Calculate download size
    await calDownSize(BOT.SOURCE)

    # Get download name
    if not is_dir:
        await get_d_name(BOT.SOURCE[0])
    else:
        Messages.download_name = ospath.basename(BOT.SOURCE[0])

    # Prepare zip path if needed
    if is_zip:
        Paths.down_path = ospath.join(Paths.down_path, Messages.download_name)
        if not ospath.exists(Paths.down_path):
            makedirs(Paths.down_path)

    BotTimes.current_time = time()

    # Execute task
    if BOT.Mode.mode != "mirror":
        await Do_Leech(BOT.SOURCE, is_dir, BOT.Mode.ytdl, is_zip, is_unzip, is_dualzip)
    else:
        await Do_Mirror(BOT.SOURCE, BOT.Mode.ytdl, is_zip, is_unzip, is_dualzip)


# =============================================================================
# Leech Execution
# =============================================================================
async def Do_Leech(source, is_dir: bool, is_ytdl: bool, is_zip: bool, is_unzip: bool, is_dualzip: bool):
    """
    Execute leech task.

    Args:
        source: list of sources
        is_dir: directory leech flag
        is_ytdl: YT-DLP mode flag
        is_zip: zip output flag
        is_unzip: unzip input flag
        is_dualzip: unzip then zip flag
    """
    from leechbot.utility.variables import Paths, Messages, Transfer, BOT
    if is_dir:
        for s in source:
            if not ospath.exists(s):
                logger.error("Directory does not exist")
                await cancelTask("Directory does not exist")
                return

            Paths.down_path = s

            if is_zip:
                await Zip_Handler(Paths.down_path, True, False)
                await Leech(Paths.temp_zpath, True)
            elif is_unzip:
                await Unzip_Handler(Paths.down_path, False)
                await Leech(Paths.temp_unzip_path, True)
            elif is_dualzip:
                await Unzip_Handler(Paths.down_path, False)
                await Zip_Handler(Paths.temp_unzip_path, True, True)
                await Leech(Paths.temp_zpath, True)
            else:
                if ospath.isdir(s):
                    await Leech(Paths.down_path, False)
                else:
                    Transfer.total_down_size = ospath.getsize(s)
                    makedirs(Paths.temp_dirleech_path)
                    shutil.copy(s, Paths.temp_dirleech_path)
                    Messages.download_name = ospath.basename(s)
                    await Leech(Paths.temp_dirleech_path, True)
    else:
        await downloadManager(source, is_ytdl)
        Transfer.total_down_size = getSize(Paths.down_path)
        applyCustomName()

        if is_zip:
            await Zip_Handler(Paths.down_path, True, True)
            await Leech(Paths.temp_zpath, True)
        elif is_unzip:
            await Unzip_Handler(Paths.down_path, True)
            await Leech(Paths.temp_unzip_path, True)
        elif is_dualzip:
            await Unzip_Handler(Paths.down_path, True)
            await Zip_Handler(Paths.temp_unzip_path, True, True)
            await Leech(Paths.temp_zpath, True)
        else:
            await Leech(Paths.down_path, True)

    await SendLogs(True)
    BotStats.total_downloaded += sum(Transfer.down_bytes)
    BotStats.total_uploaded += sum(Transfer.up_bytes)


# =============================================================================
# Mirror Execution
# =============================================================================
async def Do_Mirror(source, is_ytdl: bool, is_zip: bool, is_unzip: bool, is_dualzip: bool):
    """
    Execute mirror task (upload to Google Drive).

    Args:
        source: list of sources
        is_ytdl: YT-DLP mode flag
        is_zip: zip output flag
        is_unzip: unzip input flag
        is_dualzip: unzip then zip flag
    """
    from leechbot.utility.variables import Paths, Messages, Transfer
    if not ospath.exists(Paths.MOUNTED_DRIVE):
        await cancelTask("Google Drive is not mounted")
        return

    if not ospath.exists(Paths.mirror_dir):
        makedirs(Paths.mirror_dir)

    await downloadManager(source, is_ytdl)
    Transfer.total_down_size = getSize(Paths.down_path)
    applyCustomName()

    if is_zip:
        await Zip_Handler(Paths.down_path, True, True)
        shutil.copytree(Paths.temp_zpath, Paths.mirror_dir, dirs_exist_ok=True)
    elif is_unzip:
        await Unzip_Handler(Paths.down_path, True)
        shutil.copytree(Paths.temp_unzip_path, Paths.mirror_dir, dirs_exist_ok=True)
    elif is_dualzip:
        await Unzip_Handler(Paths.down_path, True)
        await Zip_Handler(Paths.temp_unzip_path, True, True)
        shutil.copytree(Paths.temp_zpath, Paths.mirror_dir, dirs_exist_ok=True)
    else:
        shutil.copytree(Paths.down_path, Paths.mirror_dir, dirs_exist_ok=True)

    await SendLogs(False)
    BotStats.total_downloaded += sum(Transfer.down_bytes)
