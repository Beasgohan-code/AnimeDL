# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
Lightweight web server for the LeechBot dashboard.

Runs alongside the bot on Colab/VPS. Exposes REST API + WebSocket
for the HTML dashboard to display queue, stats, settings, and
real-time progress.
"""

import os
import logging
import asyncio
from datetime import datetime
from aiohttp import web, WSMsgType

logger = logging.getLogger(__name__)

# Connected WebSocket clients
_ws_clients: set = set()

# Auth token (set at startup)
_auth_token: str = ""


def _get_bot_state() -> dict:
    """Collect current bot state for API responses."""
    try:
        from leechbot.utility.variables import (
            BOT, Queue, BotTimes, Messages, Transfer, BotStats, Paths
        )
        from leechbot.utility.helper import getSize, sizeUnit, getTime
    except ImportError:
        # Bot modules not loaded — return minimal state
        return {
            "status": "starting",
            "task": {"active": False},
            "queue": {"pending": 0, "current": False, "items": []},
            "transfer": {"total_down_size": 0, "files_sent": 0, "files_sent_names": []},
            "stats": {"total_tasks": 0, "total_downloaded": 0, "total_uploaded": 0,
                      "failed_tasks": 0, "uptime": 0, "uptime_human": "0s"},
            "system": {"cpu": 0, "ram_used": 0, "ram_total": 0, "ram_percent": 0,
                       "disk_free": 0, "disk_total": 0},
            "settings": {},
            "timestamp": datetime.now().isoformat(),
        }

    # Current task info
    task_active = BOT.State.task_going
    elapsed = 0
    if task_active:
        elapsed = int((datetime.now() - BotTimes.start_time).total_seconds())

    # Queue info
    queue_items = []
    for i, item in enumerate(list(Queue._queue), 1):
        queue_items.append({
            "index": i,
            "links": len(item.get("links", [])),
            "first_link": item["links"][0][:80] if item.get("links") else "",
            "mode": item.get("mode", "leech"),
            "added_at": item.get("added_at", datetime.now()).isoformat(),
        })

    # Download size
    try:
        down_size = getSize(Paths.down_path) if os.path.exists(Paths.down_path) else 0
    except Exception:
        down_size = 0

    # System info
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
    except Exception:
        cpu, ram, disk = 0, None, None

    return {
        "status": "active" if task_active else "idle",
        "task": {
            "active": task_active,
            "mode": BOT.Mode.mode,
            "type": BOT.Mode.type,
            "ytdl": BOT.Mode.ytdl,
            "gallery": BOT.Mode.gallery,
            "download_name": Messages.download_name,
            "elapsed": elapsed,
            "elapsed_human": getTime(elapsed),
            "down_size": down_size,
            "down_size_human": sizeUnit(down_size),
        },
        "queue": {
            "pending": Queue.pending,
            "current": bool(Queue.current),
            "items": queue_items,
        },
        "transfer": {
            "total_down_size": Transfer.total_down_size,
            "total_down_size_human": sizeUnit(Transfer.total_down_size),
            "files_sent": len(Transfer.sent_file),
            "files_sent_names": Transfer.sent_file_names[-10:],
        },
        "stats": {
            "total_tasks": BotStats.total_tasks,
            "total_downloaded": BotStats.total_downloaded,
            "total_downloaded_human": sizeUnit(BotStats.total_downloaded),
            "total_uploaded": BotStats.total_uploaded,
            "total_uploaded_human": sizeUnit(BotStats.total_uploaded),
            "failed_tasks": BotStats.failed_tasks,
            "uptime": int((datetime.now() - BotStats.start_time).total_seconds()),
            "uptime_human": getTime(int((datetime.now() - BotStats.start_time).total_seconds())),
        },
        "system": {
            "cpu": cpu,
            "ram_used": ram.used if ram else 0,
            "ram_total": ram.total if ram else 0,
            "ram_percent": ram.percent if ram else 0,
            "disk_free": disk.free if disk else 0,
            "disk_total": disk.total if disk else 0,
        },
        "settings": {
            "stream_upload": BOT.Setting.stream_upload,
            "convert_video": BOT.Setting.convert_video,
            "split_video": BOT.Setting.split_video,
            "caption": BOT.Setting.caption,
            "prefix": bool(BOT.Setting.prefix),
            "suffix": bool(BOT.Setting.suffix),
            "thumbnail": BOT.Setting.thumbnail,
            "photo_mode": BOT.Setting.photo_mode,
            "auto_delete": BOT.Setting.auto_delete,
            "auto_delete_delay": BOT.Setting.auto_delete_delay,
        },
        "timestamp": datetime.now().isoformat(),
    }


def _check_auth(request) -> bool:
    """Check if request has valid auth token."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        token = request.query.get("token", "")
    return token == _auth_token


# =============================================================================
# REST API Routes
# =============================================================================

async def handle_status(request):
    """GET /api/status — full bot state."""
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    return web.json_response(_get_bot_state())


async def handle_queue(request):
    """GET /api/queue — queue details."""
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    from leechbot.utility.variables import Queue
    state = _get_bot_state()
    return web.json_response(state["queue"])


async def handle_stats(request):
    """GET /api/stats — statistics."""
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    state = _get_bot_state()
    return web.json_response({
        "stats": state["stats"],
        "system": state["system"],
    })


async def handle_settings(request):
    """GET /api/settings — current settings."""
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    state = _get_bot_state()
    return web.json_response(state["settings"])


async def handle_cancel(request):
    """POST /api/cancel — cancel current task."""
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        from leechbot.utility.handler import cancelTask
        from leechbot.utility.variables import BOT

        if BOT.State.task_going:
            await cancelTask("Cancelled via web dashboard")
            return web.json_response({"ok": True, "message": "Task cancelled"})
        return web.json_response({"ok": False, "message": "No active task"})
    except ImportError:
        return web.json_response({"ok": False, "message": "Bot not ready"})


async def handle_queue_clear(request):
    """POST /api/queue/clear — clear the queue."""
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        from leechbot.utility.variables import Queue
        Queue.clear()
        return web.json_response({"ok": True, "message": "Queue cleared"})
    except ImportError:
        return web.json_response({"ok": False, "message": "Bot not ready"})


async def handle_health(request):
    """GET /api/health — health check (no auth)."""
    return web.json_response({"status": "ok", "bot": "AnimeDL"})


# =============================================================================
# WebSocket Handler
# =============================================================================

async def handle_ws(request):
    """WebSocket endpoint for real-time updates."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Auth check via first message
    try:
        auth_msg = await ws.receive(timeout=5)
        auth_data = auth_msg.json()
        if auth_data.get("auth") != _auth_token:
            await ws.close(code=4001, message=b"Unauthorized")
            return ws
    except Exception:
        await ws.close(code=4002, message=b"Auth timeout")
        return ws

    _ws_clients.add(ws)
    logger.info("WebSocket client connected (%d total)", len(_ws_clients))

    try:
        # Send initial state
        await ws.send_json(_get_bot_state())

        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                if msg.data == "ping":
                    await ws.send_str("pong")
                elif msg.data == "status":
                    await ws.send_json(_get_bot_state())
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        _ws_clients.discard(ws)
        logger.info("WebSocket client disconnected (%d total)", len(_ws_clients))

    return ws


# =============================================================================
# Broadcast updates to all WebSocket clients
# =============================================================================

async def broadcast_update(data: dict = None):
    """Send update to all connected WebSocket clients."""
    if not _ws_clients:
        return

    if data is None:
        data = _get_bot_state()

    dead = set()
    for ws in _ws_clients:
        try:
            await ws.send_json(data)
        except Exception:
            dead.add(ws)
    _ws_clients -= dead


async def _auto_broadcast():
    """Background task that broadcasts state every 3 seconds."""
    while True:
        await asyncio.sleep(3)
        if _ws_clients:
            try:
                await broadcast_update()
            except Exception as e:
                logger.debug("Broadcast error: %s", e)


# =============================================================================
# CORS Middleware
# =============================================================================

@web.middleware
async def cors_middleware(request, handler):
    """Add CORS headers for cross-origin dashboard access."""
    if request.method == "OPTIONS":
        response = web.Response()
    else:
        try:
            response = await handler(request)
        except web.HTTPException as e:
            response = e

    response.headers["Access-Control-Allow-Origin"] = os.getenv("WEB_CORS_ORIGIN", "*")
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    return response


# =============================================================================
# Server Startup
# =============================================================================

async def start_web_server(port: int = 8080, token: str = ""):
    """
    Start the web dashboard server.

    Args:
        port: HTTP port to listen on
        token: Auth token for API access
    """
    global _auth_token
    _auth_token = token

    app = web.Application(middlewares=[cors_middleware])

    # Routes
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/api/queue", handle_queue)
    app.router.add_get("/api/stats", handle_stats)
    app.router.add_get("/api/settings", handle_settings)
    app.router.add_post("/api/cancel", handle_cancel)
    app.router.add_post("/api/queue/clear", handle_queue_clear)
    app.router.add_get("/ws", handle_ws)

    # Serve the dashboard HTML
    html_path = os.path.join(os.path.dirname(__file__), "..", "..", "public", "index.html")
    if os.path.exists(html_path):
        app.router.add_static("/static", os.path.dirname(html_path))
        async def serve_dashboard(request):
            return web.FileResponse(html_path)
        app.router.add_get("/dashboard", serve_dashboard)
        app.router.add_get("/", serve_dashboard)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    # Start auto-broadcast background task
    asyncio.create_task(_auto_broadcast())

    logger.info("🌐 Web dashboard running on http://0.0.0.0:%d", port)
    logger.info("📊 Dashboard URL: http://0.0.0.0:%d/dashboard", port)
    logger.info("🔑 Auth token: %s****", token[:4] if token else "NONE")

    return port
