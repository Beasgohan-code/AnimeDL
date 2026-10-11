# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
RSS feed monitor for auto-downloading new items.

Feeds are stored in BASE_DIR/rss_feeds.json. The poller runs in the
background while the bot is online and dispatches new entries to the
configured command (e.g., tupload, ytupload).

Note: Colab runtimes are not always online, so items published while the
bot is offline will be missed unless the feed is re-fetched on startup and
the entries are still recent.
"""

import json
import logging
from collections import deque
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import feedparser

from pyrogram import types
from leechbot import OWNER, app
from leechbot.utility.helper import extract_links
from leechbot.utility.variables import BOT, MSG, BotTimes

logger = logging.getLogger(__name__)

RSS_FEEDS_FILE: Path = None  # set by load_feeds()
_DEFAULT_INTERVAL = 15  # minutes
_POLLTASK = None
_STOP_EVENT = False
_PENDING: deque = deque()


class _FakeMessage:
    """Minimal message stand-in for dispatching URLs programmatically."""

    def __init__(self, chat_id: int, text: str):
        self.text = text
        self.caption = None
        self.chat = SimpleNamespace(id=chat_id)
        self.from_user = SimpleNamespace(id=chat_id)

    async def delete(self):
        pass

    async def reply_text(self, text, link_preview_options=None, reply_markup=None):
        return await app.send_message(
            chat_id=self.chat.id,
            text=text,
            link_preview_options=link_preview_options,
            reply_markup=reply_markup,
        )


def _feeds_path() -> Path:
    import config
    return config.BASE_DIR / "rss_feeds.json"


def load_feeds() -> list:
    """Load RSS feed configuration from disk."""
    path = _feeds_path()
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception as e:
        logger.warning("Failed to load RSS feeds: %s", e)
    return []


def save_feeds(feeds: list):
    """Persist RSS feed configuration to disk."""
    path = _feeds_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(feeds, f, indent=2)
    except Exception as e:
        logger.error("Failed to save RSS feeds: %s", e)


def add_feed(url: str, command: str, interval: int = _DEFAULT_INTERVAL) -> int:
    """Add a new RSS feed. Returns the assigned feed id."""
    feeds = load_feeds()
    new_id = max((f.get("id", 0) for f in feeds), default=0) + 1
    feeds.append({
        "id": new_id,
        "url": url,
        "command": command.lower().lstrip("/"),
        "interval": max(5, int(interval)),
        "seen_guids": [],
        "last_check": None,
        "enabled": True,
    })
    save_feeds(feeds)
    return new_id


def remove_feed(feed_id: int) -> bool:
    """Remove a feed by id."""
    feeds = load_feeds()
    for i, f in enumerate(feeds):
        if f.get("id") == feed_id:
            feeds.pop(i)
            save_feeds(feeds)
            return True
    return False


def list_feeds() -> list:
    """Return current feed list."""
    return load_feeds()


def _command_to_mode(command: str):
    """Map alias/command to BOT.Mode settings."""
    cmd = command.lower().lstrip("/")
    # defaults
    mode = "leech"
    ytdl = False
    gallery = False

    if cmd in ("tupload", "tg", "dl"):
        mode = "leech"
    elif cmd in ("gdupload", "gd", "mirror"):
        mode = "mirror"
    elif cmd in ("ytupload", "yt"):
        mode = "leech"
        ytdl = True
    elif cmd in ("glupload", "gal", "gallery"):
        mode = "leech"
        gallery = True
    elif cmd in ("drupload", "dir"):
        mode = "dir-leech"
    else:
        mode = "leech"

    return mode, ytdl, gallery


async def _dispatch_url(url: str, command: str):
    """Start a download task for the given URL and command."""
    from asyncio import get_running_loop

    if BOT.State.task_going:
        _PENDING.append((url, command))
        logger.info("RSS task busy; queued %s", url[:80])
        try:
            await app.send_message(
                chat_id=OWNER,
                text=f"<b>⏳ RSS item queued</b>\n\n<code>{url[:200]}</code>\n\n"
                     f"Current task complete hone ke baad auto-start hoga.",
                link_preview_options=types.LinkPreviewOptions(is_disabled=True),
            )
        except Exception:
            pass
        return

    await _start_task(url, command)


async def _start_task(url: str, command: str):
    """Actually start a download task."""
    from asyncio import get_running_loop

    mode, ytdl, gallery = _command_to_mode(command)

    BOT.Mode.mode = mode
    BOT.Mode.ytdl = ytdl
    BOT.Mode.gallery = gallery
    BOT.Mode.type = "normal"
    BOT.SOURCE = extract_links(url)

    if not BOT.SOURCE:
        logger.warning("RSS item produced no extractable links: %s", url)
        return

    try:
        MSG.status_msg = await app.send_message(
            chat_id=OWNER,
            text=f"<b>🚀 RSS Auto-Download Started</b>\n\n"
                 f"<b>Command:</b> <code>/{command}</code>\n"
                 f"<b>Source:</b> <code>{BOT.SOURCE[0][:200]}</code>",
            link_preview_options=types.LinkPreviewOptions(is_disabled=True),
        )
    except Exception as e:
        logger.error("Failed to send RSS status message: %s", e)
        return

    BOT.State.task_going = True
    BOT.State.started = False
    BotTimes.start_time = datetime.now()

    from leechbot.utility.task_manager import taskScheduler
    loop = get_running_loop()
    BOT.TASK = loop.create_task(taskScheduler())
    BOT.TASK.add_done_callback(_on_task_done)
    logger.info("RSS started task for %s", url[:80])


def _on_task_done(task):
    """Process next queued RSS item when a task finishes."""
    BOT.State.task_going = False
    logger.info("RSS task finished; checking pending queue")
    if _PENDING:
        url, command = _PENDING.popleft()
        try:
            loop = task.get_loop()
            loop.create_task(_start_task(url, command))
        except Exception as e:
            logger.error("Failed to start pending RSS task: %s", e)


async def _fetch_feed(session: aiohttp.ClientSession, url: str) -> str:
    """Fetch raw feed content."""
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
        resp.raise_for_status()
        return await resp.text()


async def check_feeds_once():
    """Manually check all feeds and dispatch new items."""
    feeds = load_feeds()
    if not feeds:
        return

    async with aiohttp.ClientSession() as session:
        for feed in feeds:
            if not feed.get("enabled", True):
                continue
            try:
                raw = await _fetch_feed(session, feed["url"])
                parsed = feedparser.parse(raw)
                seen = set(feed.get("seen_guids", []))
                new_entries = []

                for entry in parsed.entries:
                    guid = entry.get("id") or entry.get("guid") or entry.get("link")
                    if not guid:
                        continue
                    if guid not in seen:
                        seen.add(guid)
                        new_entries.append(entry)

                if new_entries:
                    for entry in new_entries:
                        link = entry.get("link") or entry.get("enclosures", [{}])[0].get("href") or ""
                        if link:
                            await _dispatch_url(link, feed["command"])

                    # Notify owner
                    try:
                        titles = "\n".join(f"• {e.get('title', 'No title')[:100]}" for e in new_entries[:5])
                        await app.send_message(
                            chat_id=OWNER,
                            text=f"<b>📰 RSS Update</b>\n\n{len(new_entries)} new item(s) from feed:\n"
                                 f"<code>{feed['url'][:100]}</code>\n\n{titles}",
                            link_preview_options=types.LinkPreviewOptions(is_disabled=True),
                        )
                    except Exception:
                        pass

                feed["seen_guids"] = list(seen)[-500:]  # keep last 500 to avoid bloat
                feed["last_check"] = datetime.now().isoformat()
            except Exception as e:
                logger.warning("RSS check failed for %s: %s", feed.get("url", "?"), e)

    save_feeds(feeds)


async def rss_poller():
    """Background loop that checks feeds periodically."""
    global _STOP_EVENT
    from asyncio import sleep

    logger.info("RSS poller started")
    while not _STOP_EVENT:
        try:
            await check_feeds_once()
        except Exception as e:
            logger.error("RSS poller error: %s", e)

        # Sleep interval (use shortest feed interval, default 15 min)
        feeds = load_feeds()
        interval = min((f.get("interval", _DEFAULT_INTERVAL) for f in feeds if f.get("enabled", True)), default=_DEFAULT_INTERVAL)
        await sleep(interval * 60)

    logger.info("RSS poller stopped")


def start_rss_poller():
    """Start the background RSS polling task."""
    global _POLLTASK, _STOP_EVENT
    import asyncio
    _STOP_EVENT = False
    if _POLLTASK is None or _POLLTASK.done():
        _POLLTASK = asyncio.create_task(rss_poller())


def stop_rss_poller():
    """Signal the RSS poller to stop and cancel its task so shutdown
    does not leave a pending task behind."""
    global _STOP_EVENT, _POLLTASK
    _STOP_EVENT = True
    if _POLLTASK and not _POLLTASK.done():
        _POLLTASK.cancel()
    _POLLTASK = None
