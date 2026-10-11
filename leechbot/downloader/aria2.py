# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
Aria2c downloader module.

Handles downloads using aria2c: HTTP/HTTPS, FTP, torrents, and magnet links.
Includes bandwidth limiting and real-time progress parsing.
"""

import re
import os
import shlex
import asyncio
import logging
import subprocess
from datetime import datetime

from leechbot.utility.helper import sizeUnit, status_bar
from leechbot.utility.variables import BOT, Aria2c, Paths, Messages, BotTimes

logger = logging.getLogger(__name__)


# =============================================================================
# Tracker Configuration (lazy-loaded, not at import time)
# =============================================================================
ARIA2_DIR = os.path.expanduser("~/.aria2")
TRACKER_FILES = [
    ("best_aria2.txt", "https://cf.trackerslist.com/best_aria2.txt"),
    ("all_aria2.txt", "https://cf.trackerslist.com/all_aria2.txt"),
]

_trackers: list = []
_trackers_loaded = False


def _load_trackers():
    """Load tracker lists from disk or download them. Runs once."""
    global _trackers, _trackers_loaded
    if _trackers_loaded:
        return
    _trackers_loaded = True

    os.makedirs(ARIA2_DIR, exist_ok=True)
    for fname, url in TRACKER_FILES:
        fpath = os.path.join(ARIA2_DIR, fname)
        if not os.path.exists(fpath):
            try:
                subprocess.run(["wget", "-q", "-O", fpath, url], timeout=10)
            except Exception:
                pass
        try:
            with open(fpath, "r") as f:
                _trackers.append(f.read().replace("\n", ",").strip())
        except Exception:
            pass


def _get_tracker_string() -> str:
    """Return comma-separated tracker list."""
    _load_trackers()
    return ",".join(t for t in _trackers if t)


# =============================================================================
# Link Validation
# =============================================================================
def is_torrent_or_magnet(link: str) -> bool:
    """Check if link is a torrent file or magnet link."""
    return link.endswith(".torrent") or link.startswith("magnet:")


# =============================================================================
# Link Option Parsing
# =============================================================================
def parse_link_options(link: str):
    """
    Parse link for custom aria2c options embedded in the URL string.

    Supports:
        --header "Name: Value"
        --out filename.ext

    Returns:
        tuple: (url, headers_list, output_name)
    """
    try:
        parts = shlex.split(link)
    except ValueError:
        return link, [], None

    url = None
    headers = []
    out = None
    i = 0

    while i < len(parts):
        part = parts[i]
        if part == "--header" and i + 1 < len(parts):
            headers.append(parts[i + 1])
            i += 2
        elif part == "--out" and i + 1 < len(parts):
            out = parts[i + 1]
            i += 2
        elif part.startswith("--"):
            i += 1
        else:
            if url is None:
                url = part
            i += 1

    return url, headers, out


# =============================================================================
# Build Aria2c Command
# =============================================================================
def _build_command(url: str, headers: list, out: str, bandwidth_limit: str) -> list:
    """Build the aria2c command list with all options."""
    command = ["aria2c"]

    if is_torrent_or_magnet(url):
        command += [
            "--enable-dht=true",
            "--enable-peer-exchange=true",
            "--bt-enable-lpd=true",
            "--bt-max-peers=100",
            "--bt-request-peer-speed-limit=0",
            "--bt-tracker-connect-timeout=10",
            "--bt-tracker-interval=60",
            "--bt-tracker-timeout=10",
            "--max-connection-per-server=16",
            "--max-concurrent-downloads=5",
            "--seed-time=0",
            "--summary-interval=1",
            "--console-log-level=notice",
        ]
        tracker_str = _get_tracker_string()
        if tracker_str:
            command.append(f"--bt-tracker={tracker_str}")
    else:
        command += [
            "-x16",
            "-s16",
            "-k1M",
            "--seed-time=0",
            "--summary-interval=1",
            "--max-tries=3",
            "--max-concurrent-downloads=5",
            "--console-log-level=notice",
            "--optimize-concurrent-downloads=true",
            "--file-allocation=prealloc",
        ]

    # Bandwidth limit
    if bandwidth_limit:
        command.append(f"--max-overall-download-limit={bandwidth_limit}")

    # Output directory
    command += ["-d", Paths.down_path]

    # Custom headers
    for h in headers:
        command += ["--header", h]

    # Custom output name
    if out:
        command += ["-o", out]

    command.append(url)
    return command


# =============================================================================
# Main Download Function
# =============================================================================
async def aria2_Download(link: str, num: int):
    """
    Download file using aria2c.

    Args:
        link: URL to download (may include --header/--out options)
        num: link number for display
    """
    url, headers, out = parse_link_options(link)
    if url is None:
        logger.error("No valid URL found in link")
        return

    name_d = get_Aria2c_Name(url if out is None else out)
    BotTimes.task_start = datetime.now()
    Messages.status_head = (
        f"<b>📥 Downloading</b> <code>Link {str(num).zfill(2)}</code>\n\n"
        f"<b>🏷️ Name:</b> <code>{name_d}</code>\n"
    )

    bandwidth = BOT.Options.bandwidth_limit
    command = _build_command(url, headers, out, bandwidth)

    logger.info(f"Aria2c command: {' '.join(command)}")

    # Launch as async subprocess — does NOT block the event loop
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Read output in real-time
    while True:
        raw = await proc.stdout.readline()
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").strip()
        if line:
            logger.debug(f"Aria2c: {line}")
            await on_output(line)

    # Check exit code
    await proc.wait()

    if proc.returncode != 0:
        stderr_data = await proc.stderr.read()
        error_output = stderr_data.decode("utf-8", errors="replace").strip()
        error_messages = {
            3: "Resource not found",
            9: "Insufficient disk space",
            24: "HTTP authorization failed",
        }
        error_msg = error_messages.get(proc.returncode, f"Aria2c failed with code {proc.returncode}")
        logger.error(f"{error_msg}: {error_output}")
        raise RuntimeError(error_msg)


# =============================================================================
# Get Filename
# =============================================================================
def get_Aria2c_Name(link: str) -> str:
    """Get filename from link using aria2c dry-run."""
    if BOT.Options.custom_name:
        return BOT.Options.custom_name

    try:
        cmd = ['aria2c', '-x10', '--dry-run', '--file-allocation=none', link]
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=15,
        )
        stdout_str = result.stdout.decode("utf-8", errors="replace")

        filename = stdout_str.split("complete: ")[-1].split("\n")[0]
        name = filename.split("/")[-1].strip()
        return name if name else "Unknown"
    except Exception:
        return "Unknown"


# =============================================================================
# Progress Parsing
# =============================================================================
async def on_output(output: str):
    """Parse aria2c console output and update the status bar."""
    total_size = "0B"
    progress_percentage = "0B"
    downloaded_bytes = "0B"
    eta = "0s"

    try:
        if "ETA:" in output:
            parts = output.split()
            total_size = parts[1].split("/")[1].split("(")[0]
            progress_percentage = parts[1][parts[1].find("(") + 1:parts[1].find(")")]
            downloaded_bytes = parts[1].split("/")[0]
            eta = parts[4].split(":")[1][:-1]
    except Exception:
        return

    # Extract numeric percentage
    try:
        percentage = float(re.findall(r"\d+\.\d+|\d+", progress_percentage)[0])
    except Exception:
        percentage = 0

    # Extract downloaded amount
    try:
        down = float(re.findall(r"\d+\.\d+|\d+", downloaded_bytes)[0])
        down_unit = re.findall(r"[a-zA-Z]+", downloaded_bytes)[0]
    except Exception:
        return

    spd_map = {"G": 3, "M": 2, "K": 1}
    spd = spd_map.get(down_unit[0], 0) if down_unit else 0

    elapsed = max((datetime.now() - BotTimes.task_start).total_seconds(), 0.01)

    # Dead link detection
    if elapsed >= 270 and not Aria2c.link_info:
        logger.warning("Failed to get download info after 270s — possible dead link")

    if total_size != "0B":
        Aria2c.link_info = True
        current_speed = (down * (1024 ** spd)) / elapsed
        speed_string = f"{sizeUnit(current_speed)}/s"

        await status_bar(
            Messages.status_head,
            speed_string,
            int(percentage),
            eta,
            downloaded_bytes,
            total_size,
            "Aria2c ⚡",
        )
