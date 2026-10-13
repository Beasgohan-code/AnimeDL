# AnimeDL — manga engine bridge
# Wires the vendored chapter-update engine (mangarepo/, MIT — see
# mangarepo/README.md) onto the ONE shared AnimeDL client:
#   • imports its plugin modules so their handlers attach, then registers
#     them on the shared app (kurigram class-level decorator metadata)
#   • mirrors the upstream bot.py runtime: channel listener + APScheduler
#     jobs (chapter checks every 5 min, cache/storage/memory cleanups,
#     daily DB backup, persistent-task processor)
# The engine's /start /help /ban /unban /broadcast /stats /settings
# /usettings /eval /sh handlers were removed or left unregistered — AnimeDL
# already owns those commands (single command surface, zero duplicates).
#
# License: MIT (vendored engine) — mangarepo/LICENSE.

import logging

log = logging.getLogger(__name__)

# Plugin modules whose decorated handlers attach to the shared client.
# (mangarepo.plugins.sett pulls the whole settings/ package via *-import;
#  mangarepo.plugins.check pulls shared + cmd + scheduler.
#  mangarepo.plugins.eval is intentionally NOT loaded — remote code exec.)
_MODULES = (
    "mangarepo.plugins.start",       # help/about/admin-panel callbacks
    "mangarepo.plugins.search",      # /search — 35-source parallel search
    "mangarepo.plugins.msearch",     # search UI engine (sources → manga → chapters → track)
    "mangarepo.plugins.list",        # /list tracked series · /del
    "mangarepo.plugins.check",       # /check /stop /info + tracking engine
    "mangarepo.plugins.sett",        # /msettings — quality/interval/watermark/promos
    "mangarepo.plugins.usersettings",  # /usersettings — owner panel
    "mangarepo.plugins.thumb",       # per-user PDF thumbnails
    "mangarepo.plugins.fsub",        # force-subscribe gate ( decorator lib)
    "mangarepo.plugins.admin",       # /banned /dbstats /deluser + ban gates
    "mangarepo.plugins.broadcast",   # /cbroadcast + persistent broadcast tasks
    "mangarepo.plugins.chan_listen", # channel auto-post listener
)


def install_manga_engine(app) -> int:
    """Register every vendored handler on the shared client. Returns count.

    Walks module namespaces recursively (packages like plugins.check and
    plugins.settings keep their handlers in submodules) and de-dupes by
    handler id — the same function object is often re-exported by several
    namespaces via *-imports."""
    import importlib
    import types

    seen_mods, seen_handlers = set(), set()
    found = []

    def _walk(mod):
        if id(mod) in seen_mods:
            return
        seen_mods.add(id(mod))
        for obj in list(vars(mod).values()):
            if isinstance(obj, types.ModuleType):
                if getattr(obj, "__name__", "").startswith("mangarepo."):
                    _walk(obj)
                continue
            meta = getattr(obj, "handlers", None)
            if callable(obj) and meta:
                for handler, group in meta:
                    if id(handler) not in seen_handlers:
                        seen_handlers.add(id(handler))
                        found.append((handler, group))

    loaded = 0
    for modname in _MODULES:
        try:
            mod = importlib.import_module(modname)
        except Exception as e:  # noqa: BLE001 — one bad module ≠ dead engine
            log.error("manga engine module %s failed to load: %s", modname, e)
            continue
        loaded += 1
        _walk(mod)
        # chan_listen exposes a raw MessageHandler instance
        raw = vars(mod).get("chan_listener")
        if raw is not None and hasattr(raw, "callback"):
            found.append((raw, 0))

    for handler, group in found:
        app.add_handler(handler, group)
    log.info("📄 manga engine: %d handlers from %d/%d modules",
             len(found), loaded, len(_MODULES))
    return len(found)


async def start_manga_engine(app) -> None:
    """Runtime wiring that needs a started client: channel listener,
    index cleanup, and the upstream scheduler job set."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from mangarepo.config import Config
    from mangarepo.database.db import db

    # channel listener (upstream bot.py order: init → add_handler → start)
    from mangarepo.plugins import chan_listen
    chan_listen.init_listener(app)
    app.add_handler(chan_listen.chan_listener)
    await chan_listen.start_listener()
    log.info("📄 manga engine: channel listener ready")

    await db.cleanup_indexes()

    sched = AsyncIOScheduler()

    # upstream jobs, same cadence as the vendored bot.py
    from mangarepo.plugins.check.scheduler import check_job
    from mangarepo.plugins.broadcast import delete_broadcast_msgs
    from mangarepo.services.backup import create_db_backup

    async def cache_cleanup():
        try:
            await db.clear_all_cache()
        except Exception as e:  # noqa: BLE001
            log.error("[CACHE] cleanup error: %s", e)

    async def storage_cleanup():
        import os
        import shutil
        import gc
        try:
            if os.path.exists(Config.DOWNLOAD_DIR):
                for name in os.listdir(Config.DOWNLOAD_DIR):
                    p = os.path.join(Config.DOWNLOAD_DIR, name)
                    if os.path.isfile(p) or os.path.islink(p):
                        os.unlink(p)
                    elif os.path.isdir(p):
                        shutil.rmtree(p)
            if os.path.exists("temp"):
                shutil.rmtree("temp", ignore_errors=True)
            gc.collect()
        except Exception as e:  # noqa: BLE001
            log.error("[STORAGE] cleanup error: %s", e)

    async def memory_cleanup():
        import gc
        gc.collect(0), gc.collect(1), gc.collect(2)

    async def process_persistent_tasks():
        try:
            tasks = await db.get_tasks()
            for task in tasks:
                if task.get("name") == "broadcast_delete":
                    await delete_broadcast_msgs(app, task.get("data"))
                await db.del_task(task["_id"])
        except Exception as e:  # noqa: BLE001
            log.error("[TASKS] process error: %s", e)

    sched.add_job(check_job, "interval", minutes=5, args=[app])
    sched.add_job(cache_cleanup, "interval", minutes=10)
    sched.add_job(storage_cleanup, "interval", minutes=10)
    sched.add_job(memory_cleanup, "interval", minutes=5)
    sched.add_job(create_db_backup, "interval", hours=24, args=[app])
    sched.add_job(process_persistent_tasks, "interval", minutes=1)
    sched.start()
    log.info("📄 manga engine: scheduler started "
             "(check 5m · cache 10m · storage 10m · mem 5m · backup 24h · tasks 1m)")


async def ensure_manga_user(uid: int) -> None:
    """Best-effort upsert of a user record in the engine's DB (called from
    AnimeDL's own /start so /usersettings + panels see every user)."""
    try:
        from mangarepo.database.db import db
        await db.add_usr(uid)
    except Exception as e:  # noqa: BLE001
        log.debug("manga user upsert skipped for %s: %s", uid, e)
