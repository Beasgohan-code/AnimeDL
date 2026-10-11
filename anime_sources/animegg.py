# ============================================================================
#  AnimeDL — AnimeGG source (animegg.org)
# ============================================================================
#  Python port of walterwhite-69/Anivexa-API's animegg provider (2026-10-10):
#    • search  — /search/?q= returns `class="mse"` series links; a compact
#                alphanumeric token query ("Re:Zero" → "ReZero") surfaces the
#                season variants, merged in
#    • series  — /series/<slug> <li> blocks carry `anm_det_pop` episode links
#                with btn-subbed / btn-dubbed badges
#    • watch   — episode page exposes <a data-toggle="tab" data-id=…> embed
#                tabs per server/audio; /embed/<id> carries a
#                `var videoSources = [...]` JSON array (file/label/bk backup)
#  animegg.org is a long-stable host with no aggressive bot protection —
#  this is the most likely source to "just work" as a fallback.
# ============================================================================

import base64
import json
import os
import re
from urllib.parse import unquote

from anime_sources.base import (
    http_session,
    BaseProvider, Episode, ResolvedEpisode, SearchResult, SourceError, DEFAULT_UA,
)

BASE = os.getenv("ANIMEDL_ANIMEGG_BASE", "https://www.animegg.org")

_MSE_RE = re.compile(r'<a\b[^>]*class=["\'][^"\']*\bmse\b[^"\']*["\'][^>]*>([\s\S]*?)</a>', re.I)
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
_STRONG_RE = re.compile(r"<strong[^>]*>([\s\S]*?)</strong>", re.I)
_TAB_RE = re.compile(r"<a\b[^>]*data-toggle=[\"']tab[\"'][^>]*>", re.I)
_ATTR_RE = re.compile(r'data-(id|mirror|version)=["\']([^"\']*)["\']', re.I)
_SOURCES_RE = re.compile(r"var\s+videoSources\s*=\s*(\[[\s\S]*?\]);")


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def _parse_video_sources(js_array: str) -> list:
    """The embed sources array is JSON-with-JS-isms: unquoted keys + single
    quotes. Same normalization the upstream port applies."""
    js = re.sub(r"([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'\1"\2":', js_array)
    js = re.sub(r":\s*'([^']*)'", r': "\1"', js)
    try:
        data = json.loads(js)
    except ValueError:
        return []
    out = []
    for s in data if isinstance(data, list) else []:
        if not isinstance(s, dict):
            continue
        file = s.get("file") or ""
        if file and not file.startswith("http"):
            file = f"{BASE}{file}"
        backup = None
        bk = s.get("bk")
        if bk:
            try:
                backup = unquote(base64.b64decode(bk).decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001 — backup is best-effort
                backup = None
        m_q = re.search(r"(\d{3,4})", str(s.get("label") or ""))
        out.append({
            "quality": m_q.group(1) if m_q else "auto",
            "url": file,
            "backup": backup,
        })
    return [s for s in out if s["url"]]


class AnimeGGSource(BaseProvider):
    id = "animegg"
    name = "AnimeGG"

    def _get(self, url: str, referer: str = None):
        resp = http_session().get(
            url,
            headers={"User-Agent": DEFAULT_UA, "Referer": referer or f"{BASE}/"},
            timeout=(6, 20),
        )
        if resp.status_code != 200:
            raise SourceError(f"AnimeGG: HTTP {resp.status_code}")
        return resp

    # ---------------------------------------------------------------- search
    def _search_once(self, query: str) -> list:
        body = self._get(f"{BASE}/search/", params={"q": query}).text
        results = []
        for m in _MSE_RE.finditer(body):
            inner = m.group(1)
            href = _HREF_RE.search(m.group(0))
            if not href:
                continue
            sm = re.match(r"^/series/([^/?#]+)", href.group(1))
            if not sm:
                continue
            strong = _STRONG_RE.search(inner)
            results.append({
                "slug": sm.group(1),
                "text": _strip_tags(strong.group(1)) if strong
                        else sm.group(1).replace("-", " "),
            })
            if len(results) >= 10:
                break
        return results

    def search(self, query: str) -> list:
        results = self._search_once(query)
        # AnimeGG needs a plain alphanumeric token to surface all season
        # variants: "Re:Zero" → 0 results, "ReZero" → every slug.
        compact = re.sub(r"[^a-zA-Z0-9]", "", (query or "").split(" ")[0] if query else "")
        if len(compact) >= 4 and compact.lower() != (query or "").lower():
            try:
                seen = {r["slug"] for r in results}
                for r in self._search_once(compact):
                    if r["slug"] not in seen:
                        results.append(r)
            except Exception:  # noqa: BLE001 — extra query is best-effort
                pass
        return [SearchResult(id=r["slug"], title=r["text"], provider=self.id)
                for r in results[:10]]

    # -------------------------------------------------------------- episodes
    def episodes(self, anime_id: str) -> list:
        from anime_sources.base import cached_episodes
        return cached_episodes(f"animegg:{anime_id}", self._fetch_episodes, anime_id)

    def _fetch_episodes(self, slug: str) -> list:
        body = self._get(f"{BASE}/series/{slug}").text
        eps, seen = [], set()
        for m in re.finditer(r"<li\b[^>]*>([\s\S]*?)</li>", body):
            block = m.group(1)
            if "anm_det_pop" not in block:
                continue
            link = re.search(
                r'<a\b[^>]*class=["\'][^"\']*anm_det_pop[^"\']*["\'][^>]*>', block, re.I)
            if not link:
                continue
            href = _HREF_RE.search(link.group(0))
            if not href:
                continue
            href = re.sub(r"^/|#.*$", "", href.group(1))
            strong = _strip_tags(_STRONG_RE.search(block).group(1)) \
                if _STRONG_RE.search(block) else ""
            rng = re.search(r"(\d+)-(\d+)\s*$", strong)
            num_m = rng or re.search(r"(\d+)\s*$", strong)
            if not num_m:
                continue
            number = int(num_m.group(1))
            if number in seen:
                continue
            seen.add(number)
            title = re.search(
                r'<i\b[^>]*class=["\'][^"\']*anititle[^"\']*["\'][^>]*>([\s\S]*?)</i>',
                block, re.I)
            eps.append(Episode(
                number=str(number),
                url=f"animegg://{href}",
                title=_strip_tags(title.group(1)) if title else strong or f"Episode {number}",
            ))
        try:
            eps.sort(key=lambda e: float(e.number))
        except ValueError:
            pass
        return eps

    def show_name(self, anime_id: str) -> str:
        """Recovery hook: ids are slugs (or episode hrefs)."""
        base = re.sub(r"animegg://", "", anime_id or "")
        base = re.sub(r"-episode-\d+$", "", base.split("/")[-1])
        return base.replace("-", " ").strip().title()

    # ---------------------------------------------------------------- resolve
    def resolve(self, url: str, mode: str = "sub") -> ResolvedEpisode:
        href = re.sub(r"^animegg://", "", url or "").lstrip("/")
        if not href:
            raise SourceError("AnimeGG: could not parse episode reference")
        page = self._get(f"{BASE}/{href}").text

        m_title = re.search(
            r'<div\b[^>]*class=["\'][^"\']*\binfo\b[^"\']*["\'][^>]*>[\s\S]*?<a[^>]*>([\s\S]*?)</a>',
            page)
        title = _strip_tags(m_title.group(1)) if m_title else self.show_name(href)
        m_ep = re.search(r"-episode-([0-9.]+)", href)

        tabs = []
        for m in _TAB_RE.finditer(page):
            attrs = dict(_ATTR_RE.findall(m.group(0)))
            embed_id = attrs.get("id")
            if not embed_id:
                continue
            version = attrs.get("version") or "subbed"
            tabs.append({
                "embed_id": embed_id,
                "audio": "dub" if version.startswith("dub") else "sub",
                "server": attrs.get("mirror") or "AnimeGG",
            })
        if not tabs:
            raise SourceError("AnimeGG: no embed tabs on the episode page")
        # subs first, bounded — a dead embed must not stall the resolve
        tabs.sort(key=lambda t: 0 if t["audio"] == "sub" else 1)

        streams = []
        for tab in tabs[:3]:
            try:
                embed = self._get(f"{BASE}/embed/{tab['embed_id']}",
                                  referer=f"{BASE}/").text
            except Exception:  # noqa: BLE001 — next embed
                continue
            m = _SOURCES_RE.search(embed)
            if not m:
                continue
            for s in _parse_video_sources(m.group(1)):
                streams.append({
                    "quality": s["quality"],
                    "url": s["url"],
                    "audio": tab["audio"],
                    "headers": {"Referer": f"{BASE}/"},
                })
            if len(streams) >= 3:
                break
        if not streams:
            raise SourceError("AnimeGG: no videoSources in any embed")

        uniq, seen = [], set()
        for st in streams:
            key = (st["url"], st["audio"])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(st)

        def _q(s):
            try:
                return int(s["quality"])
            except (ValueError, TypeError):
                return 0
        uniq.sort(key=_q, reverse=True)
        return ResolvedEpisode(
            title=title or "AnimeGG",
            ep_num=m_ep.group(1) if m_ep else "1",
            streams=uniq,
        )
