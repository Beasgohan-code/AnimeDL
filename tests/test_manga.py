#!/usr/bin/env python3
"""v4.22.0 manga engine tests — 11 providers, builders, aggregation, NSFW
gate. All provider contracts run on faked HTTP (deterministic); live probes
are best-effort and never fail the suite."""
import io
import json
import os
import sys
import threading
import http.server
import socketserver
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

from manga_sources import (MangaChapter, MangaError, MangaSearchResult,
                           build_output, fetch_images, sanitize, search_all)
from manga_sources.base import images_to_cbz, images_to_pdf
from PIL import Image

import shutil as _sh
tmp = Path("/tmp/t_manga"); _sh.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)

# ══ 1. builders ═════════════════════════════════════════════════════════════
print("— PDF/CBZ builders")
pages = []
for i, color in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
    img = Image.new("RGB", (60, 80), color)
    p = tmp / f"{i:04d}.img"
    img.save(p, format="PNG")
    pages.append(p)
prog = []
pdf = images_to_pdf(pages, tmp / "ch.pdf", progress=lambda d, t: prog.append((d, t)))
ok("PDF built", pdf.exists() and pdf.stat().st_size > 500)
with open(pdf, "rb") as f:
    ok("PDF magic", f.read(5) == b"%PDF-")
ok("PDF progress fired", bool(prog))
import zipfile
cbz = images_to_cbz(pages, tmp / "ch.cbz")
with zipfile.ZipFile(cbz) as zf:
    names = zf.namelist()
ok("CBZ built with 3 STORED pages", len(names) == 3 and
   zf.getinfo(names[0]).compress_type == zipfile.ZIP_STORED)

# ══ 2. fetch_images (loopback + dead page) ══════════════════════════════════
print("— fetch_images (loopback + dead page)")
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/dead":
            self.send_error(404); return
        buf = io.BytesIO()
        Image.new("RGB", (40, 50), (200, 100, 50)).save(buf, format="PNG")
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.end_headers()
        self.wfile.write(buf.getvalue())
srv = socketserver.TCPServer(("127.0.0.1", 0), H)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
wd = tmp / "fetch"
got = fetch_images([f"http://127.0.0.1:{PORT}/a", f"http://127.0.0.1:{PORT}/dead",
                    f"http://127.0.0.1:{PORT}/c"], wd, progress=lambda d, t: None)
ok("dead page skipped, good pages kept in order",
   len(got) == 2 and got[0].name == "0000.img" and got[1].name == "0002.img",
   str([g.name for g in got]))
srv.shutdown()

# ══ 3. MangaDex ═════════════════════════════════════════════════════════════
print("— MangaDex provider")
from manga_sources import mangadex as mdx
mdx.http_json = lambda url, headers=None, params=None: (
    {"data": [{
        "id": "a1b2", "attributes": {
            "title": {"en": "Solo Leveling"},
            "altTitles": [{"ko": "나혼자만"}], "status": "ongoing",
            "tags": [{"attributes": {"name": {"en": "Action"}}}]},
        "relationships": [{"type": "cover_art",
                           "attributes": {"fileName": "cover.jpg"}}]}]}
     if url.endswith("/manga") else
     {"data": [
         {"id": "ch1", "attributes": {"chapter": "110", "title": "The End", "pages": 14}},
         {"id": "ch0", "attributes": {"chapter": "109.5", "title": "", "pages": 8}},
         {"id": "chx", "attributes": {"chapter": "108", "title": "ext", "pages": 0}}]}
     if "/feed" in url else
     {"baseUrl": "https://uploads.mangadex.org",
      "chapter": {"hash": "h1", "data": ["p1.jpg", "p2.jpg"], "dataSaver": []}})
prov = mdx.MangaDexProvider()
res = prov.search("solo")
ok("mangadex search shape", len(res) == 1 and res[0].title == "Solo Leveling")
chs = prov.chapters("a1b2")
ok("mangadex chapters (0-page external skipped)",
   [c.number for c in chs] == ["110", "109.5"])
urls, ref = prov.images(MangaChapter(id="ch1", number="110"))
ok("mangadex at-home image urls", urls == [
    "https://uploads.mangadex.org/data/h1/p1.jpg",
    "https://uploads.mangadex.org/data/h1/p2.jpg"])

# ══ 4. Comick ═══════════════════════════════════════════════════════════════
print("— Comick provider")
from manga_sources import comick as ck
ckp = ck.ComickProvider()
ckp._api_get = lambda path, params=None: (
    [{"slug": "solo-leveling", "title": "Solo Leveling",
      "md_covers": [{"b2key": "k1"}], "status": "ongoing"}]
    if path == "/v1.0/search/" else
    {"comic": {"hid": "HID9"}} if path.startswith("/comic/solo") else
    {"chapters": [{"hid": "c1", "chap": "179", "title": "Arise"},
                  {"hid": "c2", "chap": "178", "title": None},
                  {"hid": "c3", "chap": "", "title": "skip me"}]})
s = ckp.search("solo")
ok("comick search shape", len(s) == 1 and s[0].cover.endswith("k1"))
chs = ckp.chapters("solo-leveling")
ok("comick chapters (dedupe + numberless skipped)",
   [c.number for c in chs] == ["179", "178"])
NEXT_HTML = ('<html><script id="__NEXT_DATA__" type="application/json">'
             + json.dumps({"props": {"pageProps": {"chapter": {"md_images": [
                 {"b2key": "img1"}, {"b2key": "img2"}]}}}})
             + "</script></html>")
class FakeResp:
    text = NEXT_HTML; status_code = 200; content = NEXT_HTML.encode()
ck.http_get = lambda url, headers=None: FakeResp()
urls, ref = ckp.images(MangaChapter(id="c1", number="179"))
ok("comick NEXT_DATA images", urls == [
    "https://meo.comick.pictures/img1", "https://meo.comick.pictures/img2"])

# ══ 5. Asura ════════════════════════════════════════════════════════════════
print("— Asura provider")
from manga_sources import asura as asr
SEARCH_HTML = ('<a href="/series/solo-leveling-12345"><img src="https://gg.asuracomic.net/c.jpg"/>'
               '<span>Solo Leveling</span></a>')
asr.http_get = lambda url, headers=None: type("R", (), {"text": SEARCH_HTML, "status_code": 200})()
ap = asr.AsuraProvider()
s = ap.search("solo")
ok("asura search shape", len(s) == 1 and s[0].id == "12345")
CH_HTML = ('<a href="/series/solo-leveling-12345/chapter-180"><h3>Chapter 180</h3></a>'
           '<a href="/series/solo-leveling-12345/chapter-179.5"><h3>Chapter 179.5</h3></a>')
asr.http_get = lambda url, headers=None: type("R", (), {"text": CH_HTML, "status_code": 200})()
chs = ap.chapters("https://asuracomic.net/series/solo-leveling-12345")
ok("asura chapters incl. decimal", [c.number for c in chs] == ["180", "179.5"])
FLIGHT = 'self.__next_f.push([1,"x \\"pages\\":[{\\"url\\":\\"https://gg.asuracomic.net/p1.webp\\"},{\\"url\\":\\"https://gg.asuracomic.net/p2.webp\\"}] y")'
asr.http_get = lambda url, headers=None: type("R", (), {"text": FLIGHT, "status_code": 200})()
urls, ref = ap.images(chs[0])
ok("asura flight-data images", urls == [
    "https://gg.asuracomic.net/p1.webp", "https://gg.asuracomic.net/p2.webp"])

# ══ 6. WeebCentral ══════════════════════════════════════════════════════════
print("— WeebCentral provider")
from manga_sources import weebcentral as wc
WC_SEARCH = ('<a href="https://weebcentral.com/series/01J76XY7/solo-leveling">'
             '<img src="https://wc-cdn/c.jpg"/><div><div>Solo Leveling</div></div></a>')
wc.http_get = lambda url, headers=None: type("R", (), {"text": WC_SEARCH, "status_code": 200})()
wcp = wc.WeebCentralProvider()
s = wcp.search("solo")
ok("weebcentral search", len(s) == 1 and s[0].id.startswith("https://weebcentral.com/series/"))
WC_CH = ('<a href="https://weebcentral.com/chapters/01ABC"><span class="grow flex items-center gap-2">'
         '<span>Chapter 180</span></span></a>'
         '<a href="https://weebcentral.com/chapters/01ABD"><span>Chapter 179</span></a>')
wc.http_get = lambda url, headers=None: type("R", (), {"text": WC_CH, "status_code": 200})()
chs = wcp.chapters("https://weebcentral.com/series/01J76XY7/solo-leveling")
ok("weebcentral chapters", [c.number for c in chs] == ["180", "179"],
   str([c.number for c in chs]))
WC_IMG = ('<img src="https://wc-manga-cdn/x/manga_01/001.webp"/>'
          '<img src="https://weebcentral.com/static/images/brand.png"/>')
wc.http_get = lambda url, headers=None: type("R", (), {"text": WC_IMG, "status_code": 200})()
urls, ref = wcp.images(chs[0])
ok("weebcentral images (brand filtered)",
   urls == ["https://wc-manga-cdn/x/manga_01/001.webp"], str(urls))

# ══ 7. Mgeko ════════════════════════════════════════════════════════════════
print("— Mgeko provider")
from manga_sources import mgeko as mg
MG_SEARCH = ('<li><a href="https://mgeko.cc/series/solo" title="Solo Max-Level Newbie">'
             '<img src="https://mg/c.jpg"/></a></li>')
mg.http_get = lambda url, headers=None: type("R", (), {"text": MG_SEARCH, "status_code": 200})()
mgp = mg.MgekoProvider()
s = mgp.search("solo")
ok("mgeko search", len(s) == 1 and s[0].title == "Solo Max-Level Newbie")
MG_CH = '<div id="chpagedlist"><li><a href="https://mgeko.cc/solo-chapter-201-xyz/">c201</a></li></div>'
mg.http_get = lambda url, headers=None: type("R", (), {"text": MG_CH, "status_code": 200})()
chs = mgp.chapters("https://mgeko.cc/series/solo")
ok("mgeko chapters from href", [c.number for c in chs] == ["201"])
MG_IMG = '<div id="chapter-reader"><img src="https://mg-p/1.webp"/><img src="https://mg-p/2.webp"/></div>'
mg.http_get = lambda url, headers=None: type("R", (), {"text": MG_IMG, "status_code": 200})()
urls, ref = mgp.images(chs[0])
ok("mgeko reader images", urls == ["https://mg-p/1.webp", "https://mg-p/2.webp"])

# ══ 8. wp-manga family (manhuafast / manhuaplus / templetoons) ══════════════
print("— wp-manga family")
from manga_sources import wpmanga as wp
import manga_sources.base as msbase
mf = wp.ManhuaFastProvider()
MF_SEARCH = ('<div class="c-tabs-item__content"><a href="https://manhuafast.net/manga/solo"/>'
             '<h3>Solo Farming</h3><img data-src="https://mf/c.jpg"/></div>')
wp.http_get = lambda url, headers=None: type("R", (), {"text": MF_SEARCH, "status_code": 200})()
s = mf.search("solo")
ok("manhuafast search", len(s) == 1 and s[0].title == "Solo Farming")
MF_CH = '<a href="https://manhuafast.net/manga/solo-chapter-77/">77</a>'
wp.http_get = lambda url, headers=None: type("R", (), {"text": MF_CH, "status_code": 200})()
chs = mf.chapters("https://manhuafast.net/manga/solo")
ok("manhuafast ajax chapters", [c.number for c in chs] == ["77"])
MF_IMG = ('<div class="reading-content"><div class="page-break no-gaps">'
          '<img data-src="https://mf/p1.jpg"/></div></div>')
wp.http_get = lambda url, headers=None: type("R", (), {"text": MF_IMG, "status_code": 200})()
urls, ref = mf.images(chs[0])
ok("manhuafast reading-content images", urls == ["https://mf/p1.jpg"])

mp = wp.ManhuaPlusProvider()
MP_SEARCH = '{"list": [{"slug": "solo", "name": "Solo Bug Farmer", "cover": "/covers/s.jpg"}]}'
class _R:
    def __init__(self, text, code=200):
        self.text = text; self.status_code = code
    def json(self): return json.loads(self.text)
_orig_get = msbase.requests.get
_orig_post = msbase.requests.post
msbase.requests.get = lambda *a, **k: _R(MP_SEARCH)
msbase.requests.post = lambda *a, **k: _R(MP_SEARCH)
s = mp.search("solo")
msbase.requests.get = _orig_get
msbase.requests.post = _orig_post
ok("manhuaplus ajax search", len(s) == 1 and s[0].title == "Solo Bug Farmer"
   and s[0].url.endswith("/manga/solo"), str(s)[:80])
MP_CH = '<div class="bc-fff s1 r2 p-13"><a href="/manga/solo/chapter-12/">Ch 12</a></div>'
wp.http_get = lambda url, headers=None: type("R", (), {"text": MP_CH, "status_code": 200})()
chs = mp.chapters("https://manhuaplus.org/manga/solo")
ok("manhuaplus chapters", [c.number for c in chs] == ["12"])
class _MPRead:
    text = "const CHAPTER_ID = 4567;"; status_code = 200
MP_IMG_HTML = "<img src=" + chr(39) + "https://mp/p1.webp" + chr(39) + ">"
MP_IMG_JSON = json.dumps({"html": MP_IMG_HTML})
wp.http_get = lambda url, headers=None: _MPRead()
msbase.requests.get = lambda *a, **k: _R(MP_IMG_JSON)
msbase.requests.post = lambda *a, **k: _R(MP_IMG_JSON)
try:
    urls, ref = mp.images(chs[0])
    ok("manhuaplus ajax image list", urls == ["https://mp/p1.webp"], str(urls))
except Exception as e:
    ok("manhuaplus ajax image list", False, f"{type(e).__name__}: {e}")
msbase.requests.get = _orig_get
msbase.requests.post = _orig_post

tt = wp.TempleToonsProvider()
_real_wp_json, _real_wp_get = wp.http_json, wp.http_get
wp.http_json = lambda url: [{"title": "Toon World", "series_slug": "toon-world",
                             "thumbnail": "https://tt/c.jpg"}]
s = tt.search("toon")
ok("templetoons api search", len(s) == 1
   and s[0].url == "https://templetoons.com/comic/toon-world")
TT_CH = '<a href="/comic/toon-world/chapter-31"><h1>Chapter 31</h1></a>'
wp.http_get = lambda url, headers=None: type("R", (), {"text": TT_CH, "status_code": 200})()
chs = tt.chapters("https://templetoons.com/comic/toon-world")
ok("templetoons chapters", [c.number for c in chs] == ["31"]
   and chs[0].url.endswith("/comic/toon-world/chapter-31"))
TT_READ = r'self.__next_f.push([1,"images\":\[\"https:\/\/cdn.toon\/images\/p1.jpg\"'
wp.http_get = lambda url, headers=None: type("R", (), {"text": TT_READ, "status_code": 200})()
urls, ref = tt.images(chs[0])
ok("templetoons flight-data images", urls == ["https://cdn.toon/images/p1.jpg"], str(urls))
wp.http_json, wp.http_get = _real_wp_json, _real_wp_get

# ══ 9. aggregation + NSFW gate + registry ═══════════════════════════════════
print("— aggregation, NSFW gate, registry")
import manga_sources as MS
real_gp = MS.get_provider
class Boom:
    def search(self, q): raise RuntimeError("down")
MS.get_provider = lambda pid: Boom() if pid == "comick" else real_gp(pid)
results, tried = MS.search_all("solo")
MS.get_provider = real_gp
ok("one dead provider ≠ dead search", len(results) >= 1
   and any(pid == "comick" and isinstance(o, str) for pid, o in tried), str(tried))
ok("8 default providers registered", len(MS.SEARCH_ORDER) == 8, str(MS.SEARCH_ORDER))
ok("CHAPTERS_ARG covers defaults", all(p in MS.CHAPTERS_ARG for p in MS.SEARCH_ORDER))
ok("NSFW locked by default",
   all(pid not in ("manhwaclan", "manga18fx", "manhwa18") for pid, _ in tried))
os.environ["ANIMEDL_MANGA_NSFW"] = "1"
from manga_sources import nsfw as nsfw_mod
ok("nsfw env gate flips", nsfw_mod.nsfw_enabled() is True)
p18 = MS.get_provider("manga18fx")
ok("gated provider loads when enabled", p18 is not None and p18.id == "manga18fx")
os.environ["ANIMEDL_MANGA_NSFW"] = "0"
try:
    MS.get_provider("manga18fx")
    ok("gated provider locked when disabled", False, "loaded!")
except MangaError:
    ok("gated provider locked when disabled", True)

# ══ 10. sanitize + plugin wiring + version ══════════════════════════════════
print("— sanitize & wiring")
ok("sanitize strips junk", sanitize('a/b:c*d?"<>|') == "abcd")
plug = Path(ROOT, "cantarella", "telegram", "plugins", "manga.py").read_text()
ok("plugin dispatches via CHAPTERS_ARG", "CHAPTERS_ARG" in plug)
ok("plugin sends documents", "send_document" in plug)
ok("no third-party branding",
   not any(b in plug.lower() for b in ("codeflix", "abhinai", "dra-sama")))
ok("help mentions /manga", "/manga" in Path(ROOT, "Script.py").read_text())
from config import VERSION
ok("VERSION == 4.22.0", VERSION == "4.22.0", VERSION)

# ══ 11. LIVE probes (best-effort) ═══════════════════════════════════════════
print("— live probes (best-effort)")
import requests as _rq
try:
    _rq.get("https://api.mangadex.org/ping", timeout=5)
    live = mdx.MangaDexProvider()
    live_res = live.search("solo leveling")
    ok("LIVE mangadex search", len(live_res) > 0, f"{len(live_res)}")
    if live_res:
        live_chs = live.chapters(live_res[0].id)
        ok("LIVE mangadex chapters", len(live_chs) > 0, f"{len(live_chs)}")
        if live_chs:
            urls, ref = live.images(live_chs[0])
            ok("LIVE mangadex images", len(urls) > 0, f"{len(urls)}")
except Exception as e:
    print(f"  ⏭ live mangadex unreachable: {type(e).__name__}")
try:
    _rq.get("https://asuracomic.net", timeout=5)
    live_ap = asr.AsuraProvider()
    r2 = live_ap.search("solo leveling")
    ok("LIVE asura search", len(r2) > 0, f"{len(r2)}")
except Exception as e:
    print(f"  ⏭ live asura unreachable: {type(e).__name__}")

n_fail = sum(1 for _, c in PASS if not c)
print(f"\n═══ test_manga: {len(PASS) - n_fail}/{len(PASS)} passed ═══")
sys.exit(1 if n_fail else 0)
