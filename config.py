# ============================================================================
#  AnimeDL — Unified Configuration
# ============================================================================
#  Single configuration module for the merged bot:
#    • anime downloader core  (cantarella/)
#    • leech engine           (leechbot/)
#
#  All settings come from environment variables (or a .env file) with sane
#  defaults. Required variables are validated at startup by main.py.
#
#  License: GPL-3.0 (anime core) — see LICENSE
#           MIT (leech core)     — see LICENSES/LeechBot-LICENSE
# ============================================================================

import os
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ============================================================================
# Version
# ============================================================================
VERSION = os.getenv("VERSION", "6.0.0")
BUILD_DATE = os.getenv("BUILD_DATE", "2026-10-11")
BOT_REPO = os.getenv("BOT_REPO", "https://github.com/Beasgohan-code/AnimeDL")

# ============================================================================
# Telegram credentials (required)
# ============================================================================
API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Owner's Telegram user ID (numeric). Required.
try:
    OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
except ValueError:
    OWNER_ID = 0

# Where leech uploads go. Falls back to MAIN_CHANNEL when unset.
# A bare 10-digit id is auto-expanded to the -100… supergroup form.
DUMP_ID = int(os.getenv("DUMP_ID", "0") or 0)
if DUMP_ID and len(str(abs(DUMP_ID))) == 10 and not str(DUMP_ID).startswith("-100"):
    DUMP_ID = int(f"-100{DUMP_ID}")

# ============================================================================
# Branding / support
# ============================================================================
# Shown on the "banned" screen and in leech help panels. Set to your
# support channel/username link, e.g. https://t.me/YourChannel
SUPPORT_CONTACT = os.getenv("SUPPORT_CONTACT", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")

# ============================================================================
# Anime core — cantarella/
# ============================================================================
MONGO_URL = os.getenv("MONGO_URL", "")
MONGO_NAME = os.getenv("MONGO_NAME", "animedl")

# Target chat the anime downloads are posted to (defaults to the requester).
TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID", "")
# Primary channel for posted episodes (optional).
MAIN_CHANNEL = os.getenv("MAIN_CHANNEL", "")
# Channel that receives operational logs (optional).
LOG_CHANNEL = os.getenv("LOG_CHANNEL", "")

# Ongoing-episode scheduler interval, in seconds.
SET_INTERVAL = int(os.getenv("SET_INTERVAL", "60"))

# Contact link shown by admin tooling (defaults to the bot owner's profile).
ADMIN_URL = os.getenv("ADMIN_URL", "")

# Force-subscription prompt image + link expiry (seconds).
FSUB_PIC = os.getenv("FSUB_PIC", "https://files.catbox.moe/bli70r.jpg")
FSUB_LINK_EXPIRY = int(os.getenv("FSUB_LINK_EXPIRY", "600"))
# Image used on the /start screen.
START_PIC = os.getenv("START_PIC", "https://files.catbox.moe/4b8jvw.jpg")

# ─── Filename & caption formats ───
FORMAT = os.getenv("FORMAT", "[S{season}-E{episode}] {title} [{quality}] [{audio}]")
CAPTION = os.getenv("CAPTION", "{FORMAT}")

# ─── Progress bar template ───
PROGRESS_BAR = os.getenv(
    "PROGRESS_BAR",
    """
<blockquote> {bar} </blockquote>
<blockquote>📁 <b>{title}</b>
⚡ Speed: {speed}
📦 {current} / {total}</blockquote>
""",
)

# ============================================================================
# Reliability: keep-alive & watchdog
# ============================================================================
# Self-ping loop that keeps PaaS dynos awake + optional external rendezvous URL
KEEP_ALIVE_ENABLED = os.getenv("KEEP_ALIVE_ENABLED", "true").lower() in ("1", "true", "yes")
KEEP_ALIVE_INTERVAL = int(os.getenv("KEEP_ALIVE_INTERVAL", "600"))      # seconds
KEEP_ALIVE_URL = os.getenv("KEEP_ALIVE_URL", "").strip() or None        # external URL to ping

# Watchdog (stall / memory / disk / connection / scheduled restart)
WATCHDOG_ENABLED = os.getenv("WATCHDOG_ENABLED", "true").lower() in ("1", "true", "yes")
WATCHDOG_INTERVAL = int(os.getenv("WATCHDOG_INTERVAL", "60"))            # seconds between checks
WATCHDOG_STALL_MIN = int(os.getenv("WATCHDOG_STALL_MIN", "20"))          # min without progress → cancel
WATCHDOG_MEM_SOFT_MB = int(os.getenv("WATCHDOG_MEM_SOFT_MB", "1536"))    # gc + cleanup
WATCHDOG_MEM_HARD_MB = int(os.getenv("WATCHDOG_MEM_HARD_MB", "2560"))    # restart (if auto)
WATCHDOG_MIN_FREE_MB = int(os.getenv("WATCHDOG_MIN_FREE_MB", "1024"))    # disk floor; below → refuse tasks
WATCHDOG_AUTO_RESTART = os.getenv("WATCHDOG_AUTO_RESTART", "true").lower() in ("1", "true", "yes")

# ─── Multi-source engine ───
# GogoAnime domain rotates often — override when it moves
GOGO_BASE = os.getenv("GOGO_BASE", "https://gogoanime.bid/")
# Optional self-hosted REST APIs (appear in the /manage source cycle when set)
ANIMEDL_CONSUMET_URL = os.getenv("ANIMEDL_CONSUMET_URL", "")
ANIMEDL_ANIWATCH_URL = os.getenv("ANIMEDL_ANIWATCH_URL", "")

# ─── Rotating reply images (comma-separated URLs; empty = plain text) ───
RESPONSE_IMAGES = [
    u.strip() for u in os.getenv(
        "RESPONSE_IMAGES",
        "https://files.catbox.moe/5oonsm.jpg,"
        "https://files.catbox.moe/9ufgme.jpg,"
        "https://files.catbox.moe/4b8jvw.jpg,"
        "https://files.catbox.moe/bli70r.jpg,"
        "https://files.catbox.moe/uce0lw.jpg,"
        "https://files.catbox.moe/is7q4q.jpg",
    ).split(",") if u.strip()
]

# ============================================================================
# Leech core — leechbot/
# ============================================================================
# Base directory for all leech scratch data.
_default_base = "/tmp/animedl"
if os.path.exists("/content"):  # Google Colab
    _default_base = "/content/animedl/BOT_WORK"

BASE_DIR = Path(os.getenv("LEECHBOT_BASE_DIR", _default_base))
WORK_PATH = BASE_DIR / "work"
DOWNLOADS_PATH = WORK_PATH / "downloads"
TEMP_PATH = BASE_DIR / "temp"
THUMBNAIL_PATH = BASE_DIR / "thumbnails"
SESSIONS_PATH = Path(os.getenv("SESSIONS_PATH", str(BASE_DIR / "sessions")))
LOGS_PATH = BASE_DIR / "logs"

for _p in [WORK_PATH, DOWNLOADS_PATH, TEMP_PATH, THUMBNAIL_PATH, SESSIONS_PATH, LOGS_PATH]:
    try:
        _p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

HEARTBEAT_PATH = BASE_DIR / "heartbeat.json"

# ─── Telegram limits & transfer behaviour ───
MAX_FILE_SIZE = 2097152000          # 2 GB Telegram bot-API upload limit
MAX_VIDEO_SPLIT_SIZE = 1992294400   # 1.9 GB safe splitting threshold
AUTO_RETRY_COUNT = int(os.getenv("AUTO_RETRY_COUNT", "3"))
DEFAULT_UPLOAD_MODE = os.getenv("DEFAULT_UPLOAD_MODE", "media")  # media | document
BANDWIDTH_LIMIT = os.getenv("BANDWIDTH_LIMIT", "")  # e.g. "10M"

# ─── Health/dashboard web server ───
WEB_PORT = int(os.getenv("WEB_PORT", "8081"))  # dashboard port (health server uses PORT, default 8080)
WEB_TOKEN = os.getenv("WEB_TOKEN", "")

# ─── Google Drive mirror (optional) ───
TOKEN_PICKLE_PATH = os.getenv("TOKEN_PICKLE_PATH", str(BASE_DIR / "token.pickle"))

# ─── yt-dlp cookies (optional) ───
YTDL_COOKIES_FILE = os.getenv("YTDL_COOKIES_FILE", "")

# ─── Multi-user support for leech commands ───
# Comma-separated numeric user IDs. Empty = only the owner may leech.
ALLOWED_USERS = [
    int(x.strip()) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()
]


# ============================================================================
# Startup validation
# ============================================================================
REQUIRED = ("API_ID", "API_HASH", "BOT_TOKEN", "OWNER_ID", "MONGO_URL")


def missing_required() -> list:
    """Return the names of required settings that are not configured."""
    missing = []
    if not API_ID:
        missing.append("API_ID")
    if not API_HASH:
        missing.append("API_HASH")
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not OWNER_ID:
        missing.append("OWNER_ID")
    if not MONGO_URL:
        missing.append("MONGO_URL")
    return missing
