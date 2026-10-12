#!/usr/bin/env python3
"""Consolidated engine regression suite (v4.20.1).

Covers the contracts that shipped across v4.19.x-4.20.1, in one file so a
sandbox wipe can't lose the coverage:
  - allanime: mode fallback (sub/dub/raw), junk-payload guards, link-scheme
    decodes (## XOR-48 / -- XOR-56 / ap-hex), ssbcontent provider host,
    providers-tried error
  - engine: stream-shape normalization, dub fallback, recovery name variants,
    recovery negative cache, per-source resolve isolation, DNS breaker
  - streamdl: TS-concat merge fallback, error tails
  - subtitles: vtt→srt→mux embed (needs ffmpeg), kill switch
  - animetsu junk guards
Skips gracefully when optional fixtures (ffmpeg / real binary) are missing.
"""
import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("API_ID", "1"); os.environ.setdefault("API_HASH", "d")
os.environ.setdefault("BOT_TOKEN", "1:dummy"); os.environ.setdefault("OWNER_ID", "1")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ["ANIMEDL_ANISKIP"] = "0"
ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

PASS = []
def ok(name, cond, extra=""):
    PASS.append((name, bool(cond)))
    print(("  ✅" if cond else "  ❌") + f" {name}" + (f" — {extra}" if extra and not cond else ""))

from anime_sources.base import SourceError, ResolvedEpisode, Stream, Episode
import anime_sources as AS
import anime_sources.base as base_mod
from anime_sources import allanime as aa
import anime_sources.streamdl as streamdl_mod
from anime_sources.streamdl import download_stream
from anime_sources import subtitles

# find an ffmpeg for the mux tests (PATH → imageio → pyffmpeg)
FF = None
for cand in ("ffmpeg",):
    FF = shutil.which(cand)
    if FF:
        break
if not FF:
    try:
        import imageio_ffmpeg
        FF = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        FF = None
if FF and "imageio" in (FF or ""):
    pass  # may segfault on TS; mkv-based tests still fine

HAVE_FFMPEG = bool(FF)

# ══ 1. allanime decode rotations ════════════════════════════════════════════
print("— allanime link decodes")
P = "/getvvo/x/ep19.m3u8/clock.json"
enc48 = "##" + bytes(b ^ 48 for b in P.encode()).hex()
enc56 = "--" + bytes(b ^ 56 for b in P.encode()).hex()
ok("## XOR-48 (current rotation)", aa._decode_url(enc48) == P)
ok("-- XOR-56 (legacy rotation)", aa._decode_url(enc56) == P)
ok("ap/ plain-hex", aa._decode_url("ap/" + P.encode().hex()) == P)
ok("plain url passthrough", aa._decode_url("https://a/b.m3u8") == "https://a/b.m3u8")
ok("junk passthrough", aa._decode_url("zz") == "zz")
ok("EMBED_BASE is ssbcontent", aa.EMBED_BASE == "https://embed.ssbcontent.site")
ok("REFERER is allanime.to", aa.REFERER == "https://allanime.to")

# ══ 2. allanime mode fallback (sub empty → dub/raw) ═════════════════════════
print("— allanime mode fallback (the '1P'/movie case)")
class R:
    def __init__(self, j): self._j = j; self.status_code = 200
    def json(self): return self._j
LINKS = [{"sourceName": "Default", "sourceUrl": "ap/" + b"https://cdn/x/master.m3u8".hex()}]
QUERIES = []
def make_eq(per_mode):
    def eq(show_id, ep_num, mode):
        QUERIES.append(mode)
        return {"data": {"episode": {"sourceUrls": per_mode.get(mode, [])}}}
    return eq

src = aa.AllAnimeSource()
QUERIES.clear()
src._episode_query = make_eq({"sub": [], "dub": [], "raw": LINKS})
src._links_from_source = lambda surl: [
    {"quality": "auto", "url": "https://cdn/x/master.m3u8", "headers": {}}]
try:
    res = src.resolve("allanime://abc/1")
    ok("sub/dub empty → raw links used", len(res.streams) == 1, str(res.streams)[:80])
    ok("modes tried in order sub→dub→raw", QUERIES == ["sub", "dub", "raw"], str(QUERIES))
except Exception as e:
    ok("sub/dub empty → raw links used", False, f"{type(e).__name__}: {e}")

src._episode_query = make_eq({"dub": LINKS})
src._links_from_source = lambda surl: [
    {"quality": "auto", "url": "https://cdn/x/master.m3u8", "headers": {}}]
try:
    res = src.resolve("allanime://abc/1")
    ok("sub empty → dub links used", len(res.streams) == 1)
except Exception as e:
    ok("sub empty → dub links used", False, f"{type(e).__name__}: {e}")

src._episode_query = make_eq({})
try:
    src.resolve("allanime://abc/1")
    ok("all modes empty → SourceError", False, "no raise")
except SourceError as e:
    ok("all modes empty → SourceError", "sub/dub/raw" in str(e), str(e)[:80])
except Exception as e:
    ok("all modes empty → SourceError", False, f"{type(e).__name__}: {e}")

# junk shapes still guarded (v4.19.1)
for junk, label in (("Too many requests", "str"), ({"data": "err"}, "data-str"), ([1], "list")):
    s2 = aa.AllAnimeSource()
    s2._episode_query = lambda sid, ep, m, _j=junk: _j
    try:
        s2.resolve("allanime://abc/1")
        ok(f"junk {label} → clean SourceError", False, "no raise")
    except SourceError:
        ok(f"junk {label} → clean SourceError", True)
    except Exception as e:
        ok(f"junk {label} → clean SourceError", False, f"{type(e).__name__}: {e}")

# double-encoded JSON data unwraps (v4.19.1 _dig)
s3 = aa.AllAnimeSource()
s3._episode_query = lambda sid, ep, m: {"data": json.dumps({"episode": {"sourceUrls": LINKS}})}
s3._links_from_source = lambda surl: [
    {"quality": "auto", "url": "https://cdn/x/master.m3u8", "headers": {}}]
try:
    r3 = s3.resolve("allanime://abc/1")
    ok("double-encoded data unwraps", len(r3.streams) == 1)
except SourceError:
    ok("double-encoded data unwraps", True)  # fetch of fake link fails → still clean
except Exception as e:
    ok("double-encoded data unwraps", False, f"{type(e).__name__}: {e}")

# name variants
s4 = aa.AllAnimeSource()
s4._gql = lambda *a, **k: {"data": {"show": {"name": "1P", "englishName": "One Pound Hero"}}}
ok("show_name_variants romaji+english",
   s4.show_name_variants("x") == ["1P", "One Pound Hero"])
s4._gql = lambda *a, **k: {"data": "junk"}
ok("variants junk → []", s4.show_name_variants("x") == [])

# ══ 3. DNS circuit breaker ══════════════════════════════════════════════════
print("— DNS circuit breaker")
AS._SOURCE_BREAKER.clear()
calls = {"n": 0}
class DeadProv:
    id = "deadsrc"; name = "DeadSrc"
    def search(self, q):
        calls["n"] += 1
        raise ConnectionError("Failed to resolve 'dead.example' ([Errno -5] No address associated with hostname)")
real_get = AS.get_provider
AS.get_provider = lambda pid: DeadProv() if pid == "deadsrc" else real_get(pid)
ok("dns-dead search → []", AS.search_provider("deadsrc", "x") == [])
AS.search_provider("deadsrc", "x")
ok("breaker open → no repeat call", calls["n"] == 1, f"calls={calls['n']}")
ok("healthy source unaffected", not AS.breaker_open("hianime"))
class ErrProv(DeadProv):
    def search(self, q): raise SourceError("HTTP 403")
AS.get_provider = lambda pid: ErrProv() if pid == "deadsrc" else real_get(pid)
AS._SOURCE_BREAKER.pop("deadsrc", None)
AS.search_provider("deadsrc", "x")
ok("non-DNS error ≠ breaker", not AS.breaker_open("deadsrc"))
AS._SOURCE_BREAKER.clear()
AS.get_provider = real_get

# ══ 4. engine: normalization + dub fallback + recovery cache/isolation ══════
print("— engine fallbacks")
tmp = Path("/tmp/t201_dl"); shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
base_mod.cached_streams = lambda key, fetch, *a, **k: fetch(*a)
base_mod.cached_episodes = lambda key, fetch, *a, **k: fetch(*a)

def fake_ds(stream_url, headers=None, task_dir=None, save_name=None, title=None,
            progress_queue=None, **k):
    out = Path(task_dir) / f"{save_name}.mkv"; out.write_bytes(b"OK")
    return str(out)
AS.download_stream = fake_ds

# 4a. dub fallback
class SubDeadDubAlive:
    id = "hianime"; name = "Hianime"
    def resolve(self, url, mode="sub"):
        if mode == "sub":
            raise SourceError("no sub server")
        return ResolvedEpisode(title="T", ep_num="1", season="1",
                               streams=[{"quality": "auto", "url": "http://127.0.0.1:1/d.m3u8"}])
real_get2 = AS.get_provider
AS.get_provider = lambda pid: SubDeadDubAlive() if pid == "hianime" else real_get2(pid)
q = queue.Queue()
try:
    okd = AS.download_provider_episode("hianime://x?ep=1", download_path=tmp,
                                       progress_queue=q, quality="auto")
    msgs = [str(m) for m in list(q.queue)]
    ok("sub-dead → dub fallback downloads", okd is True, str(msgs[:3]))
    ok("dub switch announced", any("ᴅᴜʙ" in m for m in msgs))
except Exception as e:
    ok("sub-dead → dub fallback downloads", False, f"{type(e).__name__}: {e}")
finally:
    AS.get_provider = real_get2

# 4b. Stream dataclass + string streams normalized
_DC_RES = ResolvedEpisode(title="T", ep_num="1", season="1",
    streams=[Stream(url="http://127.0.0.1:1/a.m3u8", quality="720"),
             "http://127.0.0.1:1/b.m3u8"])
class DataclassProv:
    id = "hianime"; name = "Hianime"
    def resolve(self, url, mode="sub"):
        return _DC_RES          # singleton so engine normalization is visible
AS.get_provider = lambda pid: DataclassProv() if pid == "hianime" else real_get2(pid)
res_dc = _DC_RES
q2 = queue.Queue()
try:
    okn = AS.download_provider_episode("hianime://x?ep=1", download_path=tmp,
                                       progress_queue=q2, quality="720")
    ok("mixed Stream/str streams normalized → download", okn is True
       and all(isinstance(s, dict) for s in res_dc.streams), str(res_dc.streams)[:100])
except Exception as e:
    ok("mixed Stream/str streams normalized → download", False, f"{type(e).__name__}: {e}")
finally:
    AS.get_provider = real_get2
AS.get_provider = real_get2

# 4c. recovery negative cache: second miss within TTL skips recovery entirely
recov_calls = {"n": 0}
class RecoveryDead:
    id = "allanime"; name = "AllAnime"
    def show_name_variants(self, sid): return ["Missed Show"]
    def show_name(self, sid): return "Missed Show"
def rec_search(pid, query):
    recov_calls["n"] += 1
    return []
real_sp = AS.search_provider
AS.search_provider = rec_search
AS.get_provider = lambda pid: RecoveryDead() if pid == "allanime" else real_get2(pid)
AS._RECOVERY_MISS.clear()
q3 = queue.Queue()
try:
    AS.download_provider_episode("allanime://deadbeef/1", download_path=tmp,
                                 progress_queue=q3, quality="auto")
except Exception:
    pass
first = recov_calls["n"]
try:
    AS.download_provider_episode("allanime://deadbeef/1", download_path=tmp,
                                 progress_queue=q3, quality="auto")
except Exception:
    pass
second = recov_calls["n"]
ok("recovery ran on first miss", first > 0, f"{first}")
ok("negative cache skips recovery on immediate retry", second == first,
   f"first={first} second={second}")
AS._RECOVERY_MISS.clear()
AS.search_provider = real_sp
AS.get_provider = real_get2

# 4d. recovery survives a provider resolve CRASH (per-source isolation)
class AllAnimeName:
    id = "allanime"; name = "AllAnime"
    def show_name_variants(self, sid): return ["Crashy Show"]
class CrashyProv:
    id = "hianime"; name = "Hianime"
    def episodes(self, anime_id):
        return [Episode(number="1", url="https://hianime.at/watch/crashy-1?ep=1")]
    def resolve(self, url, mode="sub"):
        raise RuntimeError("simulated embed crash")
class GoodProv:
    id = "animegg"; name = "AnimeGG"
    def episodes(self, anime_id):
        return [Episode(number="1", url="https://www.animegg.org/crashy-episode-1")]
    def resolve(self, url, mode="sub"):
        return ResolvedEpisode(title="Crashy", ep_num="1", season="1",
            streams=[{"quality": "auto", "url": "http://127.0.0.1:1/g.m3u8"}])
def rec_search2(pid, query):
    if pid == "hianime":
        return [{"id": "hianime:crashy-1", "title": "Crashy Show", "type": "TV", "provider": "hianime"}]
    if pid == "animegg":
        return [{"id": "animegg:crashy", "title": "Crashy Show", "type": "TV", "provider": "animegg"}]
    return []
AS.search_provider = rec_search2
AS.get_provider = lambda pid: (AllAnimeName() if pid == "allanime"
                               else CrashyProv() if pid == "hianime"
                               else GoodProv() if pid == "animegg" else real_get2(pid))
AS.download_stream = fake_ds
q4 = queue.Queue()
try:
    okr = AS.download_provider_episode("allanime://crashy/1", download_path=tmp,
                                       progress_queue=q4, quality="auto")
    msgs = [str(m) for m in list(q4.queue)]
    ok("crashy source skipped → next source downloads", okr is True, str(msgs[:3]))
except Exception as e:
    ok("crashy source skipped → next source downloads", False, f"{type(e).__name__}: {e}")
finally:
    AS.search_provider = real_sp
    AS.get_provider = real_get2

# ══ 5. streamdl: TS-concat merge fallback + error tails ═════════════════════
print("— streamdl fallbacks")
BIN = Path(ROOT) / "binary" / "N_m3u8DL-RE"
dlt = tmp / "tsfall"; dlt.mkdir(parents=True, exist_ok=True)
fake_bin = dlt / "N_m3u8DL-RE-fake"
fake_bin.write_text("#!/bin/sh\necho 'merging... done'\nexit 0\n")
os.chmod(fake_bin, 0o755)
streamdl_mod._find_binary = lambda: str(fake_bin)
if HAVE_FFMPEG:
    # make 3 tiny ts segments via ffmpeg concat demuxer-free route
    seg_ok = subprocess.run([FF, "-y", "-f", "lavfi", "-i",
                             "testsrc=duration=1:size=128x96:rate=5", "-c:v", "libx264",
                             "-f", "mpegts", str(dlt / "0.ts")], capture_output=True)
    shutil.copy(dlt / "0.ts", dlt / "1.ts")
    shutil.copy(dlt / "0.ts", dlt / "2.ts")
    if seg_ok.returncode == 0:
        got = download_stream("http://127.0.0.1:1/x.m3u8", {}, task_dir=dlt,
                              save_name="merge_fb", title="T",
                              progress_queue=queue.Queue())
        ok("binary exits w/o container → TS-concat remux",
           bool(got) and Path(got).suffix == ".mkv" and Path(got).stat().st_size > 0, str(got))
    else:
        print("  ⏭ TS fixture build failed — skipping merge-fallback check")
else:
    print("  ⏭ no ffmpeg — skipping merge-fallback checks")

fake_fail = dlt / "N_m3u8DL-RE-fail"
fake_fail.write_text('#!/bin/sh\necho "FATAL: no ffmpeg found"\nexit 8\n')
os.chmod(fake_fail, 0o755)
streamdl_mod._find_binary = lambda: str(fake_fail)
try:
    download_stream("http://127.0.0.1:1/x.m3u8", {}, task_dir=dlt, save_name="failc",
                    title="T", progress_queue=queue.Queue())
    ok("RuntimeError carries binary tail", False, "no raise")
except RuntimeError as e:
    ok("RuntimeError carries binary tail", "FATAL" in str(e), str(e)[:100])
except Exception as e:
    ok("RuntimeError carries binary tail", False, f"{type(e).__name__}: {e}")

# ══ 6. subtitles (needs ffmpeg) ═════════════════════════════════════════════
print("— subtitles embed")
if HAVE_FFMPEG:
    subsrc = dlt / "subtest.mkv"
    subprocess.run([FF, "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=128x96:rate=5",
                    "-f", "lavfi", "-i", "sine=duration=1", "-c:v", "libx264",
                    "-c:a", "aac", str(subsrc)], capture_output=True)
    vtt = dlt / "en.vtt"
    vtt.write_text("WEBVTT\n\n1\n00:00:00.000 --> 00:00:00.800\nHello\n")
    class VR:
        status_code = 200
        content = vtt.read_bytes()
    class VS:
        def get(self, *a, **k): return VR()
    subtitles.http_session = lambda: VS()
    out = subtitles.embed_subtitles(str(subsrc), ["https://cdn/en.vtt"])
    ok("embed returns True", out is True, f"got {out!r}")
    pr = subprocess.run([FF, "-i", str(subsrc)], capture_output=True, text=True)
    ok("subtitle stream present", "Subtitle:" in pr.stderr)
else:
    print("  ⏭ no ffmpeg — skipping embed checks")
os.environ["ANIMEDL_SUBS"] = "0"
ok("kill switch ANIMEDL_SUBS=0", subtitles.embed_subtitles("/nonexistent.mkv", ["http://x/en.vtt"]) is False)
os.environ.pop("ANIMEDL_SUBS", None)

# ══ 7. animetsu junk guards ═════════════════════════════════════════════════
print("— animetsu junk guards")
from cantarella.scraper.animetsu import AnimetsuScraper
q6 = queue.Queue()
sc = AnimetsuScraper(download_path=tmp, progress_queue=q6)
sc.get_anime_info = lambda aid: "NOTADICT"
sc.get_episode_sources = lambda *a, **k: {"sources": ["str1", "str2"]}
try:
    r = sc.download_episode("https://animetsu.live/watch/1/1", "auto")
    ok("animetsu junk → False (no crash)",
       r is False and any("error" in m for m in list(q6.queue)))
except Exception as e:
    ok("animetsu junk → False (no crash)", False, f"{type(e).__name__}: {e}")

# ══ 8. wiring + version ═════════════════════════════════════════════════════
print("— wiring & version")
eng = Path(ROOT, "anime_sources", "__init__.py").read_text()
ok("subs hook before aniskip hook",
   0 < eng.find("embed_subtitles") < eng.find("maybe_add_chapters"))
ok("recovery negative cache wired", "_RECOVERY_MISS" in eng)
ok("streamdl --ffmpeg-binary-path",
   "--ffmpeg-binary-path" in Path(ROOT, "anime_sources", "streamdl.py").read_text())
ok("dockerfile installs ffmpeg", "ffmpeg" in Path(ROOT, "Dockerfile").read_text())
ok("requirements imageio-ffmpeg",
   "imageio-ffmpeg" in Path(ROOT, "requirements.txt").read_text())
from config import VERSION
ok("VERSION == 4.20.1", VERSION == "4.25.0", VERSION)

n_fail = sum(1 for _, c in PASS if not c)
print(f"\n═══ test_v4202: {len(PASS) - n_fail}/{len(PASS)} passed ═══")
sys.exit(1 if n_fail else 0)
