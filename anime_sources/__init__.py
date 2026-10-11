# ============================================================================
#  AnimeDL — Multi-source anime engine
# ============================================================================
#  One import away from every anime source the bot supports:
#
#      from anime_sources import get_provider, download_episode
#
#  Sources (in-process): hianime.at, api.allanime.day, GogoAnime, AnimePahe
#  Sources (remote):     Consumet-compatible & Aniwatch-API REST servers
#  Legacy sources:       Animetsu & AniWatch (cantarella scrapers, unchanged)
# ============================================================================

import logging
import os
import re
from pathlib import Path

import requests

from anime_sources.base import (  # noqa: F401
    BaseProvider, Episode, ResolvedEpisode, SearchResult, SourceError,
    Stream, get_provider, is_provider_url, provider_id_for_url,
    next_episode_url, SOURCE_CYCLE, SOURCE_NAMES,
)
from anime_sources.streamdl import download_stream  # noqa: F401

logger = logging.getLogger(__name__)


def search_provider(provider_id: str, query: str) -> list:
    """Search one provider; returns dicts shaped like the legacy scrapers'
    results so the Telegram layer needs no special casing."""
    try:
        provider = get_provider(provider_id)
        return [
            {
                "title": r.title,
                # namespaced ids flow through the existing callback chain
                "id": f"{provider_id}:{r.id}",
                "type": f"{provider.name} · {r.type}" if r.type else provider.name,
                "provider": provider_id,
            }
            for r in provider.search(query)
        ]
    except Exception as e:
        logger.warning("search on %s failed: %s", provider_id, e)
        return []


def list_provider_episodes(provider_id: str, anime_id: str) -> list:
    """List episodes for a provider anime; returns legacy entry dicts
    ({'title', 'number', 'url', 'type'})."""
    provider = get_provider(provider_id)
    entries = []
    for ep in provider.episodes(anime_id):
        entries.append({
            "title": ep.title or f"Episode {ep.number}",
            "number": ep.number,
            "url": ep.url,
            "type": provider.name,
        })
    return entries


def download_provider_episode(url: str, download_path: Path, progress_queue,
                              quality: str = "auto", name_override: str = None,
                              season_override: str = None,
                              ep_num_override: str = None,
                              title_fallback: str = None,
                              ep_num_fallback: str = None) -> bool:
    """Resolve + download one episode from any provider, emitting the
    progress-queue contract used by cantarella's upload pipeline.

    Returns True when at least one file was handed to the queue.
    """
    provider_id = provider_id_for_url(url)
    provider = get_provider(provider_id)

    # Retry the resolve step once — embed/server pages fail transiently
    # (Cloudflare interstitials, AJAX blips), and a batch/auto run should
    # not lose an episode to a one-off hiccup.
    resolved = None
    from anime_sources.base import SourceError as _SE, cached_streams as _cs
    for _attempt in range(2):
        try:
            # cache-hit when the quality menu prefetched this episode already
            resolved = _cs(f"res:{provider_id}:{url}", provider.resolve, url)
            break
        except (_SE, requests.RequestException) as e:
            if _attempt:
                raise
            logging.getLogger(__name__).info(
                "resolve failed for %s (%s) — retrying once", url, e
            )
            import time as _t
            _t.sleep(1.5)
    if resolved is None:
        raise _SE(f"resolve failed for {url}")
    title = name_override or resolved.title or title_fallback or "Anime"
    ep_num = str(ep_num_override or resolved.ep_num or ep_num_fallback or "1")
    season = str(season_override or resolved.season or "1")

    def sanitize(name: str) -> str:
        return re.sub(r'[\\/*?:"<>|]', "", name)

    def pick(streams, wanted: str):
        if wanted.isdigit():
            for s in streams:
                if str(s.get("quality")) == wanted:
                    return s
        return streams[0] if streams else None

    qual_str = quality if quality in ("360", "720", "1080") else "auto"
    task_dir = download_path / f"{provider_id}_{sanitize(title)[:40]}_{ep_num}_{qual_str}"
    task_dir.mkdir(parents=True, exist_ok=True)

    from config import FORMAT as _F  # re-read inside thread-safe scope
    base_name = sanitize(_F.format(
        season=season, episode=ep_num, title=title,
        quality=f"{qual_str}p", audio="JP",
    ))

    stream = pick(resolved.streams, quality if quality.isdigit() else "")
    if not stream:
        progress_queue.put({"error": f"No {qual_str} stream available."})
        return False

    save_name = f"{base_name}_{provider_id}"
    try:
        final_path = download_stream(
            stream_url=stream["url"],
            headers=stream.get("headers") or {},
            task_dir=task_dir,
            save_name=save_name,
            title=f"{title} [EP {ep_num}]",
            progress_queue=progress_queue,
        )

        # rename to the canonical format name (keep extension)
        final_file = download_path / f"{base_name}{Path(final_path).suffix}"
        try:
            os.replace(final_path, final_file)
        except Exception:
            final_file = Path(final_path)

        progress_queue.put({
            "finished": True,
            "filename": str(final_file),
            "title": f"{base_name}",
        })
        return True
    except Exception as e:
        progress_queue.put({"error": f"{provider.name}: {e}"})
        return False


import os  # noqa: E402  (used in download_provider_episode)
import re  # noqa: F402
