# ============================================================================
#  ManhuaFast + ManhuaPlus + TempleToons providers (WordPress-manga family).
#  Ported from Manhwa-Bot (Webs/manhuafast.py, Webs/manhuaplus.py,
#  Webs/templetoons.py), hardened.
# ============================================================================

import json
import logging
import re
from urllib.parse import quote_plus

from manga_sources import MangaChapter, MangaError, MangaSearchResult
from manga_sources.base import http_get, http_json

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  ManhuaFast — manhuafast.net (wp-manga)
# ─────────────────────────────────────────────
class ManhuaFastProvider:
    id = "manhuafast"
    BASE = "https://manhuafast.net"

    def search(self, query: str) -> list:
        resp = http_get(
            f"{self.BASE}/?s={quote_plus(query)}&post_type=wp-manga")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        out, seen = [], set()
        for card in soup.select(".c-tabs-item__content"):
            a = card.find("a", href=True)
            if not a:
                continue
            href = a["href"]
            if href in seen:
                continue
            seen.add(href)
            h3 = card.find("h3") or card.find("h4")
            img = card.find("img")
            cover = (img.get("data-src") or img.get("src") or "") if img else ""
            out.append(MangaSearchResult(
                provider=self.id,
                id=href,
                title=(h3.get_text(strip=True) if h3 else "Unknown"),
                cover=cover,
                url=href,
            ))
            if len(out) >= 8:
                break
        return out

    def chapters(self, series_url: str, lang: str = "en") -> list:
        # wp-manga ajax: POST {series}/ajax/chapters/ → chapter-list HTML
        resp = http_get(series_url.rstrip("/") + "/ajax/chapters/")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        out, seen = [], set()
        for a in soup.find_all("a", href=re.compile(r"-chapter-")):
            href = a.get("href", "")
            if href in seen:
                continue
            seen.add(href)
            num_m = re.search(r"chapter-(\d+(?:\.\d+)?)", href)
            if not num_m:
                continue
            out.append(MangaChapter(
                id=href, number=num_m.group(1), title="",
                url=href,
            ))
        if not out:
            raise MangaError("ManhuaFast: no chapters parsed")
        return out

    def images(self, chapter: MangaChapter) -> tuple:
        resp = http_get(chapter.url)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        content = soup.find(class_="reading-content") or soup
        urls, seen = [], set()
        # NOTE: find_all, not .select() — soupsieve 3.0.1 tag selectors
        # crash at runtime in this environment (known trap)
        for img in content.find_all("img"):
            if True:
                pass
            src = (img.get("data-src") or img.get("src") or "").strip()
            src = src.replace("https:///", "https://")
            if src.startswith("http") and src not in seen:
                seen.add(src)
                urls.append(src)
        if not urls:
            raise MangaError("ManhuaFast: no page images found")
        return urls, self.BASE + "/"


# ─────────────────────────────────────────────
#  ManhuaPlus — manhuaplus.org (ajax-driven)
# ─────────────────────────────────────────────
class ManhuaPlusProvider:
    id = "manhuaplus"
    BASE = "https://manhuaplus.org"

    def search(self, query: str) -> list:
        # their ajax search answers a form POST with a json {list: [...]}
        import requests, time
        from manga_sources.base import DEFAULT_HEADERS
        last = None
        for _ in (1, 2):
            try:
                resp = requests.post(
                    f"{self.BASE}/ajax/search",
                    data={"search": query},
                    headers={**DEFAULT_HEADERS, "X-Requested-With": "XMLHttpRequest",
                             "Referer": self.BASE + "/"},
                    timeout=(6, 20))
                if resp.status_code == 200:
                    data = resp.json()
                    break
                last = IOError(f"HTTP {resp.status_code}")
            except Exception as e:  # noqa: BLE001
                last = e
            time.sleep(0.6)
        else:
            raise MangaError(f"ManhuaPlus: search failed ({last})")
        out = []
        for card in (data or {}).get("list") or []:
            slug = card.get("slug") or card.get("url") or ""
            if not slug:
                continue
            url = slug if slug.startswith("http") else f"{self.BASE}/manga/{slug}"
            out.append(MangaSearchResult(
                provider=self.id,
                id=url,
                title=card.get("name") or card.get("title") or "Unknown",
                cover=(card.get("cover") or "") if str(card.get("cover", "")).startswith("http")
                      else (self.BASE + card.get("cover", "") if card.get("cover") else ""),
                url=url,
            ))
            if len(out) >= 8:
                break
        return out

    def chapters(self, series_url: str, lang: str = "en") -> list:
        resp = http_get(series_url)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        con = soup.find(class_="bc-fff s1 r2 p-13") or soup
        out, seen = [], set()
        for a in con.find_all("a", href=True):
            href = a.get("href", "")
            if href in seen or "/chapter" not in href:
                continue
            seen.add(href)
            num_m = re.search(r"chapter-(\d+(?:\.\d+)?)", href)
            if not num_m:
                continue
            out.append(MangaChapter(
                id=href, number=num_m.group(1),
                title=a.get_text(strip=True)[:40],
                url=href if href.startswith("http") else self.BASE + href,
            ))
        if not out:
            raise MangaError("ManhuaPlus: no chapters parsed")
        return out

    def images(self, chapter: MangaChapter) -> tuple:
        resp = http_get(chapter.url)
        m = re.search(r"const\s+CHAPTER_ID\s*=\s*(\d+)", resp.text)
        if not m:
            raise MangaError("ManhuaPlus: CHAPTER_ID not on page")
        import requests
        from manga_sources.base import DEFAULT_HEADERS
        r = requests.get(
            f"{self.BASE}/ajax/image/list/chap/{m.group(1)}",
            headers={**DEFAULT_HEADERS, "Referer": chapter.url},
            timeout=(6, 20))
        if r.status_code != 200:
            raise MangaError(f"ManhuaPlus: image-list HTTP {r.status_code}")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup((r.json() or {}).get("html") or "", "html.parser")
        urls = [img.get("src") for img in soup.find_all("img") if img.get("src")]
        if not urls:
            raise MangaError("ManhuaPlus: no page images found")
        return urls, self.BASE + "/"


# ─────────────────────────────────────────────
#  TempleToons — templetoons.com (api + Next.js reader)
# ─────────────────────────────────────────────
class TempleToonsProvider:
    id = "templetoons"
    BASE = "https://templetoons.com"
    API = "https://api.templetoons.com/api/allComics"

    def search(self, query: str) -> list:
        data = http_json(self.API)
        q = query.lower()
        out = []
        for card in data or []:
            title = card.get("title") or ""
            if q not in title.lower():
                continue
            slug = card.get("series_slug") or ""
            out.append(MangaSearchResult(
                provider=self.id,
                id=slug,
                title=title,
                cover=card.get("thumbnail") or "",
                url=f"{self.BASE}/comic/{slug}",
            ))
            if len(out) >= 8:
                break
        return out

    def chapters(self, series_url: str, lang: str = "en") -> list:
        resp = http_get(series_url)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        slug = series_url.rstrip("/").split("/")[-1]
        out, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            chapter_slug = href.strip("/").split("/")[-1]
            if not re.match(r"chapter[-_]?\d", chapter_slug):
                continue
            key = chapter_slug
            if key in seen:
                continue
            seen.add(key)
            num_m = re.search(r"(\d+(?:\.\d+)?)", chapter_slug)
            if not num_m:
                continue
            h1 = a.find("h1")
            out.append(MangaChapter(
                id=key, number=num_m.group(1),
                title=(h1.get_text(strip=True) if h1 else "")[:40],
                url=f"{self.BASE}/comic/{slug}/{chapter_slug}",
            ))
        if not out:
            raise MangaError("TempleToons: no chapters parsed")
        return out

    def images(self, chapter: MangaChapter) -> tuple:
        resp = http_get(chapter.url)
        # reader page embeds the image list in a flight-data script blob;
        # the blob escapes "/" as "\/" — unescape the whole text first
        text = resp.text.replace("\\/", "/")
        candidates = re.findall(r'https?://[^\s"\'\\]+/images/[^\s"\'\\]+\.(?:jpg|jpeg|webp|png)',
                                text)
        urls, seen = [], set()
        for u in candidates:
            if u not in seen:
                seen.add(u)
                urls.append(u)
        if not urls:
            urls = [m for m in re.findall(
                r'https?://[^\s"\'\\]+\.(?:jpg|jpeg|webp|png)', text)
                if "logo" not in m and "brand" not in m]
        if not urls:
            raise MangaError("TempleToons: no page images found")
        return urls, self.BASE + "/"
