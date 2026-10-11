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
}


def http_get(url: str, headers: dict = None, timeout=(6, 20)):
    last = None
    # loopback hosts must bypass system proxies (sandbox/CI export proxy envs;
    # routing 127.0.0.1 through them breaks local fixtures and health checks)
    if url.startswith(("http://127.0.0.1", "http://localhost")):
        sess = requests.Session()
        sess.trust_env = False
        getter = sess.get
    else:
        getter = requests.get
    for attempt in (1, 2):   # one transparent retry per request
        try:
            resp = getter(url, headers={**DEFAULT_HEADERS, **(headers or {})},
                          timeout=timeout)
            if resp.status_code == 200:
                return resp
            last = IOError(f"HTTP {resp.status_code} on {url[:80]}")
        except requests.RequestException as e:
            last = e
        time.sleep(0.6)
    raise last or IOError(f"GET failed: {url[:80]}")


def http_json(url: str, headers: dict = None):
    return http_get(url, headers=headers).json()


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
