# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
Screenshot commands.

Generates screenshots/thumbnails from videos and PDFs.
Uses ffmpeg (video) and Pillow (PDF) from LeechBot's existing stack.
"""

import os
import asyncio
import logging
from os import path as ospath
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from leechbot import app, OWNER
from leechbot.utility.variables import BOT, Paths
from leechbot.utility.helper import sizeUnit, sysINFO

logger = logging.getLogger(__name__)

# Per-user watermark storage (in-memory, resets on restart)
_user_watermarks: dict = {}

# Per-user lock to prevent concurrent screenshots
_user_locks: dict = {}


@app.on_message(filters.command("setwm"))
async def set_watermark(client, message):
    """Set custom watermark text for screenshots."""
    user_id = message.from_user.id

    if user_id != OWNER:
        return await message.reply("❌ Only owner can set watermark.")

    args = message.text.split(None, 1)
    if len(args) < 2:
        return await message.reply(
            "<b>Usage:</b> <code>/setwm Your Watermark</code>\n\n"
            "<i>Use <code>/setwm off</code> to disable watermark.</i>"
        )

    wm_text = args[1].strip()

    if wm_text.lower() == "off":
        _user_watermarks.pop(user_id, None)
        return await message.reply("✅ Watermark disabled.")

    _user_watermarks[user_id] = wm_text
    await message.reply(f"✅ Watermark set to:\n<code>{wm_text}</code>")


def _get_watermark(user_id: int) -> str:
    """Get watermark text for a user."""
    if user_id in _user_watermarks:
        return _user_watermarks[user_id]
    return ""


def _add_watermark_pil(image_path: str, text: str):
    """Add watermark to image using Pillow."""
    if not text:
        return
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(image_path)
        draw = ImageDraw.Draw(img)

        # Try to use a decent font, fall back to default
        font_size = max(16, img.width // 30)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except (IOError, OSError):
            try:
                font = ImageFont.truetype("/system/fonts/Roboto-Regular.ttf", font_size)
            except (IOError, OSError):
                font = ImageFont.load_default()

        # Calculate position (bottom-right with padding)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = img.width - text_width - 15
        y = img.height - text_height - 15

        # Draw shadow + text
        draw.text((x + 2, y + 2), text, fill=(0, 0, 0), font=font)
        draw.text((x, y), text, fill=(255, 255, 255), font=font)

        img.save(image_path)
    except Exception as e:
        logger.warning(f"Watermark failed: {e}")


async def _video_screenshots(file_path: str, count: int, watermark: str) -> list:
    """Extract screenshots from video using ffmpeg."""
    screenshots = []
    output_dir = Paths.temp_dirleech_path if ospath.exists(Paths.temp_dirleech_path) else "/tmp"
    base_name = ospath.splitext(ospath.basename(file_path))[0]

    try:
        # Get video duration
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *probe_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        duration = float(stdout.decode().strip()) if stdout else 60.0

        interval = duration / (count + 1)

        for i in range(1, count + 1):
            timestamp = interval * i
            output_path = ospath.join(output_dir, f"{base_name}_ss_{i}.jpg")

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(timestamp),
                "-i", file_path,
                "-vframes", "1",
                "-q:v", "2",
                output_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()

            if ospath.exists(output_path) and ospath.getsize(output_path) > 0:
                _add_watermark_pil(output_path, watermark)
                screenshots.append(output_path)

    except Exception as e:
        logger.error(f"Video screenshot failed: {e}")

    return screenshots


async def _pdf_screenshots(file_path: str, count: int, watermark: str) -> list:
    """Extract screenshots from PDF using Pillow."""
    screenshots = []
    output_dir = Paths.temp_dirleech_path if ospath.exists(Paths.temp_dirleech_path) else "/tmp"
    base_name = ospath.splitext(ospath.basename(file_path))[0]

    try:
        from PIL import Image
        import io

        # Use pdf2image if available, otherwise fall back to ffmpeg
        try:
            from pdf2image import convert_from_path
            pages = convert_from_path(file_path, dpi=200, first_page=1, last_page=count)
            for i, page in enumerate(pages, 1):
                output_path = ospath.join(output_dir, f"{base_name}_page_{i}.jpg")
                # Resize to reasonable width
                if page.width > 1280:
                    ratio = 1280 / page.width
                    page = page.resize((1280, int(page.height * ratio)), Image.LANCZOS)
                page.save(output_path, "JPEG", quality=90)
                _add_watermark_pil(output_path, watermark)
                screenshots.append(output_path)
        except ImportError:
            # Fallback: use ffmpeg for PDF
            for i in range(1, count + 1):
                output_path = ospath.join(output_dir, f"{base_name}_page_{i}.jpg")
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "image2pipe",
                    "-i", file_path,
                    "-vf", f"select=eq(n\\,{i - 1})",
                    "-vframes", "1",
                    "-q:v", "2",
                    output_path
                ]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc.communicate()
                if ospath.exists(output_path) and ospath.getsize(output_path) > 0:
                    _add_watermark_pil(output_path, watermark)
                    screenshots.append(output_path)

    except Exception as e:
        logger.error(f"PDF screenshot failed: {e}")

    return screenshots


@app.on_message(filters.command("screenshot"))
async def screenshot_command(client, message):
    """Generate screenshots from a video or PDF file.

    Usage: Reply to a video/PDF with /screenshot [count]
    Default count: 5
    """
    user_id = message.from_user.id

    # Check if replying to a file
    if not message.reply_to_message:
        return await message.reply(
            "<b>📸 Screenshot Generator</b>\n\n"
            "<b>Usage:</b> Reply to a video or PDF with\n"
            "<code>/screenshot [count]</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/screenshot</code> — 5 screenshots (default)\n"
            "• <code>/screenshot 10</code> — 10 screenshots\n\n"
            "<b>Supported:</b> MP4, MKV, AVI, MOV, WebM, PDF\n"
            "Use <code>/setwm text</code> to add watermark."
        )

    reply = message.reply_to_message

    # Get file info
    file_name = ""
    file_size = 0
    if reply.document:
        file_name = reply.document.file_name or "document"
        file_size = reply.document.file_size
    elif reply.video:
        file_name = reply.video.file_name or "video.mp4"
        file_size = reply.video.file_size
    elif reply.animation:
        file_name = reply.animation.file_name or "animation.mp4"
        file_size = reply.animation.file_size
    else:
        return await message.reply("❌ Please reply to a video or PDF file.")

    # Check file type
    ext = ospath.splitext(file_name)[1].lower()
    supported_video = [".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".ts", ".m4v"]
    supported_doc = [".pdf"]

    is_video = ext in supported_video
    is_pdf = ext in supported_doc

    if not is_video and not is_pdf:
        return await message.reply(
            f"❌ Unsupported file type: <code>{ext}</code>\n\n"
            f"<b>Supported:</b> {', '.join(supported_video + supported_doc)}"
        )

    # Check file size (limit to 2GB)
    if file_size > 2 * 1024 * 1024 * 1024:
        return await message.reply("❌ File too large (max 2GB).")

    # Parse count
    args = message.text.split()
    count = 5
    if len(args) > 1:
        try:
            count = int(args[1])
            count = max(1, min(count, 20))  # 1-20 range
        except ValueError:
            return await message.reply("❌ Invalid count. Use a number between 1-20.")

    # Check for concurrent processing
    if _user_locks.get(user_id, False):
        return await message.reply("⏳ Please wait, previous screenshot still processing.")

    _user_locks[user_id] = True

    status_msg = await message.reply(
        f"📸 <b>Generating {count} screenshots...</b>\n\n"
        f"📄 <b>File:</b> <code>{file_name}</code>\n"
        f"📦 <b>Size:</b> {sizeUnit(file_size)}\n"
        f"🎬 <b>Type:</b> {'Video' if is_video else 'PDF'}"
    )

    try:
        # Download file
        await status_msg.edit_text("📥 <b>Downloading file...</b>")

        from leechbot.utility.variables import Paths
        down_dir = Paths.temp_dirleech_path if ospath.exists(Paths.temp_dirleech_path) else "/tmp"
        file_path = ospath.join(down_dir, file_name)

        await reply.download(file_name=file_path)

        if not ospath.exists(file_path):
            await status_msg.edit_text("❌ Download failed.")
            _user_locks[user_id] = False
            return

        # Generate screenshots
        watermark = _get_watermark(user_id)
        await status_msg.edit_text(f"📸 <b>Extracting {count} frames...</b>")

        if is_video:
            screenshots = await _video_screenshots(file_path, count, watermark)
        else:
            screenshots = await _pdf_screenshots(file_path, count, watermark)

        if not screenshots:
            await status_msg.edit_text("❌ Failed to generate screenshots.")
            _user_locks[user_id] = False
            # Cleanup
            try:
                os.remove(file_path)
            except Exception:
                pass
            return

        # Upload screenshots
        await status_msg.edit_text(f"📤 <b>Uploading {len(screenshots)} screenshots...</b>")

        for i, img_path in enumerate(screenshots, 1):
            try:
                if watermark:
                    await client.send_photo(
                        chat_id=message.chat.id,
                        photo=img_path,
                        caption=f"📸 Screenshot {i}/{len(screenshots)}"
                    )
                else:
                    await client.send_photo(
                        chat_id=message.chat.id,
                        photo=img_path,
                        caption=f"📸 {i}/{len(screenshots)}"
                    )
            except Exception as e:
                logger.warning(f"Upload failed for screenshot {i}: {e}")

        # Done
        await status_msg.edit_text(
            f"✅ <b>Done!</b> Generated {len(screenshots)} screenshots from "
            f"<code>{file_name}</code>"
        )

    except Exception as e:
        logger.error(f"Screenshot error: {e}")
        await status_msg.edit_text(f"❌ Error: <code>{str(e)[:200]}</code>")

    finally:
        _user_locks[user_id] = False
        # Cleanup downloaded file and screenshots
        try:
            if ospath.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
        for img in screenshots if 'screenshots' in dir() else []:
            try:
                if ospath.exists(img):
                    os.remove(img)
            except Exception:
                pass
