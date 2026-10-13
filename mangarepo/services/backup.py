# Made by @codexnano from scratch.
# If you find any bugs, please let us know in the channel updates.
# You can 'git pull' to stay updated with the latest changes.

import json
import logging
import asyncio
from datetime import datetime
from pathlib import Path
from mangarepo.database.db import db
from mangarepo.config import Config
log = logging.getLogger(__name__)
async def create_db_backup(app):
    if not Config.LOG_GROUP:
        log.warning("[BACKUP] No LOG_GROUP configured. Skipping backup.")
        return
    try:
        log.info("[BACKUP] Starting database backup...")
        backup_data = {}
        collections = {
            "users": db.users,
            "subs": db.subs,
            "conf": db.conf,
        }
        for name, coll in collections.items():
            docs = await coll.find({}).to_list(None)
            for doc in docs:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
            backup_data[name] = docs
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"db_backup_{timestamp}.json"
        filepath = Path(filename)
        with open(filepath, "w") as f:
            json.dump(backup_data, f, indent=4)
        await app.send_document(
            chat_id=Config.LOG_GROUP,
            document=str(filepath),
            caption=f"<b>[#BACKUP] Database Auto-Backup</b>\n\n"
                    f"<b>Date:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
                    f"<b>Collections:</b> <code>{', '.join(collections.keys())}</code>\n"
                    f"<b>Total Records:</b> <code>{sum(len(v) for v in backup_data.values())}</code>"
        )
        filepath.unlink()
        log.info(f"[BACKUP] Backup sent successfully: {filename}")
    except Exception as e:
        log.error(f"[BACKUP] Backup failed: {e}")
async def create_user_backup(app, uid: int, chat_id: int):
    try:
        log.info(f"[USER_BACKUP] Creating backup for user {uid}")
        backup_data = {
            "user_id": uid,
            "backup_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "subscriptions": [],
            "settings": {}
        }
        subs = await db.subs.find({"uid": uid}).to_list(None)
        for sub in subs:
            if "_id" in sub:
                sub["_id"] = str(sub["_id"])
            backup_data["subscriptions"].append(sub)
        configs = await db.conf.find({"uid": uid}).to_list(None)
        for cfg in configs:
            key = cfg.get("key")
            val = cfg.get("val")
            if key:
                backup_data["settings"][key] = val
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"user_backup_{uid}_{timestamp}.json"
        filepath = Path(filename)
        with open(filepath, "w") as f:
            json.dump(backup_data, f, indent=4, default=str)
        sub_count = len(backup_data["subscriptions"])
        settings_count = len(backup_data["settings"])
        await app.send_document(
            chat_id=chat_id,
            document=str(filepath),
            caption=(
                f"<b>📦 Your Data Backup</b>\n\n"
                f"<blockquote>"
                f"<b>Date:</b> <code>{backup_data['backup_date']}</code>\n"
                f"<b>Subscriptions:</b> <code>{sub_count}</code>\n"
                f"<b>Settings:</b> <code>{settings_count}</code>"
                f"</blockquote>\n\n"
                f"<i>Keep this file safe to restore your data later.</i>"
            )
        )
        filepath.unlink()
        log.info(f"[USER_BACKUP] Backup sent to user {uid}")
        return True
    except Exception as e:
        log.error(f"[USER_BACKUP] Backup failed for user {uid}: {e}")
        return False
