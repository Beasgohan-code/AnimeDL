# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
StreamTape.com video downloader.

Extracts direct download links from StreamTape embed pages.
"""

import re
import asyncio
import logging
from os import path as ospath

import aiohttp

from leechbot.utility.variables import Paths

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def _extract_download_url(page_url: str) -> tuple:
    """
    Extract direct download URL from StreamTape page.

    Returns: (download_url, filename)
    """
    async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
        async with session.get(page_url, headers=_HEADERS) as resp:
            html = await resp.text()

    url = None

    # Method 1: Direct link pattern in page source
    dl_match = re.search(r"getElementById\('norobotlink'\)\.href\s*=\s*['\"]([^'\"]+)", html)
    if dl_match:
        url = dl_match.group(1)
        if url.startswith("//"):
            url = "https:" + url

    # Method 2: Token-based extraction
    if not url:
        token_match = re.search(r"token=([a-zA-Z0-9_]+)", html)
        if token_match:
            token = token_match.group(1)
            url = f"https://streamtape.com/get_video?id={token}"

    # Method 3: Obfuscated link construction
    if not url:
        parts = re.findall(r"(/\d+/[^'\"]+)", html)
        if parts:
            url = "https://streamtape.com" + parts[-1]

    if not url:
        raise Exception("Could not extract download URL from StreamTape page")

    # Extract filename from page
    title_match = re.search(r'<title>([^<]+)</title>', html)
    filename = title_match.group(1).strip() if title_match else "streamtape_video"
    filename = re.sub(r'[^\w\s\-.]', '', filename).strip()
    if not filename.endswith(('.mp4', '.mkv', '.avi', '.webm')):
        filename += '.mp4'

    return url, filename


async def streamtape_download(link: str, num: int):
    """
    Download video from StreamTape.

    Args:
        link: StreamTape URL
        num: link number in batch
    """
    logger.info(f"StreamTape: extracting from {link[:60]}")

    url, filename = await _extract_download_url(link)
    logger.info(f"StreamTape: direct URL extracted, downloading via aria2c")

    dest = ospath.join(Paths.down_path, filename)

    from leechbot.utility.variables import Messages
    Messages.status_head = f"<b>📥 StreamTape</b> <code>{num}</code>\n\n<code>{filename}</code>\n"

    # Use aria2c for reliable download (resumable, multi-connection)
    cmd = [
        "aria2c",
        f"--dir={Paths.down_path}",
        f"--out={filename}",
        "--max-connection-per-server=16",
        "--split=16",
        "--min-split-size=1M",
        "--continue=true",
        "--summary-interval=0",
        "--console-log-level=error",
        url,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.wait()

    if proc.returncode != 0:
        stderr = await proc.stderr.read()
        raise Exception(f"aria2c failed with code {proc.returncode}: {stderr.decode()[:200]}")

    logger.info(f"StreamTape: downloaded {filename}")


def is_streamtape_link(link: str) -> bool:
    """Check if link is a StreamTape URL."""
    lower = link.lower()
    return "streamtape" in lower or "stape." in lower
