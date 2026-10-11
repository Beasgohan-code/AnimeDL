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
    if pid in ("manhwaclan", "manga18fx", "manhwa18"):
        # 18+ sources: only when the operator opts in via env (public bot)
        from manga_sources.nsfw import nsfw_enabled
        if nsfw_enabled():
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

# default search order (SFW sources first; 18+ appended only when enabled)
SEARCH_ORDER = ("mangadex", "comick", "asura", "weebcentral", "mgeko",
                "manhuafast", "manhuaplus", "templetoons",
                "mangakakalot", "mangasee", "mangabuddy", "ninemanga")


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


def search_all(query: str, per_provider: int = 6, nsfw: bool = False) -> tuple:
    """Search every provider; returns (results, tried) where tried is
    [(provider_id, n_or_error)] so the UI can show health per source.
    nsfw=True additionally queries the 18+ sources (env-gated too)."""
    results, tried = [], []
    for pid in _search_order(nsfw):
        try:
            prov = get_provider(pid)
            found = prov.search(query)[:per_provider]
            tried.append((pid, len(found)))
            results.extend(found)
        except Exception as e:  # noqa: BLE001 — one dead source ≠ dead search
            logger.info("manga search on %s failed: %s", pid, e)
            tried.append((pid, f"{type(e).__name__}: {str(e)[:60]}"))
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
