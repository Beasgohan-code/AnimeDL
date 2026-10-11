# ============================================================================
#  AnimeDL — AniWorld source (aniworld.to)
# ============================================================================
#  Python port of phoenixthrush/AniWorld-Downloader (332★, pushed 2026-10-09):
#    • search   — /search?q= series list (/anime/stream/<slug> links)
#    • episodes — series page → staffel-N season pages → episode-M links
#    • resolve  — episode page `li[data-lang-key][data-link-target]` rows;
#      language keys: 1=German Dub, 2=ENGLISH SUB, 3=German Sub, 4=English Dub
#      → follow /redirect/<id> → hoster embed → hostextract decoders
#      (VOE → FileMoon → DoodStream → Vidoza attempt order)
#  The hoster decoders are upstream-tested (2026-01) and live in
#  anime_sources/hostextract.py — shared with every other source.
# ============================================================================

import os
import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from anime_sources.base import (
    tls_get, SourceError, DEFAULT_UA,
    BaseProvider, Episode, ResolvedEpisode, SearchResult, Stream,
)

BASE = os.getenv("ANIMEDL_ANIWORLD_BASE", "https://aniworld.to")

# language preference: English Sub → English Dub → German Sub → German Dub
_LANG_PRIORITY = ("2", "4", "3", "1")
# hoster attempt order per language (all covered by hostextract)
_PROVIDER_ORDER = ("voe", "filemoon", "doodstream", "vidoza")

_EPISODE_LINK_RE = re.compile(r"data-lang-key=[\"'](\d)[\"'][^>]*data-link-target=[\"']([^\"']+)[\"']", re.I)
_H4_RE = re.compile(r"<h4>\s*([^<]+?)\s*</h4>", re.I)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


class AniWorldSource(BaseProvider):
    id = "aniworld"
    name = "AniWorld"

    def _get(self, url: str, referer: str = None):
        last = None
        for b in (BASE,):
            try:
                return tls_get(url if url.startswith("http") else b + url,
                               headers={"User-Agent": DEFAULT_UA,
                                        "Referer": referer or f"{b}/"},
                               timeout=(6, 25))
            except SourceError as e:
                last = e
        raise last or SourceError("AniWorld: fetch failed")

    # ---------------------------------------------------------------- search
    def search(self, query: str) -> list:
        resp = self._get(f"/search?q={quote_plus(query)}")
        soup = BeautifulSoup(resp.text, "html.parser")
        out, seen = [], set()
        for a in soup.find_all("a", href=True):
            m = re.match(r"^/anime/stream/([a-z0-9-]+)/?$", a["href"].split("?")[0])
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            title = (a.get("title") or a.get_text(strip=True)
                     or m.group(1).replace("-", " ")).strip()
            out.append(SearchResult(id=m.group(1), title=title, provider=self.id))
            if len(out) >= 10:
                break
        if not out:
            # markup drift: harvest ANY series-ish link — /anime/<slug>,
            # /anime/stream/<slug>, with or without trailing slash, any attr
            for m in re.finditer(
                    r'href="[^"]*?/anime/(?:stream/)?([a-z0-9][a-z0-9-]{2,})/?["\']'
                    r'[^>]*>([^<]{2,80})', resp.text, re.I):
                slug = m.group(1)
                if slug in seen or slug in ("stream", "genre", "season", "anime"):
                    continue
                seen.add(slug)
                out.append(SearchResult(
                    id=slug,
                    title=_clean(m.group(2)) or slug.replace("-", " "),
                    provider=self.id))
                if len(out) >= 10:
                    break
        return out

    # -------------------------------------------------------------- episodes
    def episodes(self, anime_id: str) -> list:
        from anime_sources.base import cached_episodes
        return cached_episodes(f"aniworld:{anime_id}", self._fetch_episodes, anime_id)

    def _season_links(self, slug: str) -> list:
        page = self._get(f"/anime/stream/{slug}").text
        links = re.findall(r'href="(/anime/stream/' + re.escape(slug) +
                           r'/staffel-\d+)"', page)
        # de-dup preserving order; fall back to season 1
        seen, out = set(), []
        for l in links:
            if l not in seen:
                seen.add(l)
                out.append(l)
        return out or [f"/anime/stream/{slug}/staffel-1"]

    def _fetch_episodes(self, slug: str) -> list:
        eps = []
        for season_path in self._season_links(slug)[:12]:
            m_s = re.search(r"staffel-(\d+)", season_path)
            season = m_s.group(1) if m_s else "1"
            page = self._get(season_path).text
            for m in re.finditer(
                    r'href="(/anime/stream/' + re.escape(slug) +
                    r'/staffel-\d+/episode-([0-9.]+)[^"]*)"', page):
                ep_num = m.group(2)
                if any(e.number == ep_num and e.title.endswith(f"S{season}")
                       for e in eps):
                    continue
                eps.append(Episode(
                    number=ep_num,
                    url=f"aniworld://{slug}/staffel-{season}/episode-{ep_num}",
                    title=f"Episode {ep_num} (S{season})",
                ))
        try:
            eps.sort(key=lambda e: (float(e.title.split("S")[-1].rstrip(")")),
                                    float(e.number)))
        except ValueError:
            pass
        return eps

    def show_name(self, anime_id: str) -> str:
        """Recovery hook: ids are slugs."""
        return (anime_id or "").replace("-", " ").strip().title()

    # ---------------------------------------------------------------- resolve
    def resolve(self, url: str, mode: str = "sub") -> ResolvedEpisode:
        m = re.match(r"aniworld://([^/?#]+)/staffel-(\d+)/episode-([0-9.]+)", url or "")
        if not m:
            raise SourceError("AniWorld: could not parse episode reference")
        slug, season, ep = m.groups()
        page = self._get(f"/anime/stream/{slug}/staffel-{season}/episode-{ep}",
                         referer=f"{BASE}/anime/stream/{slug}").text

        m_title = re.search(r"<h2>\s*<span[^>]*>([^<]+)</span>", page) or \
            re.search(r"<title>\s*([^<]+?)\s*Staffel", page)
        title = m_title.group(1).strip() if m_title else self.show_name(slug)

        # provider rows grouped by language key (target id sits on the
        # <li> OPEN tag, hoster name inside the block)
        by_lang = {}
        for lm in re.finditer(
                r'(<li[^>]*data-lang-key=["\'](\d)["\'][^>]*>)([\s\S]*?)</li>', page):
            open_tag, key, block = lm.group(1), lm.group(2), lm.group(3)
            tm = re.search(r'data-link-target=["\']([^"\']+)["\']', open_tag)
            hm = re.search(r"<h4>\s*([^<]+?)\s*</h4>", block)
            if not tm or not hm:
                continue
            by_lang.setdefault(key, []).append(
                (hm.group(1).strip().lower(), tm.group(1)))

        if not by_lang:
            raise SourceError("AniWorld: no provider links on the episode page")

        # attempt order: preferred languages first, best hosters first
        attempts = []
        for key in _LANG_PRIORITY:
            for provider_name, target in by_lang.get(key, []):
                rank = next((i for i, p in enumerate(_PROVIDER_ORDER)
                             if p in provider_name), len(_PROVIDER_ORDER))
                attempts.append((rank, key, provider_name, target))
        attempts.sort(key=lambda t: (_LANG_PRIORITY.index(t[1]) if t[1] in _LANG_PRIORITY
                                     else 9, t[0]))

        from anime_sources.hostextract import resolve_host_embed
        errors = []
        for _rank, key, pname, target in attempts[:6]:
            try:
                redir = self._get(target, referer=f"{BASE}/")
                embed = str(getattr(redir, "url", "")) or target
                if "aniworld.to" in embed:  # redirect didn't hop — use target as path
                    embed = BASE + target
                streams = resolve_host_embed(embed, referer=f"{BASE}/")
                if streams:
                    audio = "dub" if key in ("1", "4") else "sub"
                    for s in streams:
                        s.setdefault("audio", audio)
                    return ResolvedEpisode(title=title, ep_num=ep, streams=streams)
                errors.append(f"{pname}: no stream")
            except Exception as e:  # noqa: BLE001 — next provider
                errors.append(f"{pname}: {e}")
        raise SourceError("AniWorld: no hoster yielded a stream ("
                          + "; ".join(errors[:3]) + ")")
