# AnimeDL 📺⬇️

**An all-in-one Telegram bot: advanced anime downloader + universal file leecher, in a single process.**

AnimeDL merges a full anime search & download engine (search, multi-quality episodes, batch downloads, airing scheduler) with a powerful leech engine that can pull files from dozens of sources — direct links, MediaFire, PixelDrain, Gofile, Terabox, Mega, Streamtape, catbox, galleries, torrents/magnets, YouTube & 1000+ yt-dlp sites — and upload them straight to Telegram or mirror them to Google Drive.

---

## ✨ Features

### 🎬 Anime downloader — 7 sources
| Source | Type | Notes |
|---|---|---|
| ⚡ **Hianime** (hianime.at) | built-in | sub + dub, subs extracted; Cloudflare bypass via curl-impersonate TLS (ani-cli v5 port) |
| 🌌 **AllAnime** (api.allanime.day) | built-in | sub + dub, wixmp/fast4speed links, AES-CTR payload decoding (ani-cli v4 port) |
| 🍉 **GogoAnime** | built-in | AES-extractor for encrypt-ajax streams (animdl port); domain via `GOGO_BASE` |
| 🐾 **AnimePahe** (animepahe.si) | built-in | Kwik embed + JS packer unpacker (otaku-watcher port) |
| 🌐 **Animetsu** | built-in | original core |
| 📺 **AniWatch** (aniwatchtv.to) | built-in | original core |
| 🛰️ **Consumet / Aniwatch-API** | optional | self-hosted REST APIs — one-line env config, containers in compose profile |

Switch sources in `/manage` → **Switch source**. Search results are tagged with
their source; episode downloads flow through the same N_m3u8DL-RE + upload
pipeline with per-provider referers.

- **Search & download** — send an anime name or an episode URL, pick quality, get the file
- **Multi-quality** — 360p / 720p / 1080p via `N_m3u8DL-RE` + ffmpeg
- **Batch & season downloads** — grab a whole range of episodes in one tap
- **Airing tracker** — auto-downloads new ongoing episodes on an IST schedule
- **MongoDB-backed** — users, admins, bans, force-sub, favorites, channel mapping

### 📥 Leech engine
- **Upload to Telegram** — video / audio / document / photo, auto-split at 2 GB
- **Mirror to Google Drive** — optional, token-based
- **Auto-rename templates** — `{season} {episode} {quality} {audio} {title}` placeholders
- **Thumbnails, zip/unzip with passwords, prefix/suffix, captions styles**
- **Auto-screenshots** after upload, watermark support
- **RSS auto-download** — add a feed, get new items automatically
- **yt-dlp cookies** support (upload `cookies.txt` to the bot)
- **Torrents & magnets** via libtorrent/aria2 with tracker auto-refresh
- **Queue, per-task progress bars, cancel, speed caps**

### 🧩 One bot, one process
Both cores share a single Telegram session. Command menus, callbacks and
message routing are de-conflicted so `/start`, search, leech and settings all
live together cleanly.

### 🎨 Rich modern UI (Bot API 10.3)
Powered by [richgram](https://github.com/Badmunda05/richgram):
- **Native rich messages** — headings, key/value tables, expandable `<details>`
  sections and brand footers render natively in updated clients
- **Styled buttons** — primary / success / danger / link styles on menus
- **Live progress panels** — Unicode progress bar + speed/ETA/size table +
  system stats, updated in place during every task
- **Automatic fallback** — any client or path that can't render rich gets a
  clean classic-HTML version of the same panel

---

## 📋 Commands (highlights)

| Command | What it does |
| :--- | :--- |
| `/start` · `/help` | Welcome + full help menu |
| *(send anime name)* | Search anime |
| *(send anime/episode URL)* | Open episode / series download |
| `/ongoing` · `/schedule` | Today's airing schedule |
| `/manage` | Anime bot settings (admin) |
| `/autodel` | Auto-delete timer for posted files (admin) |
| `t.me-link` · MediaFire · PixelDrain · Gofile · Terabox · Mega · … | Send any supported link → leech menu |
| `/tupload <link>` | Leech a link to Telegram |
| `/ytupload <url>` | Download via yt-dlp |
| `/glupload <url>` | Download an image gallery |
| `/settings` | Leech settings panel |
| `/queue` · `/status` · `/cancel` · `/cancel_all` | Queue control |
| `/sysstats` | CPU / RAM / disk / network |
| `/autorename` · `/setname` · `/format` · `/speed` | Naming & quality options |
| `/rss_add` … | RSS auto-download |
| `/stats` · `/users` · `/admins` · `/broadcast` | Anime-bot admin tools |
| `/ping` · `/restart` · `/logs` · `/update` | Maintenance |

<details>
<summary><b>All BotFather commands (copy-paste)</b></summary>

```text
start - Start the bot
help - Help and features
favorites - View favourite anime (Admin)
ongoing - Today's anime schedule
autodel - Set auto-delete timer (Admin)
manage - Anime bot settings (Admin)
stats - Anime bot statistics (Admin)
maplist - View anime mappings (Admin)
setmap - Set anime mapping (Admin)
unmap - Remove anime mapping (Admin)
admins - View bot administrators (Admin)
users - View total users (Admin)
tupload - Leech a link to Telegram
gdupload - Mirror to Google Drive
drupload - Upload a local directory
ytupload - Download with yt-dlp
glupload - Download image galleries
formats - List formats for a URL
preview - Preview a gallery (dry run)
settings - Leech settings menu
setname - Set custom filename
autorename - Auto-rename template
alias - Create command alias
aliases - List command aliases
unalias - Remove command alias
format - Set yt-dlp quality
speed - Set bandwidth limit
queue - View download queue
cancel - Cancel current leech task
cancel_all - Cancel & clear queue
sysstats - System statistics
status - Active leech task + queue
screenshot - Screenshot tool
rss_add - Add RSS auto-download feed
rss_list - List RSS feeds
rss_remove - Remove RSS feed
rss_check - Check RSS feeds now
ping - Check bot latency
restart - Restart the bot (Admin)
broadcast - Broadcast a message (Admin)
```
</details>

---

## ⚙️ Configuration

Copy `.env.example` → `.env` and fill in:

| Variable | Required | Description |
| :--- | :---: | :--- |
| `API_ID` / `API_HASH` | ✅ | From [my.telegram.org](https://my.telegram.org) |
| `BOT_TOKEN` | ✅ | From [@BotFather](https://t.me/BotFather) |
| `OWNER_ID` | ✅ | Your numeric Telegram user ID |
| `MONGO_URL` | ✅ | MongoDB connection string |
| `DUMP_ID` | ➖ | Chat for leech uploads (falls back to request chat) |
| `SUPPORT_CONTACT` | ➖ | Support link shown in the UI |
| `TARGET_CHAT_ID` / `MAIN_CHANNEL` / `LOG_CHANNEL` | ➖ | Anime posting channels |
| `FORMAT` / `CAPTION` | ➖ | Filename & caption templates |
| `ALLOWED_USERS` | ➖ | Extra leech users (default: owner only) |
| `GOGO_BASE` | ➖ | GogoAnime domain override (rotates often) |
| `ANIMEDL_CONSUMET_URL` | ➖ | Self-hosted Consumet API → adds the source |
| `ANIMEDL_ANIWATCH_URL` | ➖ | Self-hosted Aniwatch API → adds the source |
| `DEFAULT_UPLOAD_MODE` | ➖ | `media` or `document` |

All variables are documented inline in `.env.example`.

---

## 🚀 Deployment

### Docker (recommended)
```bash
cp .env.example .env    # edit values
docker compose up -d
```

### VPS / Linux
```bash
sudo apt install -y python3-pip ffmpeg aria2 p7zip-full unrar-free unzip
pip install -r requirements.txt
bash run.sh
```

Once running:
- `GET /health` on port **8080** — health/uptime JSON
- `GET /dashboard` on port **8081** — leech dashboard (token printed in logs)

### Heroku
Deploy as-is — `Procfile`, `Aptfile` and `runtime.txt` are included.

### Windows
```bash
pip install -r requirements.txt
python scripts/fetch_binary.py   # fetch N_m3u8DL-RE.exe
python main.py
```

---

## ⚠️ Disclaimer

This project is for **educational purposes** only. You are responsible for
complying with the laws and platform terms of your jurisdiction and for the
content you download and distribute. The authors assume no liability for
misuse.

---

## 📄 License & attribution

- Anime downloader core: **GPL-3.0** — see [`LICENSE`](LICENSE)
- Leech engine: based on LeechBot, released under the **MIT License** —
  see [`LICENSES/LeechBot-LICENSE`](LICENSES/LeechBot-LICENSE)
- [`N_m3u8DL-RE`](https://github.com/nilaoda/N_m3u8DL-RE) binary is bundled
  for convenience; all rights remain with its authors.

See [`NOTICE.md`](NOTICE.md) for details.
