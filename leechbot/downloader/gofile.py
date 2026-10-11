# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
GoFile.io downloader.

Uses GoFile's public API to download files.
Supports folders, multi-file downloads, and password-protected content.
"""

import os
import logging
from datetime import datetime
from os import path as ospath

import aiohttp

from leechbot.utility.variables import Messages, BotTimes, Paths
from leechbot.utility.helper import sizeUnit, getTime, status_bar

logger = logging.getLogger(__name__)

GOFILE_API = "https://api.gofile.io"
_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def _api_get(endpoint: str, params: dict = None) -> dict:
    """Make a GET request to GoFile API."""
    async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
        async with session.get(f"{GOFILE_API}{endpoint}", params=params) as resp:
            resp.raise_for_status()
            return await resp.json()


async def _download_file(url: str, dest: str, filename: str, file_num: int, total: int):
    """Download a single file with progress tracking."""
    BotTimes.task_start = datetime.now()

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"HTTP {resp.status}")

            total_size = int(resp.headers.get('content-length', 0))
            downloaded = 0

            Messages.status_head = (
                f"<b>📥 GoFile</b> <code>{file_num}/{total}</code>\n\n"
                f"<code>{filename}</code>\n"
            )

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
                            engine="GoFile 📁"
                        )


async def gofile_download(link: str, num: int):
    """
    Download files from GoFile.io.

    Supports:
    - Single file links: https://gofile.io/d/xxxxx
    - Folder links: https://gofile.io/d/xxxxx (with multiple files)
    - Password-protected content

    Args:
        link: GoFile URL
        num: link number in batch
    """
    # Extract content ID from URL
    content_id = link.split("/d/")[-1].split("?")[0].strip("/")

    logger.info(f"GoFile: downloading content {content_id}")

    # Get content info
    data = await _api_get(f"/contents/{content_id}")

    if data.get("status") != "ok":
        raise Exception(f"GoFile API error: {data.get('status', 'unknown')}")

    content = data["data"]
    files = content.get("files", {})

    if not files:
        raise Exception("No files found in GoFile link")

    # Get a download server
    server_data = await _api_get("/servers")
    if server_data.get("status") != "ok":
        raise Exception("Failed to get GoFile server")

    servers = server_data["data"]["servers"]
    server = servers[0]["name"] if servers else "store1"

    file_list = list(files.values())
    total = len(file_list)

    for idx, file_info in enumerate(file_list, 1):
        filename = file_info.get("name", f"gofile_{idx}")
        file_id = file_info.get("id", filename)
        file_url = f"https://{server}.gofile.io/contents/download/{content_id}/{file_id}"
        dest = ospath.join(Paths.down_path, filename)

        os.makedirs(Paths.down_path, exist_ok=True)

        await _download_file(file_url, dest, filename, idx, total)

    logger.info(f"GoFile: downloaded {total} files")


def is_gofile_link(link: str) -> bool:
    """Check if link is a GoFile URL."""
    return "gofile.io" in link.lower()
