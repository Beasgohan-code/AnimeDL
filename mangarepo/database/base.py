# Made by @codexnano from scratch.
# If you find any bugs, please let us know in the channel updates.
# You can 'git pull' to stay updated with the latest changes.

from motor.motor_asyncio import AsyncIOMotorClient
from mangarepo.config import Config
import logging
log = logging.getLogger(__name__)
class BaseDB:
    def __init__(self):
        try:
            if not Config.MONGO_DB_URI:
                raise ValueError("MONGO_DB_URI is not set in environment variables")
            self.c = AsyncIOMotorClient(
                Config.MONGO_DB_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                socketTimeoutMS=10000
            )
            self.db = self.c.BotDB
            self.users = self.db.users
            self.subs = self.db.subs
            self.cache = self.db.cache
            self.conf = self.db.conf
            self._indexes_cleaned = False
            log.info("[DB] MongoDB client initialized successfully")
        except ValueError as e:
            log.critical(f"[DB] Configuration error: {e}")
            raise
        except Exception as e:
            log.critical(f"[DB] Failed to initialize MongoDB client: {e}")
            raise ConnectionError(f"Could not connect to MongoDB: {e}")
    async def cleanup_indexes(self):
        if self._indexes_cleaned:
            return
        try:
            indexes = await self.cache.index_information()
            problematic_indexes = ['mid_1_src_1', 'mid_1', 'src_1']
            for idx_name in problematic_indexes:
                if idx_name in indexes:
                    try:
                        await self.cache.drop_index(idx_name)
                        log.info(f"[DB] Dropped stale index: {idx_name}")
                    except Exception as e:
                        log.warning(f"[DB] Failed to drop index {idx_name}: {e}")
            await self._ensure_indexes()
            self._indexes_cleaned = True
        except Exception as e:
            log.warning(f"[DB] Index cleanup failed: {e}")
    async def _ensure_indexes(self):
        try:
            await self.users.create_index("id", unique=True, background=True)
            await self.subs.create_index([("uid", 1), ("sid", 1)], background=True)
            await self.subs.create_index([("uid", 1), ("cid", 1)], background=True)
            await self.subs.create_index([("uid", 1), ("title", 1)], background=True)
            await self.subs.create_index("sid", background=True)
            await self.cache.create_index("ts", expireAfterSeconds=3600, background=True)
            await self.conf.create_index([("uid", 1), ("key", 1)], unique=True, background=True)
            log.info("[DB] Performance indexes created/verified")
        except Exception as e:
            log.warning(f"[DB] Index creation warning: {e}")
