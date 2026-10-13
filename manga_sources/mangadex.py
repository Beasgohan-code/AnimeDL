# ============================================================================
#  MangaDex provider — the OFFICIAL public API (api.mangadex.org).
#  No scraping, no Cloudflare: the most server-reliable manga source that
#  exists. Covers manga + manhwa + manhua in dozens of languages.
#    search    GET /manga?title=…&includes[]=cover_art
#    chapters  GET /manga/{id}/feed?translatedLanguage[]=en&order[chapter]=desc
#    pages     GET /at-home/server/{chapterId} → baseUrl/data/{hash}/{page}
# ============================================================================

import logging

from manga_sources import MangaChapter, MangaError, MangaSearchResult
from manga_sources.base import http_json

logger = logging.getLogger(__name__)

API = "https://api.mangadex.org"


class MangaDexProvider:
    id = "mangadex"

    def _parse(self, item: dict) -> MangaSearchResult:
        attrs = item.get("attributes") or {}
        title = (
            (attrs.get("title") or {}).get("en")
            or ((attrs.get("altTitles") or [{}])[0].values() and
                list((attrs.get("altTitles") or [{}])[0].values())[0])
            or "Unknown"
        )
        cover = ""
        for rel in item.get("relationships") or []:
            if rel.get("type") == "cover_art":
                fname = (rel.get("attributes") or {}).get("fileName")
                if fname:
                    cover = (f"https://uploads.mangadex.org/covers/"
                             f"{item['id']}/{fname}.256.jpg")
                break
        tags = [t["attributes"]["name"]["en"]
                for t in (attrs.get("tags") or [])[:3] if t.get("attributes")]
        return MangaSearchResult(
            provider=self.id,
            id=item["id"],
            title=title,
            cover=cover,
            url=f"https://mangadex.org/title/{item['id']}",
            extra=" · ".join(tags) or
                  (attrs.get("status") or "").replace("_", " "),
        )

    def search(self, query: str) -> list:
        data = http_json(
            f"{API}/manga",
            # acceptable ratings only — the bot ships to public channels
            params={
                "title": query,
                "limit": 10,
                "includes[]": "cover_art",
                "contentRating[]": ["safe", "suggestive"],
                "order[relevance]": "desc",
            },
        )
        return [self._parse(item) for item in data.get("data") or []]

    def random_sfw(self) -> MangaSearchResult:
        """One random SFW series — powers /mrandom (dice feature)."""
        data = http_json(
            f"{API}/random-manga",
            params={
                "includes[]": "cover_art",
                "contentRating[]": ["safe", "suggestive"],
            },
        )
        item = (data or {}).get("data") or {}
        if not item.get("id"):
            raise MangaError("MangaDex: random returned nothing")
        return self._parse(item)

    def info(self, query: str) -> dict:
        """Details card for /minfo — title/status/year/tags/description."""
        data = http_json(
            f"{API}/manga",
            params={
                "title": query,
                "limit": 1,
                "includes[]": "cover_art",
                "contentRating[]": ["safe", "suggestive"],
            },
        )
        items = data.get("data") or []
        if not items:
            raise MangaError("MangaDex: no match for info lookup")
        item = items[0]
        res = self._parse(item)
        attrs = item.get("attributes") or {}
        desc = (attrs.get("description") or {}).get("en") or ""
        return {
            "result": res,
            "status": (attrs.get("status") or "?").replace("_", " "),
            "year": attrs.get("year") or "?",
            "description": desc,
            "tags": [t["attributes"]["name"]["en"]
                     for t in (attrs.get("tags") or [])[:6]
                     if t.get("attributes")],
        }

    def chapters(self, manga_id: str, lang: str = "en") -> list:
        """Newest-first chapter feed (up to 500; enough for a tap flow)."""
        chapters, offset = [], 0
        while True:
            data = http_json(
                f"{API}/manga/{manga_id}/feed",
                params={
                    "translatedLanguage[]": lang,
                    "limit": 500,
                    "offset": offset,
                    "order[chapter]": "desc",
                    "contentRating[]": ["safe", "suggestive", "erotica"],
                    "includeExternalUrl": "0",
                },
            )
            batch = data.get("data") or []
            if not batch:
                break
            for item in batch:
                attrs = item.get("attributes") or {}
                pages = attrs.get("pages") or 0
                if not pages:
                    continue   # external chapters have no at-home images
                num = attrs.get("chapter") or "0"
                chapters.append(MangaChapter(
                    id=item["id"],
                    number=num,
                    title=attrs.get("title") or "",
                    lang=lang,
                    pages_hint=pages,
                ))
            offset += len(batch)
            if offset >= (data.get("total") or 0) or offset >= 500:
                break
        return chapters

    def images(self, chapter: MangaChapter) -> tuple:
        data = http_json(f"{API}/at-home/server/{chapter.id}")
        base = (data or {}).get("baseUrl")
        ch = (data or {}).get("chapter") or {}
        quality = "data" if ch.get("data") else "dataSaver"
        files = ch.get(quality) or []
        if not base or not files:
            raise MangaError("MangaDex: at-home returned no pages")
        host = "data-saver" if quality == "dataSaver" else "data"
        urls = [f"{base}/{host}/{ch['hash']}/{f}" for f in files]
        return urls, "https://mangadex.org/"
