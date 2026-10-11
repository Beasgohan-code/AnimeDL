# ============================================================================
#  WeebCentral provider — weebcentral.com (large general manga/manhwa source).
#  Ported from Manhwa-Bot (Webs/weebcentral.py), hardened: chapter numbers
#  regexed from the listing text, image filter excludes brand art.
#    search    POST /search/simple?location=main (form: text=…)
#    chapters  series url → …/full-chapter-list (a.hover:bg-base-300)
#    pages     chapter url + /images?…=long_strip → img[src*=manga]
# ============================================================================

import logging
import re
from urllib.parse import quote, urljoin

from manga_sources import MangaChapter, MangaError, MangaSearchResult
from manga_sources.base import http_get, http_post

logger = logging.getLogger(__name__)

BASE = "https://weebcentral.com"
_HEADERS = {
    "Referer": BASE + "/",
    "HX-Request": "true",
}


class WeebCentralProvider:
    id = "weebcentral"

    def search(self, query: str) -> list:
        """The reference bot HTMX-POSTs /search/simple with form field
        `text` (GET there -> 405); older GET variants kept as fallbacks."""
        q = quote(query)
        resp, errors = None, []
        try:
            resp = http_post(f"{BASE}/search/simple?location=main",
                             data={"text": query}, headers=_HEADERS)
        except Exception as e:
            errors.append(type(e).__name__)
        if resp is None:
            for u in (f"{BASE}/search/simple?location=main&text={q}",
                      f"{BASE}/search/data?text={q}"):
                try:
                    resp = http_get(u, headers=_HEADERS)
                    break
                except Exception as e:  # noqa: BLE001 - try next endpoint
                    errors.append(type(e).__name__)
        if resp is None:
            raise MangaError("WeebCentral: search failed ("
                             + ", ".join(errors[:3]) + ")")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        out, seen = [], set()
        for card in soup.find_all("a", href=re.compile(r"https://weebcentral\.com/series/")):
            href = card.get("href", "")
            if href in seen:
                continue
            seen.add(href)
            img = card.find("img")
            title_divs = card.find_all("div")
            title = (title_divs[-1].get_text(strip=True) if title_divs
                     else (img.get("alt") if img else "")) or "Unknown"
            out.append(MangaSearchResult(
                provider=self.id,
                id=href,
                title=title,
                cover=(img.get("src") or "") if img else "",
                url=href,
            ))
            if len(out) >= 8:
                break
        return out

    def chapters(self, series_url: str, lang: str = "en") -> list:
        m = re.search(r"^(https://weebcentral\.com/series/[^/]+)", series_url)
        if not m:
            raise MangaError("WeebCentral: bad series url")
        list_url = m.group(1) + "/full-chapter-list"
        resp = http_get(list_url, headers=_HEADERS)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        out, seen = [], set()
        for a in soup.find_all("a", href=re.compile(r"/chapters/")):
            href = a.get("href", "")
            if href in seen:
                continue
            seen.add(href)
            span = a.find("span")
            text = span.get_text(strip=True) if span else a.get_text(" ", strip=True)
            num_m = re.search(r"(\d+(?:\.\d+)?)", text or "")
            if not num_m:
                continue
            out.append(MangaChapter(
                id=href,
                number=num_m.group(1),
                title=text if text.lower() != f"chapter {num_m.group(1)}" else "",
                url=href,
            ))
        if not out:
            raise MangaError("WeebCentral: no chapters parsed")
        return out

    def images(self, chapter: MangaChapter) -> tuple:
        url = chapter.url.rstrip("/") + (
            "/images?is_prev=False&current_page=1&reading_style=long_strip")
        resp = http_get(url, headers=_HEADERS)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        urls = []
        for img in soup.find_all("img"):
            src = img.get("src") or ""
            if "manga" in src and src.startswith("http"):
                urls.append(src)
        if not urls:
            raise MangaError("WeebCentral: no page images found")
        return urls, BASE + "/"
