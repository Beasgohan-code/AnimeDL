# ============================================================================
#  AnimeDL — Generic file-host extractors (shared by every source)
# ============================================================================
#  Salvaged from anime-dl/anime-downloader (2000★, GPL-3, last pushed 2022)
#  — the only pieces of that repo still valid in 2026. MP4Upload and
#  StreamTape remain two of the most common fallback server hosts across the
#  gogo / aniwave / animegg families, and their page formats are unchanged:
#
#  • MP4Upload — the play page hides the stream in a Dean-Edwards packed JS
#    (`eval(function(p,a,c,k,e,d){…})`); unpack it and regex `player.src(…)`
#    / `src:"…"`.
#  • StreamTape — the stream url is assembled at runtime:
#    `document.getElementById('…').innerHTML = 'part1' + 'part2'`.
#
#  Both fetch through tls_get (Chrome fingerprint — mp4upload sits behind
#  Cloudflare) and return AnimeDL stream dicts with correct Referers.
# ============================================================================

import re

from anime_sources.base import tls_get, DEFAULT_UA


def _packer_to_base10(s: str, separator: int) -> str:
    """Packdown: chunk digits (base `separator`, LSB-first) → base-10 string."""
    num = 0
    for idx, ch in enumerate(reversed(s)):
        num += (int(ch) if ch.isdigit() else 0) * (separator ** idx)
    return str(num)


def unpack_packed_js(data: str, key: str, load, separator) -> str:
    """Dean-Edwards `p,a,c,k,e,d` decoder — returns the FULL unpacked text.

    Same arithmetic anime-downloader's util.deobfuscate_packed_js and our
    animepahe kwik decoder use (radix ≤ 10 on the wire is kwik/mp4upload
    practice); kept here so every provider shares one implementation.
    """
    payload = []
    i = 0
    separator = int(separator)
    load = int(load)
    delim = key[separator]
    while i < len(data):
        chunk = ""
        while i < len(data) and data[i] != delim:
            chunk += data[i]
            i += 1
        for index, value in enumerate(key):
            chunk = chunk.replace(value, str(index))
        payload.append(chr(int(_packer_to_base10(chunk, separator)) - load))
        i += 1
    return "".join(payload)


_MP4UP_PACKED_RE = re.compile(r">\s*(eval\(function[\W\w]*?)</script>", re.I)
_MP4UP_SRC_RES = (
    re.compile(r'player\.src\("([^"]*)"', re.I),
    re.compile(r'src:"([^"]*)"', re.I),
    re.compile(r"player\.src\('([^']*)'", re.I),
)
_MP4UP_DELETED = ("File was deleted", "file was deleted", "not found")


def resolve_mp4upload(url: str, referer: str = None) -> list:
    """MP4Upload embed → [{'quality','url','headers'}, …] (empty on failure)."""
    out = []
    try:
        resp = tls_get(url, headers={
            "User-Agent": DEFAULT_UA, "Referer": referer or "https://www.mp4upload.com/",
        })
        soup = resp.text
        if any(m in soup for m in _MP4UP_DELETED):
            return out
        m = _MP4UP_PACKED_RE.search(soup)
        if not m:
            return out
        unpacked = _unpack_any(m.group(1))
        for rx in _MP4UP_SRC_RES:
            sm = rx.search(unpacked)
            if sm:
                out.append({
                    "quality": "auto",
                    "url": sm.group(1),
                    "headers": {"Referer": "https://www.mp4upload.com/"},
                })
                break
    except Exception:  # noqa: BLE001 — fallback host must never crash a resolve
        pass
    return out


def _unpack_any(packed_script: str) -> str:
    """Find the (p,a,c,k,e,d) args inside an eval(function…) and unpack."""
    m = re.search(r"\}\s*\(\s*'((?:[^'\\]|\\.)*)'\s*,\s*(\d+)\s*,\s*"
                  r"'((?:[^'\\]|\\.)*)'\s*,\s*(\d+)\s*,\s*(\d+)", packed_script)
    if not m:
        return ""
    data, _a, key, load, sep = m.groups()
    try:
        return unpack_packed_js(data.replace("\\'", "'"), key, load, sep)
    except Exception:  # noqa: BLE001
        return ""


# innerHTML concat: quote style varies; both parts are concatenated verbatim
_ST_RES = (
    re.compile(r"getElementById\((?:'[^']*'|\"[^\"]*\")\)\s*\.innerHTML\s*=\s*"
               r"(?:'([^']*)'\s*\+\s*'([^']*)'|\"([^\"]*)\"\s*\+\s*\"([^\"]*)\")"),
    # 2026 variant: link split across a <script> + <div id='videooutput'> pair
    re.compile(r"\.innerHTML\s*=\s*(?:'([^']*)'\s*\+\s*'([^']*)'|\"([^\"]*)\"\s*\+\s*\"([^\"]*)\")"),
)


def resolve_streamtape(url: str, referer: str = None) -> list:
    """StreamTape embed → stream dict list (empty on failure)."""
    out = []
    try:
        resp = tls_get(url, headers={
            "User-Agent": DEFAULT_UA, "Referer": referer or "https://streamtape.com/",
        })
        body = resp.text
        for rx in _ST_RES:
            m = rx.search(body)
            if not m:
                continue
            g = m.groups()
            part1 = g[0] if g[0] is not None else g[2]
            part2 = g[1] if g[1] is not None else g[3]
            if part1 and part2:
                stream = part1 + part2
                if stream.startswith("//"):
                    stream = "https:" + stream
                if stream.startswith("http"):
                    out.append({
                        "quality": "auto",
                        "url": stream,
                        "headers": {"Referer": "https://streamtape.com/"},
                    })
                    break
    except Exception:  # noqa: BLE001
        pass
    return out


def resolve_host_embed(url: str, referer: str = None) -> list:
    """Route a fallback-server embed url to the right extractor (empty list
    for hosts we don't handle)."""
    host = (url or "").split("/")[2].lower() if "://" in (url or "") else ""
    if "mp4upload" in host:
        return resolve_mp4upload(url, referer=referer)
    if host.startswith("streamtape") or host.startswith("streamta") or "streamtape" in host:
        return resolve_streamtape(url, referer=referer)
    if "voe" in host:                      # voe.sx, voeunblk.com, … (rotates)
        return resolve_voe(url, referer=referer)
    if "dood" in host or "dsvplay" in host or "d000" in host:
        return resolve_doodstream(url, referer=referer)   # dood.li, dood.watch, dooood.com…
    if "filemoon" in host or "moonplayer" in host:
        return resolve_filemoon(url, referer=referer)
    if "vidoza" in host or "videzz" in host:
        return resolve_vidoza(url, referer=referer)
    return []


def is_fallback_host(url: str) -> bool:
    """True when the embed url points at a host one of our extractors covers."""
    host = (url or "").split("/")[2].lower() if "://" in (url or "") else ""
    return any(k in host for k in (
        "mp4upload", "streamtape", "streamta.", "voe", "dood", "dsvplay",
        "d000", "filemoon", "moonplayer", "vidoza", "videzz",
    ))


# ============================================================================
#  VOE — the dominant hoster across aniworld.to / aniwave-family aggregators
#  ---------------------------------------------------------------------------
#  Port of phoenixthrush/AniWorld-Downloader voe.py (tested working 2026-01-27).
#  The embed page carries the stream JSON through up to three encodings:
#    1. <script type="application/json">"…"</script>   (JSON-string wrapped)
#    2. var a168c='<encoded>';                          (classic)
#    3. plain  'hls': '<url>'                           (already decoded)
#  Decoding chain: ROT13 → junk-tokens→'' → base64 → chr-shift(-3) →
#  reverse → base64 → JSON {"source": "<hls-url>"}.
# ============================================================================
_VOE_JUNK = ["@$", "^^", "~@", "%?", "*~", "!!", "#&"]
_VOE_B64VAR_RE = re.compile(r"var a168c='([^']+)'")
_VOE_HLS_RE = re.compile(r"'hls': '([^']+)'")
_VOE_JSON_BLOCK_RE = re.compile(
    r'<script\s+type=["\']application/json["\']>(.*?)</script>', re.S)
_VOE_REDIRECT_RE = re.compile(
    r"""['"](https?://[^'"<>\s]+/e/[^'"<>\s]+)['"]""")
_VOE_M3U8_RE = re.compile(r"https?://[^\s'\"<>]+?\.m3u8[^\s'\"<>]*")


def _rot13(s: str) -> str:
    out = []
    for c in s:
        o = ord(c)
        if 65 <= o <= 90:
            o = (o - 65 + 13) % 26 + 65
        elif 97 <= o <= 122:
            o = (o - 97 + 13) % 26 + 97
        out.append(chr(o))
    return "".join(out)


def decode_voe_string(encoded: str) -> dict:
    """Decode VOE's encoded payload into its source JSON (upstream-tested)."""
    import base64 as _b64
    step = _rot13(encoded)
    for part in _VOE_JUNK:
        step = step.replace(part, "_")
    step = step.replace("_", "")
    step = _b64.b64decode(step + "=" * (-len(step) % 4)).decode()
    step = "".join(chr(ord(c) - 3) for c in step)
    step = _b64.b64decode(step[::-1] + "=" * (-len(step[::-1]) % 4)).decode()
    import json as _json
    return _json.loads(step)


def _voe_extract(html: str):
    """All three VOE encoding variants, first hit wins."""
    for m in _VOE_JSON_BLOCK_RE.finditer(html):
        enc = m.group(1).strip()
        if enc.startswith('"') and enc.endswith('"'):
            enc = enc[1:-1]
        try:
            src = decode_voe_string(enc.encode().decode("unicode_escape")).get("source")
            if src:
                return src
        except Exception:  # noqa: BLE001 — try the next variant
            continue
    m = _VOE_B64VAR_RE.search(html)
    if m:
        try:
            src = decode_voe_string(m.group(1)).get("source")
            if src:
                return src
        except Exception:  # noqa: BLE001
            pass
    m = _VOE_HLS_RE.search(html)
    if m:
        return m.group(1)
    return None


def resolve_voe(url: str, referer: str = None) -> list:
    """VOE embed → [{'quality':'auto','url':<hls>,'headers':…}] (empty on fail)."""
    headers = {
        "User-Agent": DEFAULT_UA,
        "Referer": referer or "https://voe.sx/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        resp = tls_get(url, headers=headers)
        html = resp.text
        src = _voe_extract(html)
        if not src:
            # rotated embed domain → follow an /e/ redirect embedded in the page
            m = _VOE_REDIRECT_RE.search(html) or re.search(
                r"(?:location\.href|window\.location(?:\.href)?)\s*=\s*['\"]"
                r"(https?://[^'\"<>\s]+)['\"]", html)
            if m:
                resp2 = tls_get(m.group(1), headers=headers)
                src = _voe_extract(resp2.text)
                if not src:
                    m2 = _VOE_M3U8_RE.search(resp2.text)
                    src = m2.group(0) if m2 else None
        if not src:
            m = _VOE_M3U8_RE.search(html)
            src = m.group(0) if m else None
        if src:
            return [{"quality": "auto", "url": src,
                     "headers": {"Referer": "https://voe.sx/"}}]
    except Exception:  # noqa: BLE001 — fallback host must never crash a resolve
        pass
    return []


# ============================================================================
#  DoodStream — pass_md5 dance (port of AniWorld-Downloader doodstream.py,
#  tested working 2026-01): embed page → `$.get('…/pass_md5/<x>')` path +
#  `token=` → GET pass url (returns the base url) → append
#  <random10>?token=<token>&expiry=<now>.
# ============================================================================
_DOOD_PASS_RE = re.compile(r"\$\.get\('([^']*/pass_md5/[^']*)'")
_DOOD_TOKEN_RE = re.compile(r"token=([a-zA-Z0-9]+)")


def resolve_doodstream(url: str, referer: str = None) -> list:
    import random as _random
    import time as _time
    from urllib.parse import urljoin as _urljoin
    headers = {"User-Agent": DEFAULT_UA,
               "Referer": referer or "https://dood.li/"}
    try:
        html = tls_get(url, headers=headers).text
        m = _DOOD_PASS_RE.search(html)
        if not m:
            return []
        pass_url = m.group(1)
        if not pass_url.startswith("http"):
            host = "/".join(url.split("/")[:3])
            pass_url = host + pass_url if pass_url.startswith("/") \
                else _urljoin(host + "/", pass_url)
        t = _DOOD_TOKEN_RE.search(html)
        token = t.group(1) if t else ""
        md5_body = tls_get(pass_url, headers=headers).text.strip()
        if not md5_body:
            return []
        rnd = "".join(_random.choices(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", k=10))
        direct = f"{md5_body}{rnd}?token={token}&expiry={int(_time.time())}"
        return [{"quality": "auto", "url": direct,
                 "headers": {"Referer": "https://dood.li/"}}]
    except Exception:  # noqa: BLE001
        return []


# ============================================================================
#  Vidoza — `src: "<url>"` on the embed page (upstream-tested 2026-01-27).
# ============================================================================
_VIDOZA_SRC_RE = re.compile(r'src:\s*"([^"]+)"')


def resolve_vidoza(url: str, referer: str = None) -> list:
    try:
        html = tls_get(url, headers={
            "User-Agent": DEFAULT_UA, "Referer": referer or "https://vidoza.net/",
        }).text
        if "sourcesCode:" in html:
            m = _VIDOZA_SRC_RE.search(html)
            if m:
                return [{"quality": "auto", "url": m.group(1),
                         "headers": {"Referer": "https://vidoza.net/"}}]
    except Exception:  # noqa: BLE001
        pass
    return []


# ============================================================================
#  FileMoon — packed-JS player (standard Dean packer with 'k'.split('|')
#  word table — different arithmetic from kwik's!) + sources/file regexes.
#  Port of AniWorld-Downloader filemoon.py; the Byse AES-GCM key_parts
#  variant of the player is deliberately not ported (only reachable on the
#  renamed byse-* hosts, upstream uses it as a secondary path).
# ============================================================================
_FM_SOURCES_RE = re.compile(
    r"sources\s*:\s*\[\s*\{[^}]*file:\s*['\"]([^'\"]+)['\"]", re.S)
_FM_FILE_RE = re.compile(r"file\s*:\s*['\"](https?://[^'\"]+)['\"]")
_FM_PACKED_RE = re.compile(
    r"}\s*\(\s*'((?:[^'\\]|\\.)*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*"
    r"'((?:[^'\\]|\\.)*)'\s*\.split\s*\(\s*'\|'\s*\)", re.S)


def _unpack_standard_js(p: str, a, c, k: str) -> str:
    """Classic Dean-Edwards packer (token table split by '|')."""
    import base64 as _b64
    try:
        a = int(a)
        words = k.split("|")
        count = int(c)
    except (ValueError, TypeError):
        return p
    table = {}
    for i in range(count):
        token = ""
        n = i
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"
        while True:
            token = digits[n % a] + token
            n = n // a
            if n == 0:
                break
        table[token] = words[i] if i < len(words) and words[i] else token
    return re.sub(r"\b\w+\b", lambda m: table.get(m.group(0), m.group(0)), p)


def resolve_filemoon(url: str, referer: str = None) -> list:
    try:
        html = tls_get(url, headers={
            "User-Agent": DEFAULT_UA, "Referer": referer or "https://filemoon.sx/",
        }).text
        candidate = ""
        m = _FM_PACKED_RE.search(html)
        if m:
            p, a, c, k = m.groups()
            candidate = _unpack_standard_js(p.replace("\\'", "'"), a, c, k)
        src = None
        for rx in (_FM_SOURCES_RE, _FM_FILE_RE):
            sm = rx.search(candidate) or rx.search(html)
            if sm:
                src = sm.group(1)
                break
        if not src:
            hm = _VOE_M3U8_RE.search(html)
            src = hm.group(0) if hm else None
        if src:
            origin = "/".join(url.split("/")[:3])
            return [{"quality": "auto", "url": src,
                     "headers": {"Referer": origin + "/"}}]
    except Exception:  # noqa: BLE001
        pass
    return []
