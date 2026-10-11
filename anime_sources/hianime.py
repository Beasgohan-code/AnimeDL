# ============================================================================
#  AnimeDL — Hianime source (hianime.at)
# ============================================================================
#  Python port of pystardust/ani-cli v5.1.5 (GPL-3.0) scraping flow:
#    search → episodes → servers (ZokoAnime) → embed → window.__P XOR blob
#    → master m3u8 → quality variants (+ subtitles).
#
#  Cloudflare is bypassed via curl_cffi (curl-impersonate) with a Chrome
#  TLS fingerprint — the same trick ani-cli plays with curl-impersonate.
# ============================================================================

import base64
import html as html_mod
import json
import re

from anime_sources.base import (
    BaseProvider, Episode, ResolvedEpisode, SearchResult, SourceError, DEFAULT_UA,
)

BASE = "https://hianime.at"
XOR_KEY = b"otaku-embed-v1"          # ani-cli v5: deobfuscate_blob key
IMPERSONATE = "chrome124"


class HianimeSource(BaseProvider):
    id = "hianime"
    name = "Hianime"

    # ------------------------------------------------------------------ http
    def _get(self, url: str, headers: dict = None) -> str:
        from curl_cffi import requests as c_requests
        resp = c_requests.get(
            url,
            headers={"User-Agent": DEFAULT_UA, **(headers or {})},
            impersonate=IMPERSONATE,
            timeout=15,
        )
        if resp.status_code != 200:
            raise SourceError(f"Hianime: HTTP {resp.status_code}")
        return resp.text

    # ---------------------------------------------------------------- search
    def search(self, query: str) -> list:
        page = self._get(f"{BASE}/search?keyword={query.replace(' ', '+')}")
        if "Just a moment" in page:
            raise SourceError("Hianime is Cloudflare-blocked from this server right now.")

        # The top-10 sidebar repeats result markup — cut it off first (ani-cli)
        page = page.split('id="main-sidebar"')[0]
        page = page.replace("\n", " ").split('<div class="film-detail">')

        results = []
        for chunk in page[1:]:
            m = re.search(
                r'<h3 class="film-name">\s*<a href="[^"]*/([^"/]+)"\s+title="([^"]+)"',
                chunk,
            )
            if m:
                results.append(SearchResult(
                    id=m.group(1),
                    title=html_mod.unescape(m.group(2)).replace("&#039;", "'").replace("&quot;", '"').replace("&amp;", "&"),
                    provider=self.id,
                ))
            if len(results) >= 10:
                break
        return results

    # -------------------------------------------------------------- episodes
    def episodes(self, anime_id: str) -> list:
        # ids carry a numeric suffix: "solo-leveling-383"
        numeric_id = anime_id.rsplit("-", 1)[-1]
        page = self._get(f"{BASE}/api/theme/episode/list/{numeric_id}")
        page = page.replace("\\", "")

        eps = []
        for chunk in page.split("ep-item")[1:]:
            m_num = re.search(r'data-number="([^"]*)"', chunk)
            m_id = re.search(r'data-id="([0-9]+)"', chunk)
            if m_num and m_id:
                eps.append(Episode(
                    number=m_num.group(1),
                    url=f"{BASE}/watch/{anime_id}?ep={m_num.group(1)}",
                    data_id=m_id.group(1),
                ))
        try:
            eps.sort(key=lambda e: float(e.number))
        except ValueError:
            pass
        return eps

    # ---------------------------------------------------------------- resolve
    def resolve(self, url: str, mode: str = "sub") -> ResolvedEpisode:
        m_num = re.search(r"[?&]ep=([^&]+)", url)
        m_slug = re.search(r"/watch/([^/?]+)", url)
        if not (m_num and m_slug):
            raise SourceError("Hianime: could not parse episode URL")

        slug, ep_num = m_slug.group(1), m_num.group(1)
        numeric_id = slug.rsplit("-", 1)[-1]

        # episode list → data-id for this episode number
        listing = self._get(f"{BASE}/api/theme/episode/list/{numeric_id}").replace("\\", "")
        ep_data_id = None
        for chunk in listing.split("ep-item")[1:]:
            if re.search(rf'data-number="{re.escape(ep_num)}"', chunk):
                m = re.search(r'data-id="([0-9]+)"', chunk)
                if m:
                    ep_data_id = m.group(1)
                    break
        if not ep_data_id:
            raise SourceError("Hianime: episode not found in listing")

        # servers → ZokoAnime embed for the wanted audio mode
        servers = self._get(
            f"{BASE}/api/theme/episode/servers?episodeId={ep_data_id}"
        ).replace('\\"', '"')
        data_hash = None
        for line in servers.split("server-item"):
            if f'data-type="{mode}"' in line and 'data-server-name="ZokoAnime"' in line:
                m = re.search(r'data-hash="([^"]+)"', line)
                if m:
                    data_hash = m.group(1)
                    break
        if not data_hash:
            # fall back to the other audio mode if the preferred one is missing
            other = "dub" if mode == "sub" else "sub"
            for line in servers.split("server-item"):
                if f'data-type="{other}"' in line and 'data-server-name="ZokoAnime"' in line:
                    m = re.search(r'data-hash="([^"]+)"', line)
                    if m:
                        data_hash = m.group(1)
                        mode = other
                        break
        if not data_hash:
            raise SourceError("Hianime: no ZokoAnime server available")

        embed = base64.b64decode(data_hash).decode()
        referer = re.sub(r"^(https?://[^/]*).*", r"\1/", embed)

        # embed page → window.__P blob → XOR-deobfuscated JSON
        embed_page = self._get(embed)
        m_blob = re.search(r'window\.__P="([^"]*)"', embed_page)
        if not m_blob:
            raise SourceError("Hianime: embed payload missing")
        payload = self._deobfuscate(m_blob.group(1))
        data = json.loads(payload)

        master = re.search(r'"src":"([^"]*\.m3u8[^"]*)"', payload)
        if not master:
            raise SourceError("Hianime: no m3u8 in embed payload")

        # master playlist → quality variants
        master_url = master.group(1).replace("\\/", "/")
        streams = []
        try:
            m3u8_body = self._get(master_url, headers={"Referer": referer})
            lines = m3u8_body.splitlines()
            for i, line in enumerate(lines):
                if line.startswith("#EXT-X-STREAM-INF"):
                    m_res = re.search(r"RESOLUTION=\d+x(\d+)", line)
                    target = lines[i + 1].strip() if i + 1 < len(lines) else ""
                    if not target:
                        continue
                    from urllib.parse import urljoin
                    streams.append({
                        "quality": m_res.group(1) if m_res else "auto",
                        "url": urljoin(master_url, target),
                    })
        except Exception:
            streams.append({"quality": "auto", "url": master_url})
        if not streams:
            streams.append({"quality": "auto", "url": master_url})

        subtitles = []
        m_subs = re.search(r'"subtitles":\[(.*?)\]', payload)
        if m_subs:
            for sm in re.finditer(r'\{[^{}]*\}', m_subs.group(1)):
                s_url = re.search(r'"src":"([^"]*)"', sm.group(0))
                if s_url:
                    subtitles.append(s_url.group(1).replace("\\/", "/"))

        def _sort_key(s):
            try:
                return int(s["quality"])
            except (ValueError, TypeError):
                return 0

        return ResolvedEpisode(
            title=slug.rsplit("-", 1)[0].replace("-", " ").title(),
            ep_num=ep_num,
            streams=sorted(streams, key=_sort_key, reverse=True),
            subtitles=subtitles,
        )

    # ------------------------------------------------------------ deobfuscate
    @staticmethod
    def _deobfuscate(blob: str) -> str:
        """ani-cli v5 `deobfuscate_blob`: base64 → repeating-key XOR."""
        raw = base64.b64decode(blob)
        return bytes(b ^ XOR_KEY[i % len(XOR_KEY)] for i, b in enumerate(raw)).decode(
            "utf-8", errors="replace"
        )
