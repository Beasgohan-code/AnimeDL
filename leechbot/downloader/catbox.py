# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
Catbox.moe / Litterbox downloader.

Handles direct file downloads from Catbox.moe (permanent) and
Litterbox.moe (temporary) file hosting.
"""

import os
import logging
from datetime import datetime
from os import path as ospath

import aiohttp

from leechbot.utility.variables import Messages, BotTimes, Paths
from leechbot.utility.helper import sizeUnit, getTime, status_bar

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_TIMEOUT = aiohttp.ClientTimeout(total=300)  # 5 min — catbox files can be large


async def catbox_download(link: str, num: int):
    """
    Download file from Catbox.moe or Litterbox.moe.

    Supports:
    - Direct file links: https://files.catbox.moe/xxxxx.ext
    - Litterbox links: https://litterbox.moe/files/xxxxx.ext

    Args:
        link: Catbox/Litterbox URL
        num: link number in batch
    """
    os.makedirs(Paths.down_path, exist_ok=True)

    # Extract filename from URL
    filename = link.split("/")[-1].split("?")[0]
    if not filename or "." not in filename:
        filename = f"catbox_{num}"

    dest = ospath.join(Paths.down_path, filename)

    BotTimes.task_start = datetime.now()
    Messages.status_head = f"<b>📥 Catbox</b> <code>{num}</code>\n\n<code>{filename}</code>\n"

    async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
        async with session.get(link, headers=_HEADERS) as resp:
            if resp.status != 200:
                raise Exception(f"HTTP {resp.status}")

            total_size = int(resp.headers.get('content-length', 0))
            downloaded = 0

            with open(dest, 'wb') as f:
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)

                    if total_size > 0:
                        pct = (downloaded / total_size) * 100
                        elapsed = max((datetime.now() - BotTimes.task_start).total_seconds(), 0.01)
                        speed = downloaded / elapsed
                        remaining = total_size - downloaded
                        eta = remaining / speed if speed > 0 else 0

                        await status_bar(
                            down_msg=Messages.status_head,
                            speed=f"{sizeUnit(speed)}/s",
                            percentage=pct,
                            eta=getTime(eta),
                            done=sizeUnit(downloaded),
                            left=sizeUnit(total_size),
                            engine="Catbox 📦"
                        )

    logger.info(f"Catbox: downloaded {filename} ({sizeUnit(downloaded)})")


def is_catbox_link(link: str) -> bool:
    """Check if link is a Catbox/Litterbox URL."""
    lower = link.lower()
    return "catbox.moe" in lower or "litterbox.moe" in lower
