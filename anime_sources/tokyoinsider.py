# ============================================================================
#  AnimeDL — TokyoInsider source (direct-file downloads)
# ============================================================================
#  Python port of GDjkhp/otaku-watcher-contrib (WTFPL) tokyo_insider scraper,
#  adapted to the AnimeDL provider engine:
#    - search via the /anime/list index page (24h in-process cache), fuzzy
#      matched with stdlib difflib (upstream uses thefuzz — no new dependency)
#    - TV episodes parsed from /episode/N links on the anime page; movies
#      fall back to /movie/1
#    - resolve returns the newest direct-file links (quality parsed from the
#      finfo blocks, e.g. "1280x720" → "720p")
#
#  Best-effort provider: tokyoinsider.com serves direct MP4/MKV files, so no
#  m3u8/DRM machinery is involved — download_stream handles it as a plain file.
# ============================================================================

import re
import time
from difflib import SequenceMatcher
from html import escape as _escape
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from anime_sources.base import (
    http_session,
    BaseProvider, Episode, ResolvedEpisode, SearchResult, SourceError,
    Stream, DEFAULT_UA,
)

BASE = "https://www.tokyoinsider.com"

_LIST_TTL = 86400  # 24h
_list_cache = {"at": 0.0, "items": []}

_EP_HREF_RE = re.compile(r'href="([^"]*?/episode/(\d+)(?:\?[^"]*)?)"', re.I)
_SIZE_RE = re.compile(r"([0-9.]+)\s*(MB|GB)", re.I)
_RES_RE = re.compile(r"(\d{3,4})x(\d{3,4})")


def _score(name: str, query: str) -> float:
    """Best of full-string and partial match (upstream used partial ratio)."""
    n, q = name.lower(), query.lower()
    full = SequenceMatcher(None, n, q).ratio()
    m = SequenceMatcher(None, q, n).find_longest_match(0, len(q), 0, len(n))
    partial = m.size / max(1, len(q))
    return max(full, partial)


class TokyoInsiderSource(BaseProvider):
    id = "tokyoinsider"
    name = "TokyoInsider"

    def _get(self, url: str) -> str:
        resp = http_session().get(
            url,
            headers={"User-Agent": DEFAULT_UA, "Referer": BASE + "/"},
            timeout=(6, 20),
        )
        if resp.status_code != 200:
            raise SourceError(f"TokyoInsider: HTTP {resp.status_code}")
        return resp.text

    # ------------------------------------------------------------ index list
    def _anime_list(self) -> list:
        now = time.time()
        if _list_cache["items"] and now - _list_cache["at"] < _LIST_TTL:
            return _list_cache["items"]
        soup = BeautifulSoup(self._get(f"{BASE}/anime/list"), "html.parser")
        items = []
        for div in soup.find_all("div", class_=["c_h2", "c_h2b"]):
            a = div.find("a")
            if a and a.get("href"):
                items.append((a.get_text(strip=True), a["href"]))
        if items:
            _list_cache["at"] = now
            _list_cache["items"] = items
        return items

    # ---------------------------------------------------------------- search
    def search(self, query: str) -> list:
        query = query.strip().lower()
        scored = []
        for name, href in self._anime_list():
            score = _score(name, query)
            if score >= 0.60:
                scored.append((score, name, href))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SearchResult(
                id=href,
                title=name,
                provider=self.id,
                type="TV" if "(tv)" in name.lower() else "Movie",
            )
            for _, name, href in scored[:10]
        ]

    # -------------------------------------------------------------- episodes
    def episodes(self, anime_id: str) -> list:
        if not anime_id.startswith("/"):
            anime_id = "/" + anime_id
        page = self._get(f"{BASE}{anime_id}")
        numbers = sorted({int(m.group(2)) for m in _EP_HREF_RE.finditer(page)})
        if numbers:
            return [
                Episode(number=str(n), url=f"{BASE}{anime_id}/episode/{n}",
                        title=f"Episode {n}")
                for n in numbers
            ]
        # Movie (or listing without per-episode links): single "episode"
        return [Episode(number="1", url=f"{BASE}{anime_id}/movie/1",
                        title="Movie")]

    # --------------------------------------------------------------- resolve
    def resolve(self, anime_id: str, ep_num: str, season: str = "1") -> ResolvedEpisode:
        if not anime_id.startswith("/"):
            anime_id = "/" + anime_id
        if ep_num in ("1", "movie") and "/movie" in anime_id:
            page_url = f"{BASE}{anime_id}/movie/1"
        else:
            page_url = f"{BASE}{anime_id}/episode/{ep_num}"

        soup = BeautifulSoup(self._get(page_url), "html.parser")
        inner = soup.find("div", id="inner_page")
        if not inner:
            raise SourceError("TokyoInsider: page layout changed (#inner_page missing)")

        candidates = []  # (sortkey datetime-str, quality, size, href)
        for div in inner.find_all("div", recursive=False):
            text = str(div)
            if "finfo" not in text:
                continue
            a_tags = div.find_all("a")
            if not a_tags:
                continue
            href = a_tags[-1].get("href") or ""
            if not href:
                continue
            href = urljoin(BASE, href)
            div_text = div.get_text(" ", strip=True)
            m = _RES_RE.search(div_text)
            quality = f"{m.group(2)}p" if m else "auto"
            ms = _SIZE_RE.search(div_text)
            size = f"{ms.group(1)}{ms.group(2)}" if ms else ""
            mdate = re.search(r"(\d{2}/\d{2}/\d{2})", div_text)
            date_key = mdate.group(1) if mdate else "00/00/00"
            candidates.append((date_key, quality, size, href))

        if not candidates:
            raise SourceError("TokyoInsider: no download links on the page")

        # newest links first (upstream sorts by date added, descending)
        candidates.sort(key=lambda x: x[0], reverse=True)
        seen, streams = set(), []
        for _, quality, size, href in candidates[:3]:
            if href in seen:
                continue
            seen.add(href)
            streams.append(Stream(url=href, quality=quality, audio="sub"))

        return ResolvedEpisode(
            title=anime_id.strip("/").split("/")[-1].replace("-", " ").title(),
            ep_num=ep_num,
            season=season,
            streams=streams,
        )
