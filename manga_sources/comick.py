# ============================================================================
#  Comick provider — JSON API + NEXT_DATA page parse.
#  Ported from Manhwa-Bot (Webs/comick.py) and hardened: api host fallback
#  (.fun → .cc), junk-tolerant parsers, sync requests (the bot runs workers,
#  not an asyncio scraper stack).
#    search    GET api.comick.fun/v1.0/search/?type=comic&q=…
#    chapters  GET api.comick.fun/comic/{hid}/chapters?lang=en
#    pages     chapter page __NEXT_DATA__ → md_images[].b2key → meo.comick.pictures
# ============================================================================

import json
import logging
import re

from manga_sources import MangaChapter, MangaError, MangaSearchResult
from manga_sources.base import http_get, http_json

logger = logging.getLogger(__name__)

APIS = ("https://api.comick.fun", "https://api.comick.cc")
HEADERS = {
    "Accept": "application/json",
    "Referer": "https://comick.cc/",
}


class ComickProvider:
    id = "comick"

    def _api_get(self, path: str, params: dict = None):
        last = None
        for api in APIS:
            try:
                return http_json(f"{api}{path}", headers=HEADERS)
            except Exception as e:  # noqa: BLE001
                last = e
        raise MangaError(f"Comick: API unreachable ({last})")

    def search(self, query: str) -> list:
        data = self._api_get("/v1.0/search/", params={
            "type": "comic", "page": 1, "limit": 8, "q": query, "t": "false"})
        out = []
        for m in data or []:
            try:
                cover = ""
                covers = m.get("md_covers") or []
                if covers and covers[0].get("b2key"):
                    cover = f"https://meo.comick.pictures/{covers[0]['b2key']}"
                out.append(MangaSearchResult(
                    provider=self.id,
                    id=m.get("slug") or "",
                    title=m.get("title") or "Unknown",
                    cover=cover,
                    url=f"https://comick.io/comic/{m.get('slug')}",
                    extra=(m.get("status") or "").replace("_", " ") or
                          f"{m.get('last_chapter') or '?'} ch",
                ))
            except Exception:  # noqa: BLE001 — junk entry
                continue
        return out

    def _hid(self, slug: str) -> str:
        data = self._api_get(f"/comic/{slug}", params={"lang": "en", "tachiyomi": "false"})
        hid = ((data or {}).get("comic") or {}).get("hid")
        if not hid:
            raise MangaError("Comick: comic hid not found")
        return hid

    def chapters(self, slug: str, lang: str = "en") -> list:
        hid = self._hid(slug)
        out, seen = [], set()
        page = 1
        while page <= 3:   # 3 × 50 = 150 chapters — plenty for a tap flow
            data = self._api_get(
                f"/comic/{hid}/chapters", params={"lang": lang, "page": page})
            batch = (data or {}).get("chapters") or []
            if not batch:
                break
            for ch in batch:
                num = str(ch.get("chap") or "").strip()
                cid = ch.get("hid") or ""
                if not num or cid in seen:
                    continue
                seen.add(cid)
                title = ch.get("title") or ""
                out.append(MangaChapter(
                    id=cid,
                    number=num,
                    title=title,
                    lang=lang,
                ))
            page += 1
        return out

    def images(self, chapter: MangaChapter) -> tuple:
        # the chapter "url" is comick.io's page; NEXT_DATA carries the images
        page_url = (f"https://comick.io/comic/__/chapter/__")
        url = chapter.url or page_url
        resp = http_get(url, headers={
            "User-Agent": ("Mozilla/5.0 (Linux; Android 6.0; Nexus 5) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/113.0.0.0 Mobile Safari/537.36"),
        })
        m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                      resp.text, re.S)
        if not m:
            raise MangaError("Comick: __NEXT_DATA__ missing on chapter page")
        con = json.loads(m.group(1).strip())
        imgs = (((con.get("props") or {}).get("pageProps") or {})
                .get("chapter") or {}).get("md_images") or []
        urls = [f"https://meo.comick.pictures/{i['b2key']}"
                for i in imgs if isinstance(i, dict) and i.get("b2key")]
        if not urls:
            raise MangaError("Comick: no md_images on chapter page")
        return urls, "https://comick.io/"
