# ============================================================================
#  AnimeDL — Multi-source anime engine (base types & registry)
# ============================================================================
#  Providers ported from actively-maintained open-source scrapers:
#    • hianime    — hianime.at        (port of pystardust/ani-cli v5.1.5, GPL-3)
#    • allanime   — api.allanime.day  (port of pystardust/ani-cli v4.13, GPL-3)
#    • gogo       — GogoAnime         (port of justfoolingaround/animdl, GPL-3)
#    • animepahe  — animepahe.si      (port of GDjkhp/otaku-watcher-contrib, WTFPL)
#    • remote     — self-hosted REST APIs (Consumet / Aniwatch-API), env-configured
#
#  All providers speak the same tiny interface so the Telegram layer can
#  treat them uniformly.
# ============================================================================

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class SearchResult:
    id: str                    # provider-local anime id (slug / hex id / session)
    title: str
    provider: str
    type: str = "TV"           # display hint e.g. TV / Movie / episodes count


@dataclass
class Episode:
    number: str                # canonical episode number ("1", "2.5", …)
    url: str                   # provider URL scheme understood by resolve()
    title: str = ""
    data_id: str = ""          # provider-local episode data id (optional)


@dataclass
class Stream:
    url: str
    quality: str = "auto"      # "1080", "720", … or "auto"
    audio: str = "sub"         # "sub" (JP + subs) or "dub"
    headers: dict = field(default_factory=dict)


@dataclass
class ResolvedEpisode:
    title: str                 # anime title
    ep_num: str
    season: str = "1"
    streams: list = field(default_factory=list)   # list[Stream]
    subtitles: list = field(default_factory=list) # list[str] (vtt urls)


class SourceError(Exception):
    """Raised when a provider fails; the bot surfaces the message to the user."""


# ---------------------------------------------------------------------------
# Base provider
# ---------------------------------------------------------------------------
class BaseProvider:
    """Interface every source provider implements (all methods synchronous —
    the downloader runs in a worker thread)."""

    id: str = "base"
    name: str = "Base"
    enabled: bool = True

    def search(self, query: str) -> list:
        raise NotImplementedError

    def episodes(self, anime_id: str) -> list:
        raise NotImplementedError

    def resolve(self, url: str) -> ResolvedEpisode:
        """Turn an episode URL (this provider's scheme) into streams."""
        raise NotImplementedError

    # -- helpers ------------------------------------------------------------
    def _http(self, impersonate: str = None, **kw):
        """curl_cffi session (TLS-fingerprint impersonation when specified)."""
        from curl_cffi import requests as c_requests
        session = c_requests.Session()
        if impersonate:
            session.impersonate = impersonate
        return session


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def get_provider(provider_id: str) -> BaseProvider:
    """Instantiate a provider by id (lazy import keeps startup fast)."""
    if provider_id == "hianime":
        from anime_sources.hianime import HianimeSource
        return HianimeSource()
    if provider_id == "allanime":
        from anime_sources.allanime import AllAnimeSource
        return AllAnimeSource()
    if provider_id == "gogo":
        from anime_sources.gogo import GogoSource
        return GogoSource()
    if provider_id == "animepahe":
        from anime_sources.animepahe import AnimePaheSource
        return AnimePaheSource()
    if provider_id in ("consumet", "aniwatchapi"):
        from anime_sources.remote import RemoteSource
        return RemoteSource(provider_id)
    raise SourceError(f"Unknown source provider: {provider_id}")


# Sources available in the /manage source cycle (order matters).
# Legacy sources ("animetsu", "aniwatch") are handled by the original scrapers.
SOURCE_CYCLE = ["animetsu", "aniwatch", "hianime", "allanime", "gogo", "animepahe"]

SOURCE_NAMES = {
    "animetsu": "🌐 Animetsu",
    "aniwatch": "📺 AniWatch",
    "hianime": "⚡ Hianime",
    "allanime": "🌌 AllAnime",
    "gogo": "🍉 GogoAnime",
    "animepahe": "🐾 AnimePahe",
    "consumet": "🛰️ Consumet",
    "aniwatchapi": "🛰️ Aniwatch API",
}


def is_provider_url(url: str) -> bool:
    """True when an episode URL belongs to one of the new providers
    (used to route downloads through the multi-source engine)."""
    u = (url or "").lower()
    return (
        u.startswith(("allanime://", "animepahe://", "consumet://", "aniwatchapi://"))
        or "hianime.at/" in u
        or "gogoanime" in u
        or "animepahe" in u
    )


def provider_id_for_url(url: str) -> str:
    u = (url or "").lower()
    if u.startswith("allanime://") or "allanime" in u:
        return "allanime"
    if u.startswith("animepahe://") or "animepahe" in u:
        return "animepahe"
    if u.startswith("consumet://"):
        return "consumet"
    if u.startswith("aniwatchapi://"):
        return "aniwatchapi"
    if "hianime.at/" in u:
        return "hianime"
    if "gogoanime" in u:
        return "gogo"
    raise SourceError(f"No provider handles URL: {url}")
