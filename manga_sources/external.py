# ============================================================================
#  AnimeDL — external provider adapter (drives the vendored sources/ scrapers)
# ============================================================================
#  The 35 MIT-licensed scrapers in `sources/scrapers/` (vendored from
#  github.com/KunalG932/auto-manga-chapter-update-bot) share one async
#  interface:
#     search(query)         -> [dict(title, poster, url, …)]
#     get_chapters(data)    -> data + data["chapters"]
#     iter_chapters(data)   -> [dict(title, url, …)]
#     get_pictures(chap)    -> [image_url, …]
#  This adapter bridges that async dict-world onto AnimeDL's sync
#  MangaSearchResult / MangaChapter / images() contract — so every one of
#  those sites instantly works in /manga, /msearch and the tracker.
# ============================================================================

import asyncio
import logging
import re

from manga_sources import MangaChapter, MangaError, MangaSearchResult

logger = logging.getLogger(__name__)

_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")


def _num(text) -> str:
    m = _NUM_RE.search(str(text or ""))
    return m.group(1) if m else ""


class ExternalProvider:
    """One vendored scraper, adapted to the AnimeDL provider contract."""

    def __init__(self, scraper_cls, pid: str, name: str):
        self._cls = scraper_cls
        self.id = pid
        self._name = name
        self._inst = None
        self._series_cache = {}     # series url -> their search-result dict
        self._chapter_cache = {}    # chapter url -> their chapter dict

    # ── plumbing ─────────────────────────────────────────────
    @property
    def inst(self):
        if self._inst is None:
            try:
                self._inst = self._cls()
            except Exception as e:  # noqa: BLE001
                raise MangaError(f"{self._name}: scraper init failed ({e})")
        return self._inst

    @staticmethod
    def _run(coro):
        """Providers are called from worker threads (run_in_executor) —
        spin a fresh loop there for the scraper's async methods."""
        return asyncio.run(coro)

    # ── AnimeDL contract ─────────────────────────────────────
    def search(self, query: str) -> list:
        items = self._run(self.inst.search(query)) or []
        out = []
        for it in items[:8]:
            url = it.get("url") or ""
            if not url:
                continue
            self._series_cache[url] = it
            out.append(MangaSearchResult(
                provider=self.id,
                id=url,                       # url is the stable handle
                title=(it.get("title") or url)[:60],
                cover=it.get("poster") or it.get("image") or "",
                url=url,
            ))
        if not out:
            raise MangaError(f"{self._name}: no results parsed")
        return out

    def chapters(self, series_url: str, lang: str = "en") -> list:
        data = self._series_cache.get(series_url) or {
            "title": series_url.rsplit("/", 1)[-1] or series_url,
            "url": series_url,
        }
        data = self._run(self.inst.get_chapters(data))
        chapters_raw = (data or {}).get("chapters") or []
        if hasattr(self.inst, "iter_chapters"):
            try:
                chapters_raw = self.inst.iter_chapters(data) or chapters_raw
            except Exception:              # noqa: BLE001 — fall back to raw
                pass
        out, seen = [], set()
        for ch in chapters_raw:
            curl = ch.get("url") or ""
            key = curl or f"{series_url}#{len(out)}"
            if key in seen:
                continue
            seen.add(key)
            num = (_num(ch.get("chapter")) if ch.get("chapter")
                   else _num(ch.get("title")))
            if not num:
                continue
            if curl:
                self._chapter_cache[curl] = ch
            out.append(MangaChapter(
                id=curl or key,
                number=num,
                title=(ch.get("title") or "")[:40],
                url=curl,
            ))
        if not out:
            raise MangaError(f"{self._name}: no chapters parsed")
        return out

    def images(self, chapter: MangaChapter) -> tuple:
        data = self._chapter_cache.get(chapter.id) or {"url": chapter.id}
        pics = self._run(self.inst.get_pictures(data, chapter.id)) or []
        urls = [p for p in pics if str(p).startswith("http")]
        if not urls:
            raise MangaError(f"{self._name}: no page images found")
        base = ""
        try:
            base = self.inst.url + "/" if getattr(self.inst, "url", "") else ""
        except Exception:                  # noqa: BLE001 — cosmetic referer
            base = ""
        return urls, base

# ── auto-discovery: every vendored scraper becomes a provider ──────────────
import importlib

_EXTERNAL_CLASSES = {
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
    # sites we also had first-party code for — the vendored scrapers are now
    # the PRIMARY drivers (first-party versions remain as fallback):
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

# module name per provider id (== id except where their file name differs)
_MODULE_FOR = {pid: pid for pid, _ in _EXTERNAL_CLASSES.values()}
_MODULE_FOR["asura"] = "asurascans"          # sources/scrapers/asurascans.py


def _make_provider(scraper_cls, pid, name):
    class _ExternalP(ExternalProvider):
        def __init__(self):
            super().__init__(scraper_cls, pid, name)
    _ExternalP.__name__ = "External_" + pid
    return _ExternalP


EXTERNAL_PROVIDERS = {}
for _cls_name, (_pid, _name) in _EXTERNAL_CLASSES.items():
    try:
        _mod = importlib.import_module(
            "sources.scrapers." + _MODULE_FOR[_pid])
        EXTERNAL_PROVIDERS[_pid] = _make_provider(
            getattr(_mod, _cls_name), _pid, _name)
    except Exception as _e:  # noqa: BLE001 — one bad scraper ≠ dead registry
        logger.warning("external scraper %s unavailable: %s", _pid, _e)
