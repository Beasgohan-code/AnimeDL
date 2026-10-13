# Made by @codexnano from scratch.
# If you find any bugs, please let us know in the channel updates.
# You can 'git pull' to stay updated with the latest changes.

import random
import string
class SubsMixin:
    async def _next_sid(self, uid):
        while True:
            prefix = "".join(random.choices(string.ascii_uppercase, k=4))
            digits = "".join(random.choices(string.digits, k=6))
            sid = f"{prefix}{digits}"
            exists = await self.subs.find_one({"sid": sid})
            if not exists:
                return sid
    async def add_sub(self, uid, d):
        d['uid'] = uid
        existing = await self.subs.find_one({"uid": uid, "title": d['title'], "cid": d['cid']})
        if existing:
            sid = existing['sid']
            if 'sources' not in existing:
                await self.subs.update_one(
                    {"sid": sid},
                    {"$set": {"sources": [{"mid": existing['mid'], "src": existing['src']}]}}
                )
            return sid
        sid = await self._next_sid(uid)
        d['sid'] = sid
        d['sources'] = [{"mid": d['mid'], "src": d['src']}]
        await self.subs.insert_one(d)
        return sid
    async def add_source_to_sub(self, uid, sid, mid, src, last=None, lurl=None):
        source_data = {"mid": mid, "src": src}
        if last:
            source_data["last"] = last
        if lurl:
            source_data["lurl"] = lurl
        await self.subs.update_one(
            {"uid": uid, "sid": sid},
            {"$addToSet": {"sources": source_data}}
        )
    async def get_subs(self, uid=None):
        if uid:
            return await self.subs.find({"uid": uid}).to_list(None)
        return await self.subs.find({}).to_list(None)
    async def get_user_channels(self, uid):
        return await self.subs.distinct("cid", {"uid": uid})
    async def get_sub(self, uid, sid):
        return await self.subs.find_one({"uid": uid, "sid": sid})
    async def del_sub(self, uid, sid):
        return await self.subs.delete_one({"uid": uid, "sid": sid})
    async def up_sub_promos(self, uid, sid, pids):
        await self.subs.update_one(
            {"uid": uid, "sid": sid},
            {"$set": {"last_promo_ids": pids}}
        )
    async def up_sub(self, uid, sid, chap_num, chap_title, url):
        await self.subs.update_one(
            {"uid": uid, "sid": sid},
            {"$set": {
                "last": chap_num,
                "last_title": chap_title,
                "lurl": url
            }}
        )
    async def up_source(self, uid, sid, src_name, chap_num, chap_title, url):
        await self.subs.update_one(
            {"uid": uid, "sid": sid, "sources.src": src_name},
            {"$set": {
                "sources.$.last": chap_num,
                "sources.$.last_title": chap_title,
                "sources.$.lurl": url
            }}
        )
    async def set_sub_thumb(self, uid, sid, b64_data):
        await self.subs.update_one(
            {"uid": uid, "sid": sid},
            {"$set": {"thumb_b64": b64_data}}
        )
    async def clear_sub_thumb(self, uid, sid):
        await self.subs.update_one(
            {"uid": uid, "sid": sid},
            {"$unset": {"thumb_b64": ""}}
        )
