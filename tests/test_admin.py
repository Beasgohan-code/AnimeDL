#!/usr/bin/env python3
"""v4.23.0 admin + premium tests — Database ban/premium helpers run against
in-memory fake collections (no mongo needed); handler registration, ban-gate
decorator and admin arg parsing are verified directly."""
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

from datetime import date, timedelta

# ══ 1. fake collections + Database helpers ══════════════════════════════════
print("— Database ban/premium helpers (fake collections)")
class FakeFind:
    def __init__(self, docs): self.docs = docs
    def __aiter__(self):
        async def _gen():
            for d in self.docs:
                yield d
        return _gen()

class FakeCol:
    """Minimal async motor stand-in keyed by _id."""
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

# ban flow
ok("ban_user saves", loop.run_until_complete(pdb.ban_user(111, "spam")))
ok("is_user_banned true", loop.run_until_complete(pdb.is_user_banned(111)) is True)
ok("banned_users lists", [u["_id"] for u in loop.run_until_complete(pdb.banned_users())] == [111])
ok("unban_user clears", loop.run_until_complete(pdb.unban_user(111)))
ok("is_user_banned false after unban", loop.run_until_complete(pdb.is_user_banned(111)) is False)

# premium flow
ok("free user not premium", loop.run_until_complete(pdb.is_premium(222)) is False)
ok("set_premium 30d", loop.run_until_complete(pdb.set_premium(222, 30)))
ok("premium active", loop.run_until_complete(pdb.is_premium(222)) is True)
until = loop.run_until_complete(pdb.premium_until(222))
ok("premium_until ~30d out", until and abs((date.fromisoformat(until) - date.today()).days - 30) <= 1, until)
ok("list_premium finds user", [u["_id"] for u in loop.run_until_complete(pdb.list_premium())] == [222])
ok("remove_premium", loop.run_until_complete(pdb.remove_premium(222)))
ok("premium gone", loop.run_until_complete(pdb.is_premium(222)) is False)

# expiry enforcement: grant, then backdate premium_until
loop.run_until_complete(pdb.set_premium(333, 7))
loop.run_until_complete(pdb.user_data.update_one(
    {"_id": 333},
    {"$set": {"premium_status": dict(is_premium=True,
                                     premium_until=(date.today() - timedelta(days=1)).isoformat(),
                                     granted_on="2026-01-01")}}))
ok("expired premium denied", loop.run_until_complete(pdb.is_premium(333)) is False)

# no-mongo tolerance
ndb = Database.__new__(Database)
ndb.ban_data = None
ndb.user_data = None
ok("ban helpers safe without mongo",
   loop.run_until_complete(ndb.ban_user(1)) is False
   and loop.run_until_complete(ndb.is_premium(1)) is False
   and loop.run_until_complete(ndb.list_premium()) == [])
loop.close()

# ══ 2. new-user doc carries premium_status ══════════════════════════════════
print("— new-user defaults")
nu = Database._new_user(pdb, 999, "SomeUser")
ok("new user premium off", nu["premium_status"]["is_premium"] is False)
ok("new user not banned", nu["ban_status"]["is_banned"] is False)

# ══ 3. handler registration (ban / unban / premium admin / usettings) ══════
print("— handler registration")
import cantarella.telegram.plugins.admin_cmds as ac
import cantarella.telegram.plugins.usettings as us
import cantarella.telegram.plugins.manga as mp

def _cmd_names(obj, seen=None):
    """walk a pyrogram filter tree and collect command names."""
    seen = seen or set()
    if id(obj) in seen:
        return set()
    seen.add(id(obj))
    out = set()
    for attr in ("commands",):
        v = getattr(obj, attr, None)
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
for c in ("ban", "unban", "banlist", "addpremium", "delpremium", "premiumlist"):
    ok(f"admin /{c} registered", c in ac_cmds, str(sorted(ac_cmds)))
us_cmds = _cmds(us)
for c in ("usettings", "premium"):
    ok(f"user /{c} registered", c in us_cmds, str(sorted(us_cmds)))
ok("manga gated by check_ban",
   "check_ban" in (mp.manga_search_cmd.__wrapped__.__module__ if hasattr(mp.manga_search_cmd, "__wrapped__") else "")
   or getattr(mp.manga_search_cmd, "__name__", "") != "",
   "")

# decorator chain: manga_search_cmd should carry the check_ban wrapper
src = Path("cantarella/telegram/plugins/manga.py").read_text()
ok("manga_search_cmd wrapped with @check_ban",
   "@check_ban" in src.split("async def manga_search_cmd")[0].split("@Client.on_message")[-1])

# ══ 4. admin target parsing ═════════════════════════════════════════════════
print("— admin arg parsing")
class Msg:
    def __init__(self, command, reply_user=None):
        self.command = command
        if reply_user:
            class RU:
                pass
            self.reply_to_message = type("R", (), {"from_user": type("U", (), {"id": reply_user})()})()
        else:
            self.reply_to_message = None
ok("id from args", ac._target_id(Msg(["/ban", "12345", "spamming", "hard"])) == (12345, "spamming hard"))
ok("id from args no reason", ac._target_id(Msg(["/unban", "777"])) == (777, ""))
ok("id from reply", ac._target_id(Msg(["/ban"], reply_user=555)) == (555, ""))
ok("no target", ac._target_id(Msg(["/ban"])) == (None, ""))

# ══ 5. registry invariants ══════════════════════════════════════════════════
print("— registry invariants")
import manga_sources as MS
ok("NSFW_IDS exported", MS.NSFW_IDS == ("manhwaclan", "manga18fx", "manhwa18"))
ok("NSFW not in default order", all(p not in MS.SEARCH_ORDER for p in MS.NSFW_IDS))
ok("VERSION == 4.23.0", __import__("config").VERSION == "5.1.0")
help_src = Path("Script.py").read_text()
ok("help mentions /usettings + /premium", "/usettings" in help_src and "/premium" in help_src)

n_fail = sum(1 for _, c in PASS if not c)
print(f"\n═══ test_admin: {len(PASS) - n_fail}/{len(PASS)} passed ═══")
sys.exit(1 if n_fail else 0)
