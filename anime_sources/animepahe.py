# ============================================================================
#  AnimeDL — AnimePahe source (animepahe.si)
# ============================================================================
#  Python port of GDjkhp/otaku-watcher-contrib (WTFPL) animepahe scraper,
#  including the JS packer ("eval(function(p,a,c,k,e,d)…)") decoder used to
#  unpack the Kwik embed payload into the m3u8 link.
#
#  AnimePahe sits behind DDoS-Guard; the request carries the customary
#  empty __ddg2_ cookie. Best-effort provider.
# ============================================================================

import json
import re
from urllib.parse import quote_plus

try:
    # Chrome TLS impersonation — animepahe/DDoS-Guard reject python-requests
    # fingerprints (TLSV1_ALERT_INTERNAL_ERROR on datacenter IPs).
    from curl_cffi import requests as _c_requests
except ImportError:  # pragma: no cover
    _c_requests = None

_CURL_SESSION = None


def _curl():
    """Keep-alive impersonated session (one TLS handshake per host)."""
    global _CURL_SESSION
    if _CURL_SESSION is None and _c_requests is not None:
        _CURL_SESSION = _c_requests.Session()
    return _CURL_SESSION

import requests

from anime_sources.base import (
    http_session,
    BaseProvider, Episode, ResolvedEpisode, SearchResult, SourceError, DEFAULT_UA,
)

BASE = "https://animepahe.si"
API = f"{BASE}/api"
# .si occasionally returns empty result sets; the .ru mirror serves the
# same API and often answers when .si does not.
API_MIRRORS = [API, "https://animepahe.ru/api"]


class AnimePaheSource(BaseProvider):
    id = "animepahe"
    name = "AnimePahe"

    def _get(self, url: str, params: dict = None):
        kwargs = dict(
            params=params,
            headers={
                "User-Agent": DEFAULT_UA,
                "Referer": BASE,
                "Cookie": "__ddg2_=",
            },
            timeout=20,
        )
        if _c_requests is not None:
            # impersonated Chrome TLS stack — avoids the fingerprint block
            try:
                resp = _curl().get(url, impersonate="chrome", **kwargs)
            except Exception:  # stale pooled socket -> one fresh retry
                resp = _curl().get(url, impersonate="chrome", **kwargs)
        else:
            resp = http_session().get(url, **kwargs)
        if resp.status_code != 200:
            raise SourceError(f"AnimePahe: HTTP {resp.status_code}")
        return resp

    # ---------------------------------------------------------------- search
    def search(self, query: str) -> list:
        data = {}
        for api in API_MIRRORS:  # .si empty → retry on .ru mirror
            try:
                data = self._get(api, params={"m": "search", "q": quote_plus(query)}).json()
            except Exception:
                continue
            if (data.get("data") or []):
                break
        results = []
        for anime in data.get("data", []) or []:
            results.append(SearchResult(
                id=anime.get("session", ""),
                title=anime.get("title", "Unknown"),
                provider=self.id,
                type=f"{anime.get('episodes', 1)} eps" if anime.get("episodes") else "TV",
            ))
            if len(results) >= 10:
                break
        return results

    # -------------------------------------------------------------- episodes
    def _release_page(self, session_id: str, page: int = 1) -> dict:
        return self._get(API, params={
            "m": "release", "id": session_id, "sort": "episode_asc", "page": page,
        }).json()

    def episodes(self, anime_id: str) -> list:
        eps = []
        page = 1
        while True:
            data = self._release_page(anime_id, page)
            for item in data.get("data", []) or []:
                num = item.get("episode")
                eps.append(Episode(
                    number=str(num),
                    url=f"animepahe://{anime_id}/{item.get('session')}",
                    title=f"Episode {num}",
                ))
            next_page = (data.get("next_page") or "").lower() == "yes" or data.get("next_page") is True
            if not next_page or page >= 20:
                break
            page += 1
        try:
            eps.sort(key=lambda e: float(e.number))
        except ValueError:
            pass
        return eps

    # ---------------------------------------------------------------- resolve
    def resolve(self, url: str, mode: str = "sub") -> ResolvedEpisode:
        m = re.match(r"animepahe://([^/]+)/([^/?#]+)", url)
        if not m:
            raise SourceError("AnimePahe: could not parse episode reference")
        anime_session, ep_session = m.group(1), m.group(2)

        page = self._get(f"{BASE}/play/{anime_session}/{ep_session}").text
        m_title = re.search(r'<title>\s*(.+?)\s*-?\s*Episode', page)
        m_ep = re.search(r'Episode\s*([0-9.]+)', page)

        m_btn = re.search(r'id="resolutionMenu".*?<button[^>]*class="active"[^>]*data-src="([^"]+)"',
                          page, re.S)
        if not m_btn:
            # any quality button will do
            m_btn = re.search(r'id="resolutionMenu".*?<button[^>]*data-src="([^"]+)"', page, re.S)
        if not m_btn:
            raise SourceError("AnimePahe: no quality options on the play page")
        embed_url = m_btn.group(1)

        embed_html = self._get(embed_url).text
        video_url = self._unpack_packer(embed_html)
        if not video_url:
            raise SourceError("AnimePahe: could not unpack the m3u8 link")

        return ResolvedEpisode(
            title=m_title.group(1) if m_title else "AnimePahe",
            ep_num=m_ep.group(1) if m_ep else "1",
            streams=[{"quality": "auto", "url": video_url,
                      "headers": {"Referer": embed_url}}],
        )

    # --------------------------------------------------------- JS packer decode
    @staticmethod
    def _unpack_packer(text: str) -> str:
        """Decode `eval(function(p,a,c,k,e,d){...}` payloads (WTFPL port)."""
        pattern = (
            r"\}\('(.*)'\)*,*(\d+)*,*(\d+)*,*'((?:[^'\\]|\\.)*)'"
            r"\.split\('\|'\)*,*(\d+)*,*(\{\})"
        )
        try:
            p, a, c, k, e, _d = re.findall(pattern, text)[0]
            a, c, e = int(a), int(c), int(e)
            words = k.split("|")
        except (IndexError, ValueError):
            return ""

        def base(c_: int) -> str:
            chars = "0123456789abcdefghijklmnopqrstuvwxyz"
            out = base(c_ // a) if c_ >= a else ""
            c_ = c_ % a
            return out + (chr(c_ + 29) if c_ > 35 else chars[c_])

        table = {}
        for i in range(c):
            token = base(i)
            table[token] = words[i] if i < len(words) and words[i] else token

        unpacked = re.sub(r"\b(\w+)\b", lambda mm: table.get(mm.group(0), mm.group(0)), p)
        m = re.search(r"http.*?\.m3u8", unpacked)
        return m.group(0) if m else ""
