# ============================================================================
#  AnimeDL — extra manga providers (ported from the Manga-Bot reference repo,
#  hardened for AnimeDL). Sites:
#    • MangaKakalot  (mangakakalot.gg) — big general catalogue
#    • MangaSee123   (mangasee123.com) — JSON search + vm.Chapters reader
#    • Mangabuddy    (mangabuddy.com)  — manhwa/webtoon catalogue
#    • NineManga     (ninemanga.com)   — multi-language aggregator
#  All user-facing branding remains AnimeDL's own.
# ============================================================================

import re
from urllib.parse import urljoin, quote

from manga_sources.base import http_get
from manga_sources import MangaError, MangaSearchResult, MangaChapter


def _post_json(url: str, data=None):
    """POST helper kept module-level so tests can stub it."""
    import requests
    from manga_sources.base import DEFAULT_HEADERS
    r = requests.post(url, data=data, headers=DEFAULT_HEADERS, timeout=(6, 20))
    if r.status_code != 200:
        raise MangaError(f"POST {url[:60]} → HTTP {r.status_code}")
    return r.json()


def _soup(text: str):
    from bs4 import BeautifulSoup
    return BeautifulSoup(text, "html.parser")


def _num_in(s: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)?)", s or "")
    return m.group(1) if m else ""


# ─────────────────────────────────────────────
#  MangaKakalot — mangakakalot.gg
# ─────────────────────────────────────────────
class MangaKakalotProvider:
    id = "mangakakalot"
    BASE = "https://www.mangakakalot.gg"

    def search(self, query: str) -> list:
        url = f"{self.BASE}/search/{quote(query.strip().replace(' ', '_'))}"
        resp = http_get(url)
        soup = _soup(resp.text)
        out, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full = urljoin(self.BASE + "/", href)
            if not re.search(r"/manga/[^/?#]+/?$", full) or full in seen:
                continue
            seen.add(full)
            img = a.find("img")
            if img is None and a.parent is not None:
                img = a.parent.find("img")
            title = ((img.get("alt") if img else "") or a.get("title")
                     or a.get_text(strip=True) or "").strip()
            if not title:
                continue
            cover = ""
            if img:
                cover = img.get("data-src") or img.get("src") or ""
            out.append(MangaSearchResult(
                provider=self.id, id=full, title=title[:60],
                cover=cover, url=full))
            if len(out) >= 8:
                break
        if not out:
            raise MangaError("MangaKakalot: no results parsed")
        return out

    def chapters(self, series_url: str, lang: str = "en") -> list:
        resp = http_get(series_url)
        soup = _soup(resp.text)
        container = (soup.find(class_="chapter-list")
                     or soup.find(class_="panel-content-chapter")
                     or soup.find(class_="panel-story-chapter-list")
                     or soup)
        out, seen = [], set()
        for a in container.find_all("a", href=True):
            href = a["href"]
            if "chapter" not in href:
                continue
            slug = href.rstrip("/").split("/")[-1]
            if slug in seen:
                continue
            seen.add(slug)
            num = _num_in(slug) or _num_in(a.get_text(strip=True))
            if not num:
                continue
            out.append(MangaChapter(
                id=slug, number=num,
                title=a.get_text(strip=True)[:40],
                url=urljoin(self.BASE + "/", href)))
        if not out:
            raise MangaError("MangaKakalot: no chapters parsed")
        return out

    def images(self, chapter: MangaChapter) -> tuple:
        resp = http_get(chapter.url)
        soup = _soup(resp.text)
        container = (soup.find(class_="container-chapter-reader")
                     or soup.find(id="chapter_container") or soup)
        urls, seen = [], set()
        for img in container.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if src.startswith("http") and src not in seen and "logo" not in src:
                seen.add(src)
                urls.append(src)
        if not urls:
            raise MangaError("MangaKakalot: no page images found")
        return urls, self.BASE + "/"


# ─────────────────────────────────────────────
#  MangaSee123 — mangasee123.com
# ─────────────────────────────────────────────
class MangaseeProvider:
    id = "mangasee"
    BASE = "https://mangasee123.com"
    MANGA = "https://mangasee123.com/manga"
    COVER = "https://cover.nep.li/cover"

    @staticmethod
    def _chapter_slug(cs: str) -> str:
        """mangasee packs chapters as '<index><number><odd>' — decode to a
        URL suffix, e.g. '1005.5' → '-chapter-5.5.html'."""
        t = cs[0:1]
        index = "" if t == "1" else f"-index-{t}"
        n = int(cs[1:-1])
        m = "" if cs[-1] == "0" else "." + cs[-1]
        return f"-chapter-{n}{m}{index}.html"

    @staticmethod
    def _chapter_num(cs: str) -> str:
        n = int(cs[1:-1])
        return f"{n}" if cs[-1] == "0" else f"{n}.{cs[-1]}"

    def search(self, query: str) -> list:
        docs = _post_json(f"{self.BASE}/_search.php") or []
        q = query.lower().strip()
        out = []
        for doc in docs:
            hay = " ".join([doc.get("s") or ""] + list(doc.get("a") or [])).lower()
            if q not in hay:
                continue
            i = doc.get("i") or ""
            out.append(MangaSearchResult(
                provider=self.id, id=i, title=(doc.get("s") or i)[:60],
                cover=f"{self.COVER}/{i}.jpg", url=f"{self.MANGA}/{i}"))
            if len(out) >= 8:
                break
        if not out:
            raise MangaError("Mangasee: no results parsed")
        return out

    def chapters(self, series_url: str, lang: str = "en") -> list:
        i = series_url.rstrip("/").split("/")[-1]
        resp = http_get(f"{self.MANGA}/{i}")
        m = re.search(r"vm\.Chapters\s*=\s*([\s\S]*?);", resp.text)
        if not m:
            raise MangaError("Mangasee: chapter list not on page")
        import json
        out = []
        for ch in json.loads(m.group(1)):
            cs = ch.get("Chapter") or ""
            if len(cs) < 3:
                continue
            slug = self._chapter_slug(cs)
            out.append(MangaChapter(
                id=slug, number=self._chapter_num(cs),
                title=(ch.get("Title") or "")[:40],
                url=f"{self.BASE}/read-online/{i}{slug}"))
        if not out:
            raise MangaError("Mangasee: no chapters parsed")
        return out

    def images(self, chapter: MangaChapter) -> tuple:
        import json
        resp = http_get(chapter.url)
        cur = re.search(r"vm\.CurChapter\s*=\s*([\s\S]*?);", resp.text)
        path = re.search(r"vm\.CurPathName\s*=\s*([\s\S]*?);", resp.text)
        index = re.search(r"vm\.IndexName\s*=\s*([\s\S]*?);", resp.text)
        if not (cur and path and index):
            raise MangaError("Mangasee: reader data not on page")
        cc = json.loads(cur.group(1))
        host = json.loads(path.group(1))
        idx = json.loads(index.group(1))
        cs = cc.get("Chapter") or ""
        img = cs[1:-1] + ("" if cs[-1] == "0" else "." + cs[-1])
        directory = cc.get("Directory") or ""
        prefix = f"{directory}/" if directory else ""
        total = int(cc.get("Page") or 0)
        urls = [f"https://{host}/manga/{idx}/{prefix}{img}-{('000' + str(p))[-3:]}.png"
                for p in range(1, total + 1)]
        if not urls:
            raise MangaError("Mangasee: no page images found")
        return urls, self.BASE + "/"


# ─────────────────────────────────────────────
#  Mangabuddy — mangabuddy.com
# ─────────────────────────────────────────────
class MangabuddyProvider:
    id = "mangabuddy"
    BASE = "https://mangabuddy.com"

    def search(self, query: str) -> list:
        resp = http_get(f"{self.BASE}/search?q={quote(query.strip())}")
        soup = _soup(resp.text)
        out, seen = [], set()
        cards = soup.find_all(class_="book-item")
        if not cards:
            # layout drift fallback: any series-shaped link with a title
            cards = [a for a in soup.find_all("a", href=True)
                     if re.search(r"/(manga|comic)/[^/]+/?$", a["href"])]
        for card in cards:
            a = card if card.name == "a" else card.find("a", href=True)
            if not a:
                continue
            full = urljoin(self.BASE + "/", a["href"])
            if full in seen:
                continue
            seen.add(full)
            img = card.find("img") if card.name != "a" else a.find("img")
            title = ((img.get("alt") if img else "") or a.get("title")
                     or a.get_text(strip=True) or "").strip()
            if not title:
                continue
            cover = (img.get("data-src") or img.get("src") or "") if img else ""
            out.append(MangaSearchResult(
                provider=self.id, id=full, title=title[:60], cover=cover, url=full))
            if len(out) >= 8:
                break
        if not out:
            raise MangaError("Mangabuddy: no results parsed")
        return out

    def chapters(self, series_url: str, lang: str = "en") -> list:
        resp = http_get(series_url)
        soup = _soup(resp.text)
        ul = soup.find("ul", id="chapter-list") or soup
        out, seen = [], set()
        for a in ul.find_all("a", href=True):
            href = a["href"]
            slug = href.rstrip("/").split("/")[-1]
            if "chapter" not in slug or slug in seen:
                continue
            seen.add(slug)
            strong = a.find("strong")
            num = _num_in(strong.get_text()) if strong else ""
            num = num or _num_in(slug)
            if not num:
                continue
            out.append(MangaChapter(
                id=slug, number=num,
                title=(strong.get_text(strip=True)[:40] if strong else ""),
                url=urljoin(self.BASE + "/", href)))
        if not out:
            raise MangaError("Mangabuddy: no chapters parsed")
        return out

    def images(self, chapter: MangaChapter) -> tuple:
        resp = http_get(chapter.url)
        m = re.search(r"var\s+chapImages\s*=\s*'([^']*)'", resp.text)
        if not m:
            raise MangaError("Mangabuddy: page list not on page")
        urls = [u.strip() for u in m.group(1).split(",")
                if u.strip().startswith("http")]
        if not urls:
            raise MangaError("Mangabuddy: no page images found")
        return urls, self.BASE + "/"


# ─────────────────────────────────────────────
#  NineManga — ninemanga.com (multi-page reader)
# ─────────────────────────────────────────────
class NinemangaProvider:
    id = "ninemanga"
    BASE = "https://www.ninemanga.com"

    def search(self, query: str) -> list:
        resp = http_get(f"{self.BASE}/search/?wd={quote(query.strip())}")
        soup = _soup(resp.text)
        container = soup.find("ul", class_="direlist") or soup
        out = []
        for li in container.find_all("li"):
            a = li.find("a", class_="bookname") or li.find("a", href=True)
            if not a or not a.get("href"):
                continue
            full = urljoin(self.BASE + "/", a["href"])
            img = li.find("img")
            title = ((a.get_text(strip=True)) or (img.get("alt") if img else "")
                     or "").strip()
            if not title or "login" in full:
                continue
            out.append(MangaSearchResult(
                provider=self.id, id=full, title=title[:60],
                cover=(img.get("src") or "") if img else "", url=full))
            if len(out) >= 8:
                break
        if not out:
            raise MangaError("NineManga: no results parsed")
        return out

    def chapters(self, series_url: str, lang: str = "en") -> list:
        resp = http_get(series_url)
        soup = _soup(resp.text)
        box = soup.find("div", class_="chapterbox") or soup
        out, seen = [], set()
        for a in box.find_all("a", href=True):
            href = a["href"]
            slug = href.rstrip("/").split("/")[-1]
            num = _num_in(a.get_text(strip=True)) or _num_in(slug)
            if not num:
                continue
            # real ninemanga chapter links end in a bare numeric segment
            if "chapter" not in slug.lower() and not slug.isdigit():
                continue
            if slug in seen:
                continue
            seen.add(slug)
            out.append(MangaChapter(
                id=slug, number=num, title=a.get_text(strip=True)[:40],
                url=urljoin(self.BASE + "/", href)))
        if not out:
            raise MangaError("NineManga: no chapters parsed")
        return out

    def images(self, chapter: MangaChapter) -> tuple:
        """NineManga shows ONE page per URL — the reader's <select id=page>
        lists every page URL; fetch each and pull img.manga_pic."""
        resp = http_get(chapter.url)
        soup = _soup(resp.text)
        sel = soup.find("select", id="page")
        page_urls = []
        if sel:
            for opt in sel.find_all("option"):
                v = opt.get("value") or ""
                if v and v not in page_urls:
                    page_urls.append(v)
        urls, seen = [], set()

        def _pics(text):
            s = _soup(text)
            for img in s.find_all("img", class_="manga_pic"):
                src = img.get("src") or ""
                if src.startswith("http") and src not in seen:
                    seen.add(src)
                    urls.append(src)

        _pics(resp.text)
        for v in page_urls[:60]:
            full = urljoin(chapter.url, v)
            if full == chapter.url:
                continue
            try:
                _pics(http_get(full).text)
            except Exception:  # noqa: BLE001 — tolerate single dead pages
                continue
        if not urls:
            raise MangaError("NineManga: no page images found")
        return urls, self.BASE + "/"
