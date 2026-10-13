import motor.motor_asyncio
import logging
from datetime import datetime, date
from typing import List, Optional
from config import MONGO_URL, MONGO_NAME

logging.basicConfig(level=logging.INFO)


class Database:
    def __init__(self, uri, db_name=MONGO_NAME):
        if uri:
            self.client   = motor.motor_asyncio.AsyncIOMotorClient(uri)
            self.db       = self.client[db_name]

            # ── Collections ──────────────────────────────────────
            self.user_data                  = self.db["users"]
            self.channel_data               = self.db["channels"]
            self.admins_data                = self.db["admins"]
            self.del_timer_data             = self.db["del_timer"]
            self.ban_data                   = self.db["ban_data"]
            self.fsub_data                  = self.db["fsub"]
            self.rqst_fsub_data             = self.db["request_forcesub"]
            self.rqst_fsub_Channel_data     = self.db["request_forcesub_channel"]
            self.sequence_mode              = self.db["sequence_mode"]
            self.processed                  = self.db["processed_episodes"]
            self.settings                   = self.db["user_settings"]
            self.mapped_channels            = self.db["mapped_channels"]
            self.favorites                  = self.db["favorites"]
            self.watch_history              = self.db["watch_history"]

            # Backward-compat aliases
            self.col    = self.user_data
            self.users  = self.user_data
            self.admins = self.admins_data
        else:
            # Graceful no-op when MONGO_URL is not set
            self.client = self.db = None
            self.user_data = self.channel_data = self.admins_data = None
            self.del_timer_data = self.ban_data = self.fsub_data = None
            self.watch_history = None
            self.rqst_fsub_data = self.rqst_fsub_Channel_data = None
            self.sequence_mode = self.processed = self.settings = None
            self.col = self.users = self.admins = None
            logging.warning("MONGO_URL not set — database features will be disabled.")

    # ══════════════════════════════════════════════════════
    #  USER MANAGEMENT
    # ══════════════════════════════════════════════════════

    def _new_user(self, user_id: int, username: str = None) -> dict:
        return dict(
            _id=int(user_id),
            username=username.lower() if username else None,
            join_date=date.today().isoformat(),
            active=True,
            ban_status=dict(
                is_banned=False,
                ban_duration=0,
                banned_on=date.max.isoformat(),
                ban_reason="",
            ),
        )

    async def add_user(self, user_id: int, username: str = None):
        """Add a new user if they don't already exist."""
        if self.user_data is None:
            return
        if not await self.is_user_exist(user_id):
            user = self._new_user(user_id, username)
            try:
                await self.user_data.insert_one(user)
                logging.info(f"ɴᴇᴡ ᴜꜱᴇʀ ᴀᴅᴅᴇᴅ: {user_id}")
            except Exception as e:
                logging.error(f"ᴇʀʀᴏʀ ᴀᴅᴅɪɴɢ ᴜꜱᴇʀ {user_id}: {e}")
        else:
            # Keep 'active' flag fresh
            await self.user_data.update_one(
                {"_id": int(user_id)},
                {"$set": {"active": True}},
                upsert=True
            )

    async def is_user_exist(self, user_id: int) -> bool:
        if self.user_data is None:
            return False
        try:
            return bool(await self.user_data.find_one({"_id": int(user_id)}))
        except Exception as e:
            logging.error(f"ᴇʀʀᴏʀ ᴄʜᴇᴄᴋɪɴɢ ᴜꜱᴇʀ {user_id}: {e}")
            return False

    async def get_all_users(self):
        if self.user_data is None:
            return iter([])
        return self.user_data.find({})

    async def total_users_count(self) -> int:
        if self.user_data is None:
            return 0
        return await self.user_data.count_documents({})

    # Alias used in broadcast
    async def get_user_count(self) -> int:
        return await self.total_users_count()

    async def get_total_users(self, active_only=False) -> int:
        if self.user_data is None:
            return 0
        query = {"active": True} if active_only else {}
        return await self.user_data.count_documents(query)

    async def delete_user(self, user_id: int):
        if self.user_data is not None:
            await self.user_data.delete_one({"_id": int(user_id)})

    # ══════════════════════════════════════════════════════
    #  BAN MANAGEMENT
    # ══════════════════════════════════════════════════════

    async def is_user_banned(self, user_id: int) -> bool:
        if self.ban_data is None:
            return False
        try:
            user = await self.ban_data.find_one({"_id": int(user_id)})
            if user:
                return user.get("ban_status", {}).get("is_banned", False)
            return False
        except Exception as e:
            logging.error(f"ᴇʀʀᴏʀ ᴄʜᴇᴄᴋɪɴɢ ʙᴀɴ ꜰᴏʀ {user_id}: {e}")
            return False

    async def ban_user(self, user_id: int, reason: str = "") -> bool:
        if self.ban_data is None:
            return False
        try:
            await self.ban_data.update_one(
                {"_id": int(user_id)},
                {"$set": {"ban_status": dict(
                    is_banned=True,
                    ban_duration=0,
                    banned_on=date.today().isoformat(),
                    ban_reason=reason or "")}},
                upsert=True)
            return True
        except Exception as e:
            logging.error(f"ᴇʀʀᴏʀ ʙᴀɴɴɪɴɢ {user_id}: {e}")
            return False

    async def unban_user(self, user_id: int) -> bool:
        if self.ban_data is None:
            return False
        try:
            await self.ban_data.update_one(
                {"_id": int(user_id)},
                {"$set": {"ban_status": dict(
                    is_banned=False,
                    ban_duration=0,
                    banned_on=date.max.isoformat(),
                    ban_reason="")}},
                upsert=True)
            return True
        except Exception as e:
            logging.error(f"ᴇʀʀᴏʀ ᴜɴʙᴀɴɴɪɴɢ {user_id}: {e}")
            return False

    async def banned_users(self) -> list:
        if self.ban_data is None:
            return []
        try:
            out = []
            async for u in self.ban_data.find({"ban_status.is_banned": True}):
                out.append(u)
            return out
        except Exception as e:
            logging.error(f"ᴇʀʀᴏʀ ʟɪꜱᴛɪɴɢ ʙᴀɴꜱ: {e}")
            return []

    # ══════════════════════════════════════════════════════
    #  FAVORITES
    # ══════════════════════════════════════════════════════

    async def add_favorite(self, user_id: int, anime_id: str, title: str):
        if self.favorites is not None:
            await self.favorites.update_one(
                {"user_id": user_id},
                {"$addToSet": {"items": {"id": anime_id, "title": title}}},
                upsert=True
            )

    async def remove_favorite(self, user_id: int, anime_id: str):
        if self.favorites is not None:
            await self.favorites.update_one(
                {"user_id": user_id},
                {"$pull": {"items": {"id": anime_id}}}
            )

    async def get_favorites(self, user_id: int):
        if self.favorites is None:
            return []
        data = await self.favorites.find_one({"user_id": user_id})
        return data.get("items", []) if data else []

    # ══════════════════════════════════════════════════════
    #  WATCH HISTORY (continue watching)
    # ══════════════════════════════════════════════════════

    async def add_history(self, user_id: int, title: str, episode_url: str,
                          next_url: str = None, ep_num=None, provider: str = ""):
        """Record a downloaded episode at the front of the user's history
        (deduplicated, capped at 10 entries)."""
        if self.watch_history is None:
            return
        try:
            await self.watch_history.update_one(
                {"user_id": int(user_id)},
                {"$pull": {"items": {"url": episode_url}}},
            )
            await self.watch_history.update_one(
                {"user_id": int(user_id)},
                {"$push": {
                    "items": {
                        "$each": [{
                            "title": title or "",
                            "url": episode_url or "",
                            "next": next_url or "",
                            "ep": str(ep_num or ""),
                            "provider": provider or "",
                            "ts": datetime.utcnow(),
                        }],
                        "$position": 0,
                        "$slice": 10,
                    }
                }},
                upsert=True,
            )
        except Exception as e:
            logging.error(f"add_history error: {e}")

    async def get_history(self, user_id: int, limit: int = 8) -> list:
        if self.watch_history is None:
            return []
        try:
            data = await self.watch_history.find_one({"user_id": int(user_id)})
            return (data.get("items", []) or [])[:limit]
        except Exception as e:
            logging.error(f"get_history error: {e}")
            return []

    async def clear_history(self, user_id: int):
        if self.watch_history is None:
            return
        try:
            await self.watch_history.update_one(
                {"user_id": int(user_id)}, {"$set": {"items": []}}, upsert=True
            )
        except Exception as e:
            logging.error(f"clear_history error: {e}")

    async def get_db_stats(self):
        """Fetch database storage statistics."""
        if self.db is None:
            return None
        try:
            stats = await self.db.command("dbStats")
            return {
                "data_size": stats.get("dataSize", 0),
                "storage_size": stats.get("storageSize", 0),
                "index_size": stats.get("indexSize", 0),
                "total_size": stats.get("storageSize", 0) + stats.get("indexSize", 0)
            }
        except Exception as e:
            logging.error(f"ᴇʀʀᴏʀ ꜰᴇᴛᴄʜɪɴɢ ᴅʙ ꜱᴛᴀᴛꜱ: {e}")
            return None


# ── Singleton instances ──────────────────────────────────────────────────────
db = Database(MONGO_URL)

# Backward-compat alias so any existing code using `Seishiro.x` keeps working
Seishiro = db
