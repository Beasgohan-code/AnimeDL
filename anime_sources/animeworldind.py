# ============================================================================
#  AnimeDL — AnimeWorld India source (Hindi/Tamil/Telugu anime)
# ============================================================================
#  Full port of AstraeLabs/VibraVid's animeworld service (1239★, pushed
#  2026-10-11): client.py (sessionId cookie + CSRF token bootstrap),
#  scrapper.py (li.episode listings), sweetpixel.py VideoSource
#  (/api/episode/info?id=<token>&alt=0 → {"grabber": "<direct url>"}).
#
#  VibraVid reads the domain from user config; ours is a walked mirror
#  chain — bootstrap only "counts" when a CSRF token is present, so a dead
#  or rebranded mirror falls through automatically (env override first:
#  ANIMEDL_AWI_BASE).
# ============================================================================

import os
import re
import time
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from anime_sources.base import (
    tls_get, SourceError, DEFAULT_UA,
    BaseProvider, Episode, ResolvedEpisode, SearchResult,
)

_MIRRORS = [
    os.getenv("ANIMEDL_AWI_BASE", "").rstrip("/") if os.getenv("ANIMEDL_AWI_BASE") else None,
    "https://animeworldindia.net",
    "https://animeworld-india.com",
    "https://anime-world.in",
]
_BASES = [b for b in _MIRRORS if b]

_TOKEN_RE = re.compile(r'name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', re.I)
_TOKEN_INPUT_RE = re.compile(r'name=["\']_csrf["\'][^>]*value=["\']([^"\']+)["\']', re.I)

_session_cache = {"base": None, "session": None, "csrf": None, "at": 0.0}
_TTL = 1800  # 30 min


def _bootstrap(force: bool = False) -> dict:
    """Walk the mirror chain until one hands out a CSRF token (+sessionId)."""
    now = time.time()
    if not force and _session_cache["csrf"] and now - _session_cache["at"] < _TTL:
        return _session_cache

    last = None
    for base in _BASES:
        try:
            resp = tls_get(f"{base}/", headers={
                "User-Agent": DEFAULT_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })
            html = resp.text
            m = _TOKEN_RE.search(html) or _TOKEN_INPUT_RE.search(html)
            if not m:
                last = SourceError(f"AnimeWorld IN: no csrf token on {base}")
                continue
            # collect sessionId from raw Set-Cookie headers when present
            session = None
            raw_cookies = getattr(resp, "headers", {}).get("Set-Cookie", "") or ""
            sm = re.search(r"sessionId=([^;\s]+)", raw_cookies)
            if sm:
                session = sm.group(1)
            _session_cache.update(base=base, session=session,
                                  csrf=m.group(1), at=now)
            return _session_cache
        except SourceError as e:
            last = e
    raise last or SourceError("AnimeWorld IN: no live mirror")


def _live_base() -> str:
    return _session_cache.get("base") or _BASES[0]


class AnimeWorldIndiaSource(BaseProvider):
    id = "animeworldind"
    name = "AnimeWorld IN"

    def _get(self, url: str, referer: str = None, api: bool = False):
        sess = _bootstrap()
        headers = {
            "User-Agent": DEFAULT_UA,
            "Referer": referer or f"{_live_base()}/",
        }
        if api:
            headers.update({
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": _live_base(),
                "CSRF-Token": sess["csrf"],
                **({"Cookie": f"sessionId={sess['session']}"} if sess["session"] else {}),
            })
        return tls_get(url if url.startswith("http") else _live_base() + url,
                       headers=headers, timeout=(6, 25))

    # ---------------------------------------------------------------- search
    def search(self, query: str) -> list:
        resp = self._get(f"/search?keyword={quote_plus(query)}")
        soup = BeautifulSoup(resp.text, "html.parser")
        out = []
        for a in soup.find_all("a", class_="poster"):
            img = a.find("img")
            title = (img.get("alt") if img else None) or a.get_text(strip=True)
            href = a.get("href") or ""
            m = re.search(r"/anime/([a-z0-9-]+)", href)
            if not m or not title:
                continue
            label = title.strip()
            status = a.find("div", class_="status")
            if status is not None:
                if status.find("div", class_="dub"):
                    label += " (dub)"
                if status.find("div", class_="movie"):
                    label += " · Movie"
            out.append(SearchResult(id=m.group(1), title=label, provider=self.id))
            if len(out) >= 10:
                break
        return out

    # -------------------------------------------------------------- episodes
    def episodes(self, anime_id: str) -> list:
        from anime_sources.base import cached_episodes
        return cached_episodes(f"animeworldind:{anime_id}", self._fetch_episodes, anime_id)

    def _fetch_episodes(self, slug: str) -> list:
        page = self._get(f"/anime/{slug}").text
        soup = BeautifulSoup(page, "html.parser")
        eps, seen = [], set()
        # NOTE: not soup.select("li.episode > a") — soupsieve 3.0.1 chokes
        # on tag selectors in some builds; find_all is equivalent here.
        for li in soup.find_all("li", class_="episode"):
            a = li.find("a")
            if a is None:
                continue
            num = a.get("data-episode-num") or ""
            ep_id = a.get("data-episode-id") or ""
            token = a.get("data-id") or ""
            if not num or num in seen:
                continue
            seen.add(num)
            eps.append(Episode(
                number=str(num),
                url=f"animeworldind://{slug}/{num}?id={ep_id}&t={token}",
                title=f"Episode {num}",
            ))
        try:
            eps.sort(key=lambda e: float(e.number))
        except ValueError:
            pass
        return eps

    def show_name(self, anime_id: str) -> str:
        """Recovery hook: ids are slugs."""
        return (anime_id or "").replace("-", " ").strip().title()

    # ---------------------------------------------------------------- resolve
    def resolve(self, url: str, mode: str = "sub") -> ResolvedEpisode:
        m = re.match(r"animeworldind://([^/?#]+)/([0-9.]+)", url or "")
        if not m:
            raise SourceError("AnimeWorld IN: could not parse episode reference")
        slug, num = m.group(1), m.group(2)

        token = ""
        ids = re.search(r"[?&]t=([^&]+)", url or "")
        if ids:
            token = ids.group(1)
        if not token:  # recovery came through without the token → re-list
            for ep in self.episodes(slug):
                if ep.number == num:
                    tm = re.search(r"[?&]t=([^&]+)", ep.url)
                    token = tm.group(1) if tm else ""
                    break
        if not token:
            raise SourceError("AnimeWorld IN: no episode token (re-list failed)")

        # sweetpixel.VideoSource.get_playlist: /api/episode/info?id=<token>
        resp = self._get(f"/api/episode/info?id={quote_plus(token)}&alt=0",
                         referer=f"{_live_base()}/anime/{slug}", api=True)
        try:
            data = resp.json()
        except Exception:
            raise SourceError("AnimeWorld IN: episode info returned non-JSON")
        if not isinstance(data, dict) or data.get("error"):
            raise SourceError(f"AnimeWorld IN: episode info error: {str(data)[:60]}")
        grabber = data.get("grabber")
        if not grabber:
            raise SourceError("AnimeWorld IN: no grabber url in response")

        return ResolvedEpisode(
            title=self.show_name(slug),
            ep_num=num,
            streams=[{
                "quality": "auto",
                "url": str(grabber).strip(),
                "audio": "dub",  # AWI is primarily a Hindi-dub library
                "headers": {"Referer": f"{_live_base()}/"},
            }],
        )
