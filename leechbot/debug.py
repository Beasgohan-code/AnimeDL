# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
#
# """
# Debug logging and error reporting to Telegram — v2.
#
# What a report contains now:
# - 🕒 full UTC timestamp (date + time, not just clock time)
# - ⏱️ bot uptime (restarts become obvious)
# - 🧩 logging module + 🧭 handler that raised (parsed from the dispatcher log)
# - 📍 top application-code location: file:lineno · function
# - 💥 exception type + message on its own line (no traceback-reading needed)
# - cleaned tracebacks: site-packages shortened to <pkg>/, /app/ stripped
# - 🔁 repeat suppression: the same error is silent for 10 minutes; the next
#   report carries a "+N suppressed" counter (a ping is re-sent every 25th
#   repeat so a persistent error can never fully disappear)
# - tracebacks too big to render inline are attached as a .txt document
#   instead of being bluntly truncated
#
# Provides:
# - TelegramLogHandler: sends ERROR/CRITICAL logs to DUMP_ID channel
# - AsyncExceptionHandler: catches unhandled asyncio task exceptions
# - setup_error_reporting: installs both hooks
# - send_debug: manual debug message sender
# """

import asyncio
import html as _html
import io
import logging
import re
import sys as _sys
import time
import traceback
from datetime import datetime, timezone

import uikit
from pyrogram import types

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Formatting knobs
# -----------------------------------------------------------------------------
SUPPRESS_WINDOW = 600.0   # seconds an identical error fingerprint stays silent
RESEND_EVERY = 25         # …but re-send every Nth repeat as a heartbeat
MAX_TB_CHARS = 3200       # traceback chars kept inline before switching to a file
MAX_ASYNC_TB_CHARS = 2400
MAX_REPORTS_PER_MIN = 12  # global flood guard — dump channel stays readable
BENIGN_EXC_NAMES = {      # not worth a Telegram report, ever
    "MessageNotModified",   # edit with identical content — pure Telegram chatter
    "MessageIdInvalid",     # message already gone while a task was finishing
}

_PROC_START = time.time()


# -----------------------------------------------------------------------------
# Shared helpers
# -----------------------------------------------------------------------------
def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _file_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _uptime_str() -> str:
    """Time since bot start (BotStats.start_time when available)."""
    secs = None
    try:
        from leechbot.utility.variables import BotStats

        secs = max(0, int((datetime.now() - BotStats.start_time).total_seconds()))
    except Exception:
        pass
    if secs is None:
        secs = max(0, int(time.time() - _PROC_START))
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"{days}d {hours}h {mins}m"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def _clean_tb(text: str) -> str:
    """Shorten library paths so application frames stand out."""
    text = re.sub(
        r'File "(?:/usr/local/lib/python[\d.]+/)?(?:src/)?(?:\.?venv/lib/python[\d.]+/)?site-packages/',
        'File "<pkg>/',
        text,
    )
    return (
        text.replace("/app/", "")
        .replace("/home/user/AnimeDL/", "")
    )


def _tb_tail(text: str, limit: int = MAX_TB_CHARS) -> str:
    """Keep the traceback header and the deepest frames that fit the limit."""
    if len(text) <= limit:
        return text
    lines = text.splitlines(keepends=True)
    kept, total = [], len(lines[0]) + 20
    for line in reversed(lines[1:]):
        if total + len(line) > limit:
            break
        kept.insert(0, line)
        total += len(line)
    return lines[0] + "…\n" + "".join(kept)


def _location(exc_info) -> str | None:
    """file:lineno · func of the deepest non-library frame (where *we* broke)."""
    try:
        if not exc_info or not exc_info[2]:
            return None
        tb, last, app = exc_info[2], None, None
        while tb:
            last = tb
            fname = tb.tb_frame.f_code.co_filename
            if "site-packages" not in fname and "<frozen" not in fname:
                app = tb
            tb = tb.tb_next
        target = app or last
        if not target:
            return None
        fname = target.tb_frame.f_code.co_filename
        fname = (
            fname.replace("/app/", "")
            .replace("/home/user/AnimeDL/", "")
        )
        return f"{fname}:{target.tb_lineno} · {target.tb_frame.f_code.co_name}"
    except Exception:
        return None


def _exc_summary(exc) -> str | None:
    if exc is None:
        return None
    return f"{type(exc).__name__}: {exc}"[:300]


def _handler_name(log_text: str) -> str | None:
    """pyrogram logs 'Unexpected exception raised in MessageHandler:'."""
    m = re.search(r"raised in (\w+)", log_text or "")
    return m.group(1) if m else None


# =============================================================================
# Telegram Log Handler — sends errors to DUMP_ID
# =============================================================================
class TelegramLogHandler(logging.Handler):
    """
    Logging handler that sends ERROR and CRITICAL level messages
    to the configured DUMP_ID channel via Telegram — with dedup,
    structured context and document fallback for huge tracebacks.
    """

    def __init__(self, client, dump_id: int, level=logging.ERROR):
        super().__init__(level=level)
        self.client = client
        self.dump_id = dump_id
        self._loop = None
        self._queue = asyncio.Queue()
        self._running = False
        self._suppressed = {}  # fingerprint -> [repeat_count, monotonic_ts]
        self._window_start = time.monotonic()
        self._window_count = 0
        self._dropped = 0      # reports suppressed by the 1-min flood guard

    # -- dedup ---------------------------------------------------------------
    def _fingerprint(self, record):
        exc = record.exc_info[1] if record.exc_info else None
        if exc is not None:
            return (record.name, type(exc).__name__, _location(record.exc_info))
        return (record.name, record.getMessage()[:80], None)

    def emit(self, record):
        """Dedup-check the record, then queue it for async sending."""
        if not self._running:
            return
        msg_text = record.getMessage() if hasattr(record, "getMessage") else str(record)
        if "QueryIdInvalid" in msg_text or "QUERY_ID_INVALID" in msg_text:
            return
        exc = record.exc_info[1] if record.exc_info else None
        if exc is not None and type(exc).__name__ in BENIGN_EXC_NAMES:
            return
        try:
            now = time.monotonic()
            if now - self._window_start > 60.0:
                self._window_start, self._window_count = now, 0
            if self._window_count >= MAX_REPORTS_PER_MIN:
                self._dropped += 1
                return
            self._window_count += 1
            fp = self._fingerprint(record)
            entry = self._suppressed.get(fp)
            repeats = 0
            if entry and now - entry[1] < SUPPRESS_WINDOW:
                entry[0] += 1
                entry[1] = now
                if entry[0] % RESEND_EVERY:  # silent, except every Nth repeat
                    return
                repeats = entry[0]
            else:
                if entry:
                    repeats = entry[0]
                self._suppressed[fp] = [0, now]
                if len(self._suppressed) > 64:  # prune stale fingerprints
                    for stale in list(self._suppressed)[:-32]:
                        self._suppressed.pop(stale, None)

            body, file_tb = self.format(record, repeats=repeats)
            loop = self._loop
            if loop and loop.is_running():
                loop.call_soon_threadsafe(self._queue.put_nowait, (body, file_tb))
        except Exception:
            pass

    async def _sender(self):
        """Background task that sends queued messages to Telegram."""
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            except Exception:
                await asyncio.sleep(1)
                continue

            body, file_tb = item if isinstance(item, tuple) else (item, None)
            try:
                await uikit.send(self.client, self.dump_id, body)
                if file_tb:
                    doc = io.BytesIO(file_tb.encode("utf-8", "replace"))
                    doc.name = f"traceback-{_file_stamp()}.txt"
                    await self.client.send_document(self.dump_id, doc)
            except Exception as e:
                # Don't recurse — just log to stderr
                print(f"[TelegramLogHandler] Failed to send log: {e}", flush=True)

    async def start(self):
        """Start the background sender task."""
        self._loop = asyncio.get_running_loop()
        self._running = True
        asyncio.create_task(self._sender())

    def stop(self):
        """Stop the background sender."""
        self._running = False

    def format(self, record, repeats: int = 0):
        """Format a log record as (rich error report, full_traceback_or_None)."""

        level_emoji = {
            logging.ERROR: "🔴",
            logging.CRITICAL: "💀",
            logging.WARNING: "🟡",
        }
        emoji = level_emoji.get(record.levelno, "ℹ️")

        msg_text = record.getMessage()
        exc = record.exc_info[1] if record.exc_info else None

        rows = [
            ("🕒 When", uikit.code(_utc_now_str())),
            ("🧩 Module", uikit.code(record.name)),
        ]
        handler = _handler_name(msg_text)
        if handler:
            rows.append(("🧭 Handler", uikit.code(handler)))
        loc = _location(record.exc_info)
        if loc:
            rows.append(("📍 Location", uikit.code(loc)))
        if exc is not None:
            rows.append(("💥 Error", uikit.code(_exc_summary(exc))))
        else:
            rows.append(("💬 Message", uikit.code(msg_text[:300])))
        rows.append(("⏱️ Uptime", uikit.code(_uptime_str())))
        if repeats:
            rows.append(
                ("🔁 Suppressed", uikit.code(f"+{repeats} repeats (10 min window)"))
            )
        if self._dropped:
            rows.append(
                ("📦 Flood guard", uikit.code(f"+{self._dropped} more suppressed (1 min)"))
            )
            self._dropped = 0

        body = uikit.heading(f"{emoji} {record.levelname}", level=4) + uikit.kv(rows)

        file_tb = None
        if record.exc_info and record.exc_info[1]:
            full_tb = _clean_tb(
                "".join(traceback.format_exception(*record.exc_info))
            )
            body += "<pre>" + _html.escape(_tb_tail(full_tb)) + "</pre>"
            if len(full_tb) > MAX_TB_CHARS:
                file_tb = full_tb
        else:
            body += "<pre>" + _html.escape(msg_text[:1500]) + "</pre>"

        return uikit.panel("Error report", body, level=3), file_tb


# =============================================================================
# Asyncio Exception Handler
# =============================================================================
class AsyncExceptionHandler:
    """
    Catches unhandled asyncio task exceptions and reports them to Telegram.
    """

    def __init__(self, client, dump_id: int):
        self.client = client
        self.dump_id = dump_id

    def handle(self, loop, context):
        """Handle unhandled asyncio exceptions.

        Shutdown-safe: during loop close / interpreter finalization we must
        not import modules (sys.meta_path is already None) or create tasks
        (coroutines would never be awaited) — stderr only in that case.
        """
        exception = context.get("exception")
        message = context.get("message", "Unhandled exception in asyncio task")

        try:
            loop_closed = loop.is_closed()
        except Exception:
            loop_closed = True
        if loop_closed or _sys.is_finalizing():
            print(f"[Asyncio Error] {context}", flush=True)
            return

        rows = [
            ("🕒 When", uikit.code(_utc_now_str())),
            ("💬 Message", uikit.code(str(message)[:300])),
        ]
        tb = "No traceback available"
        if exception:
            rows.append(
                ("⚠️ Exception", uikit.code(_exc_summary(exception)))
            )
            loc = _location(
                (type(exception), exception, exception.__traceback__)
            )
            if loc:
                rows.append(("📍 Location", uikit.code(loc)))
            tb = _clean_tb(
                "".join(
                    traceback.format_exception(
                        type(exception), exception, exception.__traceback__
                    )
                )
            )
            tb = _tb_tail(tb, MAX_ASYNC_TB_CHARS)
        rows.append(("⏱️ Uptime", uikit.code(_uptime_str())))

        error_msg = uikit.panel(
            "Unhandled Asyncio Exception",
            uikit.heading("💀 Unhandled Asyncio Exception", level=4)
            + uikit.kv(rows)
            + "<pre>" + _html.escape(tb) + "</pre>",
            level=3,
        )

        # Send to Telegram (non-blocking)
        try:
            loop.create_task(self._send(error_msg))
        except Exception:
            print(f"[AsyncExceptionHandler] {error_msg}", flush=True)

        # Also log to stderr
        print(f"[Asyncio Error] {context}", flush=True)

    async def _send(self, msg: str):
        """Send error message to Telegram."""
        try:
            await uikit.send(self.client, self.dump_id, msg)
        except Exception as e:
            print(f"[AsyncExceptionHandler] Failed to send: {e}", flush=True)


# =============================================================================
# Setup Function
# =============================================================================
async def setup_error_reporting(client, dump_id: int, owner_id: int):
    """
    Install all error reporting hooks:
    1. TelegramLogHandler — sends ERROR/CRITICAL logs to DUMP_ID
    2. Asyncio exception handler — catches unhandled task errors
    """
    if not dump_id:
        logger.warning("DUMP_ID not set — error reporting to Telegram disabled")
        return

    # 1. Telegram log handler
    tg_handler = TelegramLogHandler(client, dump_id, level=logging.ERROR)
    tg_handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(tg_handler)
    await tg_handler.start()
    logger.info("✅ Telegram error reporting enabled → %s", dump_id)

    # 2. Asyncio exception handler
    loop = asyncio.get_running_loop()
    async_handler = AsyncExceptionHandler(client, dump_id)
    loop.set_exception_handler(async_handler.handle)
    logger.info("✅ Asyncio exception handler installed")

    return tg_handler


# =============================================================================
# Manual Debug Sender
# =============================================================================
async def send_debug(client, dump_id: int, message: str, level: str = "info"):
    """
    Send a debug message to the DUMP_ID channel.

    Args:
        client: Pyrogram client
        dump_id: target chat ID
        message: debug text
        level: "info", "warning", "error"
    """
    emoji = {"info": "ℹ️", "warning": "🟡", "error": "🔴"}.get(level, "ℹ️")
    text = (
        f"{emoji} <b>Debug</b> <code>{_utc_now_str()}</code>\n\n"
        f"<code>{message[:3500]}</code>"
    )

    try:
        await client.send_message(
            chat_id=dump_id,
            text=text,
            link_preview_options=types.LinkPreviewOptions(is_disabled=True),
        )
    except Exception:
        pass
