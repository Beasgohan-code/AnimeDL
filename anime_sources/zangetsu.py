# ============================================================================
#  AnimeDL — Zangetsu source (zangetsu.cc)
# ============================================================================
#  Python port of ryanwtf7/hianime-api (MIT) — the zangetsu.cc service layer:
#
#    search    → /search?keyword=…  (hianime-template HTML)
#    bootstrap → /home HTML yields window.AJAX_TOKEN + session cookies;
#                all AJAX calls need X-Page-Token + Cookie + XHR headers
#    episodes  → /ajax/episodes?animeId=<numeric id>   (JSON)
#    servers   → /ajax/server?episodeId=…&sub=1&dub=0  (JSON)
#    embeds    → cdn.4animo.xyz /embed/hd-1|hd-2/…  and flixera.co /embed/ani/…
#                resolved via the MegaCloud getSources extractor
#                (anime_sources/megacloud.py — AES rotating key + megaplay
#                fallback, both ported from ewgsta/weeb-cli)
#
#  This is the aniwatchtv-family successor network — a fully independent
#  fallback source from the hianime/allanime/gogo stacks.
# ============================================================================

import html as html_mod
import os
import re
from urllib.parse import quote_plus

import requests

from anime_sources.base import (
    http_session, tls_get,
    BaseProvider, Episode, ResolvedEpisode, SearchResult, SourceError,
    Stream, DEFAULT_UA,
)
from anime_sources.megacloud import get_megacloud_stream

BASE = os.getenv("ZANGETSU_BASE", "https://zangetsu.cc").rstrip("/")
EMBED_CDN = "https://cdn.4animo.xyz"
FLIXERA = "https://flixera.co"

_TOKEN_RE = re.compile(r'window\.AJAX_TOKEN\s*=\s*"([^"]+)"')

_session_cache = {"token": None, "cookie": None, "at": 0.0}
_TTL = 1800  # 30 min


def _fetch(url: str, headers: dict = None):
    """Chrome-TLS fetch — zangetsu.cc is Cloudflare-fronted and 403s/challenges
    plain datacenter python-requests (this exact gap kept it at 0 results)."""
    return tls_get(url, headers=headers, timeout=(6, 20))


def _bootstrap(force: bool = False):
    """GET /home to obtain the AJAX page token + session cookies."""
    import time as _t
    if not force and _session_cache["token"] and _t.time() - _session_cache["at"] < _TTL:
        return _session_cache

    resp = _fetch(
        f"{BASE}/home",
        headers={"User-Agent": DEFAULT_UA,
                 "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                 "Referer": f"{BASE}/home"},
    )

    m = _TOKEN_RE.search(resp.text)
    if not m:
        raise SourceError("Zangetsu: bootstrap found no AJAX token")

    cookie = "; ".join(
        f"{c.split('=', 1)[0].strip()}={c.split('=', 1)[1].split(';')[0].strip()}"
        for c in resp.headers.get("Set-Cookie", "").split(", ")
        if "=" in c
    )
    _session_cache.update(token=m.group(1), cookie=cookie, at=_t.time())
    return _session_cache


class ZangetsuSource(BaseProvider):
    id = "zangetsu"
    name = "Zangetsu"

    # ------------------------------------------------------------------ ajax
    def _ajax(self, path: str, referer: str = "/home") -> dict:
        sess = _bootstrap()
        resp = _fetch(
            f"{BASE}{path}",
            headers={
                "User-Agent": DEFAULT_UA,
                "Accept": "application/json",
                "Referer": f"{BASE}{referer}",
                "X-Requested-With": "XMLHttpRequest",
                "X-Page-Token": sess["token"],
                **({"Cookie": sess["cookie"]} if sess["cookie"] else {}),
            },
        )
        if resp.status_code in (401, 403):
            # token/cookie expired → re-bootstrap once
            sess = _bootstrap(force=True)
            resp = _fetch(
                f"{BASE}{path}",
                headers={
                    "User-Agent": DEFAULT_UA,
                    "Accept": "application/json",
                    "Referer": f"{BASE}{referer}",
                    "X-Requested-With": "XMLHttpRequest",
                    "X-Page-Token": sess["token"],
                    **({"Cookie": sess["cookie"]} if sess["cookie"] else {}),
                },
            )
        if resp.status_code != 200:
            raise SourceError(f"Zangetsu: HTTP {resp.status_code}")
        return resp.json()

    # ---------------------------------------------------------------- search
    def search(self, query: str) -> list:
        # /search now sits behind the same AJAX_TOKEN cookie as the API —
        # without bootstrap the page 200s but yields zero results
        try:
            self._bootstrap()
        except Exception:
            pass
        page = _fetch(
            f"{BASE}/search?keyword={quote_plus(query)}",
            headers={"User-Agent": DEFAULT_UA, "Referer": f"{BASE}/home"},
        ).text.split('id="main-sidebar"')[0]
        page = page.replace("\n", " ").split('<div class="film-detail">')

        results = []
        for chunk in page[1:]:
            m = re.search(
                r'<h3 class="film-name">\s*<a href="[^"]*/([^"/]+)"\s+title="([^"]+)"',
                chunk,
            )
            if m:
                results.append(SearchResult(
                    id=m.group(1),
                    title=html_mod.unescape(m.group(2)),
                    provider=self.id,
                ))
            if len(results) >= 10:
                break
        return results

    # -------------------------------------------------------------- episodes
    def episodes(self, anime_id: str) -> list:
        from anime_sources.base import cached_episodes
        return cached_episodes(f"zangetsu:{anime_id}", self._fetch_episodes, anime_id)

    def _fetch_episodes(self, anime_id: str) -> list:
        numeric = anime_id.rsplit("-", 1)[-1]
        data = self._ajax(f"/ajax/episodes?animeId={numeric}")
        eps = data if isinstance(data, list) else data.get("episodes") or data.get("html") and []
        if not eps:
            return []
        out = []
        for ep in eps:
            num = ep.get("number") or ep.get("id") or ""
            ep_id = str(ep.get("id") or ep.get("embed_id") or "")
            ani_id = str(ep.get("ani") or "")
            if not ep_id:
                continue
            out.append(Episode(
                number=str(num),
                url=f"zangetsu://{anime_id}::{ep_id}::{ani_id or '-'}",
                title=(ep.get("titles") or {}).get("en") or ep.get("title") or f"Episode {num}",
                data_id=ep_id,
            ))
        try:
            out.sort(key=lambda e: float(e.number))
        except (ValueError, TypeError):
            pass
        return out

    # --------------------------------------------------------------- servers
    def _build_embed(self, server_name: str, ep_id: str, mode: str, ani_id: str) -> str:
        if server_name == "s-2":
            return f"{EMBED_CDN}/embed/hd-1/{ep_id}/{mode}?k=1&autoPlay=0&skipIntro=0&skipOutro=0"
        if server_name == "s-3":
            base = (f"{EMBED_CDN}/embed/hd-2/ani/{ani_id}/{mode}" if ani_id
                    else f"{EMBED_CDN}/embed/hd-2/{ep_id}/{mode}")
            return f"{base}?k=1&autoPlay=0&skipIntro=0&skipOutro=0"
        base = (f"{FLIXERA}/embed/ani/{ani_id}/{mode}" if ani_id
                else f"{FLIXERA}/embed/ani/{ep_id}/{mode}")
        return f"{base}?autoplay=0&skipintro=0&skipoutro=0"

    # ---------------------------------------------------------------- resolve
    def resolve(self, url: str, mode: str = "sub") -> ResolvedEpisode:
        m = re.match(r"zangetsu://([^:]+)::([^:]+)::(.+)", url)
        if not m:
            raise SourceError("Zangetsu: could not parse episode URL")
        slug, ep_id, ani_id = m.group(1), m.group(2), (m.group(3) if m.group(3) != "-" else "")

        sub = 1 if mode == "sub" else 0
        dub = 0 if mode == "sub" else 1
        payload = self._ajax(f"/ajax/server?episodeId={ep_id}&sub={sub}&dub={dub}")
        servers = (payload.get("dub") if mode == "dub" else payload.get("sub")) \
            or payload.get("sub") or payload.get("dub") or []
        if not servers:
            raise SourceError("Zangetsu: no servers for this episode")

        title = slug.replace("-", " ").title()
        last_err = None
        for entry in servers:
            name = str(entry.get("serverName") or "")
            embed = self._build_embed(name, ep_id, mode, ani_id)
            try:
                data = get_megacloud_stream(embed, referer=f"{BASE}/", ep_id=ep_id, mode=mode)
            except Exception as e:
                last_err = e
                continue
            if data and data.get("file"):
                subs = [t.get("file") for t in (data.get("tracks") or [])
                        if isinstance(t, dict) and str(t.get("kind")) == "captions" and t.get("file")]
                return ResolvedEpisode(
                    title=title,
                    ep_num=str(entry.get("index") or ""),
                    season="1",
                    streams=[Stream(url=data["file"], quality="auto",
                                    audio=mode,
                                    headers={"Referer": embed.split("/embed/")[0] + "/"})],
                    subtitles=[s for s in subs if isinstance(s, str)],
                )
        raise SourceError(f"Zangetsu: all servers failed ({last_err or 'no streams'})")
