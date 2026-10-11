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
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _find_binary() -> str:
    candidates = [
        Path("binary") / "N_m3u8DL-RE",
        Path("binary") / "N_m3u8DL-RE.exe",
        Path("/usr/local/bin/N_m3u8DL-RE"),
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
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
        cmd = [binary, stream_url,
               "--save-dir", str(task_dir),
               "--save-name", save_name,
               *header_args,
               "--no-log"]
    else:  # ffmpeg fallback
        cmd = [binary, "-y", *header_args, "-i", stream_url,
               "-c", "copy", str(task_dir / f"{save_name}.mkv")]

    progress_queue.put({"status": f"📥 Downloading: {title}"})

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="ignore"
    )
    for line in proc.stdout or []:
        line = line.strip()
        m = re.search(r"(\d+(?:\.\d+)?)%", line)
        if m:
            progress_queue.put({
                "percent": f"{m.group(1)}%",
                "speed": (re.search(r"([\d.]+\s*[KMG]?B/s)", line) or [None, "-"])[1],
                "downloaded": "-", "total": "-",
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
