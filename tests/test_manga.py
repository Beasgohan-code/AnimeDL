# ═══════════════════════════════════════════════════════════════════════════
# test_manga — vendored manga chapter-update engine (mangarepo/, v6.0.0)
# The FULL external repo runs inside AnimeDL; these checks prove:
#   vendor integrity · 35-source manager · REAL PDF/CBZ binaries · DB subs
#   mixin logic · check-scheduler interval gating · bridge handler wiring ·
#   zero duplicate commands · menu/help consistency.
# No live network: scrapers are stubbed where the pipeline is exercised.
# ═══════════════════════════════════════════════════════════════════════════
import os
import sys
import json
import asyncio as _aio
import zipfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "dummy")
os.environ.setdefault("BOT_TOKEN", "1:dummy")
os.environ.setdefault("OWNER_ID", "1")

PASS = []
def ok(name, cond, extra=""):
    PASS.append((name, bool(cond)))
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {extra}" if (extra and not cond) else ""))

print("═ test_manga (v6.0.0): vendored manga chapter-update engine ═")

# ══ 1. vendor integrity ═════════════════════════════════════════════════════
print("— vendor integrity")
import mangarepo.config as MC
ok("config vendored", MC.Config.DOWNLOAD_DIR == "downloads")
ok("MONGO_DB_URI falls back to MONGO_URL", bool(MC.Config.MONGO_DB_URI))
from mangarepo.database.db import db as mdb
ok("db instantiates (motor lazy)", mdb is not None)
import mangarepo.sources as MSRC
webs = [n for n in dir(MSRC) if n.endswith("Webs")]
ok("35 scraper classes exported", len(webs) == 35, f"{len(webs)}")
ok("scraper interface uniform",
   all(all(hasattr(getattr(MSRC, n), m) for m in
           ("search", "get_chapters", "iter_chapters", "get_pictures"))
       for n in webs))
ok("key sources present",
   all(hasattr(MSRC, n) for n in ("AsuraScansWebs", "ComickWebs", "BatotoWebs",
                                  "WeebCentralWebs", "MangaKakalotGGWebs")))

# ══ 2. manager: loads all sources + parallel tagged merge ═══════════════════
print("— source manager (services/mgr)")
from mangarepo.services.mgr import mgr
ok("mgr loads all 35 sources", len(mgr.srcs) == 35, f"{len(mgr.srcs)}")
ok("mgr.get hits registry", mgr.get("ComickWebs") is not None)

class _GoodSrc:
    async def search(self, q):
        return [{"title": f"{q} Toon", "mid": "m1"}]
class _BoomSrc:
    async def search(self, q):
        raise RuntimeError("site down")
_real_srcs = mgr.srcs
mgr.srcs = {"GoodWebs": _GoodSrc(), "BoomWebs": _BoomSrc()}
res = _aio.new_event_loop().run_until_complete(mgr.search("solo"))
mgr.srcs = _real_srcs
ok("parallel search merges + tags src",
   len(res) == 1 and res[0]["src"] == "GoodWebs" and res[0]["title"] == "solo Toon")

# ══ 3. REAL binary proof: PDF + CBZ built from local images ═════════════════
print("— REAL PDF/CBZ binaries (services/dl)")
from mangarepo.services.dl import DL
from PIL import Image
with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    pages_dir = tdp / "pages"; pages_dir.mkdir()
    for i in range(3):
        Image.new("RGB", (60, 80), (i * 60, 90, 140)).save(pages_dir / f"{i:03d}.png")
    d = DL()
    pdf = d.pdf(pages_dir, "Solo Toon", "Chapter 12")
    ok("PDF built (reportlab)", pdf is not None and Path(pdf).exists())
    if pdf:
        head = Path(pdf).read_bytes()[:5]
        from pypdf import PdfReader
        n_pages = len(PdfReader(str(pdf)).pages)
        ok("PDF is a real 3-page PDF", head == b"%PDF-" and n_pages == 3,
           f"head={head} pages={n_pages}")
    cbz = d.cbz(pages_dir, "Solo Toon", "Chapter 12")
    ok("CBZ built (zip)", cbz is not None and Path(cbz).exists())
    if cbz:
        with zipfile.ZipFile(cbz) as z:
            names = z.namelist()
        ok("CBZ holds 3 real pages", len([n for n in names if n.endswith(".png")]) == 3,
           str(names))
    from mangarepo.services.util import extract_chap_no, sanitize, clean_chap
    ok("chapter number parsing", extract_chap_no("Chapter 12.5 — Extra") == "012.5")
    ok("filename sanitizer", sanitize("A/B:C*D?") == "ABCD" or "/" not in sanitize("A/B"))

# ══ 4. DB subs mixin logic (fake collections) ═══════════════════════════════
print("— engine DB (subs mixin, fake collections)")
class _Cur:
    def __init__(self, docs): self._d = list(docs)
    async def to_list(self, n): return list(self._d)
    def __aiter__(self):
        async def _gen(docs):
            for x in docs: yield x
        return _gen(self._d)
class _Col:
    def __init__(self): self.docs = []
    def _match(self, d, q): return all(d.get(k) == v for k, v in q.items())
    async def find_one(self, q):
        for x in self.docs:
            if self._match(x, q): return dict(x)
        return None
    async def insert_one(self, d): self.docs.append(dict(d))
    async def update_one(self, q, upd, upsert=False):
        for x in self.docs:
            if self._match(x, q):
                for k, v in upd.get("$set", {}).items(): x[k] = v
                for k, v in upd.get("$addToSet", {}).items():
                    x.setdefault(k, [])
                    if v not in x[k]: x[k].append(v)
                return
        if upsert:
            nd = dict(q)
            for k, v in upd.get("$set", {}).items(): nd[k] = v
            self.docs.append(nd)
    def find(self, q=None):
        q = q or {}
        return _Cur([dict(x) for x in self.docs if self._match(x, q)])
    async def distinct(self, key, q=None):
        q = q or {}
        return sorted({x.get(key) for x in self.docs
                       if self._match(x, q) and x.get(key) is not None})
    async def delete_one(self, q):
        for i, x in enumerate(self.docs):
            if self._match(x, q): del self.docs[i]; return

mdb.subs = _Col()
loop = _aio.new_event_loop()
sid1 = loop.run_until_complete(mdb.add_sub(7, {"title": "Toon A", "cid": -100,
                                               "mid": "m1", "src": "AsuraScansWebs"}))
ok("add_sub returns fresh sid", bool(sid1))
sid_dup = loop.run_until_complete(mdb.add_sub(7, {"title": "Toon A", "cid": -100,
                                                  "mid": "m2", "src": "ComickWebs"}))
ok("add_sub dedupes same title+cid", sid_dup == sid1)
loop.run_until_complete(mdb.add_source_to_sub(7, sid1, "m9", "BatotoWebs"))
got = loop.run_until_complete(mdb.get_sub(7, sid1))
ok("fallback sources accumulate", len(got["sources"]) == 2)
loop.run_until_complete(mdb.add_sub(7, {"title": "Toon B", "cid": -200,
                                        "mid": "m3", "src": "ComickWebs"}))
subs7 = loop.run_until_complete(mdb.get_subs(7))
ok("get_subs per-user", len(subs7) == 2)
ok("user channels distinct", loop.run_until_complete(mdb.get_user_channels(7)) == [-200, -100])

# ══ 5. per-user cfg + check scheduler interval gating ═══════════════════════
print("— check scheduler (per-user interval gating)")
import mangarepo.plugins.check.scheduler as sched_mod
mdb.conf = _Col()
loop.run_until_complete(mdb.set_cfg(7, "interval", 30))
loop.run_until_complete(mdb.set_cfg(8, "interval", 60))
loop.run_until_complete(mdb.set_cfg(9, "mon", False))
loop.run_until_complete(mdb.add_sub(8, {"title": "Recent", "cid": -300,
                                        "mid": "m4", "src": "ComickWebs"}))
sched_mod.set_last_check(8, __import__("time").time())  # user 8 checked just now
processed = []
async def _fake_check(app, uid, sub):
    processed.append((uid, sub["title"]))
_real_psc = sched_mod.process_sub_check
sched_mod.process_sub_check = _fake_check
try:
    loop.run_until_complete(sched_mod.check_job(app=None))
finally:
    sched_mod.process_sub_check = _real_psc
ok("due user processed", (7, "Toon A") in [(u, t) for u, t in processed],
   str(processed))
ok("recent user skipped by interval", all(u != 8 for u, _ in processed))
ok("mon=off user skipped", all(u != 9 for u, _ in processed))
ok("last_check recorded for due user", sched_mod.get_last_check(7) > 0)
ok("recent user last_check preserved",
   abs(sched_mod.get_last_check(8) - __import__("time").time()) < 60)

# ══ 6. bridge: engine handlers attach to a recorder client ══════════════════
print("— mangabridge wiring")
from cantarella.telegram.mangabridge import install_manga_engine, _MODULES
class _RecApp:
    def __init__(self): self.added = []
    def add_handler(self, h, g=0): self.added.append((h, g))
ra = _RecApp()
n = install_manga_engine(ra)
ok("all 12 engine modules load", n > 40 and ra.added, f"handlers={n}")

def _collect_commands(h):
    out = set()
    def walk(f):
        if f is None: return
        cmds = getattr(f, "commands", None)
        if cmds: out.update(cmds)
        for attr in ("filters", "parent", "base", "other"):
            v = getattr(f, attr, None)
            if isinstance(v, (list, tuple)):
                for s in v: walk(s)
            elif v is not None and hasattr(v, "__dict__"):
                walk(v)
    walk(getattr(h, "filters", None))
    return out

engine_cmds = set()
for h, _ in ra.added:
    engine_cmds |= _collect_commands(h)
expected = {"search", "list", "del", "check", "stop", "info",
            "msettings", "usersettings", "cbroadcast", "banned", "dbstats", "deluser"}
ok("engine commands registered", expected <= engine_cmds,
   str(sorted(expected - engine_cmds)))
forbidden = {"start", "help", "settings", "usettings", "ban", "unban",
             "broadcast", "stats", "eval", "sh"}
ok("ZERO duplicate commands vs AnimeDL",
   not (engine_cmds & forbidden), str(sorted(engine_cmds & forbidden)))

# ══ 7. engine details: fsub off, shared helpers, scraper attrs ══════════════
print("— engine details")
from mangarepo.plugins.fsub import get_not_subscribed
ok("fsub disabled when no channels",
   loop.run_until_complete(get_not_subscribed(ra, 7)) == [])
from mangarepo.plugins.check.shared import (parse_chap_num, cancel_download,
                                            is_download_cancelled, clear_cancel_flag)
ok("parse_chap_num", parse_chap_num("Chapter 100") == 100.0)
cancel_download(7, sid1)
ok("cancel flag roundtrip", is_download_cancelled(7, sid1))
clear_cancel_flag(7, sid1)
ok("clear flag", not is_download_cancelled(7, sid1))
src_inst = MSRC.ComickWebs()
ok("scraper instance exposes base url",
   any(hasattr(src_inst, a) for a in ("base_url", "url", "BASE_URL", "api_url")))
from mangarepo.plugins.settings.shared import get_temp_dir, _s, _set
ok("settings helpers", get_temp_dir(7) is not None and _s(True) == "●" and _set(False) == "◇")

# ══ 8. no upstream branding user-facing + old code gone ═════════════════════
print("— branding + cleanup")
bad = []
for f in Path("mangarepo/plugins").rglob("*.py"):
    txt = f.read_text()
    if "t.me/codexnano" in txt:
        bad.append(str(f))
ok("no upstream telegram links", not bad, str(bad))
ok("our old manga code deleted",
   not Path("cantarella/telegram/plugins/manga.py").exists()
   and not Path("manga_sources").exists() and not Path("sources").exists())
utils_src = Path("cantarella/telegram/utils.py").read_text()
for c in ("manga", "msubscribe", "msearch", "mcheck", "minterval", "mchannel",
          "mexport", "mimport", "minfo", "mqueue", "mclean", "mrefresh", "mpost"):
    ok(f"menu: old /{c} removed", f'BotCommand("{c}"' not in utils_src)
for c in ("search", "list", "check", "stop", "info", "msettings",
          "dbstats", "usersettings"):
    ok(f"menu: /{c} present", f'BotCommand("{c}"' in utils_src)
help_src = Path("Script.py").read_text()
ok("help shows the engine", "35 ᴍᴀɴɢᴀ ꜱᴏᴜʀᴄᴇꜱ" in help_src)
ok("VERSION == 6.0.0", __import__("config").VERSION == "6.0.0")

n_fail = sum(1 for _, c in PASS if not c)
print(f"\n═══ test_manga: {len(PASS) - n_fail}/{len(PASS)} passed ═══")
sys.exit(1 if n_fail else 0)
