# Made by @codexnano from scratch.
# If you find any bugs, please let us know in the channel updates.
# You can 'git pull' to stay updated with the latest changes.

class AdminMixin:
    async def clear_all_users(self):
        return await self.users.delete_many({})
    async def clear_all_subs(self):
        return await self.subs.delete_many({})
    async def clear_user_data(self, uid):
        await self.users.delete_one({"id": int(uid)})
        await self.subs.delete_many({"uid": uid})
        await self.conf.delete_many({"uid": uid})
    async def db_stats(self):
        return {
            "users": await self.users.count_documents({}),
            "subs": await self.subs.count_documents({}),
            "cache": await self.cache.count_documents({}),
            "conf": await self.conf.count_documents({}),
            "banned": await self.users.count_documents({"banned": True})
        }
