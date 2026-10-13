# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================

"""
Terabox downloader module.

Handles downloads from Terabox using third-party API extraction,
then hands off the direct URL to aria2c for the actual download.
"""

import logging

import aiohttp

from leechbot.utility.handler import cancelTask
from leechbot.downloader.aria2 import aria2_Download

logger = logging.getLogger(__name__)

# Terabox API endpoint — third-party service, may change
_TERABOX_API = "https://ytshorts.savetube.me/api/v1/terabox-downloader"
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


# =============================================================================
# Extract direct download URLs from Terabox API
# =============================================================================
async def _fetch_download_urls(link: str) -> dict:
    """
    Call Terabox extraction API and return resolution dict.

    Raises:
        RuntimeError: if the API returns an error or no usable links.
    """
    payload = {"url": link}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
    }

    async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
        async with session.post(_TERABOX_API, data=payload, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()

    if not data.get("response"):
        raise RuntimeError("Empty response from Terabox API")

    try:
        resolutions = data["response"][0]["resolutions"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Unexpected Terabox API format: {e}")

    return resolutions


# =============================================================================
# Resolve the best working direct URL
# =============================================================================
async def _resolve_direct_url(resolutions: dict) -> str:
    """
    From the resolutions dict, return the first URL that resolves
    to an actual file (not an HTML page).

    Falls back to slow/HD link if fast link returns HTML.
    """
    fast_url = resolutions.get("Fast Download", "")
    slow_url = resolutions.get("HD Video", "")

    if not fast_url and not slow_url:
        raise RuntimeError("No download URLs found in Terabox response")

    # If we only have one URL, use it
    if fast_url and not slow_url:
        return fast_url
    if slow_url and not fast_url:
        return slow_url

    # Probe the fast URL — if it returns HTML/redirect instead of a file, fall back
    try:
        async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
            async with session.get(fast_url, allow_redirects=True) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if any(t in content_type for t in ("application/octet-stream", "video/", "audio/", "image/")):
                    logger.info("Terabox: using Fast Download link")
                    return fast_url
                else:
                    logger.info(f"Terabox: fast link returned {content_type}, using HD link")
                    return slow_url
    except Exception as e:
        logger.warning(f"Terabox: fast link probe failed ({e}), using HD link")
        return slow_url


# =============================================================================
# Main Download Function
# =============================================================================
async def terabox_download(link: str, index: int):
    """
    Download file from Terabox.

    Args:
        link: Terabox share link
        index: link number
    """
    logger.info(f"Starting Terabox download: {link[:80]}")

    try:
        # Step 1: Extract download URLs from API
        resolutions = await _fetch_download_urls(link)

        # Step 2: Resolve best direct URL
        direct_url = await _resolve_direct_url(resolutions)

        # Step 3: Hand off to aria2c for actual download
        logger.info(f"Terabox: downloading via aria2c")
        await aria2_Download(direct_url, index)

    except aiohttp.ClientError as e:
        logger.error(f"Terabox HTTP error: {e}")
        await cancelTask(f"Terabox API request failed: {e}")
    except RuntimeError as e:
        logger.error(f"Terabox error: {e}")
        await cancelTask(f"Terabox: {e}")
    except Exception as e:
        logger.error(f"Terabox download error: {e}")
        await cancelTask(f"Terabox Download Failed: {e}")
