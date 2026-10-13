# Made by @codexnano from scratch.
# If you find any bugs, please let us know in the channel updates.
# You can 'git pull' to stay updated with the latest changes.

class ConfigMixin:
    async def get_cfg(self, uid, k, d=None):
        doc = await self.conf.find_one({"uid": uid, "key": k})
        return doc.get("val", d) if doc else d
    async def set_cfg(self, uid, k, v):
        await self.conf.update_one(
            {"uid": uid, "key": k},
            {"$set": {"val": v}},
            upsert=True
        )
    async def get_global_cfg(self, k, d=None):
        doc = await self.conf.find_one({"uid": "global", "key": k})
        return doc.get("val", d) if doc else d
    async def set_global_cfg(self, k, v):
        await self.conf.update_one(
            {"uid": "global", "key": k},
            {"$set": {"val": v}},
            upsert=True
        )
    async def get_all_user_cfg(self, uid):
        cursor = self.conf.find({"uid": uid})
        return {doc['key']: doc['val'] for doc in await cursor.to_list(None)}
    async def get_all_global_cfg(self):
        cursor = self.conf.find({"uid": "global"})
        return {doc['key']: doc['val'] for doc in await cursor.to_list(None)}
    async def reset_user_cfg(self, uid):
        result = await self.conf.delete_many({"uid": uid})
        return result.deleted_count
    async def clear_all_conf(self):
        return await self.conf.delete_many({})
