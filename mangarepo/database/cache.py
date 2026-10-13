# Made by @codexnano from scratch.
# If you find any bugs, please let us know in the channel updates.
# You can 'git pull' to stay updated with the latest changes.

from datetime import datetime, timedelta
class CacheMixin:
    def _sanitize(self, obj):
        if isinstance(obj, dict):
            return {
                k.replace('.', '_').replace('$', '_'): self._sanitize(v)
                for k, v in obj.items()
            }
        elif isinstance(obj, list):
            return [self._sanitize(i) for i in obj]
        return obj
    async def set_cache(self, k, d, ttl_minutes=30):
        clean = self._sanitize(d)
        await self.cache.update_one(
            {"_id": k},
            {"$set": {"d": clean, "ts": datetime.utcnow(), "ttl": ttl_minutes}},
            upsert=True
        )
    async def get_cache(self, k, refresh=False):
        doc = await self.cache.find_one({"_id": k})
        if not doc:
            return None
        if refresh:
            await self.cache.update_one({"_id": k}, {"$set": {"ts": datetime.utcnow()}})
        return doc.get('d')
    async def clear_all_cache(self, force=False):
        if force:
            return await self.cache.delete_many({})
        cutoff = datetime.utcnow() - timedelta(minutes=30)
        result = await self.cache.delete_many({
            "$or": [
                {"ts": {"$lt": cutoff}},
                {"ts": {"$exists": False}}
            ]
        })
        return result
