# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
AnimeDL leech module initialization.

Sets up logging and exposes the SINGLE shared Pyrogram client (`app`)
used by the whole bot — both the anime downloader and this leech module
register their handlers on it, so they run together in one process.
"""

import asyncio
import logging
import warnings
import sys

import config

# =============================================================================
# Logging Configuration
# =============================================================================
_log_handlers = [logging.StreamHandler(sys.stdout)]

# File handler for /logs command — writes to LOGS_PATH/leechbot.log
# Rotated manually (or could be RotatingFileHandler if size grows)
try:
    from logging.handlers import RotatingFileHandler
    _log_file = config.LOGS_PATH / "leechbot.log"
    _log_file.parent.mkdir(parents=True, exist_ok=True)
    _file_handler = RotatingFileHandler(
        _log_file,
        maxBytes=2 * 1024 * 1024,  # 2 MB per file
        backupCount=3,             # keep 3 backups
        encoding="utf-8",
    )
    _file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                          datefmt="%Y-%m-%d %H:%M:%S")
    )
    _log_handlers.append(_file_handler)
    LOG_FILE = str(_log_file)
except Exception as _e:
    # If file logging fails (e.g. read-only fs), continue with stdout only
    LOG_FILE = None
    print(f"[leechbot] file logging disabled: {_e}", file=sys.stderr)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=_log_handlers,
)
logger = logging.getLogger(__name__)

# =============================================================================
# Re-export config values for backward compatibility
# =============================================================================
API_ID = config.API_ID
API_HASH = config.API_HASH
BOT_TOKEN = config.BOT_TOKEN
OWNER = config.OWNER_ID
DUMP_ID = config.DUMP_ID

# =============================================================================
# Event Loop Setup
# =============================================================================
def _setup_event_loop():
    """Ensure an event loop exists (needed for some environments like Colab)."""
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

_setup_event_loop()

# =============================================================================
# Shared Pyrogram Client
# =============================================================================
# `shared.app` is created exactly once for the entire merged bot and is
# imported here (and everywhere else) as `leechbot.app`. Handlers from this
# module and from the anime downloader both register on the same client.
from shared import app

logger.info("AnimeDL leech module initialized (v%s)", config.VERSION)
