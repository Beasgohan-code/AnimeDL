# ============================================================================
#  AnimeDL — AniWave-family source
#  (animewave.to / anikototv.to / animekaitv.to — one shared codebase)
# ============================================================================
#  Python port of the Yuzono Anikoto/AniWave extractors (Apache-2.0) as
#  shipped by Serenity-MIST/zangetsu-sources (updated 2026-10-09), including:
#    • the native VRF obfuscation (char-exchange + RC4 chain + double b64)
#    • the ajax API (/ajax/episode/list, /ajax/server, /ajax/server/list)
#    • the MegaPlay "enc" player payload: AES-256-CBC with the hardcoded key
#    • MegaUp CDN token signing (HMAC-SHA256, hardcoded key, +90s window)
#  All three mirror domains run the SAME aniwave codebase, so one provider
#  covers the family; bases are walked in order until one answers.
#  Server hosts whose streams need an Android-only segment proxy (kiwi,
#  vidplay, mewcdn plyr) are skipped exactly like upstream does.
# ============================================================================

import base64
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import parse_qs, quote, urlparse, urljoin

from bs4 import BeautifulSoup

from anime_sources.base import (
    http_session, looks_like_challenge,
    BaseProvider, Episode, ResolvedEpisode, SearchResult, SourceError, DEFAULT_UA,
)

# --- native crypto constants (from the upstream extractor, Apache-2.0) -------
_VRF_KEYS = {
    "ex1": ("AP6GeR8H0lwUz1", "UAz8Gwl10P6ReH"),
    "rc1": "ItFKjuWokn4ZpB",
    "rc2": "fOyt97QWFB3",
    "ex2": ("1majSlPQd2M5", "da1l2jSmP5QM"),
    "ex3": ("CPYvHj09Au3", "0jHA9CPYu3v"),
    "rc3": "736y1uTJpBLUX",
}
_KAI_AES_KEY = b"i?LMTAx0Q6,:}50U".ljust(32, b"\x00")   # AES-256-CBC (MegaPlay enc)
_KAI_AES_IV = b"W0;27ToaUpl_P%'c"
_MEGAUP_KEY = b"MpCdnT0k3n!9f2K#xQ7vL5mR8wN1pY4s".ljust(64, b"\x00")  # HMAC-SHA256


# --- native crypto primitives ------------------------------------------------
def _b64url(data: bytes) -> str:
    """The extractor's b64(): URL-safe alphabet, '=' padding kept."""
    return base64.urlsafe_b64encode(data).decode()


def _rc4_raw(key: str, data: bytes) -> bytes:
    """Standard RC4 keystream XOR (the JS operates on UTF-8 byte values)."""
    k = key.encode("utf-8")
    a = list(range(256))
    j = 0
    for i in range(256):
        j = (j + a[i] + k[i % len(k)]) % 256
        a[i], a[j] = a[j], a[i]
    i = j = 0
    out = bytearray()
    for b in data:
        i = (i + 1) % 256
        j = (j + a[i]) % 256
        a[i], a[j] = a[j], a[i]
        out.append(b ^ a[(a[i] + a[j]) % 256])
    return bytes(out)


def _exchange(s: str, a: str, b: str) -> str:
    out = []
    for ch in s:
        i = a.find(ch)
        out.append(ch if i < 0 else (b[i] if i < len(b) else ""))
    return "".join(out)


def vrf(s: str) -> str:
    """AniWave-family VRF: faithful port of the upstream chain."""
    s = _exchange(s, *_VRF_KEYS["ex1"])
    s = _b64url(_rc4_raw(_VRF_KEYS["rc1"], s.encode("utf-8")))
    s = _b64url(_rc4_raw(_VRF_KEYS["rc2"], s.encode("utf-8")))
    s = _exchange(s, *_VRF_KEYS["ex2"])
    s = _exchange(s, *_VRF_KEYS["ex3"])
    s = _b64url(_rc4_raw(_VRF_KEYS["rc3"], s[::-1].encode("utf-8")))
    # encodeURIComponent: only a small safe-set survives unencoded
    return quote(_b64url(s.encode("utf-8")), safe="-_.!~*'()")


def decode_player_sources(encoded: str):
    """Decrypt the MegaPlay `enc` payload (AES-256-CBC) into a JSON object."""
    s = re.sub(r"[^A-Za-z0-9+/=_-]", "", encoded or "")
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    raw = base64.b64decode(s)
    if not raw or len(raw) % 16:
        raise SourceError("AniWave: invalid encrypted source length")
    from Crypto.Cipher import AES
    pt = AES.new(_KAI_AES_KEY, AES.MODE_CBC, iv=_KAI_AES_IV).decrypt(raw)
    pad = pt[-1]
    if 1 <= pad <= 16 and pt[-pad:] == bytes([pad]) * pad:
        pt = pt[:-pad]
    return json.loads(pt.decode("utf-8", "replace"))


def sign_player_url(url: str, now: float = None) -> str:
    """Sign a MegaUp CDN url with the token its player would generate."""
    if re.search(r"[?&]token=", url or ""):
        return url
    m = re.search(r"/([a-f0-9]{32})/([a-f0-9]{32})/", url or "", re.I)
    if not m:
        return url
    msg = "{}|{}/{}".format(
        int(now if now is not None else time.time()) + 90,
        m.group(1).lower(), m.group(2).lower())
    sig = hmac.new(_MEGAUP_KEY, msg.encode("utf-8"), hashlib.sha256).digest()
    token = _b64url(msg.encode("utf-8")).rstrip("=")
    return url + ("&" if "?" in url else "?") + "token=" + token + "." + _b64url(sig).rstrip("=")


def source_files(value):
    """Normalize a getSources payload into a list of https urls."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        value = [value]
    out = []
    for x in value:
        f = x if isinstance(x, str) else (x or {}).get("file")
        if isinstance(f, str) and re.match(r"^https?://", f, re.I):
            out.append(f)
    return out


# ============================================================================
class KaiWaveSource(BaseProvider):
    id = "aniwave"
    name = "AniWave"

    # ------------------------------------------------------------------ http
    _CURL_SESSION = None

    @classmethod
    def _curl(cls):
        if cls._CURL_SESSION is None:
            try:
                from curl_cffi import requests as _c
                cls._CURL_SESSION = _c.Session()
            except ImportError:
                cls._CURL_SESSION = False
        return cls._CURL_SESSION or None

    def _get(self, url: str, referer: str = None, ajax: bool = False):
        """GET with Chrome TLS impersonation (Cloudflare-family sites)."""
        headers = {
            "User-Agent": DEFAULT_UA,
            "Referer": referer or self.bases[0] + "/",
            "Accept": "application/json, text/javascript, */*; q=0.01" if ajax
                      else "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"
        session = self._curl()
        if session is not None:
            try:
                resp = session.get(url, headers=headers, timeout=(6, 20), impersonate="chrome124")
                resp.raise_for_status()
                if looks_like_challenge(resp.text[:4000]):
                    raise SourceError(f"Cloudflare challenge on {url.split('/')[2]}")
                return resp
            except SourceError:
                raise  # real block → let _fetch walk to the next mirror
            except Exception:
                pass  # curl-level failure (DNS/TLS) → plain requests
        resp = http_session().get(url, headers=headers, timeout=(6, 20))
        if resp.status_code != 200:
            raise SourceError(f"AniWave: HTTP {resp.status_code}")
        if looks_like_challenge(resp.text[:4000]):
            raise SourceError(f"Cloudflare challenge on {url.split('/')[2]}")
        return resp

    @property
    def bases(self) -> list:
        custom = os.getenv("ANIMEDL_ANIWAVE_BASE")
        if custom:
            return [custom.rstrip("/")]
        return ["https://animewave.to", "https://anikototv.to", "https://animekaitv.to"]

    _base_used = None

    def _fetch(self, path: str, params: dict = None, referer: str = None,
               ajax: bool = False):
        """GET a site-relative path, walking the mirror family on failure."""
        last = None
        for b in self.bases:
            try:
                resp = self._get(f"{b}{path}", referer=referer, ajax=ajax, **({"params": params} if params else {}))
                self._base_used = b
                return resp
            except Exception as e:  # noqa: BLE001 — mirror walk must try all
                last = e
        raise last or SourceError("AniWave: all mirrors failed")

    def _live_base(self) -> str:
        return self._base_used or self.bases[0]

    @staticmethod
    def _result_markup(data: dict) -> str:
        """ajax endpoints return {"result": "<html>"} or {"result": {"html": …}}."""
        r = (data or {}).get("result")
        if isinstance(r, str):
            return r
        if isinstance(r, dict):
            return r.get("html") or ""
        return ""

    # ---------------------------------------------------------------- search
    @staticmethod
    def _slug_from_href(href: str) -> str:
        path = urlparse(href).path if href.startswith("http") else href
        path = re.sub(r"/ep-\d+(?:[?#].*)?$", "", path)
        m = re.search(r"/watch/([a-z0-9-]+)", path)
        if m:
            return m.group(1)
        return path.strip("/").split("/")[-1].replace("/", "-")

    def search(self, query: str) -> list:
        resp = self._fetch("/filter", params={
            "keyword": query, "page": 1, "vrf": vrf(query),
        })
        soup = BeautifulSoup(resp.text, "html.parser")
        out = []
        for card in soup.find_all("div", class_="item"):
            parent = card.parent
            if parent is None or "ani" not in (parent.get("class") or []):
                continue
            a = card.find("a", class_="name")
            if not a or not a.get("href"):
                continue
            out.append(SearchResult(
                id=self._slug_from_href(a["href"]),
                title=a.get("data-jp") or a.get_text(strip=True) or "Unknown",
                provider=self.id,
            ))
            if len(out) >= 10:
                break
        return out

    # -------------------------------------------------------------- episodes
    def episodes(self, anime_id: str) -> list:
        from anime_sources.base import cached_episodes
        return cached_episodes(f"aniwave:{anime_id}", self._fetch_episodes, anime_id)

    def _fetch_episodes(self, anime_id: str) -> list:
        page = self._fetch(f"/watch/{anime_id}").text
        m = re.search(r'data-id="(\d+)"', page) or re.search(r'data-tip="(\d+)"', page)
        if not m:
            raise SourceError("AniWave: anime id missing on watch page")
        anime_id_num = m.group(1)
        data = self._fetch(
            f"/ajax/episode/list/{anime_id_num}",
            params={"vrf": vrf(anime_id_num)}, referer=f"{self._live_base()}/watch/{anime_id}",
            ajax=True,
        ).json()
        markup = self._result_markup(data)
        if not markup:
            raise SourceError("AniWave: invalid episode response")
        soup = BeautifulSoup(markup, "html.parser")
        eps, seen = [], set()
        for a in soup.find_all("a", attrs={"data-ids": True}):
            num = a.get("data-num") or ""
            if not num or num in seen:
                continue
            seen.add(num)
            eps.append(Episode(
                number=str(num),
                url="aniwave://{}/{}?ids={}".format(
                    anime_id, num, quote(a["data-ids"], safe="")),
                title=f"Episode {num}",
            ))
        try:
            eps.sort(key=lambda e: float(e.number))
        except ValueError:
            pass
        return eps

    def show_name(self, anime_id: str) -> str:
        """Recovery hook: our ids are slugs — the readable title comes free."""
        return (anime_id or "").replace("-", " ").strip().title()

    # ---------------------------------------------------------------- resolve
    def resolve(self, url: str, mode: str = "sub") -> ResolvedEpisode:
        m = re.match(r"aniwave://([^/?#]+)/([0-9.]+)", url or "")
        if not m:
            raise SourceError("AniWave: could not parse episode reference")
        slug, num = m.group(1), m.group(2)
        ids = (parse_qs(urlparse(url).query).get("ids") or [""])[0]
        if not ids:  # URL came through recovery without server ids → re-list
            for ep in self.episodes(slug):
                if ep.number == num:
                    ids = (parse_qs(urlparse(ep.url).query).get("ids") or [""])[0]
                    break
        if not ids:
            raise SourceError("AniWave: no server ids for this episode")

        ref = f"{self._live_base()}/watch/{slug}"
        data = self._fetch("/ajax/server/list", params={"servers": ids},
                           referer=ref, ajax=True).json()
        servers = self._server_nodes(self._result_markup(data))
        # sub first, bounded — one dead mirror must not stall the resolve
        servers.sort(key=lambda s: 0 if s["kind"] == "sub" else 1)

        streams, failures = [], []
        for s in servers:
            if len(streams) >= 6:
                break
            if re.search(r"kiwi|vidplay", s["name"], re.I):
                continue  # Android-only segment proxy upstream
            try:
                r = self._fetch("/ajax/server", params={"get": s["id"]},
                                referer=ref, ajax=True).json()
                result = r.get("result")
                embed = result.get("url") if isinstance(result, dict) else result
                if not embed:
                    raise SourceError("missing embed url")
                streams.extend(self._resolve_embed(embed, s, ref))
            except Exception as e:  # noqa: BLE001
                failures.append(f"{s['name']}: {e}")
        if not streams:
            raise SourceError(
                "AniWave: no supported direct servers. " + "; ".join(failures[:3]))

        # dedupe on url+audio, keep order
        uniq, seen = [], set()
        for st in streams:
            key = (st.url, st.audio)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(st)
        return ResolvedEpisode(
            title=slug.replace("-", " ").strip().title(),
            ep_num=num,
            streams=uniq,
        )

    @staticmethod
    def _server_nodes(markup: str) -> list:
        soup = BeautifulSoup(markup or "", "html.parser")
        servers = []
        for li in soup.find_all("li"):
            a = li.find("a", attrs={"data-link-id": True})
            if not a or "download-icon" in (li.get("class") or []):
                continue
            label, p = "", li.parent
            while p is not None:
                if "type" in (p.get("class") or []):
                    lab = p.find("label")
                    label = lab.get_text(strip=True) if lab else (p.get("data-type") or "sub")
                    break
                p = p.parent
            servers.append({
                "id": a["data-link-id"],
                "name": a.get_text(strip=True) or "server",
                "kind": "dub" if re.search(r"dub", label, re.I) else "sub",
            })
        return servers

    def _resolve_embed(self, url: str, server: dict, ref: str,
                       depth: int = 0, audio: str = None) -> list:
        """Port of the upstream resolveEmbed (iframe/data-id/getSources chain)."""
        if depth > 3:
            raise SourceError("AniWave: too many nested players")
        audio = audio or server.get("kind", "sub")
        # fallback file-hosts get their own extractors (shared packer-based
        # mp4upload decode + streamtape innerHTML concat)
        embed_host = url.split("/")[2].lower() if "://" in url else ""
        if "mp4upload" in embed_host or "streamtape" in embed_host \
                or "streamta." in embed_host:
            from anime_sources.hostextract import resolve_host_embed
            return [Stream(url=s["url"], quality=s.get("quality", "auto"),
                           audio=audio, headers=s.get("headers") or {})
                    for s in resolve_host_embed(url, referer=ref)]
        if re.search(r"\.(?:m3u8|mp4)(?:[?#]|$)", url) and "/stream/" not in url:
            return [Stream(url=url, quality="auto", audio=audio,
                           headers={"Referer": ref})]
        body = self._get(url, referer=ref).text
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        m = re.search(r'data-id=["\']([^"\']+)["\']', body, re.I)
        if m:
            t = "dub" if re.search(r"/dub(?:[?#]|$)", url.split("?")[0]) else "sub"
            qid = quote(m.group(1), safe="")
            api = self._get(
                f"{host}/stream/getSources?id={qid}&id={qid}&type={t}&type={t}",
                referer=url).json()
            if isinstance(api, str):  # some mirrors return a raw JSON string
                try:
                    api = json.loads(api)
                except ValueError:
                    api = {}
            files = source_files(api.get("sources"))
            if not files and api.get("enc"):
                try:
                    files = source_files(decode_player_sources(api["enc"]))
                except Exception:  # noqa: BLE001 — fall through to next server
                    files = []
            tracks = api.get("tracks") or []
            subs = [t.get("file") for t in tracks
                    if isinstance(t, dict) and t.get("kind") == "captions" and t.get("file")]
            if not files:
                raise SourceError(f"{server['name']}: no direct stream in getSources")
            out = []
            for f in files:
                if "megaplay" in host:
                    f = sign_player_url(f)
                out.append(Stream(
                    url=f, quality="auto", audio=audio,
                    headers={"Referer": host + "/", "Origin": host},
                    subtitles=subs,
                ))
            return out
        m = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', body)
        if m:
            return self._resolve_embed(urljoin(url, m.group(1)), server, ref, depth + 1, audio)
        m = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', body)
        if m:
            return [Stream(url=m.group(0), quality="auto", audio=audio,
                           headers={"Referer": host + "/"})]
        m = re.search(r'<source[^>]+src=["\']([^"\']+)["\']', body)
        if m:
            return [Stream(url=urljoin(url, m.group(1)), quality="auto", audio=audio,
                           headers={"Referer": host + "/"})]
        raise SourceError(f"{server['name']}: no supported direct stream found")


# Stream import placed last to keep the crypto section dependency-free
from anime_sources.base import Stream  # noqa: E402
