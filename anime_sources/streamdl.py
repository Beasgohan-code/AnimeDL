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
            # ABSOLUTE: the downloader child runs with cwd=task_dir, a
            # relative path would resolve against the task dir and vanish
            return str(p.resolve())
        try:  # best-effort repair — deploy pipelines sometimes drop the bit
            p.chmod(p.stat().st_mode | 0o111)
            if os.access(p, os.X_OK):
                return str(p.resolve())
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

    # N_m3u8DL-RE shells out to ffmpeg for the final merge. When ffmpeg
    # isn't on PATH (minimal images), hand the child an env whose PATH
    # includes the imageio-ffmpeg static binary's directory if available.
    env = None
    try:
        from anime_sources.subtitles import find_ffmpeg
        ff = find_ffmpeg()
        if ff and os.path.dirname(ff):
            env = dict(os.environ)
            env["PATH"] = os.path.dirname(ff) + os.pathsep + env.get("PATH", "")
    except Exception:  # noqa: BLE001
        env = None

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
        # The binary shells out to ffmpeg for the final merge and exits
        # (code 8) when it can't find an executable literally named ffmpeg —
        # hand it the located static binary explicitly.
        try:
            from anime_sources.subtitles import find_ffmpeg
            _ff = find_ffmpeg()
        except Exception:  # noqa: BLE001
            _ff = None
        if _ff:
            cmd += ["--ffmpeg-binary-path", _ff]
    else:  # ffmpeg fallback
        try:
            from anime_sources.subtitles import find_ffmpeg
            ffmpeg_bin = find_ffmpeg() or "ffmpeg"
        except Exception:  # noqa: BLE001
            ffmpeg_bin = "ffmpeg"
        cmd = [ffmpeg_bin, "-y", *header_args, "-i", stream_url,
               "-c", "copy", str(task_dir / f"{save_name}.mkv")]

    progress_queue.put({"status": f"📥 Downloading: {title}"})

    # Some binary builds ignore --save-dir and write relative to the CWD —
    # run the child INSIDE task_dir so the output always lands there.
    started = time.time()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        errors="ignore", env=env, cwd=str(task_dir)
    )

    # Stall watchdog: a hung stream (dead CDN, stuck handshake) used to sit
    # forever holding one of the few global download slots, so every new
    # tap queued invisibly behind zombies. No output for 5 min -> kill it;
    # the non-zero exit then routes to the retry/fallback path.
    # NOTE: bind the Popen to a name the ffmpeg-retry below never reassigns —
    # the closure must keep watching the REAL child, not a CompletedProcess.
    _dl_proc = proc
    last_line = [time.time()]
    STALE_AFTER = 300

    def _stall_watchdog():
        while _dl_proc.poll() is None:
            if time.time() - last_line[0] > STALE_AFTER:
                try:
                    _dl_proc.kill()
                except OSError:
                    pass
                return
            time.sleep(10)

    threading.Thread(target=_stall_watchdog, daemon=True).start()

    _out_tail = []
    for line in proc.stdout or []:
        line = line.strip()
        last_line[0] = time.time()
        _out_tail.append(line)
        if len(_out_tail) > 15:
            _out_tail.pop(0)
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
        _re_tail = list(_out_tail)   # keep the binary's own last words
        try:
            from anime_sources.subtitles import find_ffmpeg
            ff_retry = find_ffmpeg() or "ffmpeg"
        except Exception:  # noqa: BLE001
            ff_retry = "ffmpeg"
        # header_args use the RE syntax (-H "K: V"); ffmpeg wants
        # -headers "K: V\r\n" — passing -H makes ffmpeg exit instantly with
        # "Unrecognized option 'H'" and the retry never had a chance.
        ff_header_args = []
        for i in range(0, len(header_args) - 1, 2):
            if header_args[i] == "-H":
                ff_header_args += ["-headers", header_args[i + 1] + "\r\n"]
        proc = subprocess.run(
            [ff_retry, "-y", *ff_header_args, "-i", stream_url, "-c", "copy",
             str(task_dir / f"{save_name}.mkv")],
            capture_output=True, text=True, env=env, cwd=str(task_dir),
        )
        code = proc.returncode
        _cerr = [ln for ln in (proc.stderr or "").strip().splitlines()
                 if ln.strip() and not ln.strip().startswith("lib")]
        _out_tail = _re_tail + ["[ffmpeg-retry]"] + _cerr[-6:]

    def _fail(msg: str) -> RuntimeError:
        # PROD FIX: bare "exit 8" told us nothing — surface the binary's own
        # last words so the log actually diagnoses the failure.
        tail = " | ".join(_out_tail[-8:]) if _out_tail else "no output captured"
        return RuntimeError(f"{msg} — tail: {tail[:400]}")

    if code != 0:
        raise _fail(f"Download failed (exit {code})")

    # Locate the produced file: recursive (some builds nest
    # <name>/<track>/<seg>.ts dirs), only files created during THIS run,
    # merged containers preferred over raw segments.
    cutoff = started - 10
    containers, segments = [], []
    try:
        for p in task_dir.rglob("*"):
            if (p.is_file()
                    and p.suffix.lower() in (".mkv", ".mp4", ".ts", ".m4a")
                    and p.stat().st_mtime >= cutoff):
                (containers if p.suffix.lower() in (".mkv", ".mp4", ".m4a")
                 else segments).append(p)
    except OSError:
        pass
    if containers:
        containers.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return str(containers[0])

    # ── MERGE FALLBACK (PROD FIX v4.19.0): some N_m3u8DL-RE builds print
    # "ffmpeg merging... Done", exit 0 — and produce NOTHING because their
    # internal ffmpeg call failed silently. If raw .ts segments landed, the
    # episode is not lost: byte-concat them (MPEG-TS is concat-safe) and
    # remux to .mkv ourselves.
    if segments:
        import shutil as _sh
        try:
            from anime_sources.subtitles import find_ffmpeg
            _ff = find_ffmpeg()
        except Exception:  # noqa: BLE001
            _ff = None
        segments.sort(key=lambda p: (
            (lambda m: (int(m.group(1)) if m else 0, p.name))(re.search(r"(\d+)", p.stem))
        ))
        concat_ts = task_dir / f"{save_name}.ts"
        try:
            with open(concat_ts, "wb") as _out:
                for seg in segments:
                    with open(seg, "rb") as _in:
                        _sh.copyfileobj(_in, _out, 1024 * 1024)
        except OSError:
            concat_ts = None
        if concat_ts and _ff:
            final_mkv = task_dir / f"{save_name}.mkv"
            _rm = subprocess.run(
                [_ff, "-y", "-i", str(concat_ts), "-c", "copy",
                 "-avoid_negative_ts", "make_zero", str(final_mkv)],
                capture_output=True, text=True, timeout=600,
            )
            if _rm.returncode == 0 and final_mkv.exists() and final_mkv.stat().st_size > 0:
                return str(final_mkv)
        if concat_ts and concat_ts.exists() and concat_ts.stat().st_size > 0:
            return str(concat_ts)   # raw TS still plays in VLC/MX Player
    raise _fail("Download finished but no output file found")

