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
        out = []
        for item in data.get("data") or []:
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
            out.append(MangaSearchResult(
                provider=self.id,
                id=item["id"],
                title=title,
                cover=cover,
                url=f"https://mangadex.org/title/{item['id']}",
                extra=" · ".join(tags) or
                      (attrs.get("status") or "").replace("_", " "),
            ))
        return out

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
