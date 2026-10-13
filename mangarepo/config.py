# Made by @codexnano from scratch.
# If you find any bugs, please let us know in the channel updates.
# You can 'git pull' to stay updated with the latest changes.

import os
from dotenv import load_dotenv
load_dotenv()
class Config:
    API_ID = int(os.getenv("API_ID", "0"))
    API_HASH = os.getenv("API_HASH", "")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    MONGO_DB_URI = os.getenv("MONGO_DB_URI") or os.getenv("MONGO_URL", "")
    OWNER_ID = [int(x) for x in os.getenv("OWNER_ID", "").split()] if os.getenv("OWNER_ID") else []
    LOG_GROUP = int(os.getenv("LOG_GROUP", "0"))
    MAX_IMAGE_SIZE = 10 * 1024 * 1024
    MAX_PDF_SIZE = 50 * 1024 * 1024
    DOWNLOAD_DIR = "downloads"
    MAX_IMAGE_WIDTH = 2500
    JPEG_QUALITY = 100
    ENABLE_WEBP = True # Option to use webp if needed
    FSUB_CHANNELS = []
    _fsub = os.getenv("FSUB_CHANNELS", "")
    if _fsub:
        for x in _fsub.split():
            try:
                FSUB_CHANNELS.append(int(x))
            except ValueError:
                FSUB_CHANNELS.append(x)
