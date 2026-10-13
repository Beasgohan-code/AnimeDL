# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
Global variables and configuration classes for the bot.

All mutable state lives here. Import the class you need and mutate
its attributes directly — this module is the single source of truth.
"""

import config
from time import time
from datetime import datetime
from pathlib import Path
from collections import deque
from pyrogram.types import Message


# =============================================================================
# Bot Configuration Class
# =============================================================================
class BOT:
    """
    Main bot configuration class.
    Stores all bot settings, options, modes, and states.
    """

    # Download sources list
    SOURCE: list = []

    # Active asyncio task reference
    TASK = None

    class Setting:
        """Persistent user preference settings (survive across tasks)."""
        stream_upload: str = config.DEFAULT_UPLOAD_MODE  # "media" or "document"
        convert_video: str = "Yes"
        convert_quality: str = "Low"
        caption: str = "Regular"
        split_video: str = "Split"
        prefix: str = ""
        suffix: str = ""
        thumbnail: bool = False
        photo_mode: str = "Group"  # "Group" (batch of 10) or "Single" (one by one)
        auto_delete: bool = False
        auto_delete_delay: int = 30
        autorename_template: str = ""
        auto_screenshot: bool = False
        screenshot_count: int = 5
        screenshot_watermark: str = ""

    class Options:
        """Runtime options for the current task (reset each task)."""
        stream_upload: bool = True
        convert_video: bool = True
        convert_quality: bool = False
        is_split: bool = True
        caption: str = "code"
        video_out: str = "mp4"
        custom_name: str = ""
        file_name: str = ""
        zip_pswd: str = ""
        unzip_pswd: str = ""
        ytdl_format: str = "bestvideo+bestaudio/best"  # YT-DLP format string
        bandwidth_limit: str = config.BANDWIDTH_LIMIT

    class Mode:
        """Current task mode."""
        mode: str = "leech"      # leech | mirror | dir-leech
        type: str = "normal"     # normal | zip | unzip | undzip
        ytdl: bool = False
        gallery: bool = False    # gallery-dl mode for image galleries

    class State:
        """Bot state tracking flags."""
        started: bool = False
        task_going: bool = False
        prefix: bool = False
        suffix: bool = False
        setting_autodelete_delay: bool = False
        set_ss_watermark: bool = False
        shutting_down: bool = False  # Set True when SIGINT/SIGTERM received — blocks new long tasks


# =============================================================================
# Download Queue
# =============================================================================
class DownloadQueue:
    """
    Thread-safe download queue.
    Allows users to queue multiple links and process them sequentially.
    """

    def __init__(self):
        self._queue: deque = deque()
        self._current = None

    def add(self, links: list, mode: str = "leech", upload_type: str = "normal"):
        """Add a batch of links to the queue."""
        self._queue.append({
            "links": links,
            "mode": mode,
            "type": upload_type,
            "added_at": datetime.now(),
        })

    def next(self):
        """Get the next item from the queue."""
        if self._queue:
            self._current = self._queue.popleft()
            return self._current
        self._current = None
        return None

    def peek(self):
        """Look at the next item without removing it."""
        return self._queue[0] if self._queue else None

    @property
    def pending(self) -> int:
        return len(self._queue)

    @property
    def current(self):
        return self._current

    def clear(self):
        self._queue.clear()
        self._current = None

    def size(self) -> int:
        """Return the number of items in the queue."""
        return len(self._queue)

    def list_items(self) -> list:
        """Return a list summary of queued items."""
        items = []
        for i, item in enumerate(self._queue, 1):
            link_count = len(item["links"])
            first_link = item["links"][0][:60] if item["links"] else "N/A"
            items.append(f"  {i}. `{first_link}{'...' if len(item['links'][0]) > 60 else ''}` ({link_count} link{'s' if link_count > 1 else ''})")
        return items


# Global queue instance
Queue = DownloadQueue()


# =============================================================================
# Admin / Multi-User Management
# =============================================================================
class Admin:
    """
    Multi-user access control.
    OWNER always has full access. Additional users are loaded from config.
    """

    _allowed: set = set(config.ALLOWED_USERS)

    @classmethod
    def is_allowed(cls, user_id: int) -> bool:
        """Check if a user is allowed to use the bot."""
        return user_id == config.OWNER_ID or user_id in cls._allowed

    @classmethod
    def add_user(cls, user_id: int):
        cls._allowed.add(user_id)

    @classmethod
    def remove_user(cls, user_id: int):
        cls._allowed.discard(user_id)

    @classmethod
    def list_users(cls) -> list:
        users = [config.OWNER_ID] + sorted(cls._allowed)
        return users

    @classmethod
    def is_owner(cls, user_id: int) -> bool:
        return user_id == config.OWNER_ID


# =============================================================================
# YT-DLP Download Status
# =============================================================================
class YTDL:
    """Real-time YT-DLP download status."""
    header: str = ""
    speed: str = ""
    percentage: float = 0.0
    eta: str = ""
    done: str = ""
    left: str = ""


# =============================================================================
# Transfer Statistics
# =============================================================================
class Transfer:
    """File transfer statistics tracker."""
    down_bytes: list = [0, 0]
    up_bytes: list = [0, 0]
    total_down_size: int = 0
    sent_file: list = []
    sent_file_names: list = []
    download_path: str = ""


# =============================================================================
# Task Error Handling
# =============================================================================
class TaskError:
    """Task error tracker."""
    state: bool = False
    text: str = ""


# =============================================================================
# Time Tracking
# =============================================================================
class BotTimes:
    """Bot timing tracker for progress calculations."""
    current_time: float = time()
    start_time: datetime = datetime.now()
    task_start: datetime = datetime.now()


# =============================================================================
# File Paths (using config.py paths)
# =============================================================================
class Paths:
    """File system paths — all derived from config.BASE_DIR."""

    # Base paths from config
    WORK_PATH: str = str(config.WORK_PATH)
    down_path: str = str(config.DOWNLOADS_PATH)

    # Thumbnail paths
    THMB_PATH: str = str(config.THUMBNAIL_PATH / "Thumbnail.jpg")
    VIDEO_FRAME: str = str(config.TEMP_PATH / "video_frame.jpg")
    ASSETS_IMAGES: str = str(Path(__file__).parent.parent.parent / "assets" / "images")
    HERO_IMAGE: str = ""
    DEFAULT_HERO: str = ""

    # Google Drive mount point
    MOUNTED_DRIVE: str = "/content/drive"

    # Working subdirectories
    temp_dirleech_path: str = str(config.WORK_PATH / "dir_leech_temp")
    mirror_dir: str = str(config.DOWNLOADS_PATH / "mirror")
    temp_zpath: str = str(config.TEMP_PATH / "zipped")
    temp_unzip_path: str = str(config.TEMP_PATH / "unzipped")
    temp_files_dir: str = str(config.TEMP_PATH / "leech_temp")
    thumbnail_ytdl: str = str(config.TEMP_PATH / "ytdl_thumbnails")

    # Token file
    access_token: str = config.TOKEN_PICKLE_PATH

    # YT-DLP cookie file
    ytdl_cookies: str = config.YTDL_COOKIES_FILE

    # Default cookie file path (uploaded via /setcookies)
    COOKIE_FILE: str = str(config.SESSIONS_PATH / "cookies.txt")


# =============================================================================
# Message Templates
# =============================================================================
class Messages:
    """Dynamic message content storage."""
    caution_msg: str = ""
    download_name: str = ""
    task_msg: str = ""
    status_head: str = ""
    dump_task: str = ""
    src_link: str = ""
    link_p: str = ""


# =============================================================================
# Message Objects
# =============================================================================
class MSG:
    """Telegram message object references."""
    sent_msg = Message(id=1)
    status_msg = Message(id=2)


# =============================================================================
# Aria2c Configuration
# =============================================================================
class Aria2c:
    """Aria2c downloader state."""
    link_info: bool = False


# =============================================================================
# Google Drive Service
# =============================================================================
class Gdrive:
    """Google Drive API service holder."""
    service = None


# =============================================================================
# Bot Statistics
# =============================================================================
class BotStats:
    """Cumulative bot usage statistics."""
    total_tasks: int = 0
    total_downloaded: int = 0
    total_uploaded: int = 0
    failed_tasks: int = 0
    start_time: datetime = datetime.now()


# =============================================================================
# Constants (re-exported from config for convenience)
# =============================================================================
MAX_FILE_SIZE = config.MAX_FILE_SIZE
MAX_VIDEO_SPLIT_SIZE = config.MAX_VIDEO_SPLIT_SIZE
VERSION = config.VERSION
BUILD_DATE = config.BUILD_DATE
