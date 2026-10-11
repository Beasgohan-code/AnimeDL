# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
Mediafire downloader module.

Handles downloads from mediafire.com file hosting links.
Extracts the direct download URL from the page and delegates to aria2c.
"""

import re
import logging
import aiohttp
from datetime import datetime
from os import path as ospath

from leechbot.utility.variables import BotTimes, Messages, Paths
from leechbot.utility.helper import sizeUnit, getTime, speedETA, status_bar

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
_TIMEOUT = aiohttp.ClientTimeout(total=60)


async def extract_mediafire_url(link: str) -> tuple:
    """
    Extract the direct download URL from a Mediafire page.

    Args:
        link: Mediafire share URL

    Returns:
        tuple: (direct_url, filename, file_size) or (None, None, None) on failure
    """
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(link, headers=_HEADERS) as resp:
                if resp.status != 200:
                    logger.error(f"Mediafire page fetch failed: HTTP {resp.status}")
                    return None, None, None
                html = await resp.text()

        # Extract direct download link
        # Pattern: <a class="input popsok" ... href="https://download...mediafire.com/...">
        dl_match = re.search(
            r'href="(https?://download\d*\.mediafire\.com/[^"]+)"',
            html
        )
        if not dl_match:
            # Alternative pattern
            dl_match = re.search(
                r'(https?://(?:www\.)?mediafire\.com/file/[^/]+/[^/]+/file)',
                html
            )

        if not dl_match:
            logger.error("Could not extract Mediafire download URL")
            return None, None, None

        direct_url = dl_match.group(1)

        # Extract filename
        name_match = re.search(
            r'<div class="filename"[^>]*>([^<]+)</div>',
            html
        )
        filename = name_match.group(1).strip() if name_match else None

        # Extract file size
        size_match = re.search(
            r'<div class="file-size"[^>]*>\s*(\d[\d,.]*)\s*(KB|MB|GB|B)\s*</div>',
            html,
            re.IGNORECASE
        )
        file_size = 0
        if size_match:
            size_val = float(size_match.group(1).replace(",", ""))
            unit = size_match.group(2).upper()
            multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
            file_size = int(size_val * multipliers.get(unit, 1))

        return direct_url, filename, file_size

    except Exception as e:
        logger.error(f"Mediafire extraction error: {e}")
        return None, None, None


async def mediafire_download(link: str, num: int):
    """
    Download file from Mediafire.

    Extracts the direct download URL, then downloads using aiohttp with progress tracking.

    Args:
        link: Mediafire share URL
        num: link number for display
    """
    BotTimes.task_start = datetime.now()

    direct_url, filename, total_size = await extract_mediafire_url(link)

    if not direct_url:
        logger.error(f"Failed to extract Mediafire URL from: {link}")
        return

    if not filename:
        # Guess filename from URL
        filename = direct_url.split("/")[-1].split("?")[0] or f"mediafire_{num}"

    Messages.download_name = filename
    Messages.status_head = (
        f"<b>📥 Downloading</b> <code>Link {str(num).zfill(2)}</code>\n\n"
        f"<b>🏷️ Name:</b> <code>{filename}</code>\n"
    )

    file_path = ospath.join(Paths.down_path, filename)
    downloaded = 0

    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(direct_url, headers=_HEADERS) as resp:
                if resp.status not in (200, 206):
                    logger.error(f"Mediafire download failed: HTTP {resp.status}")
                    return

                if total_size == 0:
                    total_size = int(resp.headers.get("Content-Length", 0))

                with open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1024 * 1024):
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
                                "Mediafire 📂"
                            )

        logger.info(f"Mediafire download complete: {filename}")

    except Exception as e:
        logger.error(f"Mediafire download error: {e}")
