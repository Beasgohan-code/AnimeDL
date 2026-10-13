# ============================================================================
#  Asura Scans provider — asuracomic.net (WordPress front-end on Next.js).
#  Ported from Manga-Bot + Manhwa-Bot asurascans.py, hardened: their exact
#  class-string selectors broke between deploys, so this uses looser regex/
#  soup lookups and the __next_f pages-blob decode for images.
# ============================================================================

import json
import logging
import re
from urllib.parse import quote, urljoin

from manga_sources import MangaChapter, MangaError, MangaSearchResult
from manga_sources.base import http_get

logger = logging.getLogger(__name__)

BASE = "https://asuracomic.net"
HEADERS = {"Host": "asuracomic.net", "Connection": "keep-alive"}


class AsuraProvider:
    id = "asura"

    def search(self, query: str) -> list:
        resp = http_get(f"{BASE}/series?name={quote(query)}", headers=HEADERS)
        soup = _soup(resp.text)
        out, seen = [], set()
        for card in soup.find_all("a", href=re.compile(r"/series/[^\"']+-\d+")):
            href = card.get("href", "")
            if href in seen:
                continue
            seen.add(href)
            title_el = card.find(string=True)
            title = (title_el or "Unknown").strip() if title_el else "Unknown"
            # poster: first img inside the card
            img = card.find("img")
            cover = (img.get("src") or "") if img else ""
            m_id = href.rsplit("-", 1)[-1]
            out.append(MangaSearchResult(
                provider=self.id,
                id=m_id,
                title=_clean(title) or "Unknown",
                cover=cover,
                url=urljoin(BASE + "/", href.lstrip("/")),
            ))
            if len(out) >= 8:
                break
        return out

    def chapters(self, manga_url: str, lang: str = "en") -> list:
        resp = http_get(manga_url, headers=HEADERS)
        soup = _soup(resp.text)
        out, seen = [], set()
        for a in soup.find_all("a", href=re.compile(r"/series/.+/chapter-")):
            href = a.get("href", "")
            if href in seen:
                continue
            seen.add(href)
            h3 = a.find("h3") or a
            num_m = re.search(r"chapter[-/](\d+(?:\.\d+)?)", href)
            if not num_m:
                continue
            title = _clean(h3.get_text(" ", strip=True))
            out.append(MangaChapter(
                id=href,
                number=num_m.group(1),
                title=title if title.lower() != f"chapter {num_m.group(1)}" else "",
                url=urljoin(BASE + "/", href.lstrip("/")),
            ))
        if not out:
            raise MangaError("Asura: no chapters parsed (layout changed?)")
        return out

    def images(self, chapter: MangaChapter) -> tuple:
        resp = http_get(chapter.url, headers=HEADERS)
        # images live in the Next.js flight data: \"pages\":[{url:…},…]
        for m in re.finditer(r'\\"pages\\":(\[.*?\])', resp.text):
            blob = m.group(1).replace('\\"', '"')
            try:
                pages = json.loads("[" + blob[blob.index("[") + 1:blob.rindex("]")] + "]")
            except Exception:  # noqa: BLE001
                pages = json.loads(f'{{"pages":{blob}}}')["pages"][0]
            urls = [p.get("url") for p in pages
                    if isinstance(p, dict) and p.get("url")]
            if urls:
                return urls, BASE + "/"
        # plain-html fallback
        urls = re.findall(r'<img[^>]+src="(https://[^"]+/(?:gg|asura)?/[^"]+\.(?:webp|jpg|jpeg|png))"',
                          resp.text)
        urls = [u for u in urls if "logo" not in u and "icon" not in u]
        if urls:
            return urls, BASE + "/"
        raise MangaError("Asura: page images not found")


def _soup(html: str):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()
