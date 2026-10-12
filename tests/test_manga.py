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
import manga_sources.base as _msb
def _mdx_fake_get(url, headers=None, params=None, timeout=None):
    class _R:
        def __init__(self, payload):
            self._p = payload
        def json(self):
            return self._p
    if url.endswith("/manga") or "/feed" in url:
        assert params is not None, \
            "base.http_json must forward params (v4.24.0 regression)"
    return _R(
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
_real_base_get = _msb.http_get
_msb.http_get = _mdx_fake_get
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
_msb.http_get = _real_base_get

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
wc.http_post = lambda url, data=None, headers=None, timeout=None: (
    type("R", (), {"text": WC_SEARCH, "status_code": 200})()
    if data == {"text": "solo"} and url.endswith("/search/simple?location=main")
    else (_ for _ in ()).throw(IOError("HTTP 999 unexpected POST " + url)))
wcp = wc.WeebCentralProvider()
s = wcp.search("solo")
ok("weebcentral search (HTMX POST)", len(s) == 1
   and s[0].id.startswith("https://weebcentral.com/series/"))
wc.http_get = lambda url, headers=None: type("R", (), {"text": "", "status_code": 200})()
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
ok("12 default providers registered", len(MS.SEARCH_ORDER) == 12, str(MS.SEARCH_ORDER))
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
ok("VERSION == 4.22.0", VERSION == "4.25.0", VERSION)

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

# ══ 12. more.py — MangaKakalot / MangaSee / Mangabuddy / NineManga ══════════
print("— more providers (mangakakalot, mangasee, mangabuddy, ninemanga)")
import manga_sources.more as more

mkk = more.MangaKakalotProvider()
MKK_SEARCH = ('<a href="/manga/solo-bug"><img src="https://c.mkk/s.jpg" alt="Solo Bug"></a>'
              '<a href="/manga/other-x"><img src="https://c.mkk/o.jpg" alt="Other X"></a>')
more.http_get = lambda url, headers=None: type("R", (), {"text": MKK_SEARCH, "status_code": 200})()
s = mkk.search("solo")
ok("mangakakalot search", len(s) == 2 and s[0].title == "Solo Bug"
   and s[0].url.endswith("/manga/solo-bug"), str(s)[:80])
MKK_CH = ('<div class="chapter-list"><div class="row"><a href="/manga/solo-bug/chapter-14">Ch 14</a></div>'
          '<div class="row"><a href="/manga/solo-bug/chapter-13.5">Ch 13.5</a></div></div>')
more.http_get = lambda url, headers=None: type("R", (), {"text": MKK_CH, "status_code": 200})()
chs = mkk.chapters("https://www.mangakakalot.gg/manga/solo-bug")
ok("mangakakalot chapters", [c.number for c in chs] == ["14", "13.5"], str(chs)[:80])
MKK_IMG = '<div class="container-chapter-reader"><img src="https://cm.mkki/1.webp"/><img src="https://cm.mkki/2.webp"/></div>'
more.http_get = lambda url, headers=None: type("R", (), {"text": MKK_IMG, "status_code": 200})()
urls, ref = mkk.images(chs[0])
ok("mangakakalot images", urls == ["https://cm.mkki/1.webp", "https://cm.mkki/2.webp"], str(urls))

mse = more.MangaseeProvider()
more._post_json = lambda url, data=None: [
    {"i": "Solo-Bug-Farmer", "s": "Solo Bug Farmer", "a": ["SBF"]},
    {"i": "Other-X", "s": "Other X", "a": []}]
s = mse.search("bug")
ok("mangasee search (client-side filter)", len(s) == 1
   and s[0].cover.endswith("/cover/Solo-Bug-Farmer.jpg"), str(s)[:80])
MS_CH = ('vm.Chapters = [{"Chapter": "1140","Type":"Chapter"}'
         ',{"Chapter": "11355","Type":"Chapter"}];'
         'vm.IndexName = "Solo-Bug-Farmer";')
more.http_get = lambda url, headers=None: type("R", (), {"text": MS_CH, "status_code": 200})()
chs = mse.chapters("https://mangasee123.com/manga/Solo-Bug-Farmer")
ok("mangasee chapter decode", [c.number for c in chs] == ["14", "135.5"]
   and chs[0].url.endswith("/read-online/Solo-Bug-Farmer-chapter-14.html"), str(chs)[:100])
MS_READ = ('vm.CurChapter = {"Chapter":"1140","Page":"2","Directory":""};'
           'vm.CurPathName = "scans.mangasee.com";vm.IndexName = "Solo-Bug-Farmer";')
more.http_get = lambda url, headers=None: type("R", (), {"text": MS_READ, "status_code": 200})()
urls, ref = mse.images(chs[0])
ok("mangasee image construction",
   urls == ["https://scans.mangasee.com/manga/Solo-Bug-Farmer/14-001.png",
            "https://scans.mangasee.com/manga/Solo-Bug-Farmer/14-002.png"], str(urls))

mbd = more.MangabuddyProvider()
MBD_SEARCH = ('<div class="book-item"><a href="/manga/solo-bug"><img data-src="https://img.mb/s.jpg" alt="Solo Bug"/></a></div>')
more.http_get = lambda url, headers=None: type("R", (), {"text": MBD_SEARCH, "status_code": 200})()
s = mbd.search("solo")
ok("mangabuddy search", len(s) == 1 and s[0].url.endswith("/manga/solo-bug")
   and s[0].title == "Solo Bug", str(s)[:80])
MBD_CH = '<ul id="chapter-list"><li><a href="/manga/solo-bug/chapter-9"><strong class="chapter-title">Chapter 9</strong></a></li></ul>'
more.http_get = lambda url, headers=None: type("R", (), {"text": MBD_CH, "status_code": 200})()
chs = mbd.chapters("https://mangabuddy.com/manga/solo-bug")
ok("mangabuddy chapters", [c.number for c in chs] == ["9"], str(chs)[:80])
more.http_get = lambda url, headers=None: type("R", (), {"text": "var chapImages = 'https://i.mb/1.jpg,https://i.mb/2.jpg';", "status_code": 200})()
urls, ref = mbd.images(chs[0])
ok("mangabuddy chapImages", urls == ["https://i.mb/1.jpg", "https://i.mb/2.jpg"], str(urls))

nmn = more.NinemangaProvider()
NMN_SEARCH = ('<ul class="direlist"><li><a class="bookname" href="/manga/Solo+Bug"><img src="https://c.nm/s.jpg"/>Solo Bug</a></li></ul>')
more.http_get = lambda url, headers=None: type("R", (), {"text": NMN_SEARCH, "status_code": 200})()
s = nmn.search("solo")
ok("ninemanga search", len(s) == 1 and s[0].url.endswith("/manga/Solo+Bug"), str(s)[:80])
NMN_CH = '<div class="chapterbox"><li><a href="/manga/Solo+Bug/10/">Chapter 10</a></li></div>'
more.http_get = lambda url, headers=None: type("R", (), {"text": NMN_CH, "status_code": 200})()
chs = nmn.chapters("https://www.ninemanga.com/manga/Solo+Bug")
ok("ninemanga chapters", [c.number for c in chs] == ["10"], str(chs)[:80])
PAGES = ['<select id="page"><option value="/read/Solo+Bug/10/1"></option><option value="/read/Solo+Bug/10/2"></option></select><img class="manga_pic" src="https://pic.nm/1.jpg"/>',
         '<img class="manga_pic" src="https://pic.nm/2.jpg"/>']
more.http_get = lambda url, headers=None: type("R", (), {"text": PAGES[1] if url.endswith("/2") else PAGES[0], "status_code": 200})()
urls, ref = nmn.images(chs[0])
ok("ninemanga multi-page reader", urls == ["https://pic.nm/1.jpg", "https://pic.nm/2.jpg"], str(urls))

ok("CHAPTERS_ARG covers new providers",
   all(p in MS.CHAPTERS_ARG for p in ("mangakakalot", "mangasee", "mangabuddy", "ninemanga")))
ok("15 providers registered", len(MS.PROVIDER_NAMES) == 15, str(len(MS.PROVIDER_NAMES)))

# ══ 13. NSFW premium gating (search flag + plugin guards) ═══════════════════
print("— NSFW premium gating")
os.environ["ANIMEDL_MANGA_NSFW"] = "1"
res2, tried2 = MS.search_all("solo", nsfw=False)
ok("search_all(nsfw=False) skips 18+",
   all(pid not in MS.NSFW_IDS for pid, _ in tried2), str([p for p, _ in tried2]))
res3, tried3 = MS.search_all("solo", nsfw=True)
ok("search_all(nsfw=True) tries 18+ (env on)",
   any(pid == "manga18fx" for pid, _ in tried3), str([p for p, _ in tried3]))
os.environ["ANIMEDL_MANGA_NSFW"] = "0"
res4, tried4 = MS.search_all("solo", nsfw=True)
ok("env OFF overrides nsfw=True flag",
   all(pid not in MS.NSFW_IDS for pid, _ in tried4))

import asyncio as _aio
import cantarella.telegram.plugins.manga as mplug
async def _gate_check():
    # db unreachable -> premium False -> nsfw never allowed
    return (await mplug._nsfw_allowed(42), await mplug._default_fmt(42))
_loop = _aio.get_event_loop()
gate, dfmt = _loop.run_until_complete(_gate_check())
ok("_nsfw_allowed denies without premium/db", gate is False)
ok("_default_fmt falls back to pdf", dfmt == "pdf")

class _FakeDB:
    def __init__(self, prem, show, fmt):
        self.prem, self.show, self.fmt = prem, show, fmt
    async def is_premium(self, uid): return self.prem
    async def get_user_setting(self, uid, key, default=None):
        return {"show_nsfw": self.show, "manga_format": self.fmt}.get(key, default)
    async def premium_until(self, uid): return "2027-01-01T00:00:00"
import cantarella.core.database as cdb
_real_db = cdb.db
cdb.db = _FakeDB(prem=True, show=True, fmt="cbz")
os.environ["ANIMEDL_MANGA_NSFW"] = "1"
gate2 = _loop.run_until_complete(mplug._nsfw_allowed(42))
cdb.db = _FakeDB(prem=False, show=True, fmt="cbz")
gate3 = _loop.run_until_complete(mplug._nsfw_allowed(42))
os.environ["ANIMEDL_MANGA_NSFW"] = "0"
cdb.db = _FakeDB(prem=True, show=True, fmt="cbz")
gate4 = _loop.run_until_complete(mplug._nsfw_allowed(42))
cdb.db = _real_db
ok("premium + opt-in + env -> nsfw on", gate2 is True)
ok("no premium -> nsfw off", gate3 is False)
ok("env off -> nsfw off even premium", gate4 is False)

# usettings builders are pure functions — verify shapes
import cantarella.telegram.plugins.usettings as us
mk_free = us._settings_markup({"fmt": "pdf", "nsfw": False, "premium": False, "until": ""})
mk_prem = us._settings_markup({"fmt": "cbz", "nsfw": True, "premium": True, "until": "2027-01-01"})
_free_labels = [b.text for row in mk_free.inline_keyboard for b in row]
_prem_labels = [b.text for row in mk_prem.inline_keyboard for b in row]
ok("usettings hides toggle for free users",
   any("ᴘʀᴇᴍɪᴜᴍ ᴏɴʟʏ" in l for l in _free_labels)
   and not any(l.startswith("🔞 18+ ꜱᴏᴜʀᴄᴇꜱ: ᴏɴ") for l in _free_labels))
ok("usettings shows toggle for premium",
   any("🔞" in l for l in _prem_labels))
txt_free = us._settings_text({"fmt": "pdf", "nsfw": False, "premium": False, "until": ""})
ok("usettings text renders", "ᴘᴅꜰ" in txt_free and "ᴏꜰꜰ" in txt_free)


# ══ 14. v4.24.0 — cloudscraper escalation, http_post, richgram UI ═══════════
print("— cloudscraper escalation + http layer (v4.24.0 render-log fixes)")
import manga_sources.base as _base

# a) params fix: real http_json forwards params (mangadex render bug)
import inspect
ok("http_json accepts params",
   "params" in inspect.signature(_base.http_json).parameters)
ok("http_get accepts params",
   "params" in inspect.signature(_base.http_get).parameters)
ok("http_post exists",
   callable(getattr(_base, "http_post", None)))

# b) cloudscraper escalation: plain requests 403 → CS session returns 200
class _CS:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
    def get(self, url, headers=None, params=None, data=None, timeout=None):
        self.calls += 1
        return type("R", (), {"status_code": 200, "text": self.payload,
                              "headers": {}})()

_probe = {"n": 0}
def _blocked_get(url, headers=None, params=None, timeout=None):
    _probe["n"] += 1
    raise _base.requests.exceptions.SSLError("no")  # pragma: no cover
class _Blocked403:
    def get(self, url, headers=None, params=None, data=None, timeout=None):
        return type("R", (), {"status_code": 403, "text": "cf", "headers": {}})()

_cs_fake = _CS("hello-after-cs")
_real_scraper = _base._scraper
_base._scraper = lambda: _cs_fake
_real_requests_get = _base.requests.get
def _req403(url, headers=None, params=None, data=None, timeout=None):
    return _Blocked403().get(url)
_base.requests.get = _req403
try:
    resp = _base.http_get("https://cf-blocked.example/search?q=x")
    ok("403 escalates to cloudscraper",
       resp.status_code == 200 and _cs_fake.calls == 1
       and _probe["n"] == 0)
finally:
    _base.requests.get = _real_requests_get
    _base._scraper = _real_scraper

# c) escalation does NOT trigger for non-block statuses (e.g. 404 → error)
class _NotFound:
    def get(self, url, headers=None, params=None, data=None, timeout=None):
        return type("R", (), {"status_code": 404, "text": "x", "headers": {}})()
_cs_fake2 = _CS("should-not-be-used")
_base._scraper = lambda: _cs_fake2
_base.requests.get = lambda url, headers=None, params=None, data=None, timeout=None: \
    _NotFound().get(url)
try:
    _base.http_get("https://example/missing")
    ok("404 stays a clean failure", False)
except IOError as e:
    ok("404 stays a clean failure", "404" in str(e) and _cs_fake2.calls == 0, str(e))
finally:
    _base.requests.get = _real_requests_get
    _base._scraper = _real_scraper

# d) http_post escalation
class _Post403_200:
    def post(self, url, data=None, headers=None, params=None, timeout=None):
        return type("R", (), {"status_code": 200, "text": "posted",
                              "headers": {}})()
def _post403(url, data=None, headers=None, params=None, timeout=None):
    return type("R", (), {"status_code": 403, "text": "cf", "headers": {}})()
_p = _Post403_200()
_real_requests_post = _base.requests.post
_base.requests.post = _post403
_base._scraper = lambda: _p
try:
    r = _base.http_post("https://blocked.example/post", data={"a": "b"})
    ok("http_post escalates on 403", r.status_code == 200 and r.text == "posted")
finally:
    _base.requests.post = _real_requests_post
    _base._scraper = _real_scraper

# e) UI: _render_results builds the richgram card (health bar + chips + pages)
print("— richgram-style results renderer")
import cantarella.telegram.plugins.manga as _mp
ok("provider badges cover registry",
   all(p in _mp._BADGES for p in MS.SEARCH_ORDER), str(MS.SEARCH_ORDER))

class _FakeMsg:
    def __init__(self):
        self.captured = {}
    async def edit_message_caption(self, caption=None, reply_markup=None, **k):
        self.captured = {"text": caption, "markup": reply_markup,
                         "caption": True}
    async def edit_text(self, text=None, reply_markup=None, **k):
        self.captured = {"text": text, "markup": reply_markup, "caption": False}

_mp.user_manga[4242] = {
    "query": "one piece", "results": [], "mangas": {}, "chapters": {},
    "tried": [("mangadex", 3), ("comick", "MangaError: x"), ("asura", 2)],
}
_msg = _FakeMsg()
_loop2 = _aio.get_event_loop()
_loop2.run_until_complete(_mp._render_results(_msg, 4242, 0))
_cap = _msg.captured.get("text") or ""
ok("results card has health bar", "▰" in _cap and "2/3" in _cap, _cap[:120])
ok("results card chips with warn", "ᴄᴋ ⚠️" in _cap, _cap[:160])
_markup = _msg.captured.get("markup")
_labels = [b.text for row in _markup.inline_keyboard for b in row] if _markup else []
_mp.user_manga[4242]["results"] = [
    MangaSearchResult(provider="mangadex", id=f"m{i}", title=f"T{i}")
    for i in range(10)]
_msg2 = _FakeMsg()
_loop2.run_until_complete(_mp._render_results(_msg2, 4242, 0))
_m2 = _msg2.captured.get("markup")
_l2 = [b.text for row in _m2.inline_keyboard for b in row] if _m2 else []
ok("8 results per page + nav",
   sum(1 for l in _l2 if l.split("·")[0].strip().isdigit()) == 8
   and any("1/2" in l for l in _l2) and any("➡️" in l for l in _l2), str(_l2))
_msg3 = _FakeMsg()
_loop2.run_until_complete(_mp._render_results(_msg3, 4242, 1))
_m3 = _msg3.captured.get("markup")
_l3 = [b.text for row in _m3.inline_keyboard for b in row] if _m3 else []
ok("page 2 shows remainder + back",
   sum(1 for l in _l3 if l.split("·")[0].strip().isdigit()) == 2
   and any("⬅️" in l for l in _l3), str(_l3))
ok("card header shows query",
   "one piece" in (_msg2.captured.get("text") or ""))
_mp.user_manga.pop(4242, None)

# f) blocked-source search still returns other providers (render-log shape)
class _CFDown:
    def search(self, q):
        raise IOError("HTTP 403 on https://cf.example/search")
MS.get_provider = lambda pid: _CFDown() if pid in ("asura", "templetoons") \
    else real_gp(pid)
res5, tried5 = MS.search_all("one piece")
MS.get_provider = real_gp
ok("CF-blocked sources degrade to ⚠️, search survives",
   any(pid == "asura" and isinstance(o, str) for pid, o in tried5)
   and len(tried5) == len(MS.SEARCH_ORDER), str(tried5)[:120])


# ══ 15. v4.24.1 — callbacks parse cq.data (no .pattern on CallbackQuery) ════
print("— v4.24.1 callback parsing (render AttributeError fix)")
for _plug in ("cantarella/telegram/plugins/manga.py",
              "cantarella/telegram/plugins/usettings.py"):
    _psrc = Path(_plug).read_text()
    ok("no cq.pattern left in " + _plug.split("/")[-1],
       "cq.pattern" not in _psrc)

class _FakeMsg2:
    def __init__(self):
        self.captured = {}
    async def edit_message_caption(self, caption=None, reply_markup=None, **k):
        self.captured = {"text": caption, "markup": reply_markup}
    async def edit_text(self, text=None, reply_markup=None, **k):
        self.captured = {"text": text, "markup": reply_markup}

class _FakeCQ:
    """Mimics the real runtime: NO .pattern attribute at all."""
    def __init__(self, data, uid):
        self.data = data
        self.from_user = type("U", (), {"id": uid})()
        self.message = _FakeMsg2()
        self.answered = []
    async def answer(self, text=None, show_alert=False):
        self.answered.append((text, show_alert))
    async def edit_message_caption(self, caption=None, reply_markup=None, **k):
        await self.message.edit_message_caption(caption=caption,
                                                reply_markup=reply_markup, **k)
    async def edit_message_text(self, text=None, reply_markup=None, **k):
        await self.message.edit_text(text=text, reply_markup=reply_markup, **k)

_loop3 = _aio.get_event_loop()

# the exact crash from the report: mgp_ pick with no .pattern attribute
_fake_prov_calls = []
class _FakeProv:
    def chapters(self, arg):
        _fake_prov_calls.append(arg)
        return [MangaChapter(id="c1", number="33", title="War")]
_real_gp15 = MS.get_provider
MS.get_provider = lambda pid: _FakeProv()
_cq = _FakeCQ("mgp_mangadex_0", 5150)
_mp.user_manga[5150] = {"query": "op", "results": [
    MangaSearchResult(provider="mangadex", id="mid", title="One Piece Test")],
    "mangas": {}, "chapters": {}, "tried": [("mangadex", 1)]}
_loop3.run_until_complete(_mp.on_manga_pick(None, _cq))
ok("on_manga_pick works without .pattern",
   _fake_prov_calls == ["mid"]
   and _mp.user_manga[5150]["chapters"]["mangadex_0"][0].number == "33",
   str(_mp.user_manga[5150].get("chapters")))
MS.get_provider = _real_gp15

# respage
_cq = _FakeCQ("mgsl_1", 5150)
_mp.user_manga[5150]["results"] = [
    MangaSearchResult(provider="mangadex", id=f"m{i}", title=f"T{i}")
    for i in range(10)]
_loop3.run_until_complete(_mp.on_manga_respage(None, _cq))
ok("on_manga_respage parses cq.data",
   _mp.user_manga[5150].get("res_page") == 1
   and "2/2" in (_cq.message.captured.get("text") or ""))

# chpage
_cq = _FakeCQ("mgc_mangadex_0_0", 5151)
_mp.user_manga[5151] = {
    "mangas": {"mangadex_0": MangaSearchResult(provider="mangadex",
                                               id="m", title="T")},
    "chapters": {"mangadex_0": [MangaChapter(id="c1", number="1")]},
    "results": [], "query": "x", "tried": []}
_loop3.run_until_complete(_mp.on_manga_chpage(None, _cq))
ok("on_manga_chpage parses cq.data",
   "ᴄʜᴀᴘᴛᴇʀꜱ: 1" in (_cq.message.captured.get("text") or ""),
   str(_cq.message.captured)[:120])

# download guard: parse succeeds → proceeds to stale-check (state empty on purpose)
_cq = _FakeCQ("mgd_mangadex_0_0_3_pdf", 5152)
_mp.user_manga[5152] = {"mangas": {}, "chapters": {}, "results": [],
                        "query": "x", "tried": []}
_loop3.run_until_complete(_mp.on_manga_download(None, _cq))
ok("on_manga_download parses 4-group cq.data",
   any("ꜱᴛᴀʟᴇ ʟɪɴᴋ" in (a[0] or "") for a in _cq.answered), str(_cq.answered))

# usettings format toggle
import cantarella.telegram.plugins.usettings as _us
import cantarella.core.database as _cdb15
class _FakeDB15:
    async def set_user_setting(self, uid, key, value): return True
    async def get_user_setting(self, uid, key, default=None):
        return {"manga_format": "cbz", "show_nsfw": False}.get(key, default)
    async def is_premium(self, uid): return False
_real_db15 = _cdb15.db
_cdb15.db = _FakeDB15()
_cq = _FakeCQ("us_fmt_cbz", 5153)
_loop3.run_until_complete(_us.on_us_fmt(None, _cq))
_cdb15.db = _real_db15
ok("on_us_fmt parses cq.data",
   "ᴄʙᴢ" in (_cq.message.captured.get("text") or ""), str(_cq.message.captured)[:120])
_mp.user_manga.pop(5150, None); _mp.user_manga.pop(5151, None)
_mp.user_manga.pop(5152, None)


# ══ 16. v4.25.0 — MangaBot command suite (/msearch /minfo /mqueue …) ════════
print("— MangaBot suite (manga-repo commands, no duplicates)")
import manga_sources.mangadex as _mdxm

# random_sfw + info parsing via faked module-level http_json
_RAND_ITEM = {"id": "rand1", "attributes": {
    "title": {"en": "Random Toon"}, "status": "ongoing",
    "year": 2024, "tags": [{"attributes": {"name": {"en": "Comedy"}}}],
    "description": {"en": "A very random toon about things. " * 40}},
    "relationships": [{"type": "cover_art",
                       "attributes": {"fileName": "r.jpg"}}]}
def _fake_json(url, headers=None, params=None):
    if "/random-manga" in url:
        return {"data": _RAND_ITEM}
    if url.endswith("/manga"):
        assert params and params.get("title"), "info must pass title param"
        return {"data": [_RAND_ITEM]}
    raise AssertionError("unexpected url " + url)
_real_mdx_json = _mdxm.http_json
_mdxm.http_json = _fake_json
try:
    _mdx_p = _mdxm.MangaDexProvider()
    rr = _mdx_p.random_sfw()
    ok("random_sfw parses", rr.id == "rand1" and rr.title == "Random Toon"
       and rr.cover.endswith("/covers/rand1/r.jpg.256.jpg"))
    inf = _mdx_p.info("random toon")
    ok("info card fields", inf["status"] == "ongoing" and inf["year"] == 2024
       and inf["tags"] == ["Comedy"]
       and len(inf["description"]) > 350 and inf["result"].id == "rand1")
finally:
    _mdxm.http_json = _real_mdx_json

# mangabot registration + source lists consistent with the registry
import cantarella.telegram.plugins.mangabot as _mb
def _cmd_names15(obj, seen=None):
    seen = seen or set()
    if id(obj) in seen:
        return set()
    seen.add(id(obj))
    out = set()
    v = getattr(obj, "commands", None)
    if v:
        out.update(v)
    for attr in ("filters", "parent", "base", "other"):
        v = getattr(obj, attr, None)
        if isinstance(v, (list, tuple)):
            for s in v:
                out |= _cmd_names15(s, seen)
        elif v is not None and hasattr(v, "__dict__"):
            out |= _cmd_names15(v, seen)
    return out
_mb_cmds = set()
for h in _mb.__dict__.values():
    if hasattr(h, "handlers"):
        for h2, _ in h.handlers:
            f = getattr(h2, "filters", None)
            if f is not None:
                _mb_cmds |= _cmd_names15(f)
for c in ("msearch", "minfo", "mqueue", "mclean", "mrefresh", "mpost"):
    ok(f"/{c} registered", c in _mb_cmds, str(sorted(_mb_cmds)))
ok("no duplicate of /manga in mangabot", "manga" not in _mb_cmds)
ok("mangabot sources == registry SFW",
   set(_mb._SFW) == set(MS.SEARCH_ORDER))
ok("mangabot NSFW list == NSFW_IDS", set(_mb._NSFW) == set(MS.NSFW_IDS))

# last_dl wiring (mrefresh depends on it)
ok("manga.py records last_dl",
   'state["last_dl"]' in Path("cantarella/telegram/plugins/manga.py").read_text())

# help + menu mention the suite
_scr15 = Path("Script.py").read_text()
ok("help mentions MangaBot suite",
   "/msearch" in _scr15 and "/mrefresh" in _scr15 and "/mpost" in _scr15)
_utils15 = Path("cantarella/telegram/utils.py").read_text()
ok("menu registers MangaBot suite",
   all(c in _utils15 for c in ("msearch", "minfo", "mqueue", "mclean",
                               "mrefresh", "mpost")))

n_fail = sum(1 for _, c in PASS if not c)
print(f"\n═══ test_manga: {len(PASS) - n_fail}/{len(PASS)} passed ═══")
sys.exit(1 if n_fail else 0)
