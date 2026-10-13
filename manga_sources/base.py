# ============================================================================
#  AnimeDL Manga Engine — base: HTTP, image fetching, PDF/CBZ builders
# ============================================================================
#  Adds manga/manhwa chapter downloading to AnimeDL (v4.21.0). Architecture
#  mined and rebuilt from three reference bots (Manga-Bot, Manhwa-Bot,
#  AUTO-MANGA-BOT), then improved:
#    • Pillow-native PDF (no extra fpdf dependency; streams one image at a
#      time to bound memory)
#    • CBZ with STORED entries (standard-compliant, faster than DEFLATE for
#      already-compressed JPEGs)
#    • per-image retry + skip-after-retry (one dead CDN page must not kill
#      a chapter)
#    • progress callback at every stage (search → chapters → pages → file)
# ============================================================================

import logging
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.5",
}

# statuses that usually mean "Cloudflare ate it" — worth a cloudscraper retry
_BLOCK_STATUSES = {403, 429, 503, 530}
_cs_session = None          # lazy cloudscraper session (created on first block)
_cs_failed = False          # cloudscraper import failed once → stop trying


def _scraper():
    """cloudscraper session, created on first use (mirrors Manhwa-Bot's
    Scraper(cs=True): datacenter IPs get CF-challenged, cloudscraper solves
    the JS/cookie handshake for us)."""
    global _cs_session, _cs_failed
    if _cs_session is None and not _cs_failed:
        try:
            import cloudscraper
            _cs_session = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows",
                         "mobile": False})
        except Exception as e:
            logger.info("cloudscraper unavailable: %s", e)
            _cs_failed = True
    return _cs_session


def _loopback(url: str) -> bool:
    return url.startswith(("http://127.0.0.1", "http://localhost"))


def _request(method: str, url: str, headers: dict = None, params=None,
             data=None, timeout=(6, 20)):
    """One HTTP call with plain-requests → cloudscraper escalation.
    attempt 1: requests · attempt 2: cloudscraper when the failure looked
    like a Cloudflare block (403/429/503/530), else plain requests again."""
    hdrs = {**DEFAULT_HEADERS, **(headers or {})}
    loop = _loopback(url)
    last, blocked = None, False
    for attempt in (1, 2):
        escalated = (attempt == 2 and blocked and not loop)
        try:
            if loop:
                sess = requests.Session()
                sess.trust_env = False
                getter = sess.get if method == "GET" else sess.post
            elif escalated:
                cs = _scraper()
                if cs is not None:
                    getter = cs.get if method == "GET" else cs.post
                else:
                    getter = requests.get if method == "GET" else requests.post
            else:
                getter = requests.get if method == "GET" else requests.post
            resp = getter(url, headers=hdrs, params=params, data=data,
                          timeout=timeout)
            if resp.status_code == 200:
                if escalated:
                    logger.info("cloudscraper recovered %s", url[:60])
                return resp
            last = IOError(f"HTTP {resp.status_code} on {url[:80]}")
            blocked = resp.status_code in _BLOCK_STATUSES
        except requests.RequestException as e:
            last = e
            blocked = False
        time.sleep(0.6)
    raise last or IOError(f"{method} failed: {url[:80]}")


def http_get(url: str, headers: dict = None, params=None, timeout=(6, 20)):
    return _request("GET", url, headers=headers, params=params,
                    timeout=timeout)


def http_json(url: str, headers: dict = None, params=None):
    return http_get(url, headers=headers, params=params).json()


def http_post(url: str, data=None, headers: dict = None, timeout=(6, 20)):
    return _request("POST", url, headers=headers, data=data, timeout=timeout)


def fetch_images(urls: list, workdir: Path, progress=None,
                 referer: str = None, max_workers: int = 8) -> list:
    """Download page images into workdir (sorted names). Returns paths of the
    successfully fetched pages, in order. Pages that fail 3 attempts are
    skipped — a single dead CDN image must not lose a whole chapter."""
    workdir.mkdir(parents=True, exist_ok=True)
    referer_headers = {"Referer": referer} if referer else {}

    done = [0]

    def _one(idx_url):
        idx, url = idx_url
        dest = workdir / f"{idx:04d}.img"
        for attempt in (1, 2, 3):
            try:
                resp = http_get(url, headers=referer_headers)
                if len(resp.content or b"") < 32:
                    raise IOError("image payload too small")
                dest.write_bytes(resp.content)
                done[0] += 1
                if progress:
                    progress(done[0], len(urls))
                return dest
            except Exception as e:  # noqa: BLE001
                if attempt == 3:
                    logger.info("manga: page %s failed (%s) — skipped", idx, e)
                    return None
                time.sleep(1.0)
        return None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(_one, enumerate(urls)))
    return [p for p in results if p is not None]


def sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()[:80] or "chapter"


def images_to_pdf(image_paths: list, out_path: Path, progress=None) -> Path:
    """Multi-page PDF via Pillow. Images are converted to RGB JPEG in memory
    one at a time (bounded memory for 60+ page chapters)."""
    from PIL import Image
    out_path = Path(out_path)
    first = None
    appendables = []
    try:
        for i, p in enumerate(image_paths):
            img = Image.open(p)
            if img.mode != "RGB":
                img = img.convert("RGB")
            buf = p.with_suffix(".jpg")
            img.save(buf, format="JPEG", quality=88)
            img.close()
            appendables.append(buf)
            if progress:
                progress(i + 1, len(image_paths))
        first = Image.open(appendables[0])
        if len(appendables) == 1:
            first.save(out_path, "PDF", resolution=100.0)
        else:
            rest = [Image.open(a) for a in appendables[1:]]
            try:
                first.save(out_path, "PDF", resolution=100.0, save_all=True,
                           append_images=rest)
            finally:
                for r in rest:
                    r.close()
        return out_path
    finally:
        if first:
            first.close()


def images_to_cbz(image_paths: list, out_path: Path, progress=None) -> Path:
    """CBZ = zip of pages with STORED entries (JPEG/WebP are already
    compressed; DEFLATE just burns CPU)."""
    out_path = Path(out_path)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_STORED) as zf:
        for i, p in enumerate(image_paths):
            ext = Path(p).suffix or ".jpg"
            zf.write(p, arcname=f"{i:04d}{ext}")
            if progress and i % 10 == 9:
                progress(i + 1, len(image_paths))
    if progress:
        progress(len(image_paths), len(image_paths))
    return out_path
