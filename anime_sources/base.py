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
import re
import threading

import requests as _requests
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
# --------------------------------------------------------------------------
#  Episode-listing cache — repeated taps and the mapped-anime watcher re-list
#  the same show constantly; a 2-minute TTL turns those into instant hits.
# --------------------------------------------------------------------------
_EP_CACHE = {}
_EP_CACHE_TTL = 120.0
_STREAM_CACHE = {}
_STREAM_CACHE_TTL = 600.0


def cached_episodes(cache_key: str, fetch, *args):
    """Return cached episode list for cache_key or fetch()+store it."""
    import time as _t
    hit = _EP_CACHE.get(cache_key)
    now = _t.time()
    if hit and now - hit[0] < _EP_CACHE_TTL:
        return list(hit[1])
    val = fetch(*args)
    if not val:  # transient empty listing — don't pin it for the TTL
        return val
    if len(_EP_CACHE) > 256:  # bounded memory: evict oldest entry
        _EP_CACHE.pop(min(_EP_CACHE, key=lambda k: _EP_CACHE[k][0]), None)
    _EP_CACHE[cache_key] = (now, val)
    return val


# ---------------------------------------------------------------------------
#  Shared keep-alive HTTP session — reuses TCP/TLS connections across the
#  whole engine (mirror walks, resolve chains, search). Saves a full
#  handshake (100-500ms) on every request after the first to each host.
# ---------------------------------------------------------------------------
_HTTP_SESSION = None
_HTTP_SESSION_LOCK = threading.Lock()


def http_session():
    """Process-wide requests.Session with a warmed connection pool."""
    global _HTTP_SESSION
    if _HTTP_SESSION is None:
        with _HTTP_SESSION_LOCK:
            if _HTTP_SESSION is None:
                from requests.adapters import HTTPAdapter
                from urllib3.util.retry import Retry
                # Anime hosts sit behind CDNs that close idle keep-alive
                # sockets within ~30-60s. Without retries, the first request
                # after an idle gap died with ConnectionError instead of
                # transparently reconnecting. Retry re-issues on a FRESH
                # connection (and rides out brief 5xx blips).
                _retry = Retry(
                    total=2, connect=2, read=1, status=2,
                    backoff_factor=0.25,
                    status_forcelist=(429, 500, 502, 503, 504),
                    allowed_methods=frozenset(
                        {"GET", "HEAD", "OPTIONS", "POST"}),  # POST = idempotent gql reads
                    raise_on_status=False,
                )
                session = _requests.Session()
                adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20,
                                      max_retries=_retry)
                session.mount("https://", adapter)
                session.mount("http://", adapter)
                session.headers["User-Agent"] = DEFAULT_UA
                _HTTP_SESSION = session
    return _HTTP_SESSION


def cached_streams(cache_key: str, fetch, *args):
    """Cache resolved stream URLs (10 min TTL).

    Empty results are NEVER cached: a transient resolve failure would
    otherwise be pinned for the whole TTL ("poison cache") and every
    quality tap would fail instantly until it expired.
    """
    import time as _t
    hit = _STREAM_CACHE.get(cache_key)
    now = _t.time()
    if hit and now - hit[0] < _STREAM_CACHE_TTL:
        return hit[1]
    val = fetch(*args)
    if not val or (hasattr(val, "streams") and not val.streams):
        return val  # transient empty — retry next tap, cache nothing
    if len(_STREAM_CACHE) > 256:  # keep memory bounded
        oldest = min(_STREAM_CACHE, key=lambda k: _STREAM_CACHE[k][0])
        _STREAM_CACHE.pop(oldest, None)
    _STREAM_CACHE[cache_key] = (now, val)
    return val


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
    if provider_id == "zangetsu":
        from anime_sources.zangetsu import ZangetsuSource
        return ZangetsuSource()
    if provider_id == "tokyoinsider":
        from anime_sources.tokyoinsider import TokyoInsiderSource
        return TokyoInsiderSource()
    if provider_id == "animepahe":
        from anime_sources.animepahe import AnimePaheSource
        return AnimePaheSource()
    if provider_id in ("consumet", "aniwatchapi"):
        from anime_sources.remote import RemoteSource
        return RemoteSource(provider_id)
    raise SourceError(f"Unknown source provider: {provider_id}")


# Sources available in the /manage source cycle (order matters).
# Legacy sources ("animetsu", "aniwatch") are handled by the original scrapers.
SOURCE_CYCLE = ["hianime", "zangetsu", "allanime", "gogo", "tokyoinsider", "animepahe", "animetsu", "aniwatch"]

SOURCE_NAMES = {
    "zangetsu": "🌀 Zangetsu",
    "tokyoinsider": "🎬 TokyoInsider",
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
    (used to route downloads through the multi-source engine).

    Accepts the WHOLE hianime mirror family (hianime.at/.bz/.pe/.to/… and
    aniwatchtv.to — the platform rotates domains), plus zangetsu. A URL from
    any live mirror must route into the engine, not just the primary base.
    """
    u = (url or "").lower()
    return (
        u.startswith(("allanime://", "animepahe://", "consumet://", "aniwatchapi://", "zangetsu://"))
        or "hianime" in u
        or "aniwatchtv" in u
        or "zangetsu" in u
        or "gogoanime" in u
        or "animepahe" in u
    )


def next_episode_url(url: str):
    """Best-effort URL of the NEXT episode for continue-watching.

    Works for episode-numbered URL schemes (hianime, allanime, gogo).
    Returns None for session-based schemes (animepahe) or unparseable URLs.
    """
    if not url:
        return None
    m = re.match(r"allanime://([^/]+)/([0-9.]+)$", url)
    if m:
        try:
            return f"allanime://{m.group(1)}/{int(float(m.group(2))) + 1}"
        except ValueError:
            return None
    m = re.search(r"([?&]ep=)([0-9.]+)$", url)
    if m:
        try:
            return url[:m.start(2)] + str(int(float(m.group(2))) + 1)
        except ValueError:
            return None
    m = re.search(r"-episode-([0-9.]+)$", url)
    if m:
        try:
            return url[:m.start(1)] + str(int(float(m.group(1))) + 1)
        except ValueError:
            return None
    return None


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
    if u.startswith("zangetsu://") or "zangetsu" in u:
        return "zangetsu"
    # aniwatchtv.to runs the SAME platform as hianime (same /api/theme
    # paths) and is in our mirror fleet — legacy-flow URLs must resolve here,
    # not die with "No provider handles URL" (this exact gap made EVERY
    # default-source download fail after the v4.14.0 routing change)
    if "aniwatchtv" in u or "hianime" in u:
        return "hianime"
    if "gogoanime" in u:
        return "gogo"
    raise SourceError(f"No provider handles URL: {url}")
