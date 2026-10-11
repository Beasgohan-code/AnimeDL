# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
#  /tosho — AnimeTosho DDL search → one-tap leech
#
#  AnimeTosho (animetosho.org) mirrors every Nyaa torrent AND exposes direct
#  download links from its storage servers via a clean JSON API. Compared to
#  /nyaasearch (torrents via aria2), /tosho hands the leech engine plain
#  HTTPS files — no seeding/wait, works even where UDP trackers are blocked.
#
#  API: https://feed.animetosho.org/json?show=files&q=<query>
#  Owner-only, ANIMEDL_TOSHO_BASE override supported.
# =============================================================================

import html as _html
import logging
import os
import re
from html import unescape

import requests
from bs4 import BeautifulSoup
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from leechbot import app, OWNER
from leechbot.utility.variables import BOT
import uikit

logger = logging.getLogger(__name__)

TOSHO_BASE = os.getenv("ANIMEDL_TOSHO_BASE", "https://feed.animetosho.org").rstrip("/")
TOSHO_SITE = os.getenv("ANIMEDL_TOSHO_SITE", "https://www.animetosho.org").rstrip("/")

# user_id -> list of entries {title, ddl, magnet, size}
TOSHO_RESULTS = {}


def _is_unreachable(e: Exception) -> bool:
    """DNS failure / connection refused (e.g. the host is blocked from
    this server's network)."""
    if isinstance(e, requests.exceptions.ConnectionError):
        text = str(e).lower()
        return "name or service not known" in text or "failed to resolve" in text or "max retries" in text
    return False


def _search_html(query: str, limit: int = 8) -> list:
    """Route B: scrape the website search when the feed host is unreachable.
    DDL/magnet links are resolved later from the per-item view page."""
    resp = requests.get(
        f"{TOSHO_SITE}/search",
        params={"q": query},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"animetosho (html): HTTP {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")
    out = []
    items = soup.find_all("div", class_=["home_list_item", "torrent_info"])
    for item in items[:limit * 2]:
        a = item.find("a", href=True)
        if not a or "/view/" not in a["href"]:
            continue
        title = a.get_text(strip=True)[:110] or "Unknown"
        view = a["href"]
        if view.startswith("/"):
            view = TOSHO_SITE + view
        out.append({"title": title, "ddl": "", "magnet": "", "size": "?", "view_url": view})
        if len(out) >= limit:
            break
    return out


def search_tosho(query: str, limit: int = 8) -> list:
    """Search AnimeTosho: JSON feed first, HTML route on failure.
    Returns parsed entries with DDL+magnet (HTML route defers DDL
    resolution to the view page at pick time)."""
    try:
        return _search_json(query, limit)
    except (requests.exceptions.ConnectionError, RuntimeError) as e:
        if _is_unreachable(e):
            logger.warning("tosho feed host unreachable (%s) — trying HTML route", e)
        elif isinstance(e, requests.exceptions.ConnectionError):
            raise
        return _search_html(query, limit)


def _search_json(query: str, limit: int = 8) -> list:
    resp = requests.get(
        f"{TOSHO_BASE}/json",
        params={"show": "files", "q": query, "nojump": "1"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"animetosho: HTTP {resp.status_code}")

    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError("animetosho: unexpected payload shape")

    out = []
    for item in data:
        title = unescape(str(item.get("title") or "Unknown")[:110])
        files = item.get("files") or []
        ddl = (files[0].get("url") if files and isinstance(files[0], dict) else "") or ""
        total = 0
        for f in files:
            try:
                total += int(f.get("size") or 0)
            except (TypeError, ValueError):
                pass
        size = f"{total / (1 << 30):.2f} GB" if total else "?"
        magnet = item.get("magnet_uri") or ""
        if not ddl and not magnet:
            continue
        out.append({
            "title": title,
            "ddl": ddl,
            "magnet": magnet,
            "size": size,
        })
        if len(out) >= limit:
            break
    return out


def _sanitize(name: str) -> str:
    return re.sub(r"[^\w\s.\-()\[\]]", "", name).strip()[:120] or "tosho_download"


def resolve_tosho_view(view_url: str) -> dict:
    """Pull DDL + magnet off an animetosho /view/ page (HTML route)."""
    resp = requests.get(view_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"animetosho view: HTTP {resp.status_code}")
    soup = BeautifulSoup(resp.text, "html.parser")
    ddl, magnet = "", ""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not ddl and (href.startswith("https://ddl.animetosho.org") or "/file/" in href):
            ddl = href
        if not magnet and href.startswith("magnet:?"):
            magnet = href
        if ddl and magnet:
            break
    return {"ddl": ddl, "magnet": magnet}


# =============================================================================
# /tosho <query>
# =============================================================================
@app.on_message(filters.command("tosho") & filters.private)
async def tosho_search_command(client, message):
    if message.chat.id != OWNER:
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply_text(
            "<b>⚠️ Usage:</b> <code>/tosho &lt;query&gt;</code>\n\n"
            "Example: <code>/tosho Frieren 1080p</code>\n"
            "<i>Direct-download mirror of Nyaa — no torrent client needed.</i>"
        )
        return

    query = parts[1].strip()
    status = await message.reply_text(
        f"📦 Searching AnimeTosho for <code>{_html.escape(query)}</code>…"
    )

    import asyncio as _aio
    try:
        entries = await _aio.to_thread(search_tosho, query)
    except requests.exceptions.ConnectionError as e:
        if _is_unreachable(e):
            await status.edit_text(
                "❌ AnimeTosho is unreachable from this server's network.\n"
                "💡 Try <code>/nyaasearch " + _html.escape(query) + "</code> — the torrent route uses a different host."
            )
            return
        await status.edit_text(f"❌ AnimeTosho search failed: <code>{_html.escape(str(e))}</code>")
        return
    except Exception as e:
        await status.edit_text(f"❌ AnimeTosho search failed: <code>{_html.escape(str(e))}</code>")
        return

    if not entries:
        await status.edit_text("❌ No results for that query.")
        return

    TOSHO_RESULTS[message.chat.id] = entries
    buttons = []
    for i, e in enumerate(entries):
        tag = "🔗 DDL" if e["ddl"] else "🧲 magnet"
        buttons.append([InlineKeyboardButton(
            f"{tag} · {e['title'][:40]} · {e['size']}",
            callback_data=f"tosh_{i}",
        )])
    buttons.append([InlineKeyboardButton("🔒 Close", callback_data="close")])

    import html as _h2
    rows = uikit.kv([
        (e["title"][:48], uikit.code(f"{e['size']} · {'ddl' if e['ddl'] else 'magnet'}"))
        for e in entries
    ])
    await status.edit_text(
        f"<blockquote>📦 <b>AnimeTosho results:</b> {_h2.escape(query)}</blockquote>\n"
        + uikit.panel("📦 DDL mirrors", rows, level=3)
        + "<i>Tap to leech — DDL links stream straight off the storage servers.</i>",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =============================================================================
# tosh_{i} — leech the picked entry
# =============================================================================
@app.on_callback_query(filters.regex(r"^tosh_(\d+)$"))
async def on_tosho_pick(client, callback_query):
    if callback_query.from_user.id != OWNER:
        return await callback_query.answer("Owner only.", show_alert=True)

    idx = int(callback_query.data.split("_")[1])
    entries = TOSHO_RESULTS.get(callback_query.message.chat.id) or []
    if idx >= len(entries):
        return await callback_query.answer("❌ Results expired — search again.", show_alert=True)

    picked = entries[idx]
    if BOT.State.task_going:
        return await callback_query.answer("⚠️ A task is already running.", show_alert=True)

    if not picked["ddl"] and not picked["magnet"] and picked.get("view_url"):
        import asyncio as _aio
        try:
            got = await _aio.to_thread(resolve_tosho_view, picked["view_url"])
            picked.update(got)
        except Exception as e:
            return await callback_query.answer(
                f"❌ Could not fetch the download links: {e}", show_alert=True)
        if not picked["ddl"] and not picked["magnet"]:
            return await callback_query.answer(
                "❌ No DDL/magnet found on that page.", show_alert=True)

    source = picked["ddl"] or picked["magnet"]
    if source.startswith("magnet:"):
        try:
            import libtorrent  # noqa: F401
        except ImportError:
            return await callback_query.answer(
                "Torrent engine not installed on this deployment — "
                "pick a 🔗 DDL entry instead (no torrent needed).",
                show_alert=True,
            )
    BOT.SOURCE = [source]
    BOT.Options.custom_name = _sanitize(picked["title"])
    try:
        from leechbot.callbacks.upload import _handle_upload_type
        await callback_query.answer("📦 Queued for leech…")
        await _handle_upload_type(client, callback_query, "normal")
    except Exception as e:
        logger.error("tosho leech dispatch failed: %s", e)
        try:
            await callback_query.answer(f"❌ {e}", show_alert=True)
        except Exception:
            pass
