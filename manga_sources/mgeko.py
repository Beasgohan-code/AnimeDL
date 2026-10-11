# ============================================================================
#  Mgeko provider — mgeko.cc (manhwa aggregator).
#  Ported from Manhwa-Bot (Webs/mgeko.py), hardened: numbers regexed from
#  chapter hrefs, image list deduped.
#    search    GET /autocomplete?term=…  (li cards)
#    chapters  series url + all-chapters/ → #chpagedlist li a
#    pages     chapter url → div#chapter-reader img
# ============================================================================

import logging
import re
from urllib.parse import quote_plus, urljoin

from manga_sources import MangaChapter, MangaError, MangaSearchResult
from manga_sources.base import http_get

logger = logging.getLogger(__name__)

BASE = "https://www.mgeko.cc"


class MgekoProvider:
    id = "mgeko"

    def search(self, query: str) -> list:
        resp = http_get(f"{BASE}/autocomplete?term={quote_plus(query)}")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        out, seen = [], set()
        for card in soup.find_all("li"):
            a = card.find("a", href=True)
            if not a or not a.get("href", "").startswith("http"):
                continue
            href = a["href"]
            if href in seen:
                continue
            seen.add(href)
            title = a.get("title") or a.get_text(strip=True) or "Unknown"
            img = card.find("img")
            out.append(MangaSearchResult(
                provider=self.id,
                id=href,
                title=title.strip(),
                cover=(img.get("src") or "") if img else "",
                url=href,
            ))
            if len(out) >= 8:
                break
        return out

    def chapters(self, series_url: str, lang: str = "en") -> list:
        resp = http_get(series_url.rstrip("/") + "/all-chapters/")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        ul = soup.find("div", {"id": "chpagedlist"}) or soup
        out, seen = [], set()
        for a in ul.find_all("a", href=True):
            href = a["href"]
            if href in seen:
                continue
            seen.add(href)
            num_m = (re.search(r"chapter[-_](\d+(?:\.\d+)?)", href)
                     or re.search(r"chapter[-_](\d+(?:\.\d+)?)", a.get("title", "")))
            if not num_m:
                continue
            out.append(MangaChapter(
                id=href,
                number=num_m.group(1),
                title="",
                url=urljoin(BASE + "/", href),
            ))
        if not out:
            raise MangaError("Mgeko: no chapters parsed")
        return out

    def images(self, chapter: MangaChapter) -> tuple:
        resp = http_get(chapter.url)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        reader = soup.find("div", {"id": "chapter-reader"}) or soup
        urls, seen = [], set()
        for img in reader.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if src.startswith("http") and src not in seen:
                seen.add(src)
                urls.append(src)
        if not urls:
            raise MangaError("Mgeko: no page images found")
        return urls, BASE + "/"
