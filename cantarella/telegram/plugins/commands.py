from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, Message
from cantarella.button import Button as InlineKeyboardButton
import asyncio
import logging
from datetime import datetime

from cantarella.core.database import db
from cantarella.core.state import user_watch_next
from cantarella.core.images import get_random_image
from cantarella.core.utils import decode_data, encode_data
from config import OWNER_ID, START_PIC
import uikit
import config
from Script import Dead
from cantarella.telegram.decorators import check_ban, check_fsub

logger = logging.getLogger(__name__)


from anime_sources import SOURCE_CYCLE, SOURCE_NAMES
import os as _os


def _source_cycle() -> list:
    """Sources available in the /manage cycle; remote ones appear when configured."""
    cycle = list(SOURCE_CYCLE)
    if _os.getenv("ANIMEDL_CONSUMET_URL"):
        cycle.append("consumet")
    if _os.getenv("ANIMEDL_ANIWATCH_URL"):
        cycle.append("aniwatchapi")
    return cycle


def _next_source(current: str) -> str:
    cycle = _source_cycle()
    if current not in cycle:
        return cycle[0]
    return cycle[(cycle.index(current) + 1) % len(cycle)]


def _source_name(source_id: str) -> str:
    return SOURCE_NAMES.get(source_id, source_id.upper())


async def check_admin(filter, client, message):
    try:
        user_id = message.from_user.id
        if user_id == OWNER_ID:
            return True
        return await db.is_admin(user_id)
    except Exception as e:
        logger.error(f"Exception in check_admin: {e}")
        return False

admin = filters.create(check_admin)

@Client.on_message(filters.private & filters.command("manage") & admin)
@check_ban
@check_fsub
async def handle_settings(client: Client, message):
    # Unified settings (merged repo): same menu as /settings
    from leechbot.utility.helper import send_settings
    await send_settings(client, message, message.id, True)

@Client.on_message(filters.private & filters.command("autodel") & admin)
@check_ban
@check_fsub
async def handle_autodel(client: Client, message):
    args = message.command
    if len(args) < 2:
        current_val = await db.get_user_setting(0, "autodel_time", 0)
        status = f"{current_val} ꜱᴇᴄᴏɴᴅꜱ" if current_val > 0 else "ᴅɪꜱᴀʙʟᴇᴅ"
        return await message.reply(
            f"<blockquote>🕒 <b>ᴄᴜʀʀᴇɴᴛ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ (ɢʟᴏʙᴀʟ):</b> {status}\n\n"
            "ᴜꜱᴀɢᴇ: <code>/autodel 600</code> (ꜱᴇᴛꜱ ɪᴛ ᴛᴏ 10 ᴍɪɴᴜᴛᴇꜱ)\n"
            "ᴜꜱᴇ <code>/autodel 0</code> ᴛᴏ ᴅɪꜱᴀʙʟᴇ.</blockquote>",
            parse_mode=ParseMode.HTML
        )

    try:
        seconds = int(args[1])
        if seconds < 0:
            return await message.reply("<blockquote>❌ ᴘʟᴇᴀꜱᴇ ᴇɴᴛᴇʀ ᴀ ᴘᴏꜱɪᴛɪᴠᴇ ɴᴜᴍʙᴇʀ.</blockquote>", parse_mode=ParseMode.HTML)

        await db.set_user_setting(0, "autodel_time", seconds)

        if seconds > 0:
            mins = seconds // 60
            await message.reply(f"<blockquote>✅ <b>ɢʟᴏʙᴀʟ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ꜱᴇᴛ:</b> {seconds} ꜱᴇᴄᴏɴᴅꜱ (~{mins} ᴍɪɴꜱ).\nғɪʟᴇꜱ ꜱᴇɴᴛ ᴛᴏ ᴀʟʟ ᴜꜱᴇʀꜱ ᴡɪʟʟ ʙᴇ ᴅᴇʟᴇᴛᴇᴅ ᴀғᴛᴇʀ ᴛʜɪꜱ ᴛɪᴍᴇ.</blockquote>", parse_mode=ParseMode.HTML)
        else:
            await message.reply("<blockquote>✅ <b>ɢʟᴏʙᴀʟ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ᴅɪꜱᴀʙʟᴇᴅ.</b></blockquote>", parse_mode=ParseMode.HTML)
    except ValueError:
        await message.reply("<blockquote>❌ ɪɴᴠᴀʟɪᴅ ғᴏʀᴍᴀᴛ. ᴜꜱᴇ: <code>/autodel 600</code></blockquote>", parse_mode=ParseMode.HTML)

@Client.on_message(filters.command(["ongoing", "schedule"]))
@check_ban
@check_fsub
async def handle_ongoing_schedule(client: Client, message):
    from cantarella.telegram.ongoing import fetch_schedule_list

    status_msg = await client.send_photo(
        message.chat.id,
        photo=get_random_image(),
        caption="<blockquote>📆 <b>ғᴇᴛᴄʜɪɴɢ ᴛᴏᴅᴀʏ'ꜱ ᴀɴɪᴍᴇ ʀᴇʟᴇᴀꜱᴇ ꜱᴄʜᴇᴅᴜʟᴇ...</b></blockquote>",
        parse_mode=ParseMode.HTML
    )
    active_source = await db.get_user_setting(0, "active_source", "hianime")
    schedule = await asyncio.to_thread(fetch_schedule_list, source=active_source)

    if not schedule:
        await status_msg.edit_caption("<blockquote>❌ <b>ɴᴏ ᴀɴɪᴍᴇ ꜱᴄʜᴇᴅᴜʟᴇᴅ ғᴏʀ ᴛᴏᴅᴀʏ ᴏʀ ғᴀɪʟᴇᴅ ᴛᴏ ғᴇᴛᴄʜ.</b></blockquote>", parse_mode=ParseMode.HTML)
        return

    date_str = datetime.now().strftime("%d %b %Y")
    text = f"<blockquote>📆 <b>ᴛᴏᴅᴀʏ'ꜱ ᴀɴɪᴍᴇ ʀᴇʟᴇᴀꜱᴇꜱ ꜱᴄʜᴇᴅᴜʟᴇ [{date_str}] [ɪꜱᴛ]</b>\n\n"

    for item in schedule:
        item_title = item['title']
        entry = f"• <b>{item_title}</b>\n  🕒 ᴛɪᴍᴇ: {item['time']} ʜʀꜱ\n\n"
        if len(text + entry + "</blockquote>") > 1024:
            break
        text += entry
    text += "</blockquote>"

    await status_msg.edit_caption(text, parse_mode=ParseMode.HTML)

@Client.on_message(filters.private & filters.command("start"))
@check_ban
@check_fsub
async def handle_start(client: Client, message):
    # Handle deep-link file retrieval (no fsub needed for file links from channel)
    if len(message.command) > 1:
        data = message.command[1]
        try:
            decoded = decode_data(data)
            # Format: msgid_chatid OR startId-endId_chatid
            if "_" in decoded:
                msg_id_part, chat_id = decoded.split("_")
                status_msg = await client.send_message(message.chat.id, "<blockquote>🔄 <b>ғᴇᴛᴄʜɪɴɢ ғɪʟᴇꜱ...</b></blockquote>", parse_mode=ParseMode.HTML)

                try:
                    # Handle Auto-Delete if enabled (Global Setting)
                    autodel_time = await db.get_user_setting(0, "autodel_time", 0)
                    notify_msg = None

                    if "-" in msg_id_part:
                        start_id, end_id = map(int, msg_id_part.split("-"))
                        for m_id in range(start_id, end_id + 1):
                            try:
                                copy_msg = await client.copy_message(
                                    chat_id=message.chat.id,
                                    from_chat_id=int(chat_id),
                                    message_id=m_id
                                )
                                if autodel_time > 0:
                                    from cantarella.telegram.download import schedule_deletion
                                    asyncio.create_task(schedule_deletion(client, message.chat.id, copy_msg.id, autodel_time))
                                await asyncio.sleep(0.3)
                            except Exception:
                                pass # skip if message deleted or not found
                    else:
                        copy_msg = await client.copy_message(
                            chat_id=message.chat.id,
                            from_chat_id=int(chat_id),
                            message_id=int(msg_id_part)
                        )
                        if autodel_time > 0:
                            from cantarella.telegram.download import schedule_deletion
                            asyncio.create_task(schedule_deletion(client, message.chat.id, copy_msg.id, autodel_time))

                    if autodel_time > 0:
                        mins = autodel_time // 60
                        notify_msg = await client.send_message(
                            message.chat.id,
                            f"<blockquote>🗑️ <b>ғɪʟᴇꜱ ᴡɪʟʟ ʙᴇ ᴅᴇʟᴇᴛᴇᴅ ᴀғᴛᴇʀ {mins} ᴍɪɴ ({autodel_time}ꜱ).</b>\n"
                            "ᴍᴀᴋᴇ ꜱᴜʀᴇ ᴛᴏ ꜱᴀᴠᴇ ᴛʜᴇᴍ ɪɴ ʏᴏᴜʀ 'ꜱᴀᴠᴇᴅ ᴍᴇꜱꜱᴀɢᴇꜱ' ɪғ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴋᴇᴇᴘ ᴛʜᴇᴍ!</blockquote>",
                            parse_mode=ParseMode.HTML
                        )
                        from cantarella.telegram.download import schedule_deletion
                        asyncio.create_task(schedule_deletion(client, message.chat.id, notify_msg.id, autodel_time))

                    await status_msg.delete()
                    return
                except Exception as e:
                    await status_msg.edit_text(f"<blockquote>❌ <b>ᴇʀʀᴏʀ ғᴇᴛᴄʜɪɴɢ ғɪʟᴇ:</b> {e}</blockquote>", parse_mode=ParseMode.HTML)
                    return
        except Exception:
            pass

    # Record user
    await db.add_user(message.from_user.id)

    buttons = []
    is_admin = await db.is_admin(message.from_user.id)
    if is_admin or message.from_user.id == OWNER_ID:
        buttons.append([
            InlineKeyboardButton("ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ", callback_data="admin_panel"),
            InlineKeyboardButton("ᴛᴏɢɢʟᴇ ᴏɴɢᴏɪɴɢ", callback_data="toggle_ongoing")
        ])
        buttons.append([
            InlineKeyboardButton("❤ ғᴀᴠᴏʀɪᴛᴇꜱ", callback_data="favorites")
        ])

    buttons.append([
        InlineKeyboardButton("• ᴀʙᴏᴜᴛ", callback_data="adl_about"),
        InlineKeyboardButton("Hᴇʟᴘ •", callback_data="help")
    ])

    inline_buttons = InlineKeyboardMarkup(buttons)

    try:
        await message.reply_photo(
            photo=START_PIC,
            caption=Dead.START_MSG.format(
                first=message.from_user.first_name,
                last=message.from_user.last_name or "",
                username="@" + message.from_user.username if message.from_user.username else None,
                mention=message.from_user.mention,
                id=message.from_user.id
            ),
            reply_markup=inline_buttons
        )
    except Exception as e:
        logger.error(f"Error in start_command: {e}")
        await message.reply_text("An error occurred while processing your request.")

@Client.on_message(filters.private & filters.command("favorites") & admin)
@check_ban
@check_fsub
async def handle_favorites(client: Client, message):
    user_id = message.from_user.id
    favorites = await db.get_favorites(user_id)

    if not favorites:
        return await message.reply("<blockquote>❤ <b>ʏᴏᴜʀ ғᴀᴠᴏʀɪᴛᴇꜱ ʟɪꜱᴛ ɪꜱ ᴇᴍᴘᴛʏ.</b>\nꜱᴇᴀʀᴄʜ ғᴏʀ ᴀɴ ᴀɴɪᴍᴇ ᴛᴏ ᴀᴅᴅ ɪᴛ ᴛᴏ ʏᴏᴜʀ ғᴀᴠᴏʀɪᴛᴇꜱ!</blockquote>", parse_mode=ParseMode.HTML)

    buttons = []
    for fav in favorites:
        buttons.append([InlineKeyboardButton(fav['title'], callback_data=f"anime_{fav['id']}")])

    buttons.append([InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ", callback_data="adl_close")])

    await message.reply_photo(
        photo=get_random_image(),
        caption="<blockquote>❤ <b>ʏᴏᴜʀ ғᴀᴠᴏʀɪᴛᴇ ᴀɴɪᴍᴇꜱ:</b></blockquote>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML
    )

@Client.on_message(filters.private & filters.command("help"))
@check_ban
@check_fsub
async def handle_help(client: Client, message):
    await db.add_user(message.from_user.id)
    inline_buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("• ʙᴀᴄᴋ", callback_data="start"),
                InlineKeyboardButton("ᴄʟᴏꜱᴇ •", callback_data="adl_close")
            ]
        ]
    )
    try:
        await message.reply_photo(
            photo=START_PIC,
            caption=Dead.HELP_TXT.format(
                first=message.from_user.first_name,
                last=message.from_user.last_name or "",
                username="@" + message.from_user.username if message.from_user.username else "ɴᴏɴᴇ",
                mention=message.from_user.mention,
                id=message.from_user.id
            ),
            reply_markup=inline_buttons
        )
    except Exception as e:
        logger.error(f"Error in help command: {e}")
        await message.reply_text("An error occurred while processing your request.")

# ─────────────────────────────────────────────
#  /health — full reliability dashboard
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("health") & admin)
async def handle_health_cmd(client: Client, message):
    import reliability

    kd = reliability.watchdog.stats()
    ka = reliability.keepalive.stats()
    from leechbot.utility.helper import getTime
    from leechbot.utility.variables import BOT, Queue, BotStats
    from datetime import datetime as _dt

    uptime = getTime(int((_dt.now() - BotStats.start_time).total_seconds()))
    mem_pct = min(100, int(kd["mem_rss_mb"] / max(1, config.WATCHDOG_MEM_HARD_MB) * 100))
    disk_pct = 100
    try:
        import shutil as _sh
        du = _sh.disk_usage(str(config.WORK_PATH))
        disk_pct = int(du.used / du.total * 100)
    except Exception:
        pass

    body = (
        uikit.heading("❇️ Health", level=3)
        + uikit.kv([
            ("🟢 Status", uikit.code("healthy" if not kd["disk_pressure"] and kd["mem_action"] != "hard" else "degraded")),
            ("⏱️ Uptime", uikit.code(uptime)),
            ("🧠 Memory", uikit.code(f"{uikit.bar(mem_pct, 12)} {kd['mem_rss_mb']} MB")),
            ("💽 Disk free", uikit.code(f"{kd['disk_free_mb']} MB" if kd["disk_free_mb"] else "?")),
            ("💓 Heartbeat", uikit.code(f"{kd['heartbeat_age_s']}s ago" if kd["heartbeat_age_s"] is not None else "n/a")),
        ])
        + uikit.details("🐕 Watchdog", uikit.kv([
            ("Checks", uikit.code(kd["checks"])),
            ("Task idle", uikit.code(f"{kd['task_idle_s']}s")),
            ("Stall cancels", uikit.code(kd["stall_actions"])),
            ("Restarts", uikit.code(kd["restarts"])),
            ("Auto-restart", uikit.code("on" if config.WATCHDOG_AUTO_RESTART else "off")),
        ]))
        + uikit.details("💓 Keep-alive", uikit.kv([
            ("Pings", uikit.code(f"{ka['total_pings']} ({ka['failed_pings']} failed)")),
            ("Interval", uikit.code(f"{ka['interval']}s")),
            ("Last OK", uikit.code(f"{ka['last_ok_ago_s']}s ago" if ka["last_ok_ago_s"] is not None else "pending")),
            ("Last error", uikit.code(str(ka.get("last_error") or "none")[:80])),
        ]))
        + uikit.details("📥 Leech", uikit.kv([
            ("Task active", uikit.code("yes" if getattr(BOT.State, "task_going", False) else "no")),
            ("Queue", uikit.code(Queue.size() if hasattr(Queue, "size") else 0)),
        ]))
        + uikit.footer("reliability")
    )
    panel = uikit.panel("Health", body, level=3, with_footer=False)
    await uikit.reply(message, panel, client=client)


# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
#  /diag — full download-pipeline self-test, live on this server
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("diag") & admin)
async def handle_diag(client: Client, message):
    """Runs a REAL mini pipeline: search 'dr stone' on hianime → episode 1 →
    resolve → check an m3u8 comes back. Reports the EXACT stage that fails
    on THIS server (search / episode list / resolve / stream host)."""
    import traceback
    from anime_sources import search_provider
    from anime_sources.base import cached_streams
    steps = []
    def mark(ok, name, detail=""):
        steps.append(("✅" if ok else "❌", name, detail))

    status = await message.reply(
        "<blockquote>🔬 ʀᴜɴɴɪɴɢ ғᴜʟʟ ᴅᴏᴡɴʟᴏᴀᴅ-ᴘɪᴘᴇʟɪɴᴇ ᴅɪᴀɢ… (~30ꜱ)</blockquote>",
        parse_mode=ParseMode.HTML,
    )

    # stage 1: search
    results = []
    try:
        results = search_provider("hianime", "dr stone") or []
        mark(bool(results), "Search (hianime 'dr stone')", f"{len(results)} results")
    except Exception as e:
        mark(False, "Search (hianime 'dr stone')", f"{type(e).__name__}: {str(e)[:60]}")

    anime_id, ep_url = None, None
    if results:
        # stage 2: episode list
        try:
            anime_id = results[0]["id"].split(":", 1)[-1]
            from anime_sources import list_provider_episodes
            eps = list_provider_episodes("hianime", anime_id) or []
            mark(bool(eps), "Episode list", f"{len(eps)} episodes for {anime_id}")
            if eps:
                ep_url = eps[0]["url"]
        except Exception as e:
            mark(False, "Episode list", f"{type(e).__name__}: {str(e)[:60]}")

    # stage 3: resolve (servers page → embed → stream host)
    resolved = None
    if ep_url:
        try:
            from anime_sources import get_provider, provider_id_for_url
            prov = get_provider(provider_id_for_url(ep_url))
            resolved = cached_streams(f"res:diag:{ep_url}", prov.resolve, ep_url)
            ok = bool(getattr(resolved, "streams", []))
            mark(ok, "Resolve (embed → stream URLs)",
                 f"{len(resolved.streams)} streams" if ok else "no streams")
        except Exception as e:
            mark(False, "Resolve (embed → stream URLs)", f"{type(e).__name__}: {str(e)[:60]}")

    # stage 4: downloader binary
    try:
        from anime_sources.streamdl import _find_binary
        b = _find_binary()
        import os as _os
        mark(True, "Downloader binary", f"{_os.path.basename(b)} (exec ✓)")
    except Exception as e:
        mark(False, "Downloader binary", str(e)[:60])

    # stage 5: key service (megacloud)
    try:
        from anime_sources.megacloud import _decryption_key
        k = _decryption_key()
        mark(bool(k), "MegaCloud key service", f"key {k[:6]}…" if k else "ALL key repos unreachable")
    except Exception as e:
        mark(False, "MegaCloud key service", str(e)[:60])

    body = "\n".join(f"{s} <b>{n}</b> — <i>{d}</i>" if d else f"{s} <b>{n}</b>" for s, n, d in steps)
    all_ok = all(s == "✅" for s, _, _ in steps)
    verdict = "🟢 ᴇᴠᴇʀʏᴛʜɪɴɢ ᴡᴏʀᴋꜱ — ᴅᴏᴡɴʟᴏᴀᴅꜱ ꜱʜᴏᴜʟᴅ ꜱᴜᴄᴄᴇᴇᴅ" if all_ok else              "🔴 ꜰɪx ᴛʜᴇ ʀᴇᴅ ʟɪɴᴇ(ꜱ) ᴀʙᴏᴠᴇ — ꜱᴇɴᴅ ᴛʜɪꜱ ᴡʜᴏʟᴇ ᴍᴇꜱꜱᴀɢᴇ ᴛᴏ ꜱᴜᴘᴘᴏʀᴛ"
    panel = (
        f"<blockquote>🔬 <b>ᴅᴏᴡɴʟᴏᴀᴅ-ᴘɪᴘᴇʟɪɴᴇ ᴅɪᴀɢ</b> · ᴠ{config.VERSION}</blockquote>\n"
        f"<blockquote>{body}</blockquote>\n"
        f"<blockquote>{verdict}</blockquote>"
    )
    try:
        await status.edit_text(panel, parse_mode=ParseMode.HTML)
    except Exception:
        await message.reply(panel, parse_mode=ParseMode.HTML)


#  /sources — live probe of every anime source
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("sources") & admin)
async def handle_sources(client: Client, message):
    """Search-probe every provider IN PARALLEL from THIS server and show
    which sources are actually alive right now — the only ground truth
    that matters, since blocks are per-IP/per-region."""
    import concurrent.futures as _cf
    from anime_sources import search_provider
    from anime_sources.base import SOURCE_CYCLE, SOURCE_NAMES
    from anime_sources.hianime import BASES as HIANIME_BASES

    order = [s for s in SOURCE_CYCLE if s not in ("animetsu", "aniwatch")]

    def _probe(src):
        # Bypass search_provider()'s swallow-all wrapper: a Cloudflare 403
        # and a genuine empty result must NOT look the same — report the
        # concrete block reason so a dead source can actually be fixed.
        from anime_sources.base import get_provider, describe_source_error
        try:
            res = get_provider(src).search("dr stone")
            return src, (f"✅ {len(res)} results" if res else "⚠️ 0 results")
        except Exception as e:
            return src, f"❌ {describe_source_error(e)}"

    status = await message.reply(
        "<blockquote>🩺 ᴘʀᴏʙɪɴɢ ᴀʟʟ ꜱᴏᴜʀᴄᴇꜱ... (ᴍᴀx ~15ꜱ)</blockquote>",
        parse_mode=ParseMode.HTML,
    )
    with _cf.ThreadPoolExecutor(max_workers=len(order)) as pool:
        futs = {pool.submit(_probe, s): s for s in order}
        verdicts = {}
        for f in _cf.as_completed(futs):
            try:
                src, verdict = f.result()
                verdicts[src] = verdict
            except Exception as e:
                verdicts[futs[f]] = f"❌ probe crash: {type(e).__name__}"

    # canonical cycle order — plain rebuild, no sorting tricks
    rows = [(SOURCE_NAMES.get(s, s), verdicts[s]) for s in order if s in verdicts]
    body = "\n".join(f"• {n} — {v}" for n, v in rows)
    overrides = (
        f"🛠 ғɪx ᴀ ᴅᴇᴀᴅ ꜱᴏᴜʀᴄᴇ: ꜱᴇᴛ ᴇɴᴠ ᴏɴ ʀᴇɴᴅᴇʀ\n"
        f"<code>ANIMEDL_HIANIME_BASE=https://hianime.bz</code>\n"
        f"<code>GOGO_BASE=…</code> · <code>ANIMEDL_ANIWAVE_BASE=…</code>\n"
        f"<code>ANIMEDL_ANIMEGG_BASE=…</code> · <code>ANIMEDL_AWI_BASE=…</code>\n"
        f"ᴍɪʀʀᴏʀꜱ ᴛʀɪᴇᴅ ғᴏʀ ʜɪᴀɴɪᴍᴇ: {len(HIANIME_BASES)}"
    )
    panel = (
        "<blockquote>🩺 <b>ꜱᴏᴜʀᴄᴇ ʜᴇᴀʟᴛʜ</b> (ʟɪᴠᴇ ғʀᴏᴍ ᴛʜɪꜱ ꜱᴇʀᴠᴇʀ)</blockquote>\n"
        f"<blockquote>{body}</blockquote>\n"
        f"<blockquote>{overrides}</blockquote>"
    )
    try:
        await status.edit_text(panel, parse_mode=ParseMode.HTML)
    except Exception:
        await message.reply(panel, parse_mode=ParseMode.HTML)


#  /setrestart — schedule the daily hygiene restart
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("setrestart") & admin)
async def handle_setrestart(client: Client, message):
    if message.from_user.id != OWNER_ID:
        return await message.reply(
            "<blockquote>❌ ᴏᴡɴᴇʀ ᴏɴʟʏ ᴄᴏᴍᴍᴀɴᴅ.</blockquote>", parse_mode=ParseMode.HTML
        )

    import reliability as _rel
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        current = await _rel._get_scheduled_restart()
        current_str = f"{current[0]:02d}:{current[1]:02d}" if current else "off"
        return await message.reply(
            "<blockquote>⏰ <b>Usage:</b> <code>/setrestart HH:MM</code> (24h) or <code>/setrestart off</code>\n"
            f"📅 <b>Current:</b> <code>{current_str}</code>\n\n"
            "Bot restarts daily at that time to keep memory clean.</blockquote>",
            parse_mode=ParseMode.HTML,
        )

    raw = args[1].strip()
    try:
        parsed = _rel.parse_restart_time(raw)
    except ValueError as e:
        return await message.reply(f"<blockquote>❌ {e}</blockquote>", parse_mode=ParseMode.HTML)

    await _rel.set_scheduled_restart(raw if parsed else None)
    if parsed:
        await message.reply(
            f"<blockquote>✅ <b>Daily auto-restart scheduled at</b> <code>{parsed[0]:02d}:{parsed[1]:02d}</code>. "
            "The watchdog will handle it.</blockquote>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.reply(
            "<blockquote>✅ <b>Daily auto-restart disabled.</b></blockquote>",
            parse_mode=ParseMode.HTML,
        )


# ─────────────────────────────────────────────
#  /anime — AniList info card (poster, score, genres)
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("anime"))
async def handle_anime_info(client: Client, message):
    from cantarella.core.state import user_ani_search
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply(
            "<blockquote>📺 <b>Usage:</b> <code>/anime solo leveling</code>\n"
            "Get info about any anime, then tap to download.</blockquote>",
            parse_mode=ParseMode.HTML,
        )
    name = parts[1].strip()

    sts = await message.reply(
        "<blockquote>🔍 ꜰᴇᴛᴄʜɪɴɢ ᴀɴɪʟɪsᴛ ɪɴғᴏ...</blockquote>", parse_mode=ParseMode.HTML
    )
    try:
        from cantarella.core.anilist import TextEditor
        import asyncio as _asyncio
        ani = TextEditor(name)
        await ani.load_anilist()
        adata = ani.adata or {}
    except Exception as e:
        logger.error(f"anime info error: {e}")
        adata = {}

    if not adata:
        return await sts.edit_text(
            "<blockquote>❌ ɴᴏ ᴀɴɪᴍᴇ ғᴏᴜɴᴅ ꜰᴏʀ ᴛʜᴀᴛ ɴᴀᴍᴇ.</blockquote>",
            parse_mode=ParseMode.HTML,
        )

    title = (adata.get("title") or {}).get("romaji") or (adata.get("title") or {}).get("english") or name
    score = adata.get("averageScore")
    episodes = adata.get("episodes") or "?"
    status = str(adata.get("status") or "").replace("_", " ").title()
    import re as _re
    description = _re.sub(r"<[^>]+>", "", adata.get("description") or "").strip()
    if len(description) > 400:
        description = description[:400] + "…"
    genres = ", ".join((adata.get("genres") or [])[:5]) or "N/A"
    season = adata.get("season")
    season_year = adata.get("seasonYear")
    season_str = f"{str(season).title()} {season_year}" if season or season_year else "N/A"

    caption = (
        f"<blockquote><b>◆ {title} ◆</b></blockquote>\n"
        f"<blockquote><b>⭐ ꜱᴄᴏʀᴇ:</b> <code>{score}/100</code>\n"
        f"📼 <b>ᴇᴘɪꜱᴏᴅᴇꜱ:</b> <code>{episodes}</code>\n"
        f"📡 <b>ꜱᴛᴀᴛᴜꜱ:</b> <code>{status}</code>\n"
        f"🗓 <b>ꜱᴇᴀꜱᴏɴ:</b> <code>{season_str}</code>\n"
        f"🎭 <b>ɢᴇɴʀᴇꜱ:</b> <code>{genres}</code></blockquote>\n"
    )
    if description:
        caption += f"<blockquote><i>{description}</i></blockquote>\n"
    caption += "<blockquote><i>ᴛᴀᴘ ʙᴇʟᴏᴡ ᴛᴏ ꜱᴇᴀʀᴄʜ ᴅᴏᴡɴʟᴏᴀᴅ ʟɪɴᴋꜱ</i></blockquote>"

    user_ani_search[message.from_user.id] = name
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 ꜱᴇᴀʀᴄʜ & ᴅᴏᴡɴʟᴏᴀᴅ", callback_data="aisearch")],
        [InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ", callback_data="adl_close")],
    ])
    poster = None
    try:
        poster = await ani.get_poster()
    except Exception:
        pass
    try:
        await sts.delete()
        if poster:
            await message.reply_photo(poster, caption=caption, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        else:
            await message.reply_text(caption, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception:
        await message.reply_text(caption, reply_markup=keyboard, parse_mode=ParseMode.HTML)


# ─────────────────────────────────────────────
#  /nextep — next-episode countdown (ani-cli port)
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("nextep"))
async def handle_nextep(client: Client, message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply(
            "<blockquote>⏰ <b>Usage:</b> <code>/nextep one piece</code>\n"
            "Shows when the next episode airs.</blockquote>",
            parse_mode=ParseMode.HTML,
        )
    query = parts[1].strip()

    sts = await uikit.reply(message, uikit.note("⏰ Checking the airing schedule…"), client=client)
    import asyncio as _asyncio
    from cantarella.core import airschedule
    try:
        entries = await _asyncio.to_thread(airschedule.lookup, query)
    except Exception as e:
        return await uikit.edit(sts, uikit.error_panel(
            "Schedule lookup failed", e,
            hint="Try the romaji title (e.g. <code>/nextep Sousou no Frieren</code>) "
                 "or retry in a minute — the schedule service may be busy."),
            client=client)

    if not entries:
        return await uikit.edit(sts, uikit.panel(
            "⏰ Airing Schedule", uikit.note("No matches found for that title."), level=3))

    body = ""
    for it in entries:
        rows = [
            ("🇯🇵 Title", uikit.code(it["jpn"])),
            ("📡 Status", uikit.code(it["status"])),
        ]
        if it.get("next_sub_ep"):
            rows.append(("🎧 Next Sub", uikit.code(f"EP {it['next_sub_ep']} in {it.get('sub_countdown') or '?'}")))
        if it.get("next_dub_ep"):
            rows.append(("🔊 Next Dub", uikit.code(f"EP {it['next_dub_ep']} in {it.get('dub_countdown') or '?'}")))
        if not it.get("next_sub_ep") and not it.get("next_dub_ep"):
            rows.append(("ℹ️", uikit.code("no scheduled episodes")))
        body += uikit.heading(f"📺 {it['title']}", level=4) + uikit.kv(rows)
    panel = uikit.panel("⏰ Next Episode", body, level=3)
    await uikit.edit(sts, panel, client=client)


# ─────────────────────────────────────────────
#  /history — continue watching
# ─────────────────────────────────────────────
@Client.on_message(filters.private & filters.command("history"))
async def handle_history(client: Client, message):
    user_id = message.from_user.id
    items = await db.get_history(user_id)
    if not items:
        return await message.reply(
            "<blockquote>📭 <b>No watch history yet.</b>\n"
            "Download an episode and it will show up here with a one-tap \"next episode\" button.</blockquote>",
            parse_mode=ParseMode.HTML,
        )

    user_watch_next[user_id] = [it.get("next") or "" for it in items]
    rows = []
    for i, it in enumerate(items):
        label = it.get("title") or "Anime"
        ep = it.get("ep") or "?"
        rows.append([InlineKeyboardButton(
            f"⏭ {label[:28]} — EP {ep} ➜ {int(ep) + 1 if ep.isdigit() else 'next'}",
            callback_data=f"wnext_{i}",
        )])
    rows.append([InlineKeyboardButton("🗑 ᴄʟᴇᴀʀ ʜɪꜱᴛᴏʀʏ", callback_data="wclear")])

    await message.reply(
        "<blockquote>🕘 <b>Continue watching</b>\nᴛᴀᴘ ᴀɴ ᴇɴᴛʀʏ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ ᴛʜᴇ ɴᴇxᴛ ᴇᴘɪꜱᴏᴅᴇ:</blockquote>",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.HTML,
    )
