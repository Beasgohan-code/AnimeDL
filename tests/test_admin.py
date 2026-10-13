#!/usr/bin/env python3
"""v5.0.0 ULTRA — admin suite tests: /ban /unban /banlist (Database helpers
against in-memory fake collections; no mongo needed) + handler registration
and premium-free invariants after the manga removal."""
import asyncio
import os
import sys
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

from datetime import date

# ══ 1. Database ban helpers on fake collections ═════════════════════════════
print("— Database ban helpers (fake collections)")
class FakeFind:
    def __init__(self, docs): self.docs = docs
    def __aiter__(self):
        async def _gen():
            for d in self.docs:
                yield d
        return _gen()

class FakeCol:
    def __init__(self):
        self.docs = {}
    async def find_one(self, q):
        return self.docs.get(q.get("_id"))
    async def update_one(self, q, upd, upsert=False):
        uid = q["_id"]
        if uid not in self.docs and upsert:
            self.docs[uid] = {"_id": uid}
        if uid in self.docs:
            self.docs[uid].update(upd["$set"])
        return None
    def find(self, q):
        key, val = next(iter(q.items()))
        parts = key.split(".")
        out = []
        for d in self.docs.values():
            cur = d
            for p in parts:
                cur = (cur or {}).get(p) if isinstance(cur, dict) else None
            if cur == val:
                out.append(d)
        return FakeFind(out)

from cantarella.core.database import Database
pdb = Database.__new__(Database)
pdb.ban_data = FakeCol()
pdb.user_data = FakeCol()

loop = asyncio.new_event_loop()
ok("ban_user saves", loop.run_until_complete(pdb.ban_user(111, "spam")))
ok("is_user_banned true", loop.run_until_complete(pdb.is_user_banned(111)) is True)
ok("banned_users lists", [u["_id"] for u in loop.run_until_complete(pdb.banned_users())] == [111])
ok("unban_user clears", loop.run_until_complete(pdb.unban_user(111)))
ok("is_user_banned false after unban", loop.run_until_complete(pdb.is_user_banned(111)) is False)

ndb = Database.__new__(Database)
ndb.ban_data = None
ndb.user_data = None
ok("ban helpers safe without mongo",
   loop.run_until_complete(ndb.ban_user(1)) is False
   and loop.run_until_complete(ndb.is_user_banned(1)) is False)
loop.close()

# ══ 2. new-user doc ══════════════════════════════════════════════════════════
print("— new-user defaults")
nu = Database._new_user(pdb, 999, "SomeUser")
ok("new user not banned", nu["ban_status"]["is_banned"] is False)
ok("new user doc has no premium field", "premium_status" not in nu)

# ══ 3. handler registration + manga-free invariants ════════════════════════
print("— handler registration")
import cantarella.telegram.plugins.admin_cmds as ac

def _cmd_names(obj, seen=None):
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
            for sub in v:
                out |= _cmd_names(sub, seen)
        elif v is not None and hasattr(v, "__dict__"):
            out |= _cmd_names(v, seen)
    return out

def _cmds(mod):
    out = set()
    for h in mod.__dict__.values():
        if hasattr(h, "handlers"):
            for h2, grp in h.handlers:
                f = getattr(h2, "filters", None)
                if f is not None:
                    out |= _cmd_names(f)
    return out

ac_cmds = _cmds(ac)
for c in ("ban", "unban", "banlist"):
    ok(f"/{c} registered", c in ac_cmds, str(sorted(ac_cmds)))
for c in ("addpremium", "delpremium", "premiumlist"):
    ok(f"/{c} gone", c not in ac_cmds)

plugins_dir = Path("cantarella/telegram/plugins")
present = {p.stem for p in plugins_dir.glob("*.py")}
ok("manga plugins deleted",
   not {"manga", "mangabot", "usettings"} & present, str(sorted(present)))
ok("manga_sources deleted", not Path("manga_sources").exists())
ok("menu has no manga commands",
   all(c not in Path("cantarella/telegram/utils.py").read_text()
       for c in ("manga", "mrandom", "msearch", "usettings")))
ok("help has no manga commands",
   all(c not in Path("Script.py").read_text()
       for c in ("/manga", "/msearch", "/usettings", "/premium")))
ok("requirements free of cloudscraper",
   "cloudscraper" not in Path("requirements.txt").read_text())
ok("VERSION == 5.0.0", __import__("config").VERSION == "5.0.0")
ok("ULTRA banner", "ULTRA" in Path("main.py").read_text())

# ══ 4. admin arg parsing ═════════════════════════════════════════════════════
print("— admin arg parsing")
class Msg:
    def __init__(self, command, reply_user=None):
        self.command = command
        if reply_user:
            self.reply_to_message = type(
                "R", (), {"from_user": type("U", (), {"id": reply_user})()})()
        else:
            self.reply_to_message = None
ok("id from args", ac._target_id(Msg(["/ban", "12345", "spamming", "hard"])) == (12345, "spamming hard"))
ok("id from args no reason", ac._target_id(Msg(["/unban", "777"])) == (777, ""))
ok("id from reply", ac._target_id(Msg(["/ban"], reply_user=555)) == (555, ""))
ok("no target", ac._target_id(Msg(["/ban"])) == (None, ""))

n_fail = sum(1 for _, c in PASS if not c)
print(f"\n═══ test_admin: {len(PASS) - n_fail}/{len(PASS)} passed ═══")
sys.exit(1 if n_fail else 0)
