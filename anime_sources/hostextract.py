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
    return []
