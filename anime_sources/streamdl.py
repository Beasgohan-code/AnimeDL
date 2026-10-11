# ============================================================================
#  AnimeDL — Stream downloader for the multi-source engine
# ============================================================================
#  Runs N_m3u8DL-RE (or falls back to ffmpeg) on resolved stream URLs with
#  provider-specific headers, reports progress through the same queue format
#  the anime core's upload pipeline already understands:
#
#      {'status': str}
#      {'percent': '62%', 'speed': …, 'downloaded': …, 'total': …, 'type': 'sub'}
#      {'finished': True, 'filename': path, 'title': str}
#      {'error': str}
# ============================================================================

import os
import re
import shutil
import subprocess
import threading
import time
from functools import lru_cache
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


@lru_cache(maxsize=4)
def _binary_version(binary: str) -> tuple:
    """(major, minor) of a downloader binary, or () when undetectable.
    Cached once per process — one --version spawn per binary."""
    try:
        out = subprocess.run([binary, "--version"], capture_output=True,
                             text=True, timeout=15).stdout
        m = re.search(r"(\d+)\.(\d+)", out)
        return (int(m.group(1)), int(m.group(2))) if m else ()
    except Exception:
        return ()


def _find_binary() -> str:
    """Locate a usable downloader binary.

    is_file() alone is NOT enough — a binary that lost its exec bit (zip
    extraction, some Docker COPY paths) passes is_file() but every spawn
    dies with PermissionError, which used to break ALL downloads. We now
    verify executability, try to chmod the repo binary back to life, and
    only then fall through to PATH (N_m3u8DL-RE → ffmpeg).
    """
    candidates = [
        Path("binary") / "N_m3u8DL-RE",
        Path("binary") / "N_m3u8DL-RE.exe",
        Path("/usr/local/bin/N_m3u8DL-RE"),
    ]
    for p in candidates:
        if not p.is_file():
            continue
        if os.access(p, os.X_OK):
            return str(p)
        try:  # best-effort repair — deploy pipelines sometimes drop the bit
            p.chmod(p.stat().st_mode | 0o111)
            if os.access(p, os.X_OK):
                return str(p)
        except OSError:
            pass
    found = shutil.which("N_m3u8DL-RE") or shutil.which("ffmpeg")
    if not found:
        raise FileNotFoundError("Neither N_m3u8DL-RE nor ffmpeg found")
    return found


def download_stream(stream_url: str, headers: dict, task_dir: Path, save_name: str,
                    title: str, progress_queue, dl_type: str = "sub") -> str:
    """Download one stream (m3u8/mp4) and return the final file path."""
    task_dir.mkdir(parents=True, exist_ok=True)
    binary = _find_binary()
    is_re = "N_m3u8DL-RE" in binary

    header_args = []
    all_headers = {"User-Agent": UA, **(headers or {})}
    for k, v in all_headers.items():
        if v:
            header_args += ["-H", f"{k}: {v}"] if is_re else ["-headers", f"{k}: {v}\r\n"]

    if is_re:
        # Speed: the binary defaults to 2 download threads — raise to 16,
        # retry segments harder, skip interactive prompts (a prompt would
        # hang the pipeline), and pull audio/video/sub tracks concurrently.
        # v0.6+ also knows --disable-update-check (a headless bot must not
        # phone home before every download); older builds don't have it.
        cmd = [binary, stream_url,
               "--save-dir", str(task_dir),
               "--save-name", save_name,
               *header_args,
               "--thread-count", "16",
               "--download-retry-count", "5",
               "--auto-select",
               "-mt",
               "--no-log"]
        if _binary_version(binary) >= (0, 6):
            cmd.append("--disable-update-check")
    else:  # ffmpeg fallback
        cmd = [binary, "-y", *header_args, "-i", stream_url,
               "-c", "copy", str(task_dir / f"{save_name}.mkv")]

    progress_queue.put({"status": f"📥 Downloading: {title}"})

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="ignore"
    )

    # Stall watchdog: a hung stream (dead CDN, stuck handshake) used to sit
    # forever holding one of the few global download slots, so every new
    # tap queued invisibly behind zombies. No output for 5 min -> kill it;
    # the non-zero exit then routes to the retry/fallback path.
    last_line = [time.time()]
    STALE_AFTER = 300

    def _stall_watchdog():
        while proc.poll() is None:
            if time.time() - last_line[0] > STALE_AFTER:
                try:
                    proc.kill()
                except OSError:
                    pass
                return
            time.sleep(10)

    threading.Thread(target=_stall_watchdog, daemon=True).start()

    for line in proc.stdout or []:
        line = line.strip()
        last_line[0] = time.time()
        m = re.search(r"(\d+(?:\.\d+)?)%", line)
        if m:
            m_size = re.search(r"([\d.]+)\s*([KMG]?B)\s*/\s*([\d.]+)\s*([KMG]?B)", line)
            progress_queue.put({
                "percent": f"{m.group(1)}%",
                "speed": (re.search(r"([\d.]+\s*[KMG]?B/s)", line) or [None, "-"])[1],
                "downloaded": f"{m_size.group(1)}{m_size.group(2)}" if m_size else "-",
                "total": f"{m_size.group(3)}{m_size.group(4)}" if m_size else "-",
                "type": dl_type, "title": title,
            })

    code = proc.wait()
    if code != 0 and is_re:
        # retry once with ffmpeg if N_m3u8DL-RE failed
        proc = subprocess.run(
            ["ffmpeg", "-y", *header_args, "-i", stream_url, "-c", "copy",
             str(task_dir / f"{save_name}.mkv")],
            capture_output=True, text=True,
        )
        code = proc.returncode

    if code != 0:
        raise RuntimeError(f"Download failed (exit {code})")

    # locate the produced file
    for pattern in (f"{save_name}.*", "*.mkv", "*.mp4", "*.ts"):
        matches = sorted(task_dir.glob(pattern))
        video = next((p for p in matches if p.suffix.lower()
                      in (".mkv", ".mp4", ".ts", ".m4a")), None)
        if video:
            return str(video)
    raise RuntimeError("Download finished but no output file found")
