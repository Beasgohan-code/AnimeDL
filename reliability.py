# ============================================================================
#  AnimeDL — Reliability layer: keep-alive + watchdog
# ============================================================================
#  Two cooperating background loops that keep the bot alive and healthy:
#
#  KeepAlive
#    • self-pings the local /health endpoint so PaaS dynos never idle-sleep
#    • optionally pings an external URL (KEEP_ALIVE_URL) as a rendezvous hook
#    • tracks ping counters for the /health dashboard
#
#  Watchdog
#    • stall watchdog   — cancels leech tasks that stopped making progress
#    • memory watchdog  — gc + temp cleanup on soft pressure, restart on hard
#    • disk watchdog    — cleans old download scratch files, flags pressure
#                         (the leech URL handler refuses tasks while flagged)
#    • connection watchdog — alerts on Telegram disconnects, restarts if stuck
#    • scheduled restart — daily hygiene restart via /setrestart HH:MM
#    • heartbeat file    — JSON liveness marker for external supervisors
#
#  Alerts go to LOG_CHANNEL (or the owner) through the rich UI, throttled per
#  alert type so a flapping condition can't spam the channel.
# ============================================================================

import asyncio
import gc
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil

import config
import uikit

logger = logging.getLogger(__name__)

ALERT_COOLDOWN = 900  # seconds between repeat alerts of the same type


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _process() -> psutil.Process:
    return psutil.Process(os.getpid())


def mem_action(rss_mb: float) -> str:
    """Pure classification of memory pressure: ok | soft | hard."""
    if rss_mb >= config.WATCHDOG_MEM_HARD_MB:
        return "hard"
    if rss_mb >= config.WATCHDOG_MEM_SOFT_MB:
        return "soft"
    return "ok"


def parse_restart_time(value: str):
    """Parse 'HH:MM' into (hour, minute); 'off'/'none' → None. Raises ValueError."""
    v = (value or "").strip().lower()
    if v in ("off", "none", "disable", "disabled", ""):
        return None
    m = _HHMM.match(v)
    if not m:
        raise ValueError("use HH:MM (24h) or 'off'")
    h, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mm <= 59):
        raise ValueError("hour 0-23, minute 0-59")
    return (h, mm)


import re as _re  # noqa: E402
_HHMM = _re.compile(r"^(\d{1,2}):(\d{2})$")


def heartbeat_write(path: Path = None, extra: dict = None):
    """Write the liveness heartbeat file (best effort)."""
    path = path or config.HEARTBEAT_PATH
    try:
        payload = {
            "ts": time.time(),
            "iso": datetime.utcnow().isoformat() + "Z",
            "pid": os.getpid(),
            "version": config.VERSION,
        }
        if extra:
            payload.update(extra)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, path)
    except Exception as e:
        logger.debug("heartbeat write failed: %s", e)


def heartbeat_age(path: Path = None) -> float:
    """Seconds since the last heartbeat, or inf when missing/unreadable."""
    path = path or config.HEARTBEAT_PATH
    try:
        return max(0.0, time.time() - json.loads(path.read_text())["ts"])
    except Exception:
        return float("inf")


def cleanup_scratch(max_age_s: int = 3600) -> int:
    """Delete old files in the leech scratch dirs. Returns files removed."""
    removed = 0
    now = time.time()
    for d in (config.DOWNLOADS_PATH, config.TEMP_PATH):
        try:
            for p in Path(d).rglob("*"):
                try:
                    if p.is_file() and now - p.stat().st_mtime > max_age_s:
                        p.unlink()
                        removed += 1
                except OSError:
                    continue
        except Exception as e:
            logger.debug("scratch cleanup skipped for %s: %s", d, e)
    return removed


# ---------------------------------------------------------------------------
# Keep-alive
# ---------------------------------------------------------------------------
def _auto_external_url():
    """Render injects RENDER_EXTERNAL_URL — pinging our own public URL counts
    as real traffic, which is what the free-tier 15-minute idle detector
    watches. The localhost self-ping alone does NOT keep the service awake
    (observed: SIGTERM at 14m55s with only local pings in the logs)."""
    url = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    if not url:
        host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
        if host:
            url = f"https://{host}"
    return url or None


class KeepAlive:
    """Self-ping + optional external ping loop."""

    def __init__(self):
        self.enabled = config.KEEP_ALIVE_ENABLED
        self.interval = max(30, config.KEEP_ALIVE_INTERVAL)
        self.external_url = config.KEEP_ALIVE_URL or _auto_external_url()
        self.total = 0
        self.failed = 0
        self.last_ok = None            # monotonic ts
        self.last_error = None
        self._stop = asyncio.Event()
        self._task = None

    # ------------------------------------------------------------------ ping
    async def _ping(self, url: str) -> None:
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(url) as resp:
                if resp.status >= 500:
                    raise RuntimeError(f"HTTP {resp.status}")

    def local_url(self) -> str:
        port = os.environ.get("PORT", "8080")
        return f"http://127.0.0.1:{port}/health"

    async def cycle_once(self) -> bool:
        """One keep-alive round. Returns True when the local ping succeeded."""
        self.total += 1
        try:
            await self._ping(self.local_url())
            self.last_ok = time.monotonic()
            self.last_error = None
        except Exception as e:
            self.failed += 1
            self.last_error = str(e)
            # warning-level so failures are visible in Render logs, but the
            # loop keeps running — pings are 1/interval, so this can't flood
            logger.warning("keep-alive local ping failed: %s", e)
        if self.external_url:
            try:
                await self._ping(self.external_url)
            except Exception as e:
                logger.debug("keep-alive external ping failed: %s", e)
        return self.last_error is None

    # ------------------------------------------------------------------- loop
    async def run(self):
        if not self.enabled:
            logger.info("Keep-alive disabled (KEEP_ALIVE_ENABLED=false)")
            return
        logger.warning("💓 Keep-alive active — self-ping every %ss%s",
                    self.interval,
                    f" + external {self.external_url} (anti-spin-down)" if self.external_url else " (NO external URL — free tier will spin down!)")
        while not self._stop.is_set():
            try:
                await self.cycle_once()
            except Exception as e:
                logger.debug("keep-alive cycle error: %s", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    def start(self):
        self._stop.clear()
        self._task = asyncio.create_task(self.run())

    async def stop(self):
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    def stats(self) -> dict:
        last_ok_s = None
        if self.last_ok is not None:
            last_ok_s = round(time.monotonic() - self.last_ok, 1)
        return {
            "enabled": self.enabled,
            "interval": self.interval,
            "external_url": self.external_url,
            "total_pings": self.total,
            "failed_pings": self.failed,
            "last_ok_ago_s": last_ok_s,
            "last_error": self.last_error,
        }


# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------
class Watchdog:
    """Periodic health checks with auto-remediation and throttled alerts."""

    def __init__(self, app=None):
        self.app = app
        self.interval = max(15, config.WATCHDOG_INTERVAL)
        self.checks = 0
        self.restarts = 0
        self.last_cycle = None
        self.disk_pressure = False
        self.stall_actions = 0
        self._last_activity = time.monotonic()
        self._last_alert = {}
        self._disconnected_since = None
        self._auto_restart_day = None
        self._stop = asyncio.Event()
        self._task = None

    # ---------------------------------------------------------------- touch
    def touch(self):
        """Progress signal — called by the download/upload progress loops."""
        self._last_activity = time.monotonic()

    @property
    def idle_s(self) -> float:
        return time.monotonic() - self._last_activity

    # ---------------------------------------------------------------- alerts
    async def alert(self, key: str, title: str, body_pairs) -> None:
        now = time.monotonic()
        if now - self._last_alert.get(key, 0) < ALERT_COOLDOWN:
            return
        self._last_alert[key] = now
        target = config.LOG_CHANNEL or config.OWNER_ID
        if not target:
            return
        try:
            target = int(target)
        except (TypeError, ValueError):
            return
        panel = uikit.panel(
            title,
            uikit.kv(list(body_pairs)) + uikit.footer("watchdog"),
            level=3,
        )
        try:
            await uikit.send(self.app, target, panel)
        except Exception as e:
            logger.debug("watchdog alert delivery failed: %s", e)

    # ---------------------------------------------------------------- checks
    def _check_memory(self) -> str:
        action = mem_action(_process().memory_info().rss / (1024 * 1024))
        if action == "soft":
            gc.collect()
            cleanup_scratch(max_age_s=1800)
            logger.info("Watchdog: soft memory pressure — gc + scratch cleanup done")
        return action

    async def _check_memory_full(self) -> None:
        action = self._check_memory()
        rss = _process().memory_info().rss / (1024 * 1024)
        if action == "hard":
            await self.alert("mem", "🧠 Memory critical", [
                ("RSS", uikit.code(f"{rss:.0f} MB")),
                ("Threshold", uikit.code(f"{config.WATCHDOG_MEM_HARD_MB} MB")),
            ])
            if config.WATCHDOG_AUTO_RESTART:
                await self.restart("memory critically high")

    def _check_disk(self) -> None:
        try:
            free_mb = shutil.disk_usage(config.WORK_PATH).free / (1024 * 1024)
        except Exception:
            return
        if free_mb < config.WATCHDOG_MIN_FREE_MB:
            if not self.disk_pressure:
                removed = cleanup_scratch(max_age_s=1800)
                try:
                    free_mb = shutil.disk_usage(config.WORK_PATH).free / (1024 * 1024)
                except Exception:
                    pass
                logger.warning("Watchdog: low disk (%.0f MB free) — cleaned %d files",
                               free_mb, removed)
            if free_mb < config.WATCHDOG_MIN_FREE_MB:
                self.disk_pressure = True
            else:
                self.disk_pressure = False
        else:
            self.disk_pressure = False

    async def _check_disk_full(self) -> None:
        # /tmp can be GC'd under us mid-run — recreate before measuring,
        # and fall back to the parent filesystem if that fails too.
        try:
            free_mb = shutil.disk_usage(config.WORK_PATH).free / (1024 * 1024)
        except OSError:
            try:
                config.WORK_PATH.mkdir(parents=True, exist_ok=True)
                free_mb = shutil.disk_usage(config.WORK_PATH).free / (1024 * 1024)
            except Exception:
                free_mb = shutil.disk_usage("/tmp").free / (1024 * 1024)
        if self.disk_pressure:
            await self.alert("disk", "💽 Disk critically low", [
                ("Free", uikit.code(f"{free_mb:.0f} MB")),
                ("Minimum", uikit.code(f"{config.WATCHDOG_MIN_FREE_MB} MB")),
                ("Action", "new leech tasks refused until cleaned"),
            ])

    async def _check_stall(self) -> None:
        try:
            from leechbot.utility.variables import BOT
        except Exception:
            return
        if not getattr(BOT.State, "task_going", False):
            return
        if self.idle_s < config.WATCHDOG_STALL_MIN * 60:
            return
        self.stall_actions += 1
        await self.alert("stall", "🐌 Stalled task cancelled", [
            ("No progress for", uikit.code(f"{self.idle_s / 60:.0f} min")),
            ("Action", "task cancelled by watchdog"),
        ])
        try:
            from leechbot.utility.handler import cancelTask
            await cancelTask("Watchdog: task stalled — no progress for "
                             f"{config.WATCHDOG_STALL_MIN} minutes")
            self.touch()  # avoid re-triggering while cancellation unwinds
        except Exception as e:
            logger.debug("stall cancel failed: %s", e)

    def _check_connection(self) -> str:
        connected = bool(getattr(self.app, "is_connected", True))
        if connected:
            self._disconnected_since = None
            return "connected"
        if self._disconnected_since is None:
            self._disconnected_since = time.monotonic()
        down_s = time.monotonic() - self._disconnected_since
        if down_s > 180:
            return "restart-wait"
        return "disconnected"

    async def _check_connection_full(self) -> None:
        state = self._check_connection()
        if state == "disconnected":
            await self.alert("conn", "📡 Telegram disconnected", [
                ("State", "reconnecting…"),
                ("Down for", uikit.code(f"{time.monotonic() - (self._disconnected_since or 0):.0f}s")),
            ])
        elif state == "restart-wait":
            if config.WATCHDOG_AUTO_RESTART:
                await self.restart("Telegram connection stuck offline")

    async def _check_scheduled_restart(self) -> None:
        try:
            scheduled = await _get_scheduled_restart()
        except Exception as e:
            logger.debug("scheduled restart lookup failed: %s", e)
            return
        if not scheduled:
            return
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        if (now.hour, now.minute) == scheduled and self._auto_restart_day != today:
            self._auto_restart_day = today
            await self.restart(f"daily hygiene restart ({scheduled[0]:02d}:{scheduled[1]:02d})")

    # ----------------------------------------------------------------- cycle
    async def run_checks(self) -> dict:
        self.checks += 1
        heartbeat_write(extra={"checks": self.checks, "idle_s": round(self.idle_s, 1)})
        mem = mem_action(_process().memory_info().rss / (1024 * 1024))
        self._check_disk()
        await self._check_memory_full()
        await self._check_disk_full()
        await self._check_stall()
        await self._check_connection_full()
        await self._check_scheduled_restart()
        self.last_cycle = time.monotonic()
        return {
            "mem": mem,
            "disk_pressure": self.disk_pressure,
            "connection": self._check_connection(),
            "idle_s": round(self.idle_s, 1),
        }

    async def run(self):
        if not config.WATCHDOG_ENABLED:
            logger.info("Watchdog disabled (WATCHDOG_ENABLED=false)")
            return
        logger.info("🐕 Watchdog active — every %ss (stall>%smin, mem>%sMB, disk<%sMB)",
                    self.interval, config.WATCHDOG_STALL_MIN,
                    config.WATCHDOG_MEM_SOFT_MB, config.WATCHDOG_MIN_FREE_MB)
        while not self._stop.is_set():
            try:
                await self.run_checks()
            except Exception:
                logger.exception("watchdog cycle error")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    def start(self, app=None):
        if app is not None:
            self.app = app
        self._stop.clear()
        self._task = asyncio.create_task(self.run())

    async def stop(self):
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def restart(self, reason: str):
        self.restarts += 1
        logger.warning("🔁 Watchdog restart: %s", reason)
        await self.alert("restart", "🔁 Watchdog restarting bot", [
            ("Reason", reason),
            ("Restart #", uikit.code(self.restarts)),
        ])
        await asyncio.sleep(1)  # give the alert a moment to flush
        # Platform-native restart: exit gracefully and let the supervisor
        # (Render/tini/systemd) relaunch the REAL entrypoint. The old
        # os.execl(python -m cantarella) replaced the process with an
        # entrypoint that never ran its coroutine — instant silent death.
        import signal as _signal
        try:
            os.kill(os.getpid(), _signal.SIGTERM)
        except Exception:
            sys.exit(0)

    def stats(self) -> dict:
        try:
            rss = round(_process().memory_info().rss / (1024 * 1024))
        except Exception:
            rss = None
        try:
            free_mb = round(shutil.disk_usage(config.WORK_PATH).free / (1024 * 1024))
        except Exception:
            free_mb = None
        return {
            "enabled": config.WATCHDOG_ENABLED,
            "interval": self.interval,
            "checks": self.checks,
            "mem_rss_mb": rss,
            "mem_action": mem_action(rss) if rss else "ok",
            "disk_free_mb": free_mb,
            "disk_pressure": self.disk_pressure,
            "task_idle_s": round(self.idle_s, 1),
            "stall_actions": self.stall_actions,
            "restarts": self.restarts,
            "heartbeat_age_s": round(heartbeat_age(), 1) if heartbeat_age() != float("inf") else None,
        }


# ---------------------------------------------------------------------------
# Scheduled restart persistence (anime core DB)
# ---------------------------------------------------------------------------
async def _get_scheduled_restart():
    from cantarella.core.database import db
    value = await db.get_user_setting(0, "auto_restart_time", None)
    if not value:
        return None
    try:
        return parse_restart_time(value)
    except ValueError:
        return None


async def set_scheduled_restart(value: str) -> None:
    """Store/clear the daily auto-restart time ('HH:MM' or None)."""
    from cantarella.core.database import db
    await db.set_user_setting(0, "auto_restart_time", value)


# ---------------------------------------------------------------------------
# Singletons + lifecycle
# ---------------------------------------------------------------------------
keepalive = KeepAlive()
watchdog = Watchdog()


def start(app) -> None:
    """Start both loops (called from main.run after the client is up)."""
    watchdog.start(app)
    keepalive.start()


async def stop_all() -> None:
    await keepalive.stop()
    await watchdog.stop()
