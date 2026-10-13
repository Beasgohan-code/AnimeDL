# mangarepo/ — vendored manga chapter-update engine

The **complete** bot code from github.com/KunalG932/auto-manga-chapter-update-bot
(MIT, © 2026 @codexnano — same upstream as the earlier `sources/` vendor),
vendored **in full** per maintainer request: `config.py`, `database/`
(MongoDB via motor), `plugins/` (search, msearch UI, tracking/check engine,
settings, watermarks, promos, channel listener, admin, broadcast),
`services/` (PDF/CBZ downloader, manager, thumbnails, backup, catbox),
and `sources/` (35 site scrapers).

## Integration (the only edits vs upstream)

1. Absolute imports rewritten to the `mangarepo.` package namespace
   (`from config import Config` → `from mangarepo.config import Config`, etc.).
2. `MONGO_DB_URI` falls back to `MONGO_URL` (AnimeDL's env name).
3. Duplicate commands removed so the merged bot has ONE command surface
   (AnimeDL's handlers win): upstream `/start` `/help` `/search`(stub)
   `/stats` in `plugins/start.py`, `/ban` `/unban` in `plugins/admin.py`,
   `/broadcast` in `plugins/broadcast.py`; `/settings` renamed `/msettings`,
   `/usettings` renamed `/usersettings`.
4. `plugins/eval.py` + `plugins/admin.py` `/eval` `/sh` are vendored but NOT
   registered (remote code execution — deliberately never exposed).
5. Runtime wiring lives in `cantarella/telegram/mangabridge.py` (handlers on
   the shared client + the upstream APScheduler job set); upstream `bot.py`
   is not vendored because AnimeDL's `main.py` is the single entry point.

User-facing upstream branding/links were removed per project policy;
attribution lives here and in NOTICE.md. License: see mangarepo/LICENSE.
