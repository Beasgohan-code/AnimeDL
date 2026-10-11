# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
Torrent/Magnet downloader using python-libtorrent.

Handles magnet links and .torrent files with:
- Fast metadata retrieval via DHT
- Real-time progress tracking (speed, ETA, peers, pieces)
- Resume data persistence for interrupted downloads
- Configurable download directory and limits
"""

import os
import time
import asyncio
import logging
from datetime import datetime

try:
    import libtorrent as lt
except ImportError:
    lt = None

from leechbot.utility.variables import (
    BOT, Transfer, MSG, Messages, BotTimes,
)
from leechbot.utility.helper import sizeUnit, status_bar
import config

logger = logging.getLogger(__name__)

# =============================================================================
# Resume data directory
# =============================================================================
RESUME_DIR = config.SESSIONS_PATH / "torrent_resume"
RESUME_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Helpers
# =============================================================================
def _check_libtorrent():
    """Raise a clear error if libtorrent is not installed."""
    if lt is None:
        raise ImportError(
            "libtorrent is not installed. Install it via:\n"
            "  • Debian/Ubuntu: sudo apt install python3-libtorrent\n"
            "  • Conda:         conda install -c conda-forge libtorrent\n"
            "  • Arch:          sudo pacman -S libtorrent-rasterbar\n"
            "  • Colab:         !apt-get install -y python3-libtorrent"
        )


def _get_resume_file(info_hash: str):
    return RESUME_DIR / f"{info_hash}.resume"


def _save_resume(handle, info_hash: str):
    """Save resume data for interrupted downloads."""
    try:
        resume_data = lt.bencode(handle.save_resume_data())
        path = _get_resume_file(info_hash)
        with open(path, "wb") as f:
            f.write(resume_data)
        logger.debug(f"Saved resume data: {info_hash}")
    except Exception as e:
        logger.debug(f"Could not save resume data: {e}")


def _load_resume(info_hash: str) -> bytes:
    """Load resume data if available."""
    path = _get_resume_file(info_hash)
    if path.exists():
        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception:
            pass
    return None


def _clear_resume(info_hash: str):
    """Remove resume data after successful download."""
    path = _get_resume_file(info_hash)
    if path.exists():
        try:
            path.unlink()
        except Exception:
            pass


# =============================================================================
# Tracker list (boosts magnet link connectivity)
# =============================================================================
TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.bittor.pw:1337/announce",
    "udp://public.popcorn-tracker.org:6969/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://explodie.org:6969/announce",
    "udp://tracker.moeking.me:6969/announce",
    "udp://tracker.internetwarriors.net:1337/announce",
    "udp://tracker.coppersurfer.tk:6969/announce",
    "udp://9.rarbg.to:2710/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "http://tracker.opentrackr.org:1337/announce",
    "http://tracker.openbittorrent.com:80/announce",
]


# =============================================================================
# Parse magnet URI for name hint
# =============================================================================
def _magnet_name(magnet_uri: str) -> str:
    """Extract display name from magnet URI if present."""
    try:
        params = lt.parse_magnet_uri(magnet_uri)
        name = params.name
        if name:
            return name
    except Exception:
        pass
    return "Magnet Download"


# =============================================================================
# Get torrent/magnet name (for get_d_name)
# =============================================================================
async def get_torrent_name(link: str) -> str:
    """Resolve human-readable name from magnet/torrent link."""
    _check_libtorrent()
    if BOT.Options.custom_name:
        return BOT.Options.custom_name

    if link.startswith("magnet:"):
        return _magnet_name(link)

    if link.endswith(".torrent"):
        try:
            info = lt.torrent_info(link)
            return info.name() or "Torrent Download"
        except Exception:
            pass

    return "Torrent Download"


# =============================================================================
# Main Download Function
# =============================================================================
async def torrent_download(link: str, num: int):
    """
    Download a torrent or magnet link using libtorrent.

    Args:
        link: magnet URI or .torrent file path
        num: link number for display
    """
    _check_libtorrent()
    BotTimes.task_start = datetime.now()

    # ─── Session setup ───────────────────────────────────────
    settings = {
        "listen_interfaces": "0.0.0.0:6881",
        "enable_dht": True,
        "enable_lsd": True,
        "enable_natpmp": True,
        "enable_upnp": True,
        "anonymous_mode": False,
        "dht_bootstrap_nodes": "router.bittorrent.com:6881,router.utorrent.com:6881,dht.transmissionbt.com:6881",
    }

    ses = lt.session(settings)
    for tracker in TRACKERS:
        ses.add_tracker({"url": tracker})

    # ─── Add torrent ─────────────────────────────────────────
    params = {
        "save_path": str(config.DOWNLOADS_PATH),
        "storage_mode": lt.storage_mode_t.storage_mode_sparse,
    }

    if link.startswith("magnet:"):
        params["flags"] = lt.torrent_flags.upload_mode
        handle = lt.add_magnet_uri(ses, link, params)
        logger.info(f"Added magnet link, fetching metadata...")
    elif link.endswith(".torrent") and os.path.exists(link):
        info = lt.torrent_info(link)
        params["ti"] = info
        handle = ses.add_torrent(params)
        logger.info(f"Added torrent: {info.name()}")
    else:
        raise ValueError(f"Invalid torrent/magnet link: {link[:80]}")

    # Apply bandwidth limit
    if BOT.Options.bandwidth_limit:
        try:
            limit = int(BOT.Options.bandwidth_limit.replace("K", "000").replace("M", "000000"))
            handle.set_download_limit(limit)
        except Exception:
            pass

    # Load resume data if available
    info_hash = str(handle.info_hash())
    resume_data = _load_resume(info_hash)
    if resume_data:
        handle.read_resume_data(resume_data)
        logger.info(f"Loaded resume data for {info_hash[:8]}...")

    # ─── Wait for metadata (magnet only) ─────────────────────
    if link.startswith("magnet:"):
        Messages.status_head = (
            f"<b>📥 Downloading</b> <code>Link {str(num).zfill(2)}</code>\n\n"
            f"<b>🏷️ Name:</b> <code>Fetching metadata...</code>\n"
            f"<b>🔗 Source:</b> <code>Magnet Link</code>\n"
        )
        await status_bar(Messages.status_head, "⏳ Waiting...", 0, "∞", "0 B", "? B", "Torrent 🧲")

        timeout = 120  # 2 min for metadata
        start = time.time()
        while not handle.has_metadata():
            await asyncio.sleep(1)
            elapsed = int(time.time() - start)
            peers = handle.status().num_peers
            print(f"\r⏳ Fetching metadata... {elapsed}s | Peers: {peers}", end="", flush=True)
            if elapsed > timeout:
                _save_resume(handle, info_hash)
                raise TimeoutError("Metadata fetch timed out (120s). Try again or add more trackers.")

        print()  # Newline after metadata progress
        logger.info(f"Metadata received: {handle.torrent_file().name()}")

    # ─── Update status with real name ────────────────────────
    torrent_name = handle.torrent_file().name() if handle.has_metadata() else "Torrent Download"
    total_size = handle.torrent_file().total_size()
    Messages.status_head = (
        f"<b>📥 Downloading</b> <code>Link {str(num).zfill(2)}</code>\n\n"
        f"<b>🏷️ Name:</b> <code>{torrent_name}</code>\n"
        f"<b>📦 Size:</b> <code>{sizeUnit(total_size)}</code>\n"
        f"<b>🔗 Source:</b> <code>{'Magnet 🧲' if link.startswith('magnet:') else 'Torrent'}</code>\n"
    )
    Transfer.total_down_size += total_size

    # ─── Download loop ───────────────────────────────────────
    handle.set_flags(lt.torrent_flags.sequential_download)
    last_progress_log = 0

    while True:
        s = handle.status()

        if s.state == lt.torrent_status.seeding:
            logger.info(f"Download complete (seeding): {torrent_name}")
            _clear_resume(info_hash)
            break

        if s.state == lt.torrent_status.finished:
            logger.info(f"Download finished: {torrent_name}")
            _clear_resume(info_hash)
            break

        # Check for errors
        if s.errc:
            _save_resume(handle, info_hash)
            raise RuntimeError(f"Torrent error: {s.errc.message()}")

        # Progress
        progress = s.progress * 100
        down_speed = s.download_rate
        up_speed = s.upload_rate
        downloaded = s.total_done
        num_peers = s.num_peers
        num_seeds = s.num_seeds

        speed_string = f"{sizeUnit(down_speed)}/s"
        eta_secs = int((total_size - downloaded) / down_speed) if down_speed > 0 else 0
        h, m, sec = eta_secs // 3600, (eta_secs % 3600) // 60, eta_secs % 60
        eta = f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"

        state_str = {
            lt.torrent_status.checking_files: "🔍 Checking",
            lt.torrent_status.downloading_metadata: "🧲 Metadata",
            lt.torrent_status.downloading: "📥 Downloading",
            lt.torrent_status.finished: "✅ Finished",
            lt.torrent_status.seeding: "🌱 Seeding",
            lt.torrent_status.checking_resume_data: "🔍 Resuming",
        }.get(s.state, "⏳ Waiting")

        await status_bar(
            Messages.status_head,
            speed_string,
            int(progress),
            eta,
            sizeUnit(downloaded),
            sizeUnit(total_size),
            f"Torrent 🧲 | {num_peers}P/{num_seeds}S",
        )

        # Log progress periodically
        if time.time() - last_progress_log > 30:
            logger.info(
                f"Torrent: {progress:.1f}% | {speed_string} | "
                f"Peers: {num_peers} | Seeds: {num_seeds} | "
                f"Downloaded: {sizeUnit(downloaded)}/{sizeUnit(total_size)}"
            )
            last_progress_log = time.time()

        # Save resume data periodically
        if int(time.time()) % 60 == 0:
            _save_resume(handle, info_hash)

        await asyncio.sleep(1)

    # ─── Copy to download path ───────────────────────────────
    download_path = config.DOWNLOADS_PATH
    torrent_files = []
    torrent_info = handle.torrent_file()

    if torrent_info.num_files() > 1:
        # Multi-file torrent — use torrent name as folder
        src = download_path / torrent_name
        if src.exists():
            Transfer.download_path = str(src)
            for root, dirs, files in os.walk(str(src)):
                for f in files:
                    torrent_files.append(os.path.join(root, f))
    else:
        # Single file
        for f in torrent_info.files():
            filepath = download_path / f.path
            if filepath.exists():
                Transfer.download_path = str(filepath)
                torrent_files.append(str(filepath))

    logger.info(f"Torrent download complete: {torrent_name} ({len(torrent_files)} files)")
    return torrent_files
