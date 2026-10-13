# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
YT-DLP downloader module.

Handles downloads from YouTube and 2000+ other sites via yt-dlp.
Supports format selection (best, 720p, 480p, audio-only).
"""

import logging
import yt_dlp
from asyncio import sleep
from threading import Thread
from os import makedirs, path as ospath

import config
from leechbot.utility.variables import YTDL, MSG, Messages, Paths, BOT
from leechbot.utility.helper import getTime, keyboard, sizeUnit, status_bar, sysINFO, _strip_sysinfo

logger = logging.getLogger(__name__)


def _schedule_state_update(loop, func, *args):
    """
    Thread-safe dispatch from the yt-dlp worker thread to the asyncio loop.

    yt-dlp invokes progress hooks and logger callbacks from its own thread,
    so direct writes to the shared `YTDL` object race with the event loop
    that reads those attributes to render the status bar. We marshal every
    mutation through `loop.call_soon_threadsafe` so the loop is the single
    owner of `YTDL` state. Under CPython's GIL the races are benign in
    practice (atomic attribute writes), but this pattern is correct under
    PyPy and future no-GIL CPython.
    """
    if loop is None or loop.is_closed():
        return
    try:
        loop.call_soon_threadsafe(func, *args)
    except RuntimeError:
        pass  # loop already closed mid-callback

# =============================================================================
# Format Presets
# =============================================================================
FORMAT_PRESETS = {
    "best": "bestvideo+bestaudio/best",
    "bestvideo": "bestvideo+bestaudio/best",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]",
    "audio": "bestaudio/best",
    "worst": "worstvideo+worstaudio/worst",
}


def get_format_string(preset: str = None) -> str:
    """Resolve a format preset name to a yt-dlp format string."""
    if preset is None:
        preset = BOT.Options.ytdl_format

    # If it's a known preset name, use it; otherwise treat as raw format string
    return FORMAT_PRESETS.get(preset.lower(), preset)


def _get_cookie_opts() -> dict:
    """
    Return yt-dlp options dict for cookie authentication.

    Resolution order:
      1. YTDL_COOKIES_FILE env var — explicit path to cookies.txt
      2. Default save path (Paths.COOKIE_FILE) — uploaded via /setcookies

    Returns:
        dict: yt-dlp options with cookie settings, or empty dict if unconfigured.
    """
    cookies_file = getattr(config, "YTDL_COOKIES_FILE", "")
    default_path = getattr(Paths, "COOKIE_FILE", "")

    # Priority 1: explicit env var
    if cookies_file and ospath.isfile(cookies_file):
        logger.info("Using cookies file (env): %s", cookies_file)
        return {"cookiefile": cookies_file}

    # Priority 2: uploaded via /setcookies command
    if default_path and ospath.isfile(default_path):
        logger.info("Using cookies file (uploaded): %s", default_path)
        return {"cookiefile": default_path}

    return {}


# =============================================================================
# YT-DLP Status Monitor
# =============================================================================
async def YTDL_Status(link: str, num: int):
    """
    Monitor YT-DLP download progress in a background thread.

    Args:
        link: video URL
        num: link number for display
    """
    from asyncio import get_running_loop

    name = await get_YT_Name(link)
    if not Messages.status_head or "📥 Downloading" not in Messages.status_head:
        Messages.status_head = (
            f"<b>📥 Downloading</b> <code>Link {str(num).zfill(2)}</code>\n\n<code>{name}</code>\n"
        )

    loop = get_running_loop()
    ytdl_thread = Thread(
        target=YouTubeDL, name="YT-DLP", args=(link, loop), daemon=True
    )
    ytdl_thread.start()

    while ytdl_thread.is_alive():
        if YTDL.header:
            try:
                await MSG.status_msg.edit_text(
                    text=_strip_sysinfo(Messages.task_msg + Messages.status_head + YTDL.header) + sysINFO(),
                    reply_markup=keyboard()
                )
            except Exception:
                pass
        else:
            try:
                await status_bar(
                    down_msg=Messages.task_msg + Messages.status_head,
                    speed=YTDL.speed,
                    percentage=float(YTDL.percentage),
                    eta=YTDL.eta,
                    done=YTDL.done,
                    left=YTDL.left,
                    engine="YT-DLP 🏮"
                )
            except Exception:
                pass

        await sleep(2.5)


# =============================================================================
# YT-DLP Logger
# =============================================================================
class MyLogger:
    """Custom logger for yt-dlp that updates the YTDL status object."""

    def __init__(self, loop=None):
        self._loop = loop

    def debug(self, msg):
        if "item" in str(msg):
            msgs = msg.split(" ")
            header = f"\n⏳ <code>Getting Info {msgs[-3]} of {msgs[-1]}</code>"
            _schedule_state_update(self._loop, _set_header, header)

    def warning(self, msg):
        pass

    def error(self, msg):
        logger.error(f"YT-DLP: {msg}")


# =============================================================================
# Progress Hook
# =============================================================================
def _set_header(value: str):
    YTDL.header = value


def _set_progress(speed: str, percentage: float, eta: str, done: str, left: str):
    """Atomically update all five YTDL progress fields. Runs on the event loop."""
    YTDL.header = ""
    YTDL.speed = speed
    YTDL.percentage = percentage
    YTDL.eta = eta
    YTDL.done = done
    YTDL.left = left


def _make_progress_hook(loop):
    """
    Build a yt-dlp progress hook bound to the given asyncio loop.

    The returned function is invoked from yt-dlp's worker thread, so it
    must NOT mutate `YTDL` directly — it dispatches via
    `loop.call_soon_threadsafe` so the event loop owns the state.
    """
    def _progress_hook(d):
        if d["status"] == "downloading":
            total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            dl_bytes = d.get("downloaded_bytes", 0)
            speed = d.get("speed")
            eta = d.get("eta")

            percent = round((float(dl_bytes) * 100 / float(total_bytes)), 2) if total_bytes else 0

            speed_str = sizeUnit(speed) if speed else "N/A"
            percentage = min(percent, 100)
            eta_str = getTime(eta) if eta else "N/A"
            done_str = sizeUnit(dl_bytes) if dl_bytes else "N/A"
            left_str = sizeUnit(total_bytes) if total_bytes else "N/A"

            _schedule_state_update(
                loop, _set_progress, speed_str, percentage, eta_str, done_str, left_str
            )

        elif d["status"] == "finished":
            _schedule_state_update(
                loop, _set_header, "\n⏳ <code>Download finished, processing...</code>"
            )

    return _progress_hook


# =============================================================================
# YT-DLP Download Function
# =============================================================================
def YouTubeDL(url: str, loop=None):
    """
    Download video/audio using yt-dlp.

    Args:
        url: video URL
        loop: asyncio event loop used to marshal progress updates from the
              yt-dlp worker thread. If None, falls back to direct writes
              (legacy behavior, used by tests).
    """
    format_str = get_format_string()
    is_audio_only = format_str == FORMAT_PRESETS.get("audio")

    ydl_opts = {
        "format": format_str,
        "merge_output_format": "mp4" if not is_audio_only else None,
        "writethumbnail": True,
        "concurrent_fragment_downloads": 16,
        "overwrites": True,
        "progress_hooks": [_make_progress_hook(loop)],
        "writesubtitles": True,
        "subtitleslangs": ["en", "en-US", "en-GB"],
        "extractor_args": {
            "subtitlesformat": "srt",
            "generic": {"impersonate": ["chrome"]},
        },
        "logger": MyLogger(loop),
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "outtmpl": {
            "default": f"{Paths.down_path}/%(title)s.%(ext)s",
            "thumbnail": f"{Paths.thumbnail_ytdl}/%(title)s.%(ext)s",
        },
    }

    # aria2c (installed in the Docker image) parallelizes direct-HTTP
    # downloads with 16 connections per server — big win for DDL hosts.
    try:
        import shutil as _shutil
        if _shutil.which("aria2c"):
            ydl_opts["external_downloader"] = {"default": "aria2c"}
            ydl_opts["external_downloader_args"] = {
                "aria2c": [
                    "-x", "16", "-s", "16", "-k", "1M",
                    "--file-allocation=none", "--console-log-level=warn",
                ]
            }
    except Exception:
        pass

    # Merge cookie authentication options (fixes YouTube bot detection)
    ydl_opts.update(_get_cookie_opts())

    # Audio-only options
    if is_audio_only:
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "320",
        }]

    if not ospath.exists(Paths.thumbnail_ytdl):
        makedirs(Paths.thumbnail_ytdl)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            _schedule_state_update(loop, _set_header, "⏳ <code>Preparing...</code>")

            if info.get("_type") == "playlist":
                # Playlist download
                playlist_name = info["title"]
                playlist_path = ospath.join(Paths.down_path, playlist_name)

                if not ospath.exists(playlist_path):
                    makedirs(playlist_path)

                ydl_opts["outtmpl"]["default"] = f"{playlist_path}/%(title)s.%(ext)s"
                # Re-bind the hook to the same loop for the inner YoutubeDL.
                ydl_opts["progress_hooks"] = [_make_progress_hook(loop)]
                ydl_opts["logger"] = MyLogger(loop)

                with yt_dlp.YoutubeDL(ydl_opts) as ydl2:
                    for entry in info.get("entries", []):
                        if entry:
                            try:
                                ydl2.download([entry["webpage_url"]])
                            except Exception as e:
                                logger.error(f"Playlist item error: {e}")
            else:
                ydl.download([url])

        except Exception as e:
            logger.error(f"YT-DLP error: {e}")
            raise


# =============================================================================
# Get Video Name
# =============================================================================
async def get_YT_Name(link: str) -> str:
    """Get video title from link without downloading."""
    try:
        opts = {
            "logger": MyLogger(),
            "quiet": True,
            "extractor_args": {"generic": {"impersonate": ["chrome"]}},
        }
        opts.update(_get_cookie_opts())
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(link, download=False)
            return info.get("title", "Unknown")
    except Exception as e:
        logger.error(f"Cannot get YT name: {e}")
        return "Unknown"


# =============================================================================
# List Available Formats
# =============================================================================
async def list_formats(link: str) -> str:
    """
    List available formats for a link.

    Returns:
        str: formatted list of available formats
    """
    try:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extractor_args": {"generic": {"impersonate": ["chrome"]}},
        }
        opts.update(_get_cookie_opts())
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(link, download=False)
            formats = info.get("formats", [])

            if not formats:
                return "<b>⚠️ No formats found</b>"

            text = f"<b>🎬 Available Formats for:</b>\n<code>{info.get('title', 'Unknown')}</code>\n\n"

            seen = set()
            for f in formats:
                fmt_id = f.get("format_id", "?")
                ext = f.get("ext", "?")
                res = f.get("resolution", "audio only")
                height = f.get("height")
                filesize = f.get("filesize") or f.get("filesize_approx", 0)

                key = f"{height}_{ext}"
                if key in seen:
                    continue
                seen.add(key)

                size_str = sizeUnit(filesize) if filesize else "N/A"
                height_str = f"{height}p" if height else "audio"

                text += f"• `{fmt_id}` — {height_str} ({ext}) — {size_str}\n"

                if len(text) > 3500:
                    text += "\n... (truncated)"
                    break

            return text

    except Exception as e:
        return f"<b>❌ Error:</b> <code>{e}</code>"
