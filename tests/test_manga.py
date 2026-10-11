#!/usr/bin/env python3
"""v4.21.0 manga engine tests — builders, fetch_images, providers (faked
HTTP), aggregation, plugin wiring. Live-reachable providers are exercised
 opportunistically (skipped, not failed, when offline)."""
import io
import json
import os
import sys
import threading
import http.server
import socketserver
import functools
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
                           build_output, fetch_images, get_provider,
                           sanitize, search_all)
from manga_sources.base import images_to_cbz, images_to_pdf
from PIL import Image

# ══ 1. builders ═════════════════════════════════════════════════════════════
print("— PDF/CBZ builders")
import shutil as _sh
tmp = Path("/tmp/t_manga"); _sh.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
pages = []
for i, color in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
    img = Image.new("RGB", (60, 80), color)
    p = tmp / f"{i:04d}.img"
    img.save(p, format="PNG")
    pages.append(p)
prog = []
pdf = images_to_pdf(pages, tmp / "ch.pdf", progress=lambda d, t: prog.append((d, t)))
ok("PDF built", pdf.exists() and pdf.stat().st_size > 500, str(pdf))
with open(pdf, "rb") as f:
    head = f.read(5)
ok("PDF magic", head == b"%PDF-")
ok("PDF progress fired", bool(prog))
cbz = images_to_cbz(pages, tmp / "ch.cbz")
import zipfile
with zipfile.ZipFile(cbz) as zf:
    names = zf.namelist()
ok("CBZ built with 3 STORED pages", len(names) == 3 and
   zipfile.ZipFile(cbz).getinfo(names[0]).compress_type == zipfile.ZIP_STORED,
   str(names))

# ══ 2. fetch_images against a live loopback server (with a dead page) ═══════
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
                    f"http://127.0.0.1:{PORT}/c"], wd,
                   progress=lambda d, t: None)
ok("dead page skipped, good pages kept in order",
   len(got) == 2 and got[0].name == "0000.img" and got[1].name == "0002.img",
   str([g.name for g in got]))
srv.shutdown()

# ══ 3. MangaDex provider (faked http_json) ══════════════════════════════════
print("— MangaDex provider")
from manga_sources import mangadex as mdx
FAKE_SEARCH = {"data": [{
    "id": "a1b2", "attributes": {
        "title": {"en": "Solo Leveling"},
        "altTitles": [{"ko": "나혼자만"}],
        "status": "ongoing",
        "tags": [{"attributes": {"name": {"en": "Action"}}},
                 {"attributes": {"name": {"en": "Fantasy"}}}],
    },
    "relationships": [{"type": "cover_art",
                       "attributes": {"fileName": "cover.jpg"}}],
}]}
mdx.http_json = lambda url, headers=None, params=None: (
    FAKE_SEARCH if "/manga?" in url or (params and "title" in (params or {}))
    and url.endswith("/manga") else
    {"data": [
        {"id": "ch1", "attributes": {"chapter": "110", "title": "The End",
                                     "pages": 14}},
        {"id": "ch0", "attributes": {"chapter": "109.5", "title": "", "pages": 8}},
        {"id": "chx", "attributes": {"chapter": "108", "title": "ext", "pages": 0}},
    ]} if "/feed" in url else
    {"baseUrl": "https://uploads.mangadex.org",
     "chapter": {"hash": "h1", "data": ["p1.jpg", "p2.jpg"], "dataSaver": []}}
)
prov = mdx.MangaDexProvider()
res = prov.search("solo")
ok("mangadex search shape", len(res) == 1 and res[0].title == "Solo Leveling"
   and "cover" in res[0].cover, str(res)[:80])
chs = prov.chapters("a1b2")
ok("mangadex chapters (0-page external skipped)",
   [c.number for c in chs] == ["110", "109.5"], str([c.number for c in chs]))
urls, ref = prov.images(MangaChapter(id="ch1", number="110"))
ok("mangadex at-home image urls", urls == [
    "https://uploads.mangadex.org/data/h1/p1.jpg",
    "https://uploads.mangadex.org/data/h1/p2.jpg"] and ref.startswith("https://mangadex"))

# ══ 4. Comick provider (faked) ══════════════════════════════════════════════
print("— Comick provider")
from manga_sources import comick as ck
ckp = ck.ComickProvider()
ckp._api_get = lambda path, params=None: (
    [{"slug": "solo-leveling", "title": "Solo Leveling",
      "md_covers": [{"b2key": "k1"}], "status": "ongoing", "last_chapter": 179}]
    if path == "/v1.0/search/" else
    {"comic": {"hid": "HID9"}} if path.startswith("/comic/solo") else
    {"chapters": [{"hid": "c1", "chap": "179", "title": "Arise"},
                  {"hid": "c2", "chap": "178", "title": None},
                  {"hid": "c3", "chap": "", "title": "skip me"}]})
s = ckp.search("solo")
ok("comick search shape", len(s) == 1 and s[0].cover.endswith("k1")
   and s[0].id == "solo-leveling")
chs = ckp.chapters("solo-leveling")
ok("comick chapters (numberless skipped)",
   [c.number for c in chs] == ["179", "178"], str([c.number for c in chs]))
NEXT_HTML = ('<html><script id="__NEXT_DATA__" type="application/json">'
             + json.dumps({"props": {"pageProps": {"chapter": {"md_images": [
                 {"b2key": "img1"}, {"b2key": "img2"}]}}}})
             + "</script></html>")
class FakeResp:
    text = NEXT_HTML
    status_code = 200
    content = NEXT_HTML.encode()
ck.http_get = lambda url, headers=None: FakeResp()
urls, ref = ckp.images(MangaChapter(id="c1", number="179"))
ok("comick NEXT_DATA images", urls == [
    "https://meo.comick.pictures/img1", "https://meo.comick.pictures/img2"])

# ══ 5. Asura provider (faked HTML) ══════════════════════════════════════════
print("— Asura provider")
from manga_sources import asura as asr
SEARCH_HTML = ('<a href="/series/solo-leveling-12345"><img src="https://gg.asuracomic.net/c.jpg"/>'
               '<span>Solo Leveling</span></a>')
asr.http_get = lambda url, headers=None: type("R", (), {"text": SEARCH_HTML, "status_code": 200})()
ap = asr.AsuraProvider()
s = ap.search("solo")
ok("asura search shape", len(s) == 1 and s[0].id == "12345"
   and s[0].url.endswith("/series/solo-leveling-12345"), str(s)[:90])
CH_HTML = ('<a href="/series/solo-leveling-12345/chapter-180"><h3>Chapter 180</h3></a>'
           '<a href="/series/solo-leveling-12345/chapter-179.5"><h3>Chapter 179.5</h3></a>')
asr.http_get = lambda url, headers=None: type("R", (), {"text": CH_HTML, "status_code": 200})()
chs = ap.chapters("https://asuracomic.net/series/solo-leveling-12345")
ok("asura chapters incl. decimal", [c.number for c in chs] == ["180", "179.5"],
   str([c.number for c in chs]))
FLIGHT = 'self.__next_f.push([1,"x \\\"pages\\\":[{\\\"url\\\":\\\"https://gg.asuracomic.net/p1.webp\\\"},{\\\"url\\\":\\\"https://gg.asuracomic.net/p2.webp\\\"}] y")'
asr.http_get = lambda url, headers=None: type("R", (), {"text": FLIGHT, "status_code": 200})()
urls, ref = ap.images(chs[0])
ok("asura flight-data images", urls == [
    "https://gg.asuracomic.net/p1.webp", "https://gg.asuracomic.net/p2.webp"],
    str(urls))

# ══ 6. aggregation tolerance ════════════════════════════════════════════════
print("— search_all aggregation")
import manga_sources as MS
real_gp = MS.get_provider
class Boom:
    def search(self, q): raise RuntimeError("down")
MS.get_provider = lambda pid: Boom() if pid == "comick" else real_gp(pid)
results, tried = MS.search_all("solo")
MS.get_provider = real_gp
ok("one dead provider ≠ dead search", len(results) >= 1
   and any(pid == "comick" and isinstance(o, str) for pid, o in tried),
   str(tried))

# ══ 7. sanitize + wiring ════════════════════════════════════════════════════
print("— sanitize & wiring")
ok("sanitize strips junk", sanitize('a/b:c*d?"<>|') == "abcd")
plug = Path(ROOT, "cantarella", "telegram", "plugins", "manga.py").read_text()
ok("plugin registered (folder-scan loads it)",
   "mgd_" in plug and "send_document" in plug)
ok("help mentions /manga", "/manga" in Path(ROOT, "Script.py").read_text())
ok("no third-party branding in plugin",
   not any(b in plug.lower() for b in ("codeflix", "abhinai", "dra-sama")))
from config import VERSION
ok("VERSION == 4.21.0", VERSION == "4.21.0", VERSION)

# ══ 8. LIVE opportunistic probes (skipped when offline) ═════════════════════
print("— live probes (best-effort)")
try:
    import requests as _rq
    _rq.get("https://api.mangadex.org/ping", timeout=5)
    live = mdx.MangaDexProvider()
    live_res = live.search("solo leveling")
    ok("LIVE mangadex search", len(live_res) > 0, f"{len(live_res)} results")
    if live_res:
        live_chs = live.chapters(live_res[0].id)
        ok("LIVE mangadex chapters", len(live_chs) > 0, f"{len(live_chs)} chapters")
        if live_chs:
            urls, ref = live.images(live_chs[0])
            ok("LIVE mangadex images", len(urls) > 0, f"{len(urls)} pages")
except Exception as e:
    print(f"  ⏭ live mangadex unreachable: {type(e).__name__}")
try:
    import requests as _rq
    _rq.get("https://api.comick.fun", timeout=5)
    ckp2 = ck.ComickProvider()
    r2 = ckp2.search("solo leveling")
    ok("LIVE comick search", len(r2) > 0, f"{len(r2)} results")
except Exception as e:
    print(f"  ⏭ live comick unreachable: {type(e).__name__}")

n_fail = sum(1 for _, c in PASS if not c)
print(f"\n═══ test_manga: {len(PASS) - n_fail}/{len(PASS)} passed ═══")
sys.exit(1 if n_fail else 0)
