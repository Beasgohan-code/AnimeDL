# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================

"""
LeechBot utility package initialization.
Exports all core modules and functions.
"""

from .variables import BOT, YTDL, Transfer, TaskError, BotTimes, Paths, Messages, MSG, Aria2c, Gdrive, MAX_FILE_SIZE, VERSION
from .helper import isLink, getTime, sizeUnit, fileType, getSize, sysINFO, speedETA, status_bar, keyboard, message_deleter, send_settings, status_keyboard
from .handler import Leech, Zip_Handler, Unzip_Handler, SendLogs, cancelTask
from .task_manager import taskScheduler, task_starter
from .converters import videoConverter, sizeChecker, archive, extract

__all__ = [
    "BOT",
    "YTDL",
    "Transfer",
    "TaskError",
    "BotTimes",
    "Paths",
    "Messages",
    "MSG",
    "Aria2c",
    "Gdrive",
    "MAX_FILE_SIZE",
    "VERSION",
    "isLink",
    "getTime",
    "sizeUnit",
    "fileType",
    "getSize",
    "sysINFO",
    "speedETA",
    "status_bar",
    "keyboard",
    "message_deleter",
    "send_settings",
    "status_keyboard",
    "Leech",
    "Zip_Handler",
    "Unzip_Handler",
    "SendLogs",
    "cancelTask",
    "taskScheduler",
    "task_starter",
    "videoConverter",
    "sizeChecker",
    "archive",
    "extract",
]
