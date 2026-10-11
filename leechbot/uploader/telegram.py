# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================

"""
Telegram uploader module.

Handles uploading files to Telegram with progress tracking.
Optimized for speed: larger chunk_size reduces round-trips.
"""

import os
import logging
import asyncio
from typing import Optional
from PIL import Image
from asyncio import sleep
from os import path as ospath
from datetime import datetime
from pyrogram import types
from pyrogram.errors import FloodWait
from pyrogram.types import InputMediaPhoto  # <--- Added for batch upload
from leechbot.utility.variables import BOT, Transfer, BotTimes, Messages, MSG, Paths
from leechbot.utility.helper import sizeUnit, fileType, getTime, status_bar, thumbMaintainer, videoExtFix

logger = logging.getLogger(__name__)

# Upload chunk size — 5MB (default Pyrogram is 1MB).
# Larger chunks = fewer HTTP round-trips = faster upload.
# Telegram supports up to 50MB chunks for bots; 5MB is a good speed/memory balance.
UPLOAD_CHUNK_SIZE = 10 * 1024 * 1024  # 10MB


# =============================================================================
# Upload Progress Callback
# =============================================================================
async def progress_bar(current: int, total: int):
    """
    Update upload progress.

    Args:
        current: bytes uploaded for this file
        total: total file size (from Pyrogram)
    """
    elapsed = max((datetime.now() - BotTimes.task_start).total_seconds(), 0.01)

    if current > 0 and elapsed > 0:
        upload_speed = current / elapsed
    else:
        upload_speed = 4 * 1024 * 1024  # Default 4MB/s

    file_total = total if total > 0 else Transfer.total_down_size
    remaining = max(file_total - current, 0)
    eta = remaining / upload_speed if upload_speed > 0 else 0
    percentage = min(current / max(file_total, 1) * 100, 100)

    await status_bar(
        down_msg=Messages.status_head,
        speed=f"{sizeUnit(upload_speed)}/s",
        percentage=percentage,
        eta=getTime(eta),
        done=sizeUnit(current),
        left=sizeUnit(file_total),
        engine="Telegram 📤"
    )


# =============================================================================
# Main Upload Function
# =============================================================================
async def upload_file(file_path: str, real_name: str, _retry_depth: int = 0):
    """
    Upload file to Telegram.

    Args:
        file_path: path to file
        real_name: original filename
    """
    BotTimes.task_start = datetime.now()

    # Build styled caption
    caption = f"<{BOT.Options.caption}>{BOT.Setting.prefix} {real_name} {BOT.Setting.suffix}</{BOT.Options.caption}>"

    # Determine file type
    type_ = fileType(file_path)
    f_type = type_ if BOT.Options.stream_upload else "document"

    try:
        if f_type == "video":
            # Video upload
            if not BOT.Options.stream_upload:
                file_path = videoExtFix(file_path)

            thmb_path, seconds = thumbMaintainer(file_path, original_name=real_name)

            # Use thumbnail if valid, otherwise skip
            if thmb_path and ospath.exists(thmb_path):
                with Image.open(thmb_path) as img:
                    width, height = img.size
            else:
                width, height = 0, 0
                thmb_path = None

            MSG.sent_msg = await MSG.sent_msg.reply_video(
                video=file_path,
                supports_streaming=True,
                width=width,
                height=height,
                caption=caption,
                thumb=thmb_path,
                duration=int(seconds),
                progress=progress_bar,
                reply_parameters=types.ReplyParameters(message_id=MSG.sent_msg.id),
            )

        elif f_type == "audio":
            # Audio upload
            thmb_path = Paths.THMB_PATH if ospath.exists(Paths.THMB_PATH) else None

            MSG.sent_msg = await MSG.sent_msg.reply_audio(
                audio=file_path,
                caption=caption,
                thumb=thmb_path,
                progress=progress_bar,
                reply_parameters=types.ReplyParameters(message_id=MSG.sent_msg.id),
            )

        elif f_type == "photo":
            # Photo upload (single, kept for backward compatibility)
            MSG.sent_msg = await MSG.sent_msg.reply_photo(
                photo=file_path,
                caption=caption,
                progress=progress_bar,
                reply_parameters=types.ReplyParameters(message_id=MSG.sent_msg.id),
            )

        else:
            # Document upload
            if ospath.exists(Paths.THMB_PATH):
                thmb_path = Paths.THMB_PATH
            elif type_ == "video":
                thmb_path, _ = thumbMaintainer(file_path, original_name=real_name)
            else:
                thmb_path = None

            MSG.sent_msg = await MSG.sent_msg.reply_document(
                document=file_path,
                caption=caption,
                thumb=thmb_path,
                progress=progress_bar,
                reply_parameters=types.ReplyParameters(message_id=MSG.sent_msg.id),
            )

        # Track sent files
        Transfer.sent_file.append(MSG.sent_msg)
        Transfer.sent_file_names.append(real_name)

    except asyncio.CancelledError:
        # Bot is shutting down (SIGINT/SIGTERM, Colab runtime disconnect,
        # or the /restart command). The current upload was cancelled mid-
        # stream by Pyrogram's dispatcher draining pending handlers.
        # Log a clean message instead of letting the CancelledError propagate
        # and produce a scary traceback at the top of the user's log.
        logger.warning(
            "Upload of %s cancelled (bot shutting down) — partial upload discarded",
            real_name,
        )
        raise  # Re-raise so the dispatcher knows to stop, but the warning is logged

    except FloodWait as e:
        if _retry_depth >= 10:
            logger.error(f"FloodWait exceeded max retries for {real_name}")
            raise
        logger.warning(f"Flood wait: waiting {e.value} seconds (retry {_retry_depth + 1}/10)")
        await sleep(e.value + 1)  # +1s safety margin
        await upload_file(file_path, real_name, _retry_depth=_retry_depth + 1)

    except Exception as e:
        logger.error(f"Upload error: {e}")


# =============================================================================
# Batch Photo Upload (New) 29-04-2026
# =============================================================================
async def _upload_photo_with_progress(file_path: str, caption: Optional[str], photo_idx: int, total_photos: int, processed: int, _retry_depth: int = 0):
    """
    Upload a single photo with progress tracking and return its file_id.

    Since reply_media_group() doesn't support progress callbacks, we upload
    each photo individually first (with full progress bar), grab the file_id,
    then delete the temporary message. The file_id is later used in the
    media group call which is instant (no re-upload).

    Args:
        file_path: path to photo file
        caption: caption text (only for first photo in group, else None)
        photo_idx: 0-based index of this photo within the current batch
        total_photos: total number of photos across all batches
        processed: number of photos already uploaded in previous batches

    Returns:
        file_id string on success, None on failure
    """
    real_name = ospath.basename(file_path)
    current_global = processed + photo_idx + 1
    Messages.status_head = (
        f"<b>📸 Uploading Photos</b> <code>{current_global}/{total_photos}</code>\n\n"
        f"<code>{real_name}</code>\n"
    )

    BotTimes.task_start = datetime.now()

    # Convert .webp to .png if needed (Telegram doesn't accept .webp as photo)
    upload_path = file_path
    if file_path.lower().endswith('.webp'):
        try:
            png_path = file_path.rsplit('.', 1)[0] + '.png'
            with Image.open(file_path) as img:
                img.save(png_path, 'PNG')
            upload_path = png_path
        except Exception as e:
            logger.warning(f"Failed to convert webp to png: {e}, sending as document")
            upload_path = file_path

    try:
        # If conversion failed or file is still .webp, send as document
        if upload_path.lower().endswith('.webp'):
            temp_msg = await MSG.sent_msg.reply_document(
                document=upload_path,
                caption=caption,
                progress=progress_bar,
                reply_parameters=types.ReplyParameters(message_id=MSG.sent_msg.id),
            )
            file_id = temp_msg.document.file_id
        else:
            temp_msg = await MSG.sent_msg.reply_photo(
                photo=upload_path,
                caption=caption,
                progress=progress_bar,
                reply_parameters=types.ReplyParameters(message_id=MSG.sent_msg.id),
            )
            file_id = temp_msg.photo.file_id

        # Delete the temporary individual photo message
        try:
            await temp_msg.delete()
        except Exception:
            pass

        # Clean up converted file if we created one
        if upload_path != file_path and ospath.exists(upload_path):
            try:
                ospath.remove(upload_path)
            except Exception:
                pass

        return file_id

    except FloodWait as e:
        if _retry_depth >= 10:
            logger.error(f"FloodWait max retries (10) reached for photo upload")
            return None
        logger.warning(f"Flood wait: waiting {e.value} seconds (retry {_retry_depth + 1}/10)")
        await sleep(e.value)
        return await _upload_photo_with_progress(file_path, caption, photo_idx, total_photos, processed, _retry_depth + 1)

    except Exception as e:
        logger.error(f"Photo upload error ({real_name}): {e}")
        return None


async def upload_photos_batch(photo_paths: list, remove: bool = False):
    """
    Upload multiple photos in batches of 10 using media groups.

    Each photo is uploaded individually first with a full progress bar
    (speed, ETA, percentage), then grouped into albums via file_id.
    The media group send is instant since files are already on Telegram servers.

    Args:
        photo_paths: list of absolute paths to photo files
        remove: whether to remove files after successful upload
    """
    if not photo_paths:
        return

    total_photos = len(photo_paths)
    batch_size = 10
    processed = 0
    i = 0

    while i < total_photos:
        batch = photo_paths[i:i + batch_size]
        media_group = []
        batch_names = []

        # Update batch label
        batch_label = f"{processed + 1}–{min(processed + batch_size, total_photos)}"

        for idx, file_path in enumerate(batch):
            real_name = ospath.basename(file_path)
            batch_names.append(real_name)

            # Caption only on first photo of each group
            caption = None
            if idx == 0:
                caption = f"<{BOT.Options.caption}>{BOT.Setting.prefix} {real_name} {BOT.Setting.suffix}</{BOT.Options.caption}>"

            # Upload individually with progress → get file_id
            file_id = await _upload_photo_with_progress(
                file_path, caption, idx, total_photos, processed
            )

            if file_id:
                media_group.append(InputMediaPhoto(media=file_id))
            else:
                logger.warning(f"Skipping {real_name} — upload failed")

            # Track upload bytes regardless
            try:
                Transfer.up_bytes.append(os.stat(file_path).st_size)
            except OSError:
                pass

        try:
            if media_group:
                # Send the media group (instant — files already on servers)
                Messages.status_head = (
                    f"<b>📤 Grouping Photos</b> <code>{batch_label}/{total_photos}</code>\n\n"
                )
                await status_bar(
                    down_msg=Messages.status_head,
                    speed="—",
                    percentage=min((processed / max(total_photos, 1)) * 100, 100),
                    eta="—",
                    done=sizeUnit(sum(Transfer.up_bytes)),
                    left=sizeUnit(Transfer.total_down_size),
                    engine="Telegram 📤",
                )

                messages = await MSG.sent_msg.reply_media_group(
                    media=media_group,
                    reply_parameters=types.ReplyParameters(message_id=MSG.sent_msg.id)
                )

                # Update the chaining message to the first of this group
                MSG.sent_msg = messages[0]

                # Track sent files
                Transfer.sent_file.extend(messages)
                Transfer.sent_file_names.extend(batch_names)

            # Clean up uploaded files if requested
            if remove:
                for file_path in batch:
                    try:
                        if ospath.exists(file_path):
                            os.remove(file_path)
                    except OSError as e:
                        logger.warning(f"Failed to remove {file_path}: {e}")

            processed += len(batch)
            logger.info(f"Uploaded photo batch {batch_label}/{total_photos}")
            i += batch_size  # Advance to next batch only on success

        except FloodWait as e:
            logger.warning(f"Flood wait: waiting {e.value} seconds")
            await sleep(e.value)
            # Do NOT advance i — retry the same batch

        except Exception as e:
            logger.error(f"Batch photo upload error: {e}")
            i += batch_size  # Skip failed batch to avoid infinite loop
