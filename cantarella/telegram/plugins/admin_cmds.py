from pyrogram import Client, filters
from pyrogram.enums import ParseMode, ChatMemberStatus
import time
import sys
import os
import asyncio
import psutil
import platform

from cantarella.core.database import db
from config import OWNER_ID
import uikit

async def check_admin(filter, client, message):
    try:
        user_id = message.from_user.id
        if user_id == OWNER_ID:
            return True
        return await db.is_admin(user_id)
    except Exception:
        return False

admin = filters.create(check_admin)

@Client.on_message(filters.private & filters.command("setmap"))
async def handle_setmap(client: Client, message):
    if message.from_user.id != OWNER_ID:
        is_admin = await db.is_admin(message.from_user.id)
        if not is_admin:
            return await message.reply("<blockquote>❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ғᴏʀ ᴀᴅᴍɪɴɪꜱᴛʀᴀᴛᴏʀꜱ ᴏɴʟʏ.</blockquote>", parse_mode=ParseMode.HTML)

    if len(message.command) < 3:
        return await message.reply("<blockquote>❌ ᴘʟᴇᴀꜱᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ᴄʜᴀɴɴᴇʟ ɪᴅ ᴀɴᴅ ᴀɴɪᴍᴇ ɴᴀᴍᴇ.\nᴜꜱᴀɢᴇ: <code>/setmap -100xxxxxxxx Anime Name</code></blockquote>", parse_mode=ParseMode.HTML)

    try:
        chat_id = int(message.command[1])
    except ValueError:
        return await message.reply("<blockquote>❌ ɪɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ɪᴅ.</blockquote>", parse_mode=ParseMode.HTML)

    anime_name = " ".join(message.command[2:])
    await db.set_mapped_channel(anime_name, chat_id)

    try:
        chat = await client.get_chat(chat_id)
        chat_title = chat.title
    except Exception:
        chat_title = "Unknown Channel"

    await message.reply(f"<blockquote>✅ <b>ᴍᴀᴘᴘɪɴɢ ꜱᴇᴛ:</b>\nᴀɴɪᴍᴇ: <code>{anime_name}</code>\nᴄʜᴀɴɴᴇʟ: <code>{chat_title} ({chat_id})</code></blockquote>", parse_mode=ParseMode.HTML)

@Client.on_message(filters.private & filters.command("maplist"))
async def handle_maplist(client: Client, message):
    if message.from_user.id != OWNER_ID:
        is_admin = await db.is_admin(message.from_user.id)
        if not is_admin:
            return await message.reply("<blockquote>❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ғᴏʀ ᴀᴅᴍɪɴɪꜱᴛʀᴀᴛᴏʀꜱ ᴏɴʟʏ.</blockquote>", parse_mode=ParseMode.HTML)

    mappings = await db.get_all_mappings()
    if not mappings:
        return await message.reply("<blockquote>📋 <b>ɴᴏ ᴍᴀᴘᴘɪɴɢꜱ ғᴏᴜɴᴅ.</b></blockquote>", parse_mode=ParseMode.HTML)

    text = "<blockquote>📋 <b>ᴀɴɪᴍᴇ ᴍᴀᴘᴘɪɴɢꜱ:</b>\n\n"
    for m in mappings:
        names = ", ".join(m.get('anime_names', []))
        text += f"• <code>{m['_id']}</code>: {names}\n"
    text += "</blockquote>"

    await message.reply(text, parse_mode=ParseMode.HTML)

@Client.on_message(filters.private & filters.command("unmap"))
async def handle_unmap(client: Client, message):
    if message.from_user.id != OWNER_ID:
        is_admin = await db.is_admin(message.from_user.id)
        if not is_admin:
            return await message.reply("<blockquote>❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ғᴏʀ ᴀᴅᴍɪɴɪꜱᴛʀᴀᴛᴏʀꜱ ᴏɴʟʏ.</blockquote>", parse_mode=ParseMode.HTML)

    if len(message.command) < 2:
        return await message.reply("<blockquote>❌ ᴘʟᴇᴀꜱᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ᴄʜᴀɴɴᴇʟ ɪᴅ.\nᴜꜱᴀɢᴇ: <code>/unmap -100xxxxxxxx</code></blockquote>", parse_mode=ParseMode.HTML)

    try:
        chat_id = int(message.command[1])
    except ValueError:
        return await message.reply("<blockquote>❌ ɪɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ɪᴅ.</blockquote>", parse_mode=ParseMode.HTML)

    await db.remove_mapped_channel(chat_id)

    try:
        chat = await client.get_chat(chat_id)
        chat_title = chat.title
    except Exception:
        chat_title = "Unknown Channel"

    await message.reply(f"<blockquote>✅ <b>ᴍᴀᴘᴘɪɴɢ ʀᴇᴍᴏᴠᴇᴅ ғᴏʀ ᴄʜᴀɴɴᴇʟ:</b> <code>{chat_title} ({chat_id})</code></blockquote>", parse_mode=ParseMode.HTML)

@Client.on_message(filters.private & filters.command("add_admin"))
async def handle_add_admin(client: Client, message):
    if message.from_user.id != OWNER_ID:
        return await message.reply("<blockquote>❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ᴏɴʟʏ ғᴏʀ ᴛʜᴇ ʙᴏᴛ ᴏᴡɴᴇʀ.</blockquote>", parse_mode=ParseMode.HTML)

    user_id = None
    user_name = "Admin"

    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
        user_name = message.reply_to_message.from_user.first_name
    elif len(message.command) > 1:
        try:
            user_id = int(message.command[1])
        except ValueError:
            return await message.reply("<blockquote>❌ ɪɴᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ.</blockquote>", parse_mode=ParseMode.HTML)

    if not user_id:
        return await message.reply("<blockquote>❌ ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴜꜱᴇʀ'ꜱ ᴍᴇꜱꜱᴀɢᴇ ᴏʀ ᴘʀᴏᴠɪᴅᴇ ᴛʜᴇɪʀ ᴜꜱᴇʀ ɪᴅ.</blockquote>", parse_mode=ParseMode.HTML)

    await db.add_admin(user_id, user_name)
    await message.reply(f"<blockquote>✅ <b>ᴀᴅᴍɪɴ ᴀᴅᴅᴇᴅ:</b> {user_name} (<code>{user_id}</code>)</blockquote>", parse_mode=ParseMode.HTML)

@Client.on_message(filters.private & filters.command("rm_admin"))
async def handle_rm_admin(client: Client, message):
    if message.from_user.id != OWNER_ID:
        return await message.reply("<blockquote>❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ᴏɴʟʏ ғᴏʀ ᴛʜᴇ ʙᴏᴛ ᴏᴡɴᴇʀ.</blockquote>", parse_mode=ParseMode.HTML)

    user_id = None
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
    elif len(message.command) > 1:
        try:
            user_id = int(message.command[1])
        except ValueError:
            return await message.reply("<blockquote>❌ ɪɴᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ.</blockquote>", parse_mode=ParseMode.HTML)

    if not user_id:
        return await message.reply("<blockquote>❌ ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴜꜱᴇʀ'ꜱ ᴍᴇꜱꜱᴀɢᴇ ᴏʀ ᴘʀᴏᴠɪᴅᴇ ᴛʜᴇɪʀ ᴜꜱᴇʀ ɪᴅ.</blockquote>", parse_mode=ParseMode.HTML)

    await db.remove_admin(user_id)
    await message.reply(f"<blockquote>✅ <b>ᴀᴅᴍɪɴ ʀᴇᴍᴏᴠᴇᴅ:</b> <code>{user_id}</code></blockquote>", parse_mode=ParseMode.HTML)

@Client.on_message(filters.private & filters.command("admins"))
async def handle_admins_list(client: Client, message):
    is_admin = await db.is_admin(message.from_user.id)
    if message.from_user.id != OWNER_ID and not is_admin:
        return await message.reply("<blockquote>❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ғᴏʀ ᴀᴅᴍɪɴɪꜱᴛʀᴀᴛᴏʀꜱ ᴏɴʟʏ.</blockquote>", parse_mode=ParseMode.HTML)

    admins = await db.get_all_admins()
    if not admins:
        return await message.reply("<blockquote>📋 <b>ɴᴏ ᴀᴅᴍɪɴꜱ ᴀᴅᴅᴇᴅ ʏᴇᴛ.</b></blockquote>", parse_mode=ParseMode.HTML)

    text = "<blockquote>📋 <b>ʙᴏᴛ ᴀᴅᴍɪɴɪꜱᴛʀᴀᴛᴏʀꜱ:</b>\n\n"
    text += f"👑 <b>ᴏᴡɴᴇʀ:</b> <code>{OWNER_ID}</code>\n"
    for admin_doc in admins:
        admin_name = admin_doc.get('name', 'Admin')
        text += f"• {admin_name}: <code>{admin_doc['_id']}</code>\n"
    text += "</blockquote>"

    await message.reply(text, parse_mode=ParseMode.HTML)

@Client.on_message(filters.private & filters.command("users"))
async def handle_users_count(client: Client, message):
    is_admin = await db.is_admin(message.from_user.id)
    if message.from_user.id != OWNER_ID and not is_admin:
        return await message.reply("<blockquote>❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ғᴏʀ ᴀᴅᴍɪɴɪꜱᴛʀᴀᴛᴏʀꜱ ᴏɴʟʏ.</blockquote>", parse_mode=ParseMode.HTML)

    count = await db.get_user_count()
    await message.reply(f"<blockquote>📊 <b>ᴛᴏᴛᴀʟ ᴜꜱᴇʀꜱ:</b> <code>{count}</code></blockquote>", parse_mode=ParseMode.HTML)

@Client.on_message(filters.private & filters.command("stats"))
async def handle_stats(client: Client, message):
    is_admin = await db.is_admin(message.from_user.id)
    if message.from_user.id != OWNER_ID and not is_admin:
        return await message.reply("<blockquote>❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ғᴏʀ ᴀᴅᴍɪɴɪꜱᴛʀᴀᴛᴏʀꜱ ᴏɴʟʏ.</blockquote>", parse_mode=ParseMode.HTML)

    sts = await uikit.reply(message, uikit.note("📊 Fetching statistics…"), client=client)

    total_users = await db.get_user_count()
    total_admins = len(await db.get_all_admins()) + 1  # +1 for owner
    processed_eps = await db.get_processed_count()
    ongoing_enabled = await db.get_user_setting(0, "ongoing_enabled", False)

    def fmt(b):
        if b < 1024*1024: return f"{b/1024:.2f} KB"
        if b < 1024*1024*1024: return f"{b/(1024*1024):.2f} MB"
        return f"{b/(1024*1024*1024):.2f} GB"

    bot_pairs = [
        ("👤 Users", uikit.code(total_users)),
        ("🛡️ Admins", uikit.code(total_admins)),
        ("📼 Episodes processed", uikit.code(processed_eps)),
        ("📡 Ongoing auto-download", uikit.code("ON" if ongoing_enabled else "OFF")),
    ]

    storage_pairs = []
    db_stats = await db.get_db_stats()
    if db_stats:
        used_bytes = db_stats['storage_size']
        total_bytes = 512 * 1024 * 1024  # Atlas M0
        percent = (used_bytes / total_bytes) * 100
        storage_pairs = [
            ("🗄️ DB storage", uikit.code(f"{uikit.bar(percent, 12)} {percent:.1f}%")),
            ("💽 DB used", uikit.code(f"{fmt(used_bytes)} / 512 MB")),
        ]

    cpu_usage = psutil.cpu_percent()
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    sys_pairs = [
        ("🖥️ CPU", uikit.code(f"{uikit.bar(cpu_usage, 12)} {cpu_usage:.0f}%")),
        ("💽 RAM", uikit.code(f"{uikit.bar(ram.percent, 12)} {fmt(ram.used)} / {fmt(ram.total)}")),
        ("💾 Disk", uikit.code(f"{uikit.bar(disk.percent, 12)} {fmt(disk.used)} / {fmt(disk.total)}")),
    ]

    specs_pairs = [
        ("🖥️ OS", uikit.code(f"{platform.system()} {platform.release()}")),
        ("🧩 Arch", uikit.code(platform.machine())),
        ("🐍 Python", uikit.code(platform.python_version())),
    ]

    panel = uikit.stats_panel(bot_pairs, uikit.kv(storage_pairs) if storage_pairs else "", sys_pairs, specs_pairs)
    await uikit.edit(sts, panel, client=client)

@Client.on_message(filters.private & filters.command("ping"))
async def handle_ping(client: Client, message):
    start_t = time.time()
    msg = await message.reply("<b>ᴘᴏɴɢ...</b>", parse_mode=ParseMode.HTML)
    end_t = time.time()

    ping = (end_t - start_t) * 1000
    quality = "Excellent" if ping < 200 else ("Good" if ping < 500 else ("Average" if ping < 1000 else "Poor"))
    from cantarella.telegram.plugins.callbacks.admin import BOT_START_TIME
    uptime = time.strftime("%Hʜ %Mᴍ %Sꜱ", time.gmtime(time.time() - BOT_START_TIME))
    try:
        ram = psutil.virtual_memory()
        sys_pairs = [
            ("🖥️ CPU", uikit.code(f"{psutil.cpu_percent(interval=None):.0f}%")),
            ("💽 RAM", uikit.code(f"{ram.percent}%")),
        ]
    except Exception:
        sys_pairs = []
    panel = uikit.ping_panel(ping, uptime, quality, sys_pairs)
    await uikit.edit(msg, panel, client=client)


@Client.on_message(filters.private & filters.command("restart"))
async def handle_restart(client: Client, message):
    is_admin = await db.is_admin(message.from_user.id)
    if message.from_user.id != OWNER_ID and not is_admin:
        return await message.reply("<blockquote>❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ᴏɴʟʏ ꜰᴏʀ ᴀᴅᴍɪɴꜱ ᴏʀ ᴛʜᴇ ʙᴏᴛ ᴏᴡɴᴇʀ.</blockquote>", parse_mode=ParseMode.HTML)

    msg = await message.reply("<b>🔄 ʀᴇꜱᴛᴀʀᴛɪɴɢ ʙᴏᴛ...</b>", parse_mode=ParseMode.HTML)

    # Save the restart message info to DB so it can be updated after restart
    await db.set_user_setting(OWNER_ID, "restart_msg_id", msg.id)
    await db.set_user_setting(OWNER_ID, "restart_chat_id", msg.chat.id)

    # Restart the current process
    os.execl(sys.executable, sys.executable, "-m", "cantarella")

@Client.on_message(filters.private & filters.command("broadcast") & admin & filters.reply)
async def handle_broadcast(client: Client, message):
    broadcast_msg = message.reply_to_message
    sts = await message.reply("<blockquote>🚀 <b>ꜱᴛᴀʀᴛɪɴɢ ʙʀᴏᴀᴅᴄᴀꜱᴛ...</b></blockquote>", parse_mode=ParseMode.HTML)

    users = await db.get_all_users()
    count = 0
    success = 0
    failed = 0

    async for user in users:
        user_id = user["_id"]
        try:
            await broadcast_msg.copy(user_id)
            success += 1
        except Exception:
            failed += 1

        count += 1
        if count % 20 == 0:
            try:
                await sts.edit_text(f"<blockquote>🚀 <b>ʙʀᴏᴀᴅᴄᴀꜱᴛɪɴɢ...</b>\n\n✅ ꜱᴜᴄᴄᴇꜱꜱ: {success}\n❌ ғᴀɪʟᴇᴅ: {failed}</blockquote>", parse_mode=ParseMode.HTML)
            except:
                pass

        await asyncio.sleep(0.5) # Avoid flood limits

    await sts.edit_text(f"<blockquote>✅ <b>ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄᴏᴍᴘʟᴇᴛᴇᴅ!</b>\n\n👥 ᴛᴏᴛᴀʟ ᴜꜱᴇʀꜱ: {success + failed}\n✨ ꜱᴜᴄᴄᴇꜱꜱ: {success}\n💀 ғᴀɪʟᴇᴅ: {failed}</blockquote>", parse_mode=ParseMode.HTML)

@Client.on_message(filters.private & filters.command("broadcast") & admin & ~filters.reply)
async def handle_broadcast_no_reply(client: Client, message):
    await message.reply("<blockquote>❌ ᴘʟᴇᴀꜱᴇ ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴍᴇꜱꜱᴀɢᴇ ᴛᴏ ʙʀᴏᴀᴅᴄᴀꜱᴛ ɪᴛ.</blockquote>", parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════
#  BAN / UNBAN / BANLIST  — /ban <id|reply> [reason] · /unban · /banlist
# ═══════════════════════════════════════════════════════════

def _target_id(message):
    """user id from the command args or from a replied-to message."""
    parts = list(message.command)
    if len(parts) >= 2:
        try:
            return int(parts[1]), " ".join(parts[2:])
        except ValueError:
            return None, ""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id, ""
    return None, ""


@Client.on_message(filters.private & filters.command("ban") & admin)
async def handle_ban(client: Client, message):
    uid, reason = _target_id(message)
    if uid is None:
        return await message.reply(
            "<blockquote>❌ ᴜꜱᴀɢᴇ: <code>/ban 123456789 ꜱᴘᴀᴍᴍɪɴɢ</code> (ᴏʀ ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴜꜱᴇʀ)</blockquote>",
            parse_mode=ParseMode.HTML)
    if uid == OWNER_ID:
        return await message.reply("<blockquote>❌ ᴄᴀɴ'ᴛ ʙᴀɴ ᴛʜᴇ ᴏᴡɴᴇʀ.</blockquote>", parse_mode=ParseMode.HTML)
    ok = await db.ban_user(uid, reason)
    if ok:
        return await message.reply(
            f"<blockquote>🔨 <b>ʙᴀɴɴᴇᴅ</b> <code>{uid}</code>"
            + (f"\nʀᴇᴀꜱᴏɴ: <i>{reason[:100]}</i>" if reason else "")
            + "</blockquote>", parse_mode=ParseMode.HTML)
    await message.reply("<blockquote>❌ ᴅᴀᴛᴀʙᴀꜱᴇ ᴇʀʀᴏʀ — ʙᴀɴ ɴᴏᴛ ꜱᴀᴠᴇᴅ.</blockquote>", parse_mode=ParseMode.HTML)


@Client.on_message(filters.private & filters.command("unban") & admin)
async def handle_unban(client: Client, message):
    uid, _ = _target_id(message)
    if uid is None:
        return await message.reply(
            "<blockquote>❌ ᴜꜱᴀɢᴇ: <code>/unban 123456789</code> (ᴏʀ ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴜꜱᴇʀ)</blockquote>",
            parse_mode=ParseMode.HTML)
    ok = await db.unban_user(uid)
    if ok:
        return await message.reply(
            f"<blockquote>🕊 <b>ᴜɴʙᴀɴɴᴇᴅ</b> <code>{uid}</code></blockquote>",
            parse_mode=ParseMode.HTML)
    await message.reply("<blockquote>❌ ᴅᴀᴛᴀʙᴀꜱᴇ ᴇʀʀᴏʀ — ᴜɴʙᴀɴ ɴᴏᴛ ꜱᴀᴠᴇᴅ.</blockquote>", parse_mode=ParseMode.HTML)


@Client.on_message(filters.private & filters.command("banlist") & admin)
async def handle_banlist(client: Client, message):
    banned = await db.banned_users()
    if not banned:
        return await message.reply("<blockquote>📋 ɴᴏ ʙᴀɴɴᴇᴅ ᴜꜱᴇʀꜱ.</blockquote>", parse_mode=ParseMode.HTML)
    lines = [f"• <code>{u['_id']}</code>" + (f" — <i>{(u.get('ban_status') or {}).get('ban_reason', '')[:60]}</i>"
                                              if (u.get('ban_status') or {}).get('ban_reason') else "")
             for u in banned[:25]]
    await message.reply(
        f"<blockquote>🔨 <b>ʙᴀɴɴᴇᴅ ᴜꜱᴇʀꜱ ({len(banned)}):</b>\n" + "\n".join(lines) + "</blockquote>",
        parse_mode=ParseMode.HTML)
