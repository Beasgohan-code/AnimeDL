# ============================================================================
#  AnimeDL — AnimePahe source (animepahe.com)
# ============================================================================
#  Rebuilt from Caylaunpredictable245/AnimePahe (core/anime_api.py, updated
#  2026-10): the site moved to animepahe.com and the play page exposes a
#  `#pickDownload` dropdown of per-quality links (kwik.cx / pahe.win). The
#  kwik page is a JS packer puzzle:
#      ("packed", a, "key", load, sep)  →  step_2/step_1  →  action + _token
#  POSTing {_token} to the action url answers 302 → Location = direct stream.
#  DDoS-Guard/Cloudflare TLS fingerprints are handled with curl_cffi Chrome
#  impersonation; the customary empty __ddg2_ cookie rides along.
# ============================================================================

import json
import re
import time
from urllib.parse import quote_plus, unquote

from bs4 import BeautifulSoup

try:
    # Chrome TLS impersonation — animepahe/kwik reject python-requests
    # fingerprints (TLSV1_ALERT_INTERNAL_ERROR on datacenter IPs).
    from curl_cffi import requests as _c_requests
except ImportError:  # pragma: no cover
    _c_requests = None

from anime_sources.base import (
    http_session, looks_like_challenge,
    BaseProvider, Episode, ResolvedEpisode, SearchResult, SourceError, DEFAULT_UA,
)

BASE = "https://animepahe.com"
API = f"{BASE}/api"
# Legacy mirrors still answer the same JSON API; .si/.ru serve when .com fails.
API_MIRRORS = [API, "https://animepahe.si/api", "https://animepahe.ru/api"]

_KWIK_RE = re.compile(r'\("([^"]+)",(\d+),"([^"]+)",(\d+),(\d+)')
_ACTION_RE = re.compile(
    r'action="([^"]+)" method="POST"><input type="hidden" name="_token"\s+value="([^"]+)')
_KWIK_LINK_RE = re.compile(r'https://kwik\.[a-z]+/f/[\w\d-]+')


def _curl():
    """Keep-alive impersonated session (one TLS handshake per host)."""
    global _CURL_SESSION
    if _CURL_SESSION is None and _c_requests is not None:
        _CURL_SESSION = _c_requests.Session()
    return _CURL_SESSION


_CURL_SESSION = None


class AnimePaheSource(BaseProvider):
    id = "animepahe"
    name = "AnimePahe"

    def _get(self, url: str, params: dict = None, referer: str = None):
        headers = {
            "User-Agent": DEFAULT_UA,
            "Referer": referer or BASE,
            "Cookie": "__ddg2_=",
        }
        session = _curl()
        if session is not None:
            kwargs = dict(params=params, headers=headers, timeout=20,
                          impersonate="chrome124")
            try:
                resp = session.get(url, **kwargs)
            except Exception:  # stale pooled socket → one fresh retry
                resp = session.get(url, **kwargs)
        else:
            resp = http_session().get(url, headers=headers, timeout=20, params=params)
        if resp.status_code != 200:
            raise SourceError(f"AnimePahe: HTTP {resp.status_code}")
        if looks_like_challenge(resp.text[:4000]):
            raise SourceError("Cloudflare challenge on animepahe")
        return resp

    # ---------------------------------------------------------------- search
    def search(self, query: str) -> list:
        data = {}
        for api in API_MIRRORS:  # .com first; .si/.ru mirror the same API
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
        from anime_sources.base import cached_episodes
        return cached_episodes(f"animepahe:{anime_id}", self._fetch_episodes, anime_id)

    def _fetch_episodes(self, anime_id: str) -> list:
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

    def show_name(self, anime_id: str) -> str:
        """Recovery hook — resolve the show title via the search API."""
        try:
            data = self._get(API, params={"m": "search", "q": anime_id[:24]}).json()
            for anime in data.get("data", []) or []:
                if anime.get("session") == anime_id:
                    return anime.get("title") or ""
        except Exception:
            pass
        return ""

    # ---------------------------------------------------------------- resolve
    def resolve(self, url: str, mode: str = "sub") -> ResolvedEpisode:
        m = re.match(r"animepahe://([^/]+)/([^/?#]+)", url or "")
        if not m:
            raise SourceError("AnimePahe: could not parse episode reference")
        anime_session, ep_session = m.group(1), m.group(2)

        page = self._get(f"{BASE}/play/{anime_session}/{ep_session}").text
        m_title = re.search(r"<title>\s*(.+?)\s*-?\s*Episode", page)
        m_ep = re.search(r"Episode\s*([0-9.]+)", page)
        title = unquote(m_title.group(1)) if m_title else "AnimePahe"

        soup = BeautifulSoup(page, "html.parser")
        links = []
        for sel in ("#pickDownload a.dropdown-item", "#downloadMenu a",
                    "a.btn-download"):
            for a in soup.select(sel):
                href = a.get("href") or a.get("data-url") or a.get("data-href")
                if not href:
                    continue
                text = a.get_text(strip=True) or ""
                m_q = re.search(r"(\d{3,4})\s*p", text, re.I)
                links.append({
                    "quality": m_q.group(1) if m_q else "auto",
                    "dub": "eng" in text.lower(),
                    "href": href,
                })
            if links:
                break
        if not links:
            raise SourceError("AnimePahe: no download options on the play page")

        # highest quality first; build streams from up to 3 working links
        def _q(l):
            try:
                return int(l["quality"])
            except (ValueError, TypeError):
                return 0
        links.sort(key=_q, reverse=True)

        streams = []
        for link in links:
            if len(streams) >= 3:
                break
            kwik_url = self._to_kwik(link["href"])
            if not kwik_url:
                continue
            stream_url = self._kwik_resolve(kwik_url)
            if not stream_url:
                continue
            streams.append({
                "quality": link["quality"],
                "audio": "dub" if link["dub"] else "sub",
                "url": stream_url,
                "headers": {"Referer": "https://kwik.cx/"},
            })
        if not streams:
            raise SourceError("AnimePahe: kwik did not yield a direct link")
        return ResolvedEpisode(
            title=title, ep_num=m_ep.group(1) if m_ep else "1", streams=streams,
        )

    # --------------------------------------------------------- kwik machinery
    def _to_kwik(self, href: str):
        """pahe.win/pahe.cx landing pages carry the real kwik link."""
        if _KWIK_LINK_RE.search(href):
            return _KWIK_LINK_RE.search(href).group(0)
        if "pahe.win" in href or "pahe.cx" in href:
            try:
                body = self._get(href, referer=BASE).text
                m = _KWIK_LINK_RE.search(body)
                return m.group(0) if m else None
            except Exception:
                return None
        return None

    def _kwik_resolve(self, kwik_url: str):
        """kwik packer decode + _token POST → direct stream url (302 Location)."""
        try:
            # warm the site cookies, then fetch the kwik page
            session = _curl()
            if session is not None:
                session.get(BASE, impersonate="chrome124", timeout=15)
                resp = session.get(kwik_url, impersonate="chrome124", timeout=20,
                                   headers={"Referer": f"{BASE}/",
                                            "User-Agent": DEFAULT_UA})
            else:
                resp = http_session().get(kwik_url, headers={
                    "User-Agent": DEFAULT_UA, "Referer": f"{BASE}/"}, timeout=20)
            m = _KWIK_RE.search(resp.text)
            if not m:
                return None
            groups = m.groups()
            if len(groups) == 5:
                data, _ign, key, load, sep = groups
            else:
                data, key, load, sep = groups
            action, token = self._kwik_unpack(data, key, load, sep)
            post_url = action if action.startswith("http") else f"https://kwik.cx{action}"
            post_headers = {
                "User-Agent": DEFAULT_UA,
                "Referer": kwik_url,
                "Origin": "https://kwik.cx",
                "Content-Type": "application/x-www-form-urlencoded",
            }
            payload = {"_token": token}
            if session is not None:
                r2 = session.post(post_url, data=payload, headers=post_headers,
                                  impersonate="chrome124", timeout=20,
                                  allow_redirects=False)
            else:
                r2 = http_session().post(post_url, data=payload,
                                         headers=post_headers, timeout=20,
                                         allow_redirects=False)
            loc = r2.headers.get("location") or r2.headers.get("Location")
            if loc:
                return loc
            if getattr(r2, "url", "") and not str(r2.url).startswith("https://kwik"):
                return str(r2.url)
            return None
        except Exception:
            return None

    # ------------------------------------------------------- JS packer decode
    @staticmethod
    def _kwik_step2(s: str, separator: int, base: int = 10) -> str:
        mapped = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/"
        numbers = mapped[:base]
        max_iter = 0
        for index, value in enumerate(reversed(s)):
            max_iter += (int(value) if value.isdigit() else 0) * (separator ** index)
        mid = ""
        while max_iter > 0:
            mid = numbers[int(max_iter % base)] + mid
            max_iter = (max_iter - (max_iter % base)) / base
        return mid or "0"

    @classmethod
    def _kwik_unpack(cls, data: str, key: str, load, separator) -> tuple:
        """Decode kwik's eval(function(p,a,c,k,e,d)) payload into (action, _token)."""
        payload = ""
        i = 0
        separator = int(separator)
        load = int(load)
        while i < len(data):
            s = ""
            while i < len(data) and data[i] != key[separator]:
                s += data[i]
                i += 1
            for index, value in enumerate(key):
                s = s.replace(value, str(index))
            payload += chr(int(cls._kwik_step2(s, separator, 10)) - load)
            i += 1
        m = _ACTION_RE.search(payload)
        if not m:
            raise SourceError("AnimePahe: kwik payload format changed")
        return m.group(1), m.group(2)
