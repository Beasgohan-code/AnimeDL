# ============================================================================
#  AnimeDL — Airing schedule & next-episode countdown
# ============================================================================
#  Python port of pystardust/ani-cli v5.1.5 `time_until_next_ep` (GPL-3.0):
#  queries the animeschedule.net v3 API for a title, then scrapes the anime's
#  page for the next sub/dub episode numbers and their countdown timestamps.
# ============================================================================

import logging
import re
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

API = "https://animeschedule.net/api/v3/anime"
SITE = "https://animeschedule.net"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_SUB_EP_RE = re.compile(
    r'release-time-type-subs"[^>]*><span class="release-time-episode-number">Episode ([0-9]+)</span>'
)
_DUB_EP_RE = re.compile(
    r'release-time-type-dub"[^>]*><span class="release-time-episode-number">Episode ([0-9]+)</span>'
)
_SUB_CD_RE = re.compile(r'class="countdown-time" datetime="([^"]+)"')
_DUB_CD_RE = re.compile(r'class="countdown-time countdown-time-dub" datetime="([^"]+)"')


def _parse_countdown(value: str) -> datetime:
    """Parse the countdown datetime (ISO 8601, usually Z-suffixed)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fmt_countdown(value: str) -> str:
    """Humanize a countdown datetime: '2d 4h 13m' / 'airing now' / '?'."""
    if not value:
        return "?"
    try:
        dt = _parse_countdown(value)
    except (ValueError, TypeError):
        return "?"
    delta = dt - datetime.now(timezone.utc)
    total = int(delta.total_seconds())
    if total <= 0:
        return "airing now"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def lookup(query: str, max_results: int = 3) -> list:
    """Search animeschedule.net and extract next-episode countdowns.

    Returns a list of dicts:
      {title, jpn, status, route,
       next_sub_ep, sub_countdown, next_dub_ep, dub_countdown}
    Countdowns are pre-formatted strings ('2d 4h 13m' / 'airing now' / '?').
    """
    resp = requests.get(
        API, params={"q": query}, headers={"User-Agent": UA}, timeout=15
    )
    if resp.status_code != 200:
        raise RuntimeError(f"animeschedule API: HTTP {resp.status_code}")

    entries = resp.json() or []
    results = []
    for entry in entries[:max_results]:
        route = entry.get("route") or ""
        item = {
            "title": entry.get("english") or entry.get("title") or "Unknown",
            "jpn": entry.get("romaji") or "N/A",
            "status": entry.get("status") or "Unknown",
            "route": route,
            "next_sub_ep": None, "sub_countdown": None,
            "next_dub_ep": None, "dub_countdown": None,
        }
        if item["status"].lower() != "finished" and route:
            try:
                page = requests.get(
                    f"{SITE}/anime/{route}",
                    headers={"User-Agent": UA},
                    timeout=15,
                ).text
                m = _SUB_EP_RE.search(page)
                item["next_sub_ep"] = m.group(1) if m else None
                m = _DUB_EP_RE.search(page)
                item["next_dub_ep"] = m.group(1) if m else None
                m = _SUB_CD_RE.search(page)
                item["sub_countdown"] = fmt_countdown(m.group(1)) if m else None
                m = _DUB_CD_RE.search(page)
                item["dub_countdown"] = fmt_countdown(m.group(1)) if m else None
            except Exception as e:
                logger.debug("countdown page scrape failed for %s: %s", route, e)
        results.append(item)
    return results
