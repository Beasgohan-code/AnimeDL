# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
Pixeldrain downloader module.

Handles downloads from pixeldrain.com links using the direct download API.
Supports both /u/ (single file) and /l/ (list) URLs.
"""

import re
import logging
import aiohttp
from datetime import datetime
from os import path as ospath

from leechbot.utility.variables import BotTimes, Messages, Paths
from leechbot.utility.helper import sizeUnit, getTime, speedETA, status_bar

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=30)


def parse_pixeldrain_url(link: str):
    """
    Parse a Pixeldrain URL and determine its type and ID.

    Returns:
        tuple: (type, id) where type is 'file' or 'list'
    """
    # Single file: https://pixeldrain.com/u/abcdefg
    file_match = re.search(r'pixeldrain\.com/u/([a-zA-Z0-9]+)', link)
    if file_match:
        return "file", file_match.group(1)

    # List: https://pixeldrain.com/l/abcdefg
    list_match = re.search(r'pixeldrain\.com/l/([a-zA-Z0-9]+)', link)
    if list_match:
        return "list", list_match.group(1)

    return None, None


async def pixeldrain_download(link: str, num: int):
    """
    Download file(s) from Pixeldrain.

    Args:
        link: Pixeldrain share URL
        num: link number for display
    """
    url_type, item_id = parse_pixeldrain_url(link)

    if not url_type:
        logger.error(f"Invalid Pixeldrain URL: {link}")
        return

    BotTimes.task_start = datetime.now()

    if url_type == "file":
        await _download_file(item_id, num)
    elif url_type == "list":
        await _download_list(item_id, num)


async def _download_file(file_id: str, num: int):
    """Download a single file from Pixeldrain."""
    api_url = f"https://pixeldrain.com/api/file/{file_id}"
    info_url = f"https://pixeldrain.com/api/file/{file_id}/info"

    async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
        # Get file info first
        try:
            async with session.get(info_url) as resp:
                if resp.status == 200:
                    info = await resp.json()
                    file_name = info.get("name", f"pixeldrain_{file_id}")
                    total_size = info.get("size", 0)
                else:
                    file_name = f"pixeldrain_{file_id}"
                    total_size = 0
        except Exception:
            file_name = f"pixeldrain_{file_id}"
            total_size = 0

        Messages.download_name = file_name
        Messages.status_head = (
            f"<b>📥 Downloading</b> <code>Link {str(num).zfill(2)}</code>\n\n"
            f"<b>🏷️ Name:</b> <code>{file_name}</code>\n"
        )

        # Download the file
        file_path = ospath.join(Paths.down_path, file_name)
        downloaded = 0

        try:
            async with session.get(api_url) as resp:
                if resp.status != 200:
                    logger.error(f"Pixeldrain download failed: HTTP {resp.status}")
                    return

                if total_size == 0:
                    total_size = int(resp.headers.get("Content-Length", 0))

                with open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1024 * 1024):  # 1MB chunks
                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            speed_string, eta, percentage = speedETA(
                                BotTimes.task_start, downloaded, total_size
                            )
                            await status_bar(
                                Messages.status_head,
                                speed_string,
                                percentage,
                                getTime(eta),
                                sizeUnit(downloaded),
                                sizeUnit(total_size),
                                "Pixeldrain 📁"
                            )

            logger.info(f"Pixeldrain download complete: {file_name}")

        except Exception as e:
            logger.error(f"Pixeldrain download error: {e}")


async def _download_list(list_id: str, num: int):
    """Download all files from a Pixeldrain list."""
    info_url = f"https://pixeldrain.com/api/list/{list_id}"

    async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
        try:
            async with session.get(info_url) as resp:
                if resp.status != 200:
                    logger.error(f"Pixeldrain list info failed: HTTP {resp.status}")
                    return
                info = await resp.json()
        except Exception as e:
            logger.error(f"Pixeldrain list error: {e}")
            return

        files = info.get("files", [])
        if not files:
            logger.error("Pixeldrain list is empty")
            return

        total_files = len(files)
        logger.info(f"Pixeldrain list has {total_files} files")

        for i, file_info in enumerate(files, 1):
            file_id = file_info.get("id")
            file_name = file_info.get("name", f"file_{i}")

            # Update status BEFORE downloading each file
            if total_files > 1:
                Messages.status_head = (
                    f"<b>📥 Pixeldrain List</b> <code>{i}/{total_files}</code>\n\n"
                    f"<b>🏷️ Name:</b> <code>{file_name}</code>\n"
                )

            await _download_file(file_id, num)
