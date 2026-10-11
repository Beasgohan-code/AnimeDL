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

from anime_sources.base import http_session
from bs4 import BeautifulSoup

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    _HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    _HAS_CRYPTO = False

logger = logging.getLogger(__name__)

# Community key repos rotate — the original (ryanwtf88) was DELETED (404 on
# GitHub API, verified 2026-10-11), which silently broke megacloud decryption
# everywhere. Chain multiple live repos + a CDN mirror; any one succeeding is
# enough. Keys are cross-identical across forks (verified: 3709ad88…, 64 hex).
KEY_URLS = [
    "https://raw.githubusercontent.com/itzzzme/megacloud-keys/refs/heads/main/key.txt",
    "https://raw.githubusercontent.com/itzrihan/megacloud-keys/refs/heads/main/key.txt",
    "https://cdn.jsdelivr.net/gh/itzzzme/megacloud-keys@main/key.txt",
    "https://raw.githubusercontent.com/ryanwtf88/megacloud-keys/refs/heads/master/key.txt",  # legacy
]
KEY_URL = KEY_URLS[0]  # kept for logging/compat
MEGAPLAY_URL = "https://megaplay.buzz/stream/s-2/"
VIDWISH_URL = "https://vidwish.live/stream/s-2/"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) "
       "Gecko/20100101 Firefox/122.0")
_HEADERS = {"User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

_cached_key: Optional[str] = None
_key_at = 0.0
_KEY_TTL = 3600


def _get(url: str, headers: dict = None, timeout=(6, 15)) -> Optional[requests.Response]:
    try:
        resp = http_session().get(url, headers=headers or _HEADERS, timeout=timeout)
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
    """Rotating key — tried across the whole KEY_URLS chain (cached 1h).

    A single dead repo must never disable decryption again: we walk every
    URL until one returns a plausible key (hex or base64-ish, >=16 chars).
    """
    global _cached_key, _key_at
    now = time.time()
    if _cached_key and now - _key_at < _KEY_TTL:
        return _cached_key
    for url in KEY_URLS:
        resp = _get(url, timeout=12)
        if resp is None:
            continue
        key = (resp.text or "").strip()
        if len(key) >= 16 and " " not in key and "<" not in key:
            _cached_key, _key_at = key, now
            return _cached_key
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


# --------------------------------------------------------------------------
#  KEY-LESS extraction (ported from abhinai2244/AniwatchTvdl — cantarellabots)
#  Handles megacloud "e-1" embeds with NO external key repo: the client key
#  comes from the embed page itself and string deobfuscation is an LCG +
#  shuffle. This is the independent fallback when the whole key chain fails.
# --------------------------------------------------------------------------
def _hash_str(key: str) -> int:
    kv = 0
    for ch in key:
        kv = (kv * 31 + ord(ch)) & 0xFFFFFFFF
    return kv


def _lcg(n: int) -> int:
    return (n * 1103515245 + 12345) & 0x7FFFFFFF


def _keyless_extract(embed_url: str) -> Optional[dict]:
    sid_m = re.search(r"e-1/([a-zA-Z0-9]+)", embed_url)
    if not sid_m:
        return None
    sid = sid_m.group(1)
    # host alternates: some edges block .tv, others .blog
    hosts = ["https://megacloud.tv", "https://megacloud.blog"]
    last_err = None
    for host in hosts:
      try:
        embed_url = re.sub(r"^https?://megacloud\.(?:tv|blog)", host, embed_url)
        page = _get(embed_url)
        html = page.text if page is not None else ""
        m = re.search(r'([a-zA-Z0-9]{48})|x: "([a-zA-Z0-9]{16})", y: "([a-zA-Z0-9]{16})", z: "([a-zA-Z0-9]{16})"}', html)
        if not m:
            last_err = RuntimeError("client key not on page")
            continue
        client_key = m.group(1) or "".join(x for x in m.groups()[1:] if x)

        from anime_sources.base import http_session
        r = http_session().get(
            f"{host}/embed-2/v3/e-1/getSources",
            params={"id": sid, "_k": client_key},
            headers={"Referer": embed_url},
            timeout=(6, 15),
        )
        if r.status_code != 200:
            last_err = RuntimeError(f"getSources HTTP {r.status_code}")
            continue
        data = r.json()
        if not isinstance(data, dict):
            last_err = RuntimeError(f"getSources payload was {type(data).__name__}")
            continue
        if isinstance(data.get("sources"), str):
            chars = list(data["sources"])
            cur = _hash_str(client_key)
            out = []
            for ch in chars:
                cur = _lcg(cur)
                out.append(chr((ord(ch) - 32 - (cur % 95)) % 95 + 32))
            # key-sorted unshuffle (inverse of the site's shuffle)
            if client_key:
                arr_count = len(out) // len(client_key)
                arrays = [[""] * len(client_key) for _ in range(arr_count)]
                order = sorted(range(len(client_key)), key=lambda i: client_key[i])
                p2 = 0
                for idx in order:
                    for a in range(arr_count):
                        if p2 < len(out):
                            arrays[a][idx] = out[p2]
                            p2 += 1
                flat = [x for arr in arrays for x in arr]
                # the site SHUFFLED with this same order — inverse is reading
                # positionally, so try both readings
                try_a = "".join(out)
                try_b = "".join(flat)
                parsed = None
                for cand in (try_a, try_b):
                    try:
                        parsed = json.loads(cand)
                        break
                    except Exception:
                        continue
                if parsed is None:
                    last_err = RuntimeError("decode failed")
                    continue
                # decoded payload may be the bare sources ARRAY or the full
                # {"sources": […], "tracks": […]} object — accept both
                if isinstance(parsed, dict):
                    if parsed.get("sources"):
                        data["sources"] = parsed["sources"]
                    if parsed.get("tracks"):
                        data["tracks"] = parsed["tracks"]
                else:
                    data["sources"] = parsed
        return data if data.get("sources") else None
      except Exception as e:
        last_err = e
        continue
    return None


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
            if isinstance(data, dict):
                src = data.get("sources")
                # sources can be the raw dict, the encrypted string (not
                # decodable on this route — skip), or junk; only a dict with
                # a file is usable here
                if isinstance(src, dict) and src.get("file"):
                    return {"file": src["file"],
                            "tracks": data.get("tracks") or []}
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

    # Key-chain independent path (Cantarella port): e-1 embeds decrypt via
    # the client key embedded in the page itself — works even when every
    # key repo on GitHub is dead.
    keyless = _keyless_extract(embed_url)
    if keyless:
        src = keyless.get("sources") or []
        if isinstance(src, list) and src and src[0].get("file"):
            tracks = [t for t in (keyless.get("tracks") or [])
                      if isinstance(t, dict) and t.get("file")]
            return {"file": src[0]["file"], "tracks": tracks}

    return megaplay_fallback(ep_id, mode)
