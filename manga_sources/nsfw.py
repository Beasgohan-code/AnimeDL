# ============================================================================
#  NSFW manga providers (18+) — manhwaclan / manga18fx / manhwa18.
#  Ported from Manhwa-Bot for completeness. DISABLED BY DEFAULT: the bot
#  ships to public channels, so these only register when the operator sets
#  ANIMEDL_MANGA_NSFW=1 on the server.
# ============================================================================

import logging
import os
import re

from manga_sources import MangaChapter, MangaError, MangaSearchResult
from manga_sources.base import http_get

logger = logging.getLogger(__name__)


def nsfw_enabled() -> bool:
    return os.getenv("ANIMEDL_MANGA_NSFW", "0") == "1"


class _WpManhwaBase:
    """Shared WordPress-manga shape: ?s= search, chapter links in page,
    .page-break image grid."""
    BASE = ""
    ID = ""

    def search(self, query: str) -> list:
        from urllib.parse import quote_plus
        resp = http_get(f"{self.BASE}/?s={quote_plus(query)}&post_type=wp-manga")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        out, seen = [], set()
        for card in soup.select(".c-tabs-item__content, .tab-thumb"):
            a = card.find("a", href=True) if card.name != "a" else card
            if a is None or not a.get("href"):
                continue
            href = a["href"]
            if href in seen:
                continue
            seen.add(href)
            h3 = card.find("h3")
            img = card.find("img")
            out.append(MangaSearchResult(
                provider=self.ID,
                id=href,
                title=(h3.get_text(strip=True) if h3
                       else (img.get("alt") if img else "")) or "Unknown",
                cover=(img.get("data-src") or img.get("src") or "") if img else "",
                url=href,
                extra="18+",
            ))
            if len(out) >= 8:
                break
        return out

    def chapters(self, series_url: str, lang: str = "en") -> list:
        resp = http_get(series_url)
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
            raise MangaError(f"{self.ID}: no chapters parsed")
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
            raise MangaError(f"{self.ID}: no page images found")
        return urls, self.BASE + "/"


class ManhwaClanProvider(_WpManhwaBase):
    id = "manhwaclan"
    BASE = "https://manhwaclan.com"
    ID = "manhwaclan"


class Manga18FxProvider(_WpManhwaBase):
    id = "manga18fx"
    BASE = "https://manga18fx.com"
    ID = "manga18fx"

    def search(self, query: str) -> list:
        from urllib.parse import quote
        resp = http_get(f"{self.BASE}/search?q={quote(query)}")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        out, seen = [], set()
        for card in soup.select(".grid_box"):
            a = card.find("a", href=True)
            if not a:
                continue
            href = a["href"]
            if href in seen:
                continue
            seen.add(href)
            img = card.find("img")
            t = card.find(class_="title") or card.find("h3")
            out.append(MangaSearchResult(
                provider=self.ID, id=href,
                title=(t.get_text(strip=True) if t else "Unknown"),
                cover=(img.get("src") or "") if img else "",
                url=href, extra="18+",
            ))
            if len(out) >= 8:
                break
        return out


class Manhwa18Provider(_WpManhwaBase):
    id = "manhwa18"
    BASE = "https://manhwa18.cc"
    ID = "manhwa18"


NSFW_PROVIDERS = {
    "manhwaclan": ManhwaClanProvider,
    "manga18fx": Manga18FxProvider,
    "manhwa18": Manhwa18Provider,
}
