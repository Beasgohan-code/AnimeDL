# ============================================================================
#  AnimeDL — MegaCloud-family stream extractor (advanced)
# ============================================================================
#  Ported from ewgsta/weeb-cli (MIT) megacloud extractor, with the Megaplay /
#  Vidwish direct fallback routes. This handles the "getSources" player family
#  (megacloud.tv, cdn.4animo.xyz, flixera.co, rapid-cloud style embeds):
#
#    1. GET the embed page (?k=1&autoPlay=0…) and pull a per-view token
#       (meta[_gg_fb] / [data-dpi] / script nonce / window.* heuristic)
#    2. GET  <embed>/getSources?id=<id>&_k=<token>   (XHR)
#    3. sources is either a plain list (done) or an AES-ECCT encrypted string:
#       decrypt with the community-rotated key published at
#       ryanwtf88/megacloud-keys (cached 1h) — pycryptodome, already a dep.
#
#  Fallback route (no tokens at all): megaplay.buzz / vidwish.live stream
#  pages expose a data-id + getSources JSON with a plain m3u8.
# ============================================================================

import base64
import json
import logging
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    _HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    _HAS_CRYPTO = False

logger = logging.getLogger(__name__)

KEY_URL = "https://raw.githubusercontent.com/ryanwtf88/megacloud-keys/refs/heads/master/key.txt"
MEGAPLAY_URL = "https://megaplay.buzz/stream/s-2/"
VIDWISH_URL = "https://vidwish.live/stream/s-2/"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) "
       "Gecko/20100101 Firefox/122.0")
_HEADERS = {"User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

_cached_key: Optional[str] = None
_key_at = 0.0
_KEY_TTL = 3600


def _get(url: str, headers: dict = None, timeout: int = 15) -> Optional[requests.Response]:
    try:
        resp = requests.get(url, headers=headers or _HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None
        return resp
    except requests.RequestException:
        return None


def _get_json(url: str, headers: dict = None) -> Optional[dict]:
    resp = _get(url, headers)
    if resp is None:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


# ------------------------------------------------------------------- AES key
def _decryption_key() -> Optional[str]:
    """Rotating key from the community repo (cached 1h)."""
    global _cached_key, _key_at
    now = time.time()
    if _cached_key and now - _key_at < _KEY_TTL:
        return _cached_key
    resp = _get(KEY_URL, timeout=12)
    if resp is None:
        return _cached_key
    key = resp.text.strip()
    if key:
        _cached_key, _key_at = key, now
    return _cached_key


def _decrypt_aes(encrypted: str, key: str):
    """AES-ECB decrypt (key tried as utf-8, then hex) → list of sources."""
    if not _HAS_CRYPTO:
        return None
    for key_bytes in (key.encode("utf-8", "ignore"),):
        try:
            cipher = AES.new(key_bytes, AES.MODE_ECB)
            data = cipher.decrypt(base64.b64decode(encrypted))
            data = unpad(data, AES.block_size)
            return json.loads(data.decode("utf-8"))
        except Exception:
            continue
    try:
        cipher = AES.new(bytes.fromhex(key), AES.MODE_ECB)
        data = unpad(cipher.decrypt(base64.b64decode(encrypted)), AES.block_size)
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


# --------------------------------------------------------------------- token
def _extract_token(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.select_one('meta[name="_gg_fb"]')
    if meta and meta.get("content"):
        return meta["content"]
    dpi = soup.select_one("[data-dpi]")
    if dpi and dpi.get("data-dpi"):
        return dpi["data-dpi"]
    for script in soup.select("script[nonce]"):
        nonce = script.get("nonce")
        if nonce and len(nonce) >= 10:
            return nonce
    for pattern in (r'window\.\w+\s*=\s*["\']([a-zA-Z0-9_-]{10,})["\']',
                    r'data-k\s*=\s*["\']([a-zA-Z0-9_-]{10,})["\']'):
        m = re.search(pattern, html)
        if m:
            return m.group(1)
    return None


# ------------------------------------------------------------- megaplay path
def megaplay_fallback(ep_id: str, mode: str = "sub") -> Optional[dict]:
    """Direct route via megaplay.buzz / vidwish.live (no token, no AES).

    ep_id is the hianime-style numeric episode id. Returns
    {file, tracks[]} or None.
    """
    mode = "sub" if mode != "dub" else "dub"
    for domain, base in (("megaplay", MEGAPLAY_URL), ("vidwish", VIDWISH_URL)):
        try:
            page = _get(
                f"{base}{ep_id}/{mode}",
                headers={**_HEADERS, "Referer": f"https://{domain}.{'buzz' if domain == 'megaplay' else 'live'}/"},
            )
            if page is None:
                continue
            m = re.search(r'data-id=["\'](\d+)["\']', page.text)
            if not m:
                continue
            data = _get_json(
                f"https://{domain}.{'buzz' if domain == 'megaplay' else 'live'}/stream/getSources?id={m.group(1)}",
                headers={**_HEADERS, "X-Requested-With": "XMLHttpRequest",
                         "Referer": f"https://{domain}.{'buzz' if domain == 'megaplay' else 'live'}/"},
            )
            if data and data.get("sources", {}).get("file"):
                return {"file": data["sources"]["file"], "tracks": data.get("tracks", [])}
        except Exception as e:
            logger.debug("megaplay fallback failed on %s: %s", domain, e)
    return None


# ------------------------------------------------------------- main exporter
def get_megacloud_stream(embed_url: str, referer: str = "https://hianime.to/",
                         ep_id: str = "", mode: str = "sub") -> Optional[dict]:
    """Resolve a MegaCloud-family embed page to {file, tracks[]}.

    Falls back to the megaplay/vidwish route when the embed path fails.
    """
    m = re.search(r"/([^/?]+)\?", embed_url)
    source_id = m.group(1) if m else None
    m_base = re.match(r"^(https?://[^/]+(?:/[^/]+){0,3})", embed_url)
    base_url = m_base.group(1) if m_base else None

    if source_id and base_url:
        page = _get(f"{embed_url}{'&' if '?' in embed_url else '?'}autoPlay=0",
                    headers={**_HEADERS, "Referer": referer})
        token = _extract_token(page.text) if page is not None else None
        if token:
            data = _get_json(
                f"{base_url}/getSources?id={source_id}&_k={token}",
                headers={**_HEADERS, "X-Requested-With": "XMLHttpRequest",
                         "Referer": f"{base_url}/{source_id}"},
            )
            if data:
                sources = data.get("sources")
                if isinstance(sources, list) and sources:
                    return {"file": sources[0].get("file"),
                            "tracks": data.get("tracks", [])}
                if isinstance(sources, str):
                    key = _decryption_key()
                    if key:
                        decrypted = _decrypt_aes(sources, key)
                        if decrypted and decrypted[0].get("file"):
                            return {"file": decrypted[0]["file"],
                                    "tracks": data.get("tracks", [])}

    return megaplay_fallback(ep_id, mode)
