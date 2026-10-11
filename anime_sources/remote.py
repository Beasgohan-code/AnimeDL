# ============================================================================
#  AnimeDL — Remote API sources (self-hosted)
# ============================================================================
#  Adapters for the popular self-hosted anime REST APIs. Point the bot at a
#  running instance via environment variables and the source appears in the
#  /manage source cycle automatically:
#
#    ANIMEDL_CONSUMET_URL   — Consumet-compatible API   (e.g. http://consumet:4000)
#    ANIMEDL_ANIWATCH_URL   — Aniwatch-API (hianime)    (e.g. http://aniwatch:3000)
#
#  docker-compose.yml ships a "remote-sources" profile that runs both.
# ============================================================================

import os
import re
from urllib.parse import quote

import requests

from anime_sources.base import (
    BaseProvider, Episode, ResolvedEpisode, SearchResult, SourceError, DEFAULT_UA,
)


class ConsumetSource(BaseProvider):
    """Consumet-compatible API adapter (provider: gogoanime)."""
    id = "consumet"
    name = "Consumet"

    @property
    def base(self):
        return os.getenv("ANIMEDL_CONSUMET_URL", "").rstrip("/")

    @property
    def enabled(self):
        return bool(self.base)

    def _get(self, path: str, params: dict = None) -> dict:
        resp = requests.get(f"{self.base}{path}", params=params,
                            headers={"User-Agent": DEFAULT_UA}, timeout=15)
        if resp.status_code != 200:
            raise SourceError(f"Consumet: HTTP {resp.status_code}")
        return resp.json()

    def search(self, query: str) -> list:
        data = self._get(f"/anime/gogoanime/{quote(query)}")
        results = []
        for item in (data.get("results") or [])[:10]:
            results.append(SearchResult(
                id=item.get("id", ""),
                title=item.get("title", "Unknown"),
                provider=self.id,
                type=(item.get("subOrDub") or item.get("type") or "TV"),
            ))
        return results

    def episodes(self, anime_id: str) -> list:
        info = self._get("/anime/gogoanime/info", params={"id": anime_id})
        eps = []
        for ep in info.get("episodes") or []:
            ep_id = ep.get("id", "")
            m = re.search(r"-episode-([0-9.]+)", ep_id)
            eps.append(Episode(
                number=str(ep.get("number", m.group(1) if m else len(eps) + 1)),
                url=f"consumet://gogoanime/{ep_id}",
            ))
        return eps

    def resolve(self, url: str, mode: str = "sub") -> ResolvedEpisode:
        m = re.match(r"consumet://gogoanime/(.+)$", url)
        if not m:
            raise SourceError("Consumet: bad episode reference")
        streams = []
        data = self._get(f"/anime/gogoanime/watch/{m.group(1)}")
        for src in data.get("sources") or []:
            headers = data.get("headers") or {}
            streams.append({
                "quality": re.sub(r"\D", "", str(src.get("quality", ""))) or "auto",
                "url": src.get("url", ""),
                "headers": {"Referer": headers.get("Referer", "")} if headers else {},
            })
        if not streams:
            raise SourceError("Consumet: no sources returned")
        return ResolvedEpisode(
            title=data.get("title") or m.group(1).rsplit("-episode-", 1)[0],
            ep_num=m.group(1).rsplit("-episode-", 1)[-1],
            streams=streams,
        )


class AniwatchApiSource(BaseProvider):
    """Aniwatch-API (hianime REST) adapter."""
    id = "aniwatchapi"
    name = "Aniwatch API"

    @property
    def base(self):
        return os.getenv("ANIMEDL_ANIWATCH_URL", "").rstrip("/")

    @property
    def enabled(self):
        return bool(self.base)

    def _get(self, path: str, params: dict = None) -> dict:
        resp = requests.get(f"{self.base}{path}", params=params,
                            headers={"User-Agent": DEFAULT_UA}, timeout=15)
        if resp.status_code != 200:
            raise SourceError(f"Aniwatch API: HTTP {resp.status_code}")
        payload = resp.json()
        if payload.get("success") is False:
            raise SourceError("Aniwatch API error")
        return payload

    def search(self, query: str) -> list:
        data = self._get("/api/v2/hianime/search", params={"q": query, "page": 1})
        results = []
        for item in ((data.get("data") or {}).get("animes") or [])[:10]:
            results.append(SearchResult(
                id=item.get("id", ""),
                title=item.get("name") or item.get("jname") or "Unknown",
                provider=self.id,
                type=item.get("type") or "TV",
            ))
        return results

    def episodes(self, anime_id: str) -> list:
        data = self._get(f"/api/v2/hianime/anime/{anime_id}/episodes")
        eps = []
        for ep in ((data.get("data") or {}).get("episodes") or []):
            eps.append(Episode(
                number=str(ep.get("number", "")),
                url=f"aniwatchapi://{anime_id}/{ep.get('episodeId', '')}",
                title=ep.get("title", "") or "",
                data_id=str(ep.get("episodeId", "")),
            ))
        return eps

    def resolve(self, url: str, mode: str = "sub") -> ResolvedEpisode:
        m = re.match(r"aniwatchapi://([^/]+)/(.+)$", url)
        if not m:
            raise SourceError("Aniwatch API: bad episode reference")
        anime_id, episode_id = m.group(1), m.group(2)
        data = self._get(
            "/api/v2/hianime/anime/episode-srcs",
            params={"animeEpisodeId": episode_id, "server": "hd-1", "category": mode},
        )
        sources = (data.get("data") or {}).get("sources") or []
        streams = []
        for src in sources:
            streams.append({
                "quality": re.sub(r"\D", "", str(src.get("quality", ""))) or "auto",
                "url": src.get("url", ""),
                "headers": {"Referer": "https://hianime.at/"},
            })
        if not streams:
            raise SourceError("Aniwatch API: no sources returned")
        info = (data.get("data") or {})
        return ResolvedEpisode(
            title=anime_id.rsplit("-", 1)[0].replace("-", " ").title(),
            ep_num=episode_id.split("ep=")[-1] if "ep=" in episode_id else episode_id,
            streams=streams,
            subtitles=[s.get("url") for s in (info.get("subtitles") or []) if s.get("url")],
        )
