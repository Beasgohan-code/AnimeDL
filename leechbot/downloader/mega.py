# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================

"""
Mega.nz downloader module.

Handles downloads from Mega.nz using megatools CLI.
Supports:
  - Single file downloads
  - Folder downloads (recursive)
  - Progress tracking with speed, size, ETA
  - Graceful error handling with clear messages
"""

import os
import re
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from leechbot.utility.helper import sizeUnit, status_bar
from leechbot.utility.variables import BotTimes, Messages, Paths, Transfer

logger = logging.getLogger(__name__)


# =============================================================================
# Check megatools availability
# =============================================================================
def _check_megadl():
    """Raise a clear error if megatools is not installed."""
    import shutil
    if shutil.which("megadl") is None:
        raise ImportError(
            "megatools is not installed. Install it via:\n"
            "  • Debian/Ubuntu: sudo apt install megatools\n"
            "  • Arch:          sudo pacman -S megatools\n"
            "  • macOS:         brew install megatools"
        )


# =============================================================================
# Link type detection
# =============================================================================
def _is_folder_link(link: str) -> bool:
    """Check if the link is a Mega folder link."""
    return "/folder/" in link or "/#F!" in link


def _extract_link_name(link: str) -> str:
    """Extract a display name hint from the Mega URL."""
    # mega.nz/file/NAME#HASH or mega.nz/folder/NAME#HASH
    try:
        fragment = link.split("#", 1)[1] if "#" in link else ""
        # Some mega links embed the name in the path
        path_part = link.split("mega.nz/", 1)[1] if "mega.nz/" in link else ""
        if path_part:
            parts = path_part.split("/")
            if len(parts) >= 2 and parts[1]:
                # parts[1] is often the file/folder name before the #hash
                name = parts[1].split("#")[0]
                if name and not name.startswith("!"):
                    return name
    except Exception:
        pass
    return ""


# =============================================================================
# Parse megadl progress output
# =============================================================================
# megadl output formats vary by version. We handle the common patterns:
#
# Single file:
#   filename.mp4: 45.2%  123.4 MiB  273.0 MiB  5.2 MiB/s
#
# Folder (multiple files):
#   folder/file1.mp4: 45.2%  123.4 MiB  273.0 MiB  5.2 MiB/s
#   folder/sub/file2.jpg: 100%  1.2 MiB  1.2 MiB  0 B/s
#
# Error messages:
#   ERROR: Can't download file - file not found
#   ERROR: Link key is invalid

_PROGRESS_RE = re.compile(
    r"([\d.]+)\s*%\s+"            # 1: percentage
    r"([\d.]+\s*[KMG]?i?B)\s+"   # 2: downloaded size
    r"([\d.]+\s*[KMG]?i?B)\s+"   # 3: total size
    r"([\d.]+\s*[KMG]?i?B/s)"    # 4: speed
)

_FILENAME_RE = re.compile(r"^(.+?):\s+")

_ERROR_RE = re.compile(r"ERROR[:\s]+(.+)", re.IGNORECASE)


def _parse_progress(line: str):
    """
    Parse megadl output line.

    Returns:
        dict with keys: name, percent, downloaded, total, speed
        None if line is not a progress line
    """
    line = line.strip()
    if not line:
        return None

    m = _PROGRESS_RE.search(line)
    if not m:
        return None

    name_match = _FILENAME_RE.match(line)
    name = name_match.group(1).strip() if name_match else ""

    return {
        "name": name,
        "percent": round(float(m.group(1))),
        "downloaded": m.group(2),
        "total": m.group(3),
        "speed": m.group(4),
    }


def _parse_error(line: str) -> str:
    """Extract error message from megadl output. Returns empty string if not an error."""
    m = _ERROR_RE.search(line)
    return m.group(1).strip() if m else ""


# =============================================================================
# Collect files from download directory
# =============================================================================
def _collect_downloaded(save_path: str, since: float) -> list:
    """
    Recursively collect files in save_path modified after `since` timestamp.

    Returns list of absolute file paths.
    """
    found = []
    for root, dirs, files in os.walk(save_path):
        for f in files:
            full = os.path.join(root, f)
            try:
                if os.path.getmtime(full) >= since:
                    found.append(full)
            except OSError:
                continue
    return sorted(found)


# =============================================================================
# Main Download Function
# =============================================================================
async def megadl(link: str, num: int):
    """
    Download file or folder from Mega.nz via megatools CLI.

    Args:
        link: Mega.nz share link (file or folder)
        num: link number for display

    Returns:
        list of downloaded file paths
    """
    _check_megadl()
    BotTimes.task_start = datetime.now()
    start_ts = BotTimes.task_start.timestamp()

    save_path = str(Paths.down_path)
    is_folder = _is_folder_link(link)
    link_hint = _extract_link_name(link)
    source_label = "Folder 📁" if is_folder else "Mega 💾"

    # Build megadl command
    command = [
        "megadl",
        "--no-ask-password",
        "--path", save_path,
        link,
    ]

    logger.info(f"Starting Mega download: {'folder' if is_folder else 'file'} — {link[:80]}")

    # Set initial status
    display_name = link_hint or ("Mega Folder" if is_folder else "Mega Download")
    Messages.download_name = display_name
    Messages.status_head = (
        f"<b>📥 Downloading</b> <code>Link {str(num).zfill(2)}</code>\n\n"
        f"<b>🏷️ Name:</b> <code>{display_name}</code>\n"
        f"<b>📦 Type:</b> <code>{source_label}</code>\n"
    )
    await status_bar(Messages.status_head, "Starting...", 0, "—", "0 B", "? B", source_label)

    # Launch as async subprocess — does NOT block the event loop
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    errors = []
    files_completed = 0
    last_update = 0.0

    try:
        while True:
            try:
                raw = await asyncio.wait_for(process.stdout.readline(), timeout=600)
            except asyncio.TimeoutError:
                process.kill()
                raise TimeoutError("Mega download timed out (no output for 10 minutes)")

            if not raw:
                break

            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            # Check for errors
            err = _parse_error(line)
            if err:
                errors.append(err)
                logger.error(f"Mega error: {err}")
                continue

            # Parse progress
            info = _parse_progress(line)
            if info:
                # Update display name from output if available
                if info["name"]:
                    Messages.download_name = info["name"]

                # Track folder progress: count completed files
                if info["percent"] == 100:
                    files_completed += 1

                Messages.status_head = (
                    f"<b>📥 Downloading</b> <code>Link {str(num).zfill(2)}</code>\n\n"
                    f"<b>🏷️ Name:</b> <code>{info['name'] or display_name}</code>\n"
                    f"<b>📦 Type:</b> <code>{source_label}</code>\n"
                )

                # Build extra info for folder downloads
                extra = source_label
                if is_folder and files_completed > 0:
                    extra = f"{source_label} | {files_completed} files done"

                now = asyncio.get_running_loop().time()
                if now - last_update >= 2:  # throttle UI updates
                    await status_bar(
                        Messages.status_head,
                        info["speed"],
                        info["percent"],
                        "Calculating...",
                        info["downloaded"],
                        info["total"],
                        extra,
                    )
                    last_update = now

            # Log notable lines
            if "downloaded successfully" in line.lower():
                logger.info(f"Mega: {line}")

        await process.wait()

    except asyncio.TimeoutError:
        process.kill()
        raise TimeoutError("Mega download timed out (no output for 10 minutes)")

    # Read any remaining stderr
    stderr_data = await process.stderr.read()
    if stderr_data:
        stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
        if stderr_text:
            for sline in stderr_text.splitlines():
                err = _parse_error(sline)
                if err:
                    errors.append(err)
                elif sline.strip():
                    logger.debug(f"Mega stderr: {sline}")

    # Check exit code
    if process.returncode != 0 and not errors:
        raise RuntimeError(f"megadl exited with code {process.returncode}")

    # If we collected errors, report them
    if errors:
        # Deduplicate
        unique_errors = list(dict.fromkeys(errors))
        error_msg = "; ".join(unique_errors[:3])
        if len(unique_errors) > 3:
            error_msg += f" (+{len(unique_errors) - 3} more)"
        raise RuntimeError(f"Mega download failed: {error_msg}")

    # Collect downloaded files
    downloaded_files = _collect_downloaded(save_path, start_ts)

    if downloaded_files:
        Transfer.download_path = save_path
        total_size = sum(os.path.getsize(f) for f in downloaded_files)
        logger.info(
            f"Mega download complete: {len(downloaded_files)} file(s), "
            f"{sizeUnit(total_size)} total"
        )
    else:
        logger.warning("Mega: no downloaded files found in save path")

    return downloaded_files
