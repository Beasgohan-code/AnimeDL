# ============================================================================
#  AnimeDL — Unified Entry Point
# ============================================================================
#  Runs the merged bot:
#    • anime downloader core  (cantarella/ — plugins auto-loaded at start)
#    • leech engine           (leechbot/  — handlers registered at import)
#
#  Both cores share ONE Pyrogram client (see shared.py) so the whole bot
#  runs as a single Telegram session in a single process.
#
#  Usage:  python main.py        (or: python -m cantarella)
# ============================================================================

import os
import sys
import asyncio
from pyrogram.enums import ParseMode  # noqa: E402
import logging

# ---------------------------------------------------------------------------
# Logging (before any bot imports)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logger = logging.getLogger("animedl")

import config  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration pre-flight check
# ---------------------------------------------------------------------------
_missing = config.missing_required()
if _missing:
    print("=" * 62)
    print("  AnimeDL cannot start — missing required configuration:")
    for name in _missing:
        print(f"   ✗ {name}")
    print("-" * 62)
    print("  Set them in your environment or in a .env file:")
    print("    API_ID / API_HASH  → https://my.telegram.org")
    print("    BOT_TOKEN          → https://t.me/BotFather")
    print("    OWNER_ID           → your numeric Telegram user ID")
    print("    MONGO_URL          → MongoDB connection string")
    print("=" * 62)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Shared client + leech handler registration
# ---------------------------------------------------------------------------
# Importing `leechbot` attaches the shared client and sets up its logging;
# importing its submodules registers the leech command/callback/message
# handlers on the shared client. The anime core's handlers are registered
# automatically from the plugins root when the client starts.
import shared  # noqa: E402
from shared import app  # noqa: E402

import leechbot  # noqa: E402,F401  (client wiring + logging)
import leechbot.aliases  # noqa: E402,F401  (alias pre-processor — first)
import leechbot.commands  # noqa: E402,F401
import leechbot.callbacks  # noqa: E402,F401
import leechbot.handlers  # noqa: E402,F401

# ---------------------------------------------------------------------------
# Health-check web server (also used by Heroku / containers)
# ---------------------------------------------------------------------------
from aiohttp import web  # noqa: E402
from datetime import datetime  # noqa: E402

START_TIME = datetime.utcnow()


async def handle_root(request):
    return web.Response(text="AnimeDL is running 🚀")


async def handle_health(request):
    # Fully guarded: a probe (or the keep-alive pinger) must ALWAYS get a
    # 200-series answer, never a handler-crash 500 that reads as downtime.
    payload = {
        "status": "ok",
        "version": config.VERSION,
        "uptime_s": 0,
        "leech_task_active": False,
        "queue_size": 0,
    }
    try:
        payload["uptime_s"] = int((datetime.utcnow() - START_TIME).total_seconds())
        from leechbot.utility.variables import BOT, Queue
        payload["leech_task_active"] = bool(getattr(BOT.State, "task_going", False))
        payload["queue_size"] = Queue.size() if hasattr(Queue, "size") else 0
    except Exception:
        pass
    try:
        import reliability
        payload["keepalive"] = reliability.keepalive.stats()
        payload["watchdog"] = reliability.watchdog.stats()
        payload["status"] = "degraded" if reliability.watchdog.disk_pressure else "ok"
    except Exception:
        pass
    return web.json_response(payload)


async def start_health_server():
    web_app = web.Application()
    web_app.router.add_get("/health", handle_health)
    web_app.router.add_get("/", handle_health)   # Render HEAD / probes → 200

    # Dashboard on the PRIMARY port — the only port Render exposes publicly.
    # (The 8081 standalone server stays up for local debugging, but on
    # Render only $PORT is reachable, so /dashboard must live here.)
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "public", "index.html")
    if os.path.exists(html_path):
        async def _serve_dashboard(request):
            return web.FileResponse(html_path)
        web_app.router.add_get("/dashboard", _serve_dashboard)
        web_app.router.add_static("/static", os.path.dirname(html_path))
    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.environ.get("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    ext = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    logger.warning("🌐 Health: %s/health", ext or f"http://0.0.0.0:{port}")
    if os.path.exists(html_path):
        logger.warning("📊 Dashboard: %s/dashboard", ext or f"http://0.0.0.0:{port}")
    else:
        logger.info("Health server listening on 0.0.0.0:%s", port)


# ---------------------------------------------------------------------------
# Peer resolution (fresh sessions don't have channel peers cached)
# ---------------------------------------------------------------------------
async def _resolve_peer(peer_id, label: str):
    if not peer_id:
        return
    try:
        await app.resolve_peer(peer_id)
        logger.info("✅ %s peer resolved: %s", label, peer_id)
        return
    except Exception:
        pass
    try:
        chat = await app.get_chat(peer_id)
        logger.info("✅ %s peer resolved via get_chat: %s", label, peer_id)
        return
    except Exception:
        pass
    try:
        msg = await app.send_message(peer_id, "🔄 AnimeDL restarted — peer cache refreshed.")
        await msg.delete()
        logger.info("✅ %s peer resolved via test message: %s", label, peer_id)
        return
    except Exception:
        pass
    logger.warning(
        "⚠️ Could not resolve %s (%s). The bot will retry when first used.",
        label, peer_id,
    )


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
def _log_target():
    """Where lifecycle/alert posts go — one unified chain for the whole bot.

    Users historically only set DUMP_ID (error reports), so announcements
    that looked only at LOG_CHANNEL silently went nowhere. Every notifier
    now resolves the same way: LOG_CHANNEL → DUMP_ID → OWNER_ID.
    Returns (chat_id or None, source_name).
    """
    for name in ("LOG_CHANNEL", "DUMP_ID", "OWNER_ID"):
        raw = getattr(config, name, None)
        if not raw:
            continue
        try:
            cid = int(raw)
        except (TypeError, ValueError):
            continue
        if cid:
            return cid, name
    return None, None


async def _announce(text: str):
    """Post a lifecycle event (start/stop/restart) to the log target. Non-fatal."""
    target, source = _log_target()
    if target is None:
        logger.warning(
            "📣 Lifecycle post skipped — set LOG_CHANNEL (or DUMP_ID) in your "
            "Render environment to see start/stop posts in Telegram"
        )
        return
    try:
        await asyncio.wait_for(
            app.send_message(target, text, parse_mode=ParseMode.HTML),
            timeout=8,
        )
    except Exception as e:
        logger.debug("lifecycle announce failed (%s): %s", source, e)


async def run():
    await start_health_server()
    await app.start()

    # Unified bot-command menu (anime + leech)
    from cantarella.telegram.utils import set_bot_commands
    await set_bot_commands(app)

    # Restore "restarted" marker (anime core)
    try:
        from cantarella.core.database import db
        restart_msg_id = await db.get_user_setting(config.OWNER_ID, "restart_msg_id")
        restart_chat_id = await db.get_user_setting(config.OWNER_ID, "restart_chat_id")
        if restart_msg_id and restart_chat_id:
            try:
                from pyrogram.enums import ParseMode
                await app.edit_message_text(
                    chat_id=restart_chat_id,
                    message_id=restart_msg_id,
                    text="<b>✅ ʙᴏᴛ ʀᴇꜱᴛᴀʀᴛᴇᴅ ꜱᴜᴄᴄᴇꜱꜱғᴜʟʟʏ!</b>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.error("Failed to edit restart message: %s", e)
            await db.set_user_setting(config.OWNER_ID, "restart_msg_id", None)
            await db.set_user_setting(config.OWNER_ID, "restart_chat_id", None)
    except Exception as e:
        logger.error("Error checking restart status: %s", e)

    # Resolve leech peers (dump channel + owner)
    await _resolve_peer(config.DUMP_ID, "dump channel")
    await _resolve_peer(config.OWNER_ID, "owner")

    # Leech engine: Telegram error reporting (logs → dump channel)
    try:
        from leechbot.debug import setup_error_reporting
        await setup_error_reporting(app, config.DUMP_ID, config.OWNER_ID)
    except Exception as e:
        logger.warning("Leech error reporting not installed: %s", e)

    # Leech engine: RSS auto-download poller
    try:
        from leechbot.utility.rss_manager import start_rss_poller
        start_rss_poller()
        logger.info("📰 RSS auto-download poller started")
    except Exception as e:
        logger.warning("RSS poller failed to start: %s", e)

    # Leech engine: web dashboard (separate port from the health server)
    try:
        import secrets
        from leechbot.web.server import start_web_server
        dash_port = config.WEB_PORT
        dash_token = config.WEB_TOKEN or secrets.token_urlsafe(32)
        await start_web_server(port=dash_port, token=dash_token)
        logger.info("🌐 Dashboard: http://0.0.0.0:%d/dashboard", dash_port)
        logger.info("🔑 Dashboard token: %s…", dash_token[:8])
    except Exception as e:
        logger.warning("Web dashboard failed to start: %s", e)

    # Ongoing-episode auto-download scheduler (anime core)
    from cantarella.telegram.ongoing import ongoing_task
    bg_tasks = [asyncio.create_task(ongoing_task(app))]

    # Reliability layer: keep-alive pinger + watchdog
    import reliability
    reliability.start(app)

    logger.info("🚀 AnimeDL v%s fully started", config.VERSION)
    _lt, _lsrc = _log_target()
    if _lt is None:
        logger.warning("📣 No LOG_CHANNEL / DUMP_ID set — start/stop posts disabled")
    else:
        logger.warning("📣 Lifecycle posts (start/stop/errors) → %s (via %s)", _lt, _lsrc)

    # Lifecycle → Telegram log channel (visible on the phone, not just Render)
    _dash = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    await _announce(
        f"<blockquote>🟢 <b>ʙᴏᴛ ᴏɴʟɪɴᴇ</b> — ᴠ{config.VERSION}</blockquote>\n"
        f"<blockquote>⏱ ᴜᴘᴛɪᴍᴇ ᴄʟᴏᴄᴋ ꜱᴛᴀʀᴛᴇᴅ · 💓 ᴋᴇᴇᴘ-ᴀʟɪᴠᴇ ᴀᴄᴛɪᴠᴇ</blockquote>"
        + (f"\n<blockquote>📊 <a href=\"{_dash}/dashboard\">ᴅᴀꜱʜʙᴏᴀʀᴅ</a></blockquote>" if _dash else "")
    )
    import pyrogram
    await pyrogram.idle()

    # Graceful shutdown — block new leech tasks before stopping the client
    try:
        from leechbot.utility.variables import BOT
        BOT.State.shutting_down = True
        from leechbot.utility.rss_manager import stop_rss_poller
        stop_rss_poller()
        try:
            from leechbot.web.server import stop_web_server
            await stop_web_server()
        except Exception:
            pass
        for _t in bg_tasks:
            _t.cancel()
        if bg_tasks:
            await asyncio.gather(*bg_tasks, return_exceptions=True)
        import reliability
        await reliability.stop_all()
    except Exception:
        pass
    _up = int((datetime.utcnow() - START_TIME).total_seconds()) // 60
    logger.warning("🛑 Stop signal received (uptime %dm) — draining…", _up)
    await _announce(
        f"<blockquote>🛑 <b>ʙᴏᴛ ꜱᴛᴏᴘᴘᴇᴅ</b> — ᴠ{config.VERSION}</blockquote>\n"
        f"<blockquote>⏱ ᴜᴘᴛɪᴍᴇ: {_up}ᴍ · ʀᴇꜱᴛᴀʀᴛɪɴɢ/ꜱʟᴇᴇᴘɪɴɢ…</blockquote>"
    )
    await app.stop()


def main():
    import os as _os
    import time as _time
    _t0 = _time.time()
    logger.warning(
        "🟢 START AnimeDL ULTRA v%s — pid=%s port=%s work=%s",
        config.VERSION, _os.getpid(), _os.environ.get("PORT", "8080"),
        str(config.WORK_PATH),
    )
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(run())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        _mins = int((_time.time() - _t0) // 60)
        logger.warning(
            "🛑 STOP AnimeDL v%s — uptime %dm%s — bye 👋",
            config.VERSION, _mins,
            " (stop signal)" if _mins >= 0 else "",
        )
        loop.close()


if __name__ == "__main__":
    main()
