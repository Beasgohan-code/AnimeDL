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
    from leechbot.utility.variables import BOT, Queue

    return web.json_response({
        "status": "ok",
        "version": config.VERSION,
        "uptime_s": int((datetime.utcnow() - START_TIME).total_seconds()),
        "leech_task_active": bool(getattr(BOT.State, "task_going", False)),
        "queue_size": Queue.size() if hasattr(Queue, "size") else 0,
    })


async def start_health_server():
    web_app = web.Application()
    web_app.router.add_get("/", handle_root)
    web_app.router.add_get("/health", handle_health)
    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.environ.get("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
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
        logger.info("🔑 Dashboard token: %s", dash_token)
    except Exception as e:
        logger.warning("Web dashboard failed to start: %s", e)

    # Ongoing-episode auto-download scheduler (anime core)
    from cantarella.telegram.ongoing import ongoing_task
    asyncio.create_task(ongoing_task(app))

    logger.info("🚀 AnimeDL v%s fully started", config.VERSION)
    import pyrogram
    await pyrogram.idle()

    # Graceful shutdown — block new leech tasks before stopping the client
    try:
        from leechbot.utility.variables import BOT
        BOT.State.shutting_down = True
        from leechbot.utility.rss_manager import stop_rss_poller
        stop_rss_poller()
    except Exception:
        pass
    logger.info("🛑 Shutdown signal received — draining…")
    await app.stop()


def main():
    logger.info("Starting AnimeDL v%s…", config.VERSION)
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(run())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown requested — goodbye.")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
