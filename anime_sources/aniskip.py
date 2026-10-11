# ============================================================================
#  AnimeDL — AniSkip intro/outro chapters (ported from AniWorld-Downloader)
# ============================================================================
#  phoenixthrush/AniWorld-Downloader's aniskip module (aniskip.py + jikan.py):
#    • Jikan v4  — api.jikan.moe/v4/anime?q=<title>&type=tv → MAL id
#    • AniSkip   — api.aniskip.com/v1/skip-times/<mal>/<ep>?types=op&types=ed
#                  → results[].interval.start_time/end_time (seconds)
#    • chapters  — FFMETADATA1 ([CHAPTER] TIMEBASE=1/1000 START/END ms)
#
#  Application for a Telegram bot: instead of mpv flags, the intro/outro
#  intervals are muxed into the downloaded mkv as CHAPTERS (ffmpeg -c copy
#  remux — no re-encode, a few seconds). Players (VLC/mpv/Infuse) then show
#  skippable "OP"/"ED" chapter markers.
#
#  Strictly fail-open: any error = keep the original file. Disabled with
#  ANIMEDL_ANISKIP=0. MAL-id lookups are cached in-process for 24h.
# ============================================================================

import logging
import os
import re
import subprocess
import tempfile
import time

from anime_sources.base import http_session

logger = logging.getLogger(__name__)

JIKAN_SEARCH = "https://api.jikan.moe/v4/anime"
ANISKIP_API = "https://api.aniskip.com/v1/skip-times/{}/{}?types=op&types=ed"

_MAL_CACHE = {}          # title.lower() → (mal_id, ts)
_MAL_TTL = 86400
_SKIP_CACHE = {}         # (mal_id, ep) → (results, ts)
_SKIP_TTL = 86400


def _get_json(url: str, params: dict = None, timeout: int = 12):
    resp = http_session().get(url, params=params, timeout=timeout)
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def mal_id_for_title(title: str):
    """Jikan TV-series search → first mal_id (popularity order), 24h cached."""
    key = re.sub(r"\s+", " ", (title or "").lower()).strip()
    if not key:
        return None
    hit = _MAL_CACHE.get(key)
    if hit and time.time() - hit[1] < _MAL_TTL:
        return hit[0]
    data = _get_json(JIKAN_SEARCH, params={
        "q": key, "type": "tv", "limit": 5,
        "order_by": "popularity", "sort": "asc", "sfw": "true",
    })
    mal_id = None
    for item in (data or {}).get("data", []) or []:
        mid = item.get("mal_id")
        if mid:
            mal_id = mid
            break
    if len(_MAL_CACHE) > 256:
        _MAL_CACHE.pop(next(iter(_MAL_CACHE)))
    _MAL_CACHE[key] = (mal_id, time.time())
    return mal_id


def skip_times(mal_id: int, episode: int):
    """AniSkip op/ed intervals for one episode, 24h cached. None if unfound."""
    if not mal_id or not episode:
        return None
    try:
        ep = int(float(episode))
    except (ValueError, TypeError):
        return None
    key = (mal_id, ep)
    hit = _SKIP_CACHE.get(key)
    if hit and time.time() - hit[1] < _SKIP_TTL:
        return hit[0]
    data = _get_json(ANISKIP_API.format(mal_id, ep))
    results = None
    if isinstance(data, dict) and data.get("found") is True:
        results = [
            {"start": float(r["interval"]["start_time"]),
             "end": float(r["interval"]["end_time"]),
             "type": str(r.get("skip_type", "op")).upper()}
            for r in data.get("results", [])
            if isinstance(r, dict) and "interval" in r
        ] or None
    if len(_SKIP_CACHE) > 256:
        _SKIP_CACHE.pop(next(iter(_SKIP_CACHE)))
    _SKIP_CACHE[key] = (results, time.time())
    return results


def _mux_chapters(video_path: str, results: list, ffmpeg_bin: str = "ffmpeg") -> bool:
    """Write FFMETADATA chapters and remux (-c copy) into video_path."""
    with tempfile.NamedTemporaryFile("w", suffix=".ffmeta", delete=False) as fh:
        fh.write(";FFMETADATA1\n")
        for r in results:
            fh.write(
                "[CHAPTER]\nTIMEBASE=1/1000\nSTART={}\nEND={}\nTITLE={}\n".format(
                    round(r["start"] * 1000), round(r["end"] * 1000), r["type"]))
        meta = fh.name
    tmp_out = video_path + ".chapters.mkv"
    try:
        # -c copy alone breaks when the input is an .mp4 carrying mov_text
        # subtitles (matroska can't copy them) — convert text subs to srt on
        # the way in. Inputs without subs are unaffected.
        proc = subprocess.run(
            [ffmpeg_bin, "-y", "-i", video_path, "-i", meta,
             "-map", "0", "-map_metadata", "1", "-c", "copy", "-c:s", "srt",
             tmp_out],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
        if proc.returncode == 0 and os.path.getsize(tmp_out) > 0:
            os.replace(tmp_out, video_path)
            return True
        return False
    except Exception:  # noqa: BLE001 — strictly fail-open
        return False
    finally:
        try:
            os.unlink(meta)
        except OSError:
            pass
        if os.path.exists(tmp_out):
            try:
                os.unlink(tmp_out)
            except OSError:
                pass


def maybe_add_chapters(video_path: str, title: str, ep_num) -> bool:
    """Entry point: add OP/ED chapters to a finished download when possible.

    Returns True when chapters were muxed in. Never raises; costs at most
    two cached API calls + one stream-copy remux when it succeeds.
    """
    if os.getenv("ANIMEDL_ANISKIP", "1") == "0":
        return False
    if not video_path or not os.path.isfile(video_path):
        return False
    if not video_path.lower().endswith((".mkv", ".mp4", ".m4v", ".ts")):
        return False
    try:
        # locate ffmpeg the same way the rest of the pipeline does (PATH →
        # imageio static) — a bare shutil.which misses hosts without apt ffmpeg
        try:
            from anime_sources.subtitles import find_ffmpeg
            ffmpeg_bin = find_ffmpeg()
        except Exception:  # noqa: BLE001
            ffmpeg_bin = None
        if not ffmpeg_bin:
            return False
        mal = mal_id_for_title(title)
        if not mal:
            return False
        results = skip_times(mal, ep_num)
        if not results:
            return False
        ok = _mux_chapters(video_path, results, ffmpeg_bin)
        if ok:
            logger.info("aniskip: %s chapters added for %s EP%s",
                        len(results), title, ep_num)
        return ok
    except Exception as e:  # noqa: BLE001 — feature must never break a download
        logger.info("aniskip: skipped (%s)", e)
        return False


def shutil_which(name: str):
    from shutil import which
    return which(name)
