# ============================================================================
#  AnimeDL — Subtitle embedding (the resolver data was there all along)
# ============================================================================
#  hianime / aniwave-family / zangetsu / remote resolvers already return
#  subtitle track URLs on ResolvedEpisode.subtitles — until v4.19.0 they were
#  parsed and then thrown away. This module:
#    1. downloads the .vtt tracks (soft-fail per track)
#    2. converts vtt → srt (ffmpeg)
#    3. muxes them into the container with -c copy (NO re-encode):
#         .mkv → -c:s srt            (best compatibility)
#         .mp4 → -c:s mov_text       (mp4 timed-text)
#    4. tags language=eng + title, replaces the file in place on success
#
#  ffmpeg locator: PATH first, then imageio-ffmpeg's static binary when
#  installed (also a safety net for hosts where apt ffmpeg is missing).
#  Strictly fail-open: any error = keep the original file. Kill-switch:
#  ANIMEDL_SUBS=0.
# ============================================================================

import logging
import os
import shutil
import subprocess

from anime_sources.base import http_session

logger = logging.getLogger(__name__)

_FFMPEG = None  # resolved once per process


def find_ffmpeg() -> str:
    """PATH → imageio-ffmpeg static binary → None (cached)."""
    global _FFMPEG
    if _FFMPEG:
        return _FFMPEG
    _FFMPEG = shutil.which("ffmpeg")
    if not _FFMPEG:
        try:
            import imageio_ffmpeg
            _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001 — optional dependency
            _FFMPEG = None
    return _FFMPEG


def _fetch_vtt(url: str, referer: str = None) -> bytes:
    headers = {"User-Agent": "Mozilla/5.0"}
    if referer:
        headers["Referer"] = referer
    resp = http_session().get(url, headers=headers, timeout=(6, 20))
    if resp.status_code != 200 or not resp.content:
        raise IOError(f"subtitle HTTP {resp.status_code}")
    if b"-->" not in resp.content and b"WEBVTT" not in resp.content[:200]:
        raise IOError("not a subtitle payload (challenge page?)")
    return resp.content


def _vtt_to_srt(ffmpeg: str, vtt_path: str, srt_path: str) -> bool:
    proc = subprocess.run(
        [ffmpeg, "-y", "-i", vtt_path, srt_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    return proc.returncode == 0 and os.path.getsize(srt_path) > 0


def embed_subtitles(video_path: str, vtt_urls: list,
                    lang: str = "eng", title: str = "English") -> bool:
    """Embed up to 2 subtitle tracks into video_path (stream-copy remux).

    Returns True when the file was rewritten with subtitle streams.
    Never raises.
    """
    try:
        if os.getenv("ANIMEDL_SUBS", "1") == "0" or not vtt_urls:
            return False
        if not video_path or not os.path.isfile(video_path):
            return False
        ext = os.path.splitext(video_path)[1].lower()
        if ext not in (".mkv", ".mp4", ".m4v"):
            return False
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            logger.info("subs: no ffmpeg available — skipping embed")
            return False

        import tempfile
        workdir = tempfile.mkdtemp(prefix="anisubs")
        srt_files = []
        try:
            for i, url in enumerate(vtt_urls[:2]):
                try:
                    data = _fetch_vtt(url)
                except Exception as e:  # noqa: BLE001 — per-track soft-fail
                    logger.info("subs: track %s failed: %s", i, e)
                    continue
                vtt = os.path.join(workdir, f"track{i}.vtt")
                srt = os.path.join(workdir, f"track{i}.srt")
                with open(vtt, "wb") as fh:
                    fh.write(data if b"WEBVTT" in data[:200]
                             else b"WEBVTT\n\n" + data)
                if not _vtt_to_srt(ffmpeg, vtt, srt):
                    continue
                srt_files.append(srt)
            if not srt_files:
                return False

            tmp_out = video_path + ".subbed" + ext
            cmd = [ffmpeg, "-y", "-i", video_path]
            for s in srt_files:
                cmd += ["-i", s]
            cmd += ["-map", "0"]
            for k in range(len(srt_files)):
                cmd += [f"-map", str(k + 1)]
            cmd += ["-c", "copy",
                    "-c:s", "mov_text" if ext in (".mp4", ".m4v") else "srt"]
            for k in range(len(srt_files)):
                cmd += [f"-metadata:s:s:{k}", f"language={lang}",
                        f"-metadata:s:s:{k}", f"title={title}"]
            # NOTE: += [tmp_out] — += tmp_out would splat the path into
            # single-character argv items and ffmpeg would exit 234.
            cmd += [tmp_out]

            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=300)
            if proc.returncode != 0 or not os.path.isfile(tmp_out) \
                    or os.path.getsize(tmp_out) < 1024:
                if os.path.isfile(tmp_out):
                    os.unlink(tmp_out)
                return False
            os.replace(tmp_out, video_path)
            logger.info("subs: %s track(s) embedded into %s",
                        len(srt_files), os.path.basename(video_path))
            return True
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    except Exception as e:  # noqa: BLE001 — feature must never break a download
        logger.info("subs: skipped (%s)", e)
        return False
