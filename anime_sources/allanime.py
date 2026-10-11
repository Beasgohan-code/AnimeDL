# ============================================================================
#  AnimeDL — AllAnime source (api.allanime.day)
# ============================================================================
#  Python port of pystardust/ani-cli v4.13.0 (GPL-3.0) allanime flow:
#    GraphQL search → episode list → episode sourceUrls (optionally AES-256-CTR
#    "tobeparsed" blobs) → hex-decoded provider paths → HLS/MP4 links.
#
#  Reference: allanime key/decoding fixed upstream in April 2026 (#1667).
#  Best-effort provider: the upstream API rotates keys; failures surface as
#  clean SourceErrors and other sources remain usable.
# ============================================================================

import base64
import logging
import hashlib
import json
import re
from typing import Optional

import requests

from anime_sources.base import (
    http_session,
    BaseProvider, Episode, ResolvedEpisode, SearchResult, SourceError, DEFAULT_UA,
)

API = "https://api.allanime.day/api"
SITE = "https://allanime.day"
EMBED_BASE = "https://embed.ssbcontent.site"   # 2026-rotation: provider JSONs live here
REFERER = "https://allanime.to"                # ani-cli 71zenith: curl -e allanime.to
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0")
SECRET = "Xot36i3lK3:v1"                      # ani-cli v4.13 key seed
AES_KEY = hashlib.sha256(SECRET.encode()).digest()

SEARCH_GQL = (
    "query( $search: SearchInput $limit: Int $page: Int "
    "$translationType: VaildTranslationTypeEnumType $countryOrigin: VaildCountryOriginEnumType ) "
    "{ shows( search: $search limit: $limit page: $page translationType: $translationType "
    "countryOrigin: $countryOrigin ) { edges { _id name availableEpisodes __typename } }}"
)
EPISODES_LIST_GQL = (
    "query ($showId: String!) { show( _id: $showId ) { _id availableEpisodesDetail }}"
)
EPISODE_EMBED_GQL = (
    "query ($showId: String!, $translationType: VaildTranslationTypeEnumType!, "
    "$episodeString: String!) { episode( showId: $showId translationType: $translationType "
    "episodeString: $episodeString ) { episodeString sourceUrls }}"
)

# Character table of the allanime path hex-encoding (from ani-cli provider_init)
HEX_TABLE = {
    "79": "A", "7a": "B", "7b": "C", "7c": "D", "7d": "E", "7e": "F", "7f": "G",
    "70": "H", "71": "I", "72": "J", "73": "K", "74": "L", "75": "M", "76": "N",
    "77": "O", "68": "P", "69": "Q", "6a": "R", "6b": "S", "6c": "T", "6d": "U",
    "6e": "V", "6f": "W", "60": "X", "61": "Y", "62": "Z",
    "59": "a", "5a": "b", "5b": "c", "5c": "d", "5d": "e", "5e": "f", "5f": "g",
    "50": "h", "51": "i", "52": "j", "53": "k", "54": "l", "55": "m", "56": "n",
    "57": "o", "48": "p", "49": "q", "4a": "r", "4b": "s", "4c": "t", "4d": "u",
    "4e": "v", "4f": "w", "40": "x", "41": "y", "42": "z",
    "08": "0", "09": "1", "0a": "2", "0b": "3", "0c": "4", "0d": "5", "0e": "6",
    "0f": "7", "00": "8", "01": "9",
    "15": "-", "16": ".", "17": "/", "02": ":", "07": "?", "1b": "#",
    "63": "[", "65": "]", "78": "@", "19": "!", "1c": "$", "1e": "&",
    "10": "(", "11": ")", "12": "*", "13": "+", "14": ",", "03": ";", "05": "=",
    "1d": "%", "67": "_", "46": "~",
}


def _hex_decode(encoded: str) -> str:
    return "".join(HEX_TABLE.get(encoded[i:i + 2], "") for i in range(0, len(encoded), 2))


def _decode_url(raw: str) -> str:
    """allanime path encodings — CURRENT (2026-10) rotation first, from
    ani-cli 71zenith: sourceUrls now start with '##' and the hex bytes are
    XOR-48 ('--' + XOR-56 was the previous rotation; kept for tolerance).
    'ap/<hex>' -> plain hex (older live-mirror scheme)."""
    if not raw:
        return raw
    for marker, key in (("##", 48), ("--", 56)):
        if raw.startswith(marker):
            try:
                return bytes(b ^ key for b in bytes.fromhex(raw[len(marker):])).decode()
            except Exception:
                pass
    if raw.startswith("ap/"):
        try:
            return bytes.fromhex(raw[3:]).decode()
        except Exception:
            pass
    return raw


CDN_BASE = "https://allanimenews.com"

SHOW_NAME_GQL = '{show(_id:"SHOW_ID"){name englishName}}'

EPISODE_INFOS_GQL = (
    "{episodeInfos(showId:\"SHOW_ID\",episodeNumStart:START,"
    "episodeNumEnd:END){vidInforssub vidInforsdub vidInforsraw}}"
)


class AllAnimeSource(BaseProvider):
    id = "allanime"
    name = "AllAnime"

    # ------------------------------------------------------------------ http
    def _gql(self, variables: dict, query: str) -> dict:
        last_exc = None
        for attempt in range(2):   # one retry for transient network blips
            try:
                resp = http_session().post(
                    API,
                    json={"variables": variables, "query": query},
                    headers={"Referer": REFERER, "Origin": REFERER, "User-Agent": UA,
                             "Content-Type": "application/json"},
                    timeout=(6, 15),
                )
                if resp.status_code != 200:
                    raise SourceError(f"AllAnime: HTTP {resp.status_code}")
                data = resp.json()
                # PROD FIX: the API answers rate-limits / blocks with a bare
                # JSON string ("Too many requests") — a .get on that raised
                # 'str' object has no attribute 'get' and killed downloads.
                # Convert to a SourceError so the engine's retry/recovery runs.
                if not isinstance(data, dict):
                    raise SourceError(
                        f"AllAnime: unexpected API payload ({type(data).__name__})")
                return data
            except requests.RequestException as e:
                last_exc = e
                import time as _t
                _t.sleep(1.2)
        raise last_exc or SourceError("AllAnime: request failed")

    @staticmethod
    def _dig(data, *keys):
        """Nested dict walk that survives junk GraphQL payloads — v4.19.1.

        The API puts STRINGS at any level when it errors/limits
        ({"data": "..."} was the live 'str'.get crash on top of the
        top-level one fixed in 4.19.0), and sometimes double-encodes
        objects as JSON strings. Any non-dict step yields {}; a
        JSON-looking string is transparently unwrapped first.
        """
        def _unwrap(v):
            if isinstance(v, str) and v[:1] in "{[":
                try:
                    return json.loads(v)
                except Exception:  # noqa: BLE001
                    return None
            return v

        cur = _unwrap(data)
        for k in keys:
            if not isinstance(cur, dict):
                return {}
            cur = _unwrap(cur.get(k))
        if isinstance(cur, (dict, list)):
            return cur
        return {}


    def _site_get(self, path: str, referer: str = None) -> str:
        resp = http_session().get(
            SITE + path if path.startswith("/") else path,
            headers={"Referer": referer or REFERER, "User-Agent": UA},
            timeout=(6, 15),
        )
        if resp.status_code != 200:
            raise SourceError(f"AllAnime: HTTP {resp.status_code}")
        return resp.text

    # ---------------------------------------------------------------- search
    def search(self, query: str) -> list:
        data = self._gql(
            {"search": {"allowAdult": False, "allowUnknown": False, "query": query},
             "limit": 20, "page": 1, "translationType": "sub", "countryOrigin": "ALL"},
            SEARCH_GQL,
        )
        results = []
        for edge in self._dig(data, "data", "shows", "edges") or []:
            if not isinstance(edge, dict):
                continue
            eps = self._dig(edge, "availableEpisodes")
            count = eps.get("sub") or eps.get("dub") or 0
            results.append(SearchResult(
                id=str(edge.get("_id", "")),
                title=edge.get("name", "Unknown"),
                provider=self.id,
                type=f"{count} eps",
            ))
        return results[:10]

    # -------------------------------------------------------------- episodes
    def episodes(self, anime_id: str) -> list:
        from anime_sources.base import cached_episodes
        return cached_episodes(f"allanime:{anime_id}", self._fetch_episodes, anime_id)

    def _fetch_episodes(self, anime_id: str) -> list:
        data = self._gql({"showId": anime_id}, EPISODES_LIST_GQL)
        show = self._dig(data, "data", "show")
        detail = self._dig(show, "availableEpisodesDetail")
        numbers = detail.get("sub") or detail.get("dub") or []
        if not isinstance(numbers, list):
            numbers = []
        eps = [
            Episode(number=str(n), url=f"allanime://{anime_id}/{n}", title=f"Episode {n}")
            for n in numbers
        ]
        try:
            eps.sort(key=lambda e: float(e.number))
        except ValueError:
            pass
        return eps

    # ---------------------------------------------------------------- resolve
    def show_name(self, show_id: str) -> str:
        """Display name for a show id (used by cross-source recovery)."""
        try:
            data = self._gql({}, SHOW_NAME_GQL.replace("SHOW_ID", show_id))
            show = self._dig(data, "data", "show")
            name = show.get("name") or show.get("englishName") or ""
            return name if isinstance(name, str) else str(name)
        except Exception:
            return ""

    def _cdn_streams(self, show_id: str, ep_num: str, mode: str) -> list:
        """Direct MP4s from the allanime CDN (episodeInfos query)."""
        try:
            epf = float(ep_num)
        except ValueError:
            return []
        q = (EPISODE_INFOS_GQL.replace("SHOW_ID", show_id)
             .replace("START", str(int(epf))).replace("END", str(int(epf))))
        try:
            data = self._gql({}, q)
        except Exception:
            return []
        infos = self._dig(data, "data", "episodeInfos")
        if not isinstance(infos, list):
            infos = []
        streams = []
        field = {"sub": "vidInforssub", "dub": "vidInforsdub"}.get(mode, "vidInforssub")
        for info in infos:
            if not isinstance(info, dict):
                continue
            for vinfo in info.get(field) or []:
                if not isinstance(vinfo, dict):
                    continue
                path = vinfo.get("vidPath", "")
                if not path:
                    continue
                url = path if path.startswith("http") else f"{CDN_BASE}/{path.lstrip('/')}"
                res = vinfo.get("vidResolution", "")
                streams.append({
                    "quality": f"{res}p" if res else "auto",
                    "url": url,
                    "headers": {"Referer": CDN_BASE + "/", "Origin": CDN_BASE},
                })
        return streams

    def resolve(self, url: str, mode: str = "sub") -> ResolvedEpisode:
        m = re.match(r"allanime://([^/]+)/([^/?#]+)", url)
        if not m:
            raise SourceError("AllAnime: could not parse episode reference")
        show_id, ep_num = m.group(1), m.group(2)

        data = self._gql(
            {"showId": show_id, "translationType": mode, "episodeString": ep_num},
            EPISODE_EMBED_GQL,
        )
        episode = self._dig(data, "data", "episode")   # survives {"data": "<str>"}
        raw_urls = episode.get("sourceUrls") or []
        if not isinstance(raw_urls, list):
            raw_urls = []
        logging.getLogger(__name__).info(
            "allanime: EP%s of %s → %d sourceUrl(s)", ep_num, show_id, len(raw_urls))

        # sourceUrl entries are marker-prefixed hex-encoded provider paths
        provider_paths = []
        for entry in raw_urls:
            if isinstance(entry, dict):
                surl = entry.get("sourceUrl", "")
                sname = entry.get("sourceName", "")
            else:
                surl, sname = str(entry), ""
            if not surl:
                continue
            if "tobeparsed" in json.dumps(entry):
                # AES-CTR encrypted payload
                surl = self._decode_tobeparsed(str(surl))
            surl = _decode_url(surl)   # '##' XOR-48 (current) / '--' XOR-56 legacy
            provider_paths.append((sname, surl))

        streams = []
        seen_referers = {}
        for sname, surl in provider_paths:
            try:
                got = self._links_from_source(surl)
                logging.getLogger(__name__).info(
                    "allanime: provider %s → %d stream(s)", sname or "?", len(got))
                for s in got:
                    seen_referers.setdefault(s.get("headers", {}).get("Referer"), True)
                streams.extend(got)
            except Exception as e:
                logging.getLogger(__name__).info(
                    "allanime: provider %s failed: %s", sname or "?", e)
                continue

        if not streams:
            # ── Direct-CDN fallback (2026 scheme): episodeInfos exposes MP4s
            # on allanimenews.com independently of the provider embeds ──
            streams = self._cdn_streams(show_id, ep_num, mode)
            logging.getLogger(__name__).info(
                "allanime: cdn fallback → %d stream(s)", len(streams))
        if not streams:
            tried = ", ".join(n or "?" for n, _ in provider_paths) or "none listed"
            raise SourceError(
                f"AllAnime: no playable links for this episode (providers tried: {tried})")

        def _q(s):
            try:
                return int(s.get("quality", 0))
            except (ValueError, TypeError):
                return 0

        return ResolvedEpisode(
            title=show_id[:24],
            ep_num=ep_num,
            streams=sorted(streams, key=_q, reverse=True),
        )

    # ------------------------------------------------------- tobeparsed (AES)
    def _decode_tobeparsed(self, blob: str) -> str:
        """ani-cli decode_tobeparsed: base64 → [1:13] IV → ctr IV+00000002 →
        ciphertext [13:-16] → AES-256-CTR."""
        from Crypto.Cipher import AES
        from Crypto.Util import Counter

        raw = base64.b64decode(blob)
        iv = raw[1:13]
        ctr = Counter.new(32 + 96, initial_value=int.from_bytes(iv + b"\x00\x00\x00\x02", "big"))
        cipher = AES.new(AES_KEY, AES.MODE_CTR, counter=ctr)
        plain = cipher.decrypt(raw[13:len(raw) - 16])
        try:
            data = json.loads(plain.decode("utf-8", errors="ignore"))
            if isinstance(data, dict) and "sourceUrl" in data:
                return data["sourceUrl"]
        except Exception:
            pass
        return plain.decode("utf-8", errors="ignore")

    # ------------------------------------------------------------------ links
    def _links_from_source(self, surl: str) -> list:
        """Fetch the provider payload and produce stream dicts."""
        # decode if the caller handed us a still-encoded path ('##' is the
        # 2026-10 rotation, '--' the previous one)
        path = surl
        if path.startswith(("##", "--")):
            path = _decode_url(path)
        if not path.startswith(("http", "/")):
            path = _hex_decode(path)
        path = path.replace("/clock", "/clock.json")

        streams = []
        if path.startswith("http") and "fast4speed" in path:
            # youtube provider — direct HLS
            streams.append({"quality": "auto", "url": path,
                            "headers": {"Referer": REFERER}})
            return streams

        # 2026-rotation (ani-cli 71zenith): provider payloads are served from
        # embed.ssbcontent.site; allanime.day stays as a fallback in case the
        # old host ever serves again.
        if path.startswith("http"):
            body = self._site_get(path)
        else:
            last_err = None
            body = None
            for base in (EMBED_BASE, SITE):
                try:
                    body = self._site_get(f"{base}{path}")
                    break
                except Exception as e:  # noqa: BLE001
                    last_err = e
            if body is None:
                raise last_err or SourceError("AllAnime: provider fetch failed")
        # wixmp repackager → direct mp4 renditions
        if "repackager.wixmp.com" in body:
            links = re.findall(r'"link":"([^"]*)".*?"resolutionStr":"([^"]*)"', body)
            for link, res in links:
                base = link.replace("repackager.wixmp.com/", "").split(".urlset")[0]
                m_opts = re.search(r",([^/]*),/mp4", link)
                if m_opts:
                    for opt in m_opts.group(1).split(","):
                        url = re.sub(r",[^/]*", opt, base, count=1)
                        streams.append({
                            "quality": re.sub(r"\D", "", res) or "auto",
                            "url": "https://" + url if not url.startswith("http") else url,
                            "headers": {"Referer": REFERER},
                        })
            return streams

        # master.m3u8 style: links + Referer inside JSON
        m_ref = re.search(r'"Referer":"([^"]*)"', body)
        referer = m_ref.group(1) if m_ref else REFERER
        links = re.findall(r'"link":"([^"]*)".*?"resolutionStr":"([^"]*)"', body)
        if not links:
            links = re.findall(r'"hls","url":"([^"]*)".*?"hardsub_lang":"en-US"', body)
            links = [(l, "auto") for l in links]
        for link, res in links:
            if link.endswith(".m3u8") or ".urlset" in link:
                streams.append({
                    "quality": re.sub(r"\D", "", res) or "auto",
                    "url": link,
                    "headers": {"Referer": referer},
                })
        return streams
