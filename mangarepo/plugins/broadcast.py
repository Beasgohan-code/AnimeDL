# Made by @codexnano from scratch.
# If you find any bugs, please let us know in the channel updates.
# You can 'git pull' to stay updated with the latest changes.

import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated
from mangarepo.database.db import db
from mangarepo.config import Config
from datetime import datetime, timedelta
log = logging.getLogger(__name__)
async def ttl_reply(m: Message, text: str, ttl: int = 15):
    sent = await m.reply(text)
    await asyncio.sleep(ttl)
    try:
        await sent.delete()
    except:
        pass
async def delete_broadcast_msgs(app, data):
    log.info(f"[TTL] Starting auto-delete for {len(data)} messages...")
    for chat_id, msg_id in data:
        try:
            await app.delete_messages(chat_id, msg_id)
        except Exception as e:
            log.warning(f"[TTL] Failed to delete msg {msg_id} in {chat_id}: {e}")
    log.info("[TTL] Auto-delete finished.")
@Client.on_message(filters.command("cbroadcast") & filters.reply & filters.private)
async def user_channel_broadcast(c: Client, m: Message):
    uid = m.from_user.id
    msg = m.reply_to_message
    ttl_mins = 0
    args = m.command[1:]
    if args:
        try:
            if args[0] == "--time" and len(args) > 1:
                ttl_mins = int(args[1])
            else:
                ttl_mins = int(args[0])
        except ValueError:
            pass
    channels = await db.get_user_channels(uid)
    if not channels:
        return await ttl_reply(m, "<b>[X] Error:</b> You haven't added any channels yet.")
    status_msg = await m.reply(f"<blockquote>[!] Broadcasting to {len(channels)} channels...</blockquote>")
    success_data = []
    failed = 0
    for cid in channels:
        try:
            sent = await msg.copy(cid)
            success_data.append((cid, sent.id))
        except FloodWait as e:
            await asyncio.sleep(e.value)
            sent = await msg.copy(cid)
            success_data.append((cid, sent.id))
        except Exception as e:
            failed += 1
            log.error(f"Channel Broadcast fail for {cid}: {e}")
    success_count = len(success_data)
    ttl_txt = ""
    if ttl_mins > 0 and success_data:
        from bot import sched, app as bot_app
        run_at = datetime.utcnow() + timedelta(minutes=ttl_mins)
        await db.add_task("broadcast_delete", success_data, run_at)
        sched.add_job(delete_broadcast_msgs, 'date', run_date=run_at, args=[bot_app, success_data])
        ttl_txt = f"│ <b>Auto-Delete:</b> <code>{ttl_mins} mins</code>\n"
    res_txt = (
        "<b>┌─ CHANNEL BROADCAST ─┐</b>\n\n"
        f"│ <b>Channels:</b> {len(channels)}\n"
        f"│ <b>Sent:</b> {success_count}\n"
        f"│ <b>Failed:</b> {failed}\n"
        f"{ttl_txt}"
        "└───────────────────\n\n"
        "<i>Self-destructing status in 20s</i>"
    )
    await status_msg.edit(res_txt)
    await asyncio.sleep(20)
    try:
        await status_msg.delete()
        await m.delete()
    except:
        pass
