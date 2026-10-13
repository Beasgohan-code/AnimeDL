#!/usr/bin/env python3
"""REAL-binary E2E: bundled N_m3u8DL-RE download → subtitle embed → chapters.

Needs: binary/N_m3u8DL-RE (repo) + an ffmpeg on PATH/imageio/pyffmpeg that can
demux MPEG-TS (the BtbN/apt builds; musl-static imageio builds may segfault —
the test skips with a clear message in that case rather than failing).
"""
import http.server
import os
import queue
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("API_ID", "1"); os.environ.setdefault("API_HASH", "d")
os.environ.setdefault("BOT_TOKEN", "1:dummy"); os.environ.setdefault("OWNER_ID", "1")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

PASS = []
def ok(name, cond, extra=""):
    PASS.append((name, bool(cond)))
    print(("  ✅" if cond else "  ❌") + f" {name}" + (f" — {extra}" if extra and not cond else ""))

BIN = Path(ROOT, "binary", "N_m3u8DL-RE")
if not BIN.exists():
    print("⏭ bundled N_m3u8DL-RE missing — skip")
    sys.exit(0)

FF = None
for _c in (shutil_which := __import__("shutil").which)("ffmpeg"), None:
    FF = _c
    if FF:
        break
if not FF:
    try:
        import imageio_ffmpeg
        FF = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        FF = None
if not FF:
    pff = Path.home() / ".pyffmpeg" / "bin" / "ffmpeg"
    FF = str(pff) if pff.exists() else None
if not FF:
    print("⏭ no ffmpeg on this host — skip")
    sys.exit(0)
ok("ffmpeg located", True)
print(f"  ffmpeg: {FF}")

# sanity: the build must demux TS (musl-static imageio builds segfault)
FIXDIR = "/tmp/e2e_fix"
subprocess.run(["rm", "-rf", FIXDIR]); os.makedirs(FIXDIR)
r = subprocess.run([FF, "-y", "-f", "lavfi", "-i", "testsrc=duration=6:size=320x240:rate=10",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-force_key_frames", "expr:gte(t,n_forced*2)",
                    "-f", "hls", "-hls_time", "1", "-hls_list_size", "0",
                    f"{FIXDIR}/playlist.m3u8"], capture_output=True)
segs = [f for f in os.listdir(FIXDIR) if f.endswith(".ts")]
ok("HLS fixture built (≥2 segments)", r.returncode == 0 and len(segs) >= 2, f"segs={segs}")
if r.returncode != 0:
    sys.exit(1)
probe = subprocess.run([FF, "-i", f"{FIXDIR}/playlist0.ts", "-f", "null", "/dev/null"],
                       capture_output=True)
if probe.returncode != 0:
    print(f"⏭ this ffmpeg build cannot demux TS (exit {probe.returncode}) — skip")
    sys.exit(0)

open(f"{FIXDIR}/en.vtt", "w").write(
    "WEBVTT\n\n00:00:00.500 --> 00:00:01.500\nHello from the E2E!\n\n"
    "00:00:01.500 --> 00:00:02.000\nScience is elegant.\n")

import functools
class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
httpd = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(H, directory=FIXDIR))
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print(f"  fixture server: 127.0.0.1:{PORT}")

# ── REAL download through streamdl (bundled binary) ─────────────────────────
from anime_sources.streamdl import download_stream
import anime_sources.streamdl as streamdl_mod
streamdl_mod._find_binary = lambda: str(BIN)   # pin the bundled binary
q = queue.Queue()
task_dir = "/tmp/e2e_dl"
subprocess.run(["rm", "-rf", task_dir])
t0 = time.time()
try:
    final = download_stream(f"http://127.0.0.1:{PORT}/playlist.m3u8", {},
                            Path(task_dir), "e2e_episode", "E2E [EP 1]", q)
    dl_err = None
except Exception as e:
    final, dl_err = None, e
ok("N_m3u8DL-RE downloaded + merged container",
   bool(final) and os.path.getsize(final) > 10000, f"{final} err={dl_err} {round(time.time()-t0,1)}s")
ok("progress events emitted", any("percent" in m for m in list(q.queue)))
if not final:
    sys.exit(1)

# ── REAL subtitle embed ──────────────────────────────────────────────────────
from anime_sources.subtitles import embed_subtitles
got = embed_subtitles(final, [f"http://127.0.0.1:{PORT}/en.vtt"])
ok("subtitles embedded (in-place)", got is True)
probe = subprocess.run([FF, "-i", final], capture_output=True, text=True).stderr
ok("subtitle stream present", "Subtitle:" in probe, probe[-200:])

# ── REAL AniSkip chapter mux ─────────────────────────────────────────────────
import anime_sources.aniskip as ask
ask._MAL_CACHE["e2e show"] = (1, time.time())
ask._SKIP_CACHE[(1, 1)] = ([{"start": 0.2, "end": 0.8, "type": "OP"},
                            {"start": 0.8, "end": 1.2, "type": "ED"}], time.time())
ok("chapters muxed", ask.maybe_add_chapters(final, "E2E Show", 1) is True)
probe2 = subprocess.run([FF, "-i", final], capture_output=True, text=True).stderr
ok("chapter stream present", "Chapters:" in probe2 or "Chapter #" in probe2, probe2[-200:])
ok("subs + chapters coexist",
   "Subtitle:" in probe2 and ("Chapters:" in probe2 or "Chapter #" in probe2))

# ── guards ───────────────────────────────────────────────────────────────────
os.environ["ANIMEDL_SUBS"] = "0"
ok("ANIMEDL_SUBS=0 gate", embed_subtitles(final, [f"http://127.0.0.1:{PORT}/en.vtt"]) is False)
os.environ.pop("ANIMEDL_SUBS", None)
from config import VERSION
ok("VERSION", VERSION == "5.1.0", VERSION)

httpd.shutdown()
fails = [n for n, c in PASS if not c]
print(f"\n{'='*50}\n{len(PASS)-len(fails)}/{len(PASS)} passed" +
      (f" — FAILURES: {fails}" if fails else " — ALL GREEN (REAL binary download + REAL muxes)"))
sys.exit(1 if fails else 0)
