# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
#  /nyaasearch — Nyaa torrent search → one-tap leech
#
#  Season packs / full-quality archives live on Nyaa; the leech engine
#  (aria2) already eats magnets. This command searches nyaa.si's RSS feed,
#  lists the best-seeded torrents and hands the picked magnet straight to
#  the normal upload-type flow ("normal" = raw file upload).
#
#  Owner-only: torrents are heavy (disk + bandwidth).
# =============================================================================

import html as _html
import logging
import os
import re
import xml.etree.ElementTree as ET
from html import unescape

import requests
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from leechbot import app, OWNER
from leechbot.utility.variables import BOT
import uikit

logger = logging.getLogger(__name__)

NYAA_BASE = os.getenv("ANIMEDL_NYAA_BASE", "https://nyaa.si").rstrip("/")
_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://exodus.desync.com:6969/announce",
]

# user_id -> list of dicts {title, magnet, size, seeders, view_url}
NYAA_RESULTS = {}

_NYAA_NS = {"nyaa": "https://nyaa.si/xmlns/nyaa"}


def _magnet(infohash: str, title: str) -> str:
    qs = "&".join(f"tr={t}" for t in _TRACKERS)
    return f"magnet:?xt=urn:btih:{infohash}&dn={_html.escape(title)}&{qs}"


def search_nyaa(query: str, limit: int = 8) -> list:
    """Search nyaa.si (RSS) sorted by seeders; returns parsed entries."""
    resp = requests.get(
        f"{NYAA_BASE}/",
        params={"page": "rss", "q": query, "f": "0", "c": "0_0",
                "s": "seeders", "o": "desc"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"nyaa: HTTP {resp.status_code}")

    root = ET.fromstring(resp.content)
    out = []
    for item in root.iter("item"):
        title = unescape((item.findtext("title") or "Unknown")[:110])
        infohash = (item.findtext("nyaa:infoHash", namespaces=_NYAA_NS) or "").strip()
        size = item.findtext("nyaa:size", namespaces=_NYAA_NS) or "?"
        seeders = item.findtext("nyaa:seeders", namespaces=_NYAA_NS) or "0"
        link = item.findtext("link") or ""
        if not infohash:
            continue
        out.append({
            "title": title,
            "magnet": _magnet(infohash, title),
            "size": size,
            "seeders": int(seeders) if seeders.isdigit() else 0,
            "view_url": link,
        })
        if len(out) >= limit:
            break
    return out


def _panel(entries: list) -> str:
    rows = [
        (f"🌱 {e['seeders']} · 💾 {e['size']}", uikit.code(e["title"][:70]))
        for e in entries
    ]
    body = uikit.kv(rows) if rows else uikit.note("No torrents found.")
    return uikit.panel("🧲 Nyaa — season packs & raws", body, level=3)


def _sanitize(name: str) -> str:
    return re.sub(r"[^\w\s.\-()\[\]]", "", name).strip()[:120] or "nyaa_download"


# =============================================================================
# /nyaasearch <query>
# =============================================================================
@app.on_message(filters.command(["nyaasearch", "nyaa"]) & filters.private)
async def nyaa_search_command(client, message):
    if message.chat.id != OWNER:
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        msg = await message.reply_text(
            "<b>⚠️ Usage:</b> <code>/nyaasearch &lt;query&gt;</code>\n\n"
            "Example: <code>/nyaasearch Frieren 1080p</code>",
        )
        return

    query = parts[1].strip()
    status = await message.reply_text(f"🧲 Searching Nyaa for <code>{_html.escape(query)}</code>…")

    import asyncio as _aio

    try:
        entries = await _aio.to_thread(search_nyaa, query)
    except Exception as e:
        await status.edit_text(f"❌ Nyaa search failed: <code>{_html.escape(str(e))}</code>")
        return

    if not entries:
        await status.edit_text("❌ No torrents found for that query.")
        return

    NYAA_RESULTS[message.chat.id] = entries
    buttons = []
    for i, e in enumerate(entries):
        label = f"🧲 {e['title'][:44]}  ·  {e['size']}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"nya_{i}")])
    buttons.append([InlineKeyboardButton("🔒 Close", callback_data="close")])

    import html as _h2
    await status.edit_text(
        f"<blockquote>🧲 <b>Nyaa results for:</b> {_h2.escape(query)}</blockquote>\n\n"
        + _panel(entries)
        + "<i>Tap a torrent to leech it through the engine.</i>",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =============================================================================
# nya_{i} — leech the picked torrent
# =============================================================================
@app.on_callback_query(filters.regex(r"^nya_(\d+)$"))
async def on_nyaa_pick(client, callback_query):
    if callback_query.from_user.id != OWNER:
        return await callback_query.answer("Owner only.", show_alert=True)

    idx = int(callback_query.data.split("_")[1])
    entries = NYAA_RESULTS.get(callback_query.message.chat.id) or []
    if idx >= len(entries):
        return await callback_query.answer("❌ Results expired — search again.", show_alert=True)

    picked = entries[idx]
    if BOT.State.task_going:
        return await callback_query.answer("⚠️ A task is already running.", show_alert=True)

    # Feed the leech engine exactly like a pasted magnet + custom name,
    # then reuse the standard upload-type flow ("normal" = upload as-is).
    BOT.SOURCE = [picked["magnet"]]
    BOT.Options.custom_name = _sanitize(picked["title"])
    try:
        from leechbot.callbacks.upload import _handle_upload_type
        await callback_query.answer("🧲 Queued for leech…")
        await _handle_upload_type(client, callback_query, "normal")
    except Exception as e:
        logger.error("nyaa leech dispatch failed: %s", e)
        try:
            await callback_query.answer(f"❌ {e}", show_alert=True)
        except Exception:
            pass
