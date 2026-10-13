# ============================================================================
#  AnimeDL Manga Engine — providers registry
# ============================================================================
#  Providers: MangaDex (official API — primary), Comick (JSON API + NEXT_DATA
#  page parse; ported from Manhwa-Bot, hardened), Asura Scans (asuracomic.net;
#  ported from Manga-Bot/Manhwa-Bot, hardened). All user-facing branding is
#  AnimeDL's own; the reference bots were used as technical documentation.
# ============================================================================

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class MangaError(Exception):
    pass


class MangaSearchResult:
    def __init__(self, provider: str, id: str, title: str, cover: str = "",
                 url: str = "", extra: str = ""):
        self.provider = provider
        self.id = id              # opaque provider-side handle
        self.title = title
        self.cover = cover
        self.url = url
        self.extra = extra        # "type/status/…" line for the buttons


class MangaChapter:
    def __init__(self, id: str, number: str, title: str = "", url: str = "",
                 lang: str = "en", pages_hint: int = 0):
        self.id = id
        self.number = number      # string — "104.5" is legal
        self.title = title
        self.url = url
        self.lang = lang
        self.pages_hint = pages_hint


def get_provider(pid: str):
    # 18+ gate first (public bot): manhwaclan exists in BOTH layers;
    # manga18fx / manhwa18 are first-party only.
    nsfw_only = pid in ("manhwaclan", "manga18fx", "manhwa18")
    if nsfw_only:
        from manga_sources.nsfw import nsfw_enabled
        if not nsfw_enabled():
            raise MangaError(f"provider {pid} is 18+ locked (env off)")
    # vendored scrapers FIRST (sources/scrapers — the primary layer);
    # first-party code below is the fallback / covers what the repo doesn't.
    if pid in _EXTERNAL_IDS:
        try:
            from manga_sources.external import EXTERNAL_PROVIDERS
            return EXTERNAL_PROVIDERS[pid]()
        except Exception as e:            # noqa: BLE001 — first-party fallback
            logger.warning("external %s failed, falling back: %s", pid, e)
            if pid == "manhwaclan":
                from manga_sources import nsfw as _nsfw
                return _nsfw.NSFW_PROVIDERS[pid]()
    if pid == "mangadex":
        from manga_sources.mangadex import MangaDexProvider
        return MangaDexProvider()
    if pid == "comick":
        from manga_sources.comick import ComickProvider
        return ComickProvider()
    if pid == "asura":
        from manga_sources.asura import AsuraProvider
        return AsuraProvider()
    if pid == "weebcentral":
        from manga_sources.weebcentral import WeebCentralProvider
        return WeebCentralProvider()
    if pid == "mgeko":
        from manga_sources.mgeko import MgekoProvider
        return MgekoProvider()
    if pid == "manhuafast":
        from manga_sources.wpmanga import ManhuaFastProvider
        return ManhuaFastProvider()
    if pid == "manhuaplus":
        from manga_sources.wpmanga import ManhuaPlusProvider
        return ManhuaPlusProvider()
    if pid == "templetoons":
        from manga_sources.wpmanga import TempleToonsProvider
        return TempleToonsProvider()
    if pid == "mangakakalot":
        from manga_sources.more import MangaKakalotProvider
        return MangaKakalotProvider()
    if pid == "mangasee":
        from manga_sources.more import MangaseeProvider
        return MangaseeProvider()
    if pid == "mangabuddy":
        from manga_sources.more import MangabuddyProvider
        return MangabuddyProvider()
    if pid == "ninemanga":
        from manga_sources.more import NinemangaProvider
        return NinemangaProvider()
    if nsfw_only:
        from manga_sources import nsfw as _nsfw
        return _nsfw.NSFW_PROVIDERS[pid]()
    raise MangaError(f"unknown manga provider {pid}")


PROVIDER_NAMES = {
    "mangadex": "MangaDex",
    "comick": "Comick",
    "asura": "Asura Scans",
    "weebcentral": "WeebCentral",
    "mgeko": "Mgeko",
    "manhuafast": "ManhuaFast",
    "manhuaplus": "ManhuaPlus",
    "templetoons": "TempleToons",
    "manhwaclan": "ManhwaClan",
    "manga18fx": "Manga18FX",
    "manhwa18": "Manhwa18",
    "mangakakalot": "MangaKakalot",
    "mangasee": "MangaSee",
    "mangabuddy": "Mangabuddy",
    "ninemanga": "NineManga",
}

# 18+ provider ids (searched/downloaded only when the operator enabled them
# via env AND the requesting user holds premium)
NSFW_IDS = ("manhwaclan", "manga18fx", "manhwa18")

# ── external (vendored sources/scrapers) registry ──────────────────────
# class name in sources/scrapers → (provider id, display name)
_EXTERNAL_MAP = {
    "AllMangaWebs": ("allmanga", "AllManga"),
    "AquaReaderWebs": ("aquareader", "AquaReader"),
    "AtsumaruWebs": ("atsumaru", "Atsumaru"),
    "BatotoWebs": ("batoto", "Bato.to"),
    "DemonicScansWebs": ("demonicscans", "DemonicScans"),
    "FlameComicsWebs": ("flamecomics", "FlameComics"),
    "HiveToonsWebs": ("hivetoons", "HiveToons"),
    "KaliScansWebs": ("kaliscans", "KaliScans"),
    "KingofShojoWebs": ("kingofshojo", "KingofShojo"),
    "LikeMangaWebs": ("likemanga", "LikeManga"),
    "LunatoonsWebs": ("lunatoons", "Lunatoons"),
    "MangaBallWebs": ("mangaball", "MangaBall"),
    "MangaCloudWebs": ("mangacloud", "MangaCloud"),
    "ManhaDNAWebs": ("mangadna", "MangaDNA"),
    "MangaKatanaWebs": ("mangakatana", "MangaKatana"),
    "MangaMobWebs": ("mangamob", "MangaMob"),
    "MangaParkWebs": ("mangapark", "MangaPark"),
    "ManhuaPlusComWebs": ("manhuapluscom", "ManhuaPlus.com"),
    "ManhuaTopWebs": ("manhuatop", "ManhuaTop"),
    "ManhuaUSWebs": ("manhuaus", "ManhuaUS"),
    "ManhwaTopWebs": ("manhwatop", "ManhwaTop"),
    "ResetScansWebs": ("resetscans", "ResetScans"),
    "TaaddWebs": ("taadd", "Taadd"),
    "ThunderScansWebs": ("thunderscans", "ThunderScans"),
    "VortexScansWebs": ("vortexscans", "VortexScans"),
    "AsuraScansWebs": ("asura", "Asura Scans"),
    "ComickWebs": ("comick", "Comick"),
    "WeebCentralWebs": ("weebcentral", "WeebCentral"),
    "MgekoWebs": ("mgeko", "Mgeko"),
    "ManhuaFastWebs": ("manhuafast", "ManhuaFast"),
    "ManhuaplusWebs": ("manhuaplus", "ManhuaPlus"),
    "TempleToonsWebs": ("templetoons", "TempleToons"),
    "MangaBuddyWebs": ("mangabuddy", "Mangabuddy"),
    "MangaKakalotGGWebs": ("mangakakalot", "MangaKakalot"),
    "ManhwaClanWebs": ("manhwaclan", "ManhwaClan"),
}
_EXTERNAL_IDS = tuple(pid for pid, _ in _EXTERNAL_MAP.values())


def _load_external_names():
    """extend PROVIDER_NAMES with the vendored scrapers (idempotent)."""
    for cls_name, (pid, name) in _EXTERNAL_MAP.items():
        PROVIDER_NAMES.setdefault(pid, name)
    for pid, name in _EXTERNAL_MAP.values():
        CHAPTERS_ARG.setdefault(pid, "url")



# default /manga search order — the repo's 34 SFW scrapers lead, backed by
# first-party MangaDex (official API — not in the repo) + MangaSee/NineManga.
# 18+ (manhwaclan · manga18fx · manhwa18) is appended only when enabled.
SEARCH_ORDER = (
    # vendored scrapers (sources/scrapers — MIT, see sources/README.md)
    "batoto", "mangapark", "flamecomics", "weebcentral", "comick",
    "asura", "mangakakalot", "mangabuddy", "mangakatana", "mangamob",
    "mangaball", "mangacloud", "mangadna", "likemanga", "lunatoons",
    "atsumaru", "aquareader", "allmanga", "mgeko", "manhuafast",
    "manhuaplus", "manhuapluscom", "manhuatop", "manhuaus", "manhwatop",
    "templetoons",
    "hivetoons", "kaliscans", "kingofshojo", "demonicscans", "resetscans",
    "thunderscans", "vortexscans", "taadd",
    # first-party (official API / repo doesn't cover them)
    "mangadex", "mangasee", "ninemanga",
)


def _search_order(nsfw: bool = False) -> tuple:
    from manga_sources.nsfw import nsfw_enabled
    if nsfw and nsfw_enabled():
        return SEARCH_ORDER + tuple(NSFW_IDS)
    return SEARCH_ORDER


# what each provider's chapters() takes: the search result's id or url
CHAPTERS_ARG = {
    "mangadex": "id",
    "comick": "id",
    "asura": "url",
    "weebcentral": "url",
    "mgeko": "url",
    "manhuafast": "url",
    "manhuaplus": "id",     # id carries the resolved series url
    "templetoons": "url",
    "mangakakalot": "url",
    "mangasee": "url",
    "mangabuddy": "url",
    "ninemanga": "url",
    "manhwaclan": "url",
    "manga18fx": "url",
    "manhwa18": "url",
}


# TTL cache for provider searches (same query twice → instant, fewer hits
# on the sources). Controlled by MANGA_CACHE_TTL (seconds, 0 disables).
import time as _time
_SEARCH_CACHE = {}


def _cache_ttl() -> int:
    import os
    try:
        return max(0, int(os.getenv("MANGA_CACHE_TTL", "600") or "600"))
    except ValueError:
        return 600


def search_all(query: str, per_provider: int = 6, nsfw: bool = False,
               providers: tuple = None) -> tuple:
    """Search providers IN PARALLEL (8 workers); returns (results, tried)
    where tried is [(provider_id, n_or_error)] for the UI health chips.
    nsfw=True additionally queries the 18+ sources (env-gated too).
    providers=None → the default order (or every source when the operator
    sets ANIMEDL_MANGA_SEARCH_ALL=1)."""
    import os
    from concurrent.futures import ThreadPoolExecutor

    pids = tuple(providers) if providers else _search_order(nsfw)
    results, tried = [], []

    ttl = _cache_ttl()
    qkey = query.strip().lower()

    def _one(pid):
        key = (pid, qkey)
        if ttl:
            hit = _SEARCH_CACHE.get(key)
            if hit and _time.time() - hit[0] < ttl:
                return pid, len(hit[1]), list(hit[1])
        try:
            prov = get_provider(pid)
            found = prov.search(query)[:per_provider]
            if ttl and found:
                _SEARCH_CACHE[key] = (_time.time(), list(found))
            return pid, len(found), found
        except Exception as e:  # noqa: BLE001 — one dead source ≠ dead search
            logger.info("manga search on %s failed: %s", pid, e)
            return pid, f"{type(e).__name__}: {str(e)[:60]}", []

    order = {pid: i for i, pid in enumerate(pids)}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for pid, outcome, found in pool.map(_one, pids):
            tried.append((pid, outcome))
            results.extend(found)
    tried.sort(key=lambda t: order.get(t[0], 999))
    return results, tried


def build_output(image_paths: list, fmt: str, out_base: Path, progress=None):
    """fmt: 'pdf' | 'cbz' → Path of the finished file."""
    out_base = Path(out_base)
    if fmt == "pdf":
        return images_to_pdf(image_paths, out_base.with_suffix(".pdf"), progress)
    return images_to_cbz(image_paths, out_base.with_suffix(".cbz"), progress)


from manga_sources.base import (  # noqa: E402,F401
    fetch_images, images_to_cbz, images_to_pdf, sanitize,
)

_load_external_names()  # noqa: E402 — needs CHAPTERS_ARG above
