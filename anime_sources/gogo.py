# ============================================================================
#  AnimeDL — GogoAnime source
# ============================================================================
#  Python port of justfoolingaround/animdl (GPL-3.0) gogoanime provider +
#  gogoplay AES extractor. The gogo domain rotates often — override with the
#  GOGO_BASE environment variable.
# ============================================================================

import base64
import json
import re
from urllib.parse import urljoin

import requests

from anime_sources.base import (
    BaseProvider, Episode, ResolvedEpisode, SearchResult, SourceError, DEFAULT_UA,
)
import os

AJAX_EPISODES = "https://ajax.gogo-load.com/ajax/load-list-episode"


class GogoSource(BaseProvider):
    id = "gogo"
    name = "GogoAnime"

    @property
    def bases(self) -> list:
        """Mirror chain: custom env override wins, else bid -> anitaku.bz
        (the anitaku.bz mirror comes straight from otaku-watcher-contrib's
        anitaku.py — same gogo-family paths, second domain to ride on)."""
        custom = os.getenv("GOGO_BASE")
        if custom:
            return [custom.rstrip("/")]
        return ["https://gogoanime.bid", "https://anitaku.bz"]

    @property
    def base(self) -> str:
        return self.bases[0]

    def _fetch(self, path: str, **kw) -> requests.Response:
        """GET a site-relative path, walking the mirror chain on failure."""
        last = None
        for b in self.bases:
            try:
                return self._get(f"{b}{path}", **kw)
            except (SourceError, requests.RequestException) as e:
                last = e
        raise last or SourceError("Gogo: all mirrors failed")

    def _get(self, url: str, **kw) -> requests.Response:
        resp = requests.get(url, headers={"User-Agent": DEFAULT_UA}, timeout=(6, 15), **kw)
        if resp.status_code != 200:
            raise SourceError(f"Gogo: HTTP {resp.status_code}")
        return resp

    # ---------------------------------------------------------------- search
    def search(self, query: str) -> list:
        resp = self._fetch("/search.html", params={"keyword": query})
        results = []
        for m in re.finditer(
            r'<p class="name">\s*<a href="(/category/[^"]+)"[^>]*>([^<]+)</a>', resp.text
        ):
            slug = m.group(1).split("/category/")[-1]
            results.append(SearchResult(id=slug, title=m.group(2).strip(), provider=self.id))
            if len(results) >= 10:
                break
        return results

    # -------------------------------------------------------------- episodes
    def episodes(self, anime_id: str) -> list:
        from anime_sources.base import cached_episodes
        return cached_episodes(f"gogo:{anime_id}", self._fetch_episodes, anime_id)

    def _fetch_episodes(self, anime_id: str) -> list:
        page = self._fetch(f"/category/{anime_id}").text
        m = re.search(r'<input.+?value="(\d+)" id="movie_id"', page)
        if not m:
            raise SourceError("Gogo: anime page did not expose its id")
        content_id = m.group(1)

        listing = self._get(
            AJAX_EPISODES,
            params={"ep_start": 0, "ep_end": 100000, "id": content_id},
        ).text

        eps = []
        for a, name in re.findall(
            r'<a[^>]+href="([^"]+)"[^>]*>.*?<div class="name">\s*Episode\s*([0-9.]+)',
            listing, re.S,
        ):
            eps.append(Episode(
                number=name,
                url=f"{self.base}{a.strip()}" if a.startswith("/") else a.strip(),
            ))
        try:
            eps.sort(key=lambda e: float(e.number))
        except ValueError:
            pass
        return eps

    # ---------------------------------------------------------------- resolve
    def resolve(self, url: str, mode: str = "sub") -> ResolvedEpisode:
        page = self._get(url).text
        m_embed = re.search(r'<iframe[^>]+src="([^"]+)"', page)
        if not m_embed:
            raise SourceError("Gogo: no embed iframe on episode page")
        embed_url = m_embed.group(1)
        if embed_url.startswith("//"):
            embed_url = "https:" + embed_url

        m_name = re.search(r"<h1>(.+?)</h1>", page)
        m_ep = re.search(r"-episode-([0-9.]+)", url)
        title = re.sub(r"<[^>]+>", "", m_name.group(1)).strip() if m_name else "Gogo Anime"

        streams = self._extract_gogoplay(embed_url)
        if not streams:
            raise SourceError("Gogo: no streams extracted from embed")

        def _q(s):
            try:
                return int(s.get("quality", 0))
            except (ValueError, TypeError):
                return 0

        return ResolvedEpisode(
            title=title,
            ep_num=m_ep.group(1) if m_ep else "1",
            streams=sorted(streams, key=_q, reverse=True),
        )

    # -------------------------------------------------- gogoplay AES extractor
    def _extract_gogoplay(self, embed_url: str) -> list:
        """animdl gogoplay extractor: page carries (container|videocontent)-<key>
        pairs; the encrypted data-value decrypts into encrypt-ajax params whose
        response decrypts into the source list."""
        from Crypto.Cipher import AES

        resp = self._get(embed_url)
        content = resp.content
        host = f"https://{embed_url.split('/')[2]}/"

        keys = re.findall(rb"(?:container|videocontent)-(\d+)", content)
        if len(keys) < 3:
            raise SourceError("Gogo: encryption keys not found on embed page")
        enc_key, iv, dec_key = (k for k in keys[:3])
        enc_key, iv, dec_key = enc_key, iv, dec_key

        m_data = re.search(rb'data-value="(.+?)"', content)
        if not m_data:
            raise SourceError("Gogo: encrypted data not found")

        content_id = re.search(r"id=([^&]+)", embed_url)
        content_id = content_id.group(1) if content_id else ""

        def aes_decrypt(data: bytes, key: bytes) -> bytes:
            return AES.new(key, AES.MODE_CBC, iv=iv).decrypt(
                base64.b64decode(data)
            ).strip(bytes(range(0x11)))

        def aes_encrypt(data: str) -> bytes:
            raw = data.encode()
            pad_len = 16 - (len(raw) % 16)
            raw += bytes([pad_len]) * pad_len
            return base64.b64encode(AES.new(enc_key, AES.MODE_CBC, iv=iv).encrypt(raw))

        component = aes_decrypt(m_data.group(1), enc_key).decode() + "&id={}&alias={}".format(
            aes_encrypt(content_id).decode(), content_id
        )
        component = component.split("&", 1)[1]

        ajax = self._get(
            host + "encrypt-ajax.php?" + component,
            headers={"x-requested-with": "XMLHttpRequest"},
        )
        payload = json.loads(
            aes_decrypt(ajax.json().get("data", ""), dec_key).decode(errors="ignore")
        )

        streams = []
        for bucket in ("source", "source_bk"):
            for item in payload.get(bucket, []) or []:
                m_q = re.search(r"(\d+) ?P", item.get("label", ""), re.I)
                streams.append({
                    "quality": m_q.group(1) if m_q else "auto",
                    "url": item.get("file", ""),
                    "headers": {"Referer": embed_url},
                })
        return streams
