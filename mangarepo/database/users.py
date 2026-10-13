# Made by @codexnano from scratch.
# If you find any bugs, please let us know in the channel updates.
# You can 'git pull' to stay updated with the latest changes.

class UsersMixin:
    async def add_usr(self, id):
        if not await self.users.find_one({'id': int(id)}):
            await self.users.insert_one({'id': id})
            return True
        return False
    async def get_usr(self, id):
        return await self.users.find_one({'id': int(id)})
    async def get_all_users(self):
        return await self.users.find({}).to_list(None)
    async def tot_usrs(self):
        return await self.users.count_documents({})
    async def ban_usr(self, uid, reason="No reason"):
        await self.users.update_one(
            {"id": int(uid)},
            {"$set": {"banned": True, "ban_reason": reason}},
            upsert=True
        )
    async def unban_usr(self, uid):
        await self.users.update_one(
            {"id": int(uid)},
            {"$set": {"banned": False, "ban_reason": None}}
        )
    async def is_banned(self, uid):
        doc = await self.users.find_one({"id": int(uid)})
        if doc and doc.get("banned"):
            return True, doc.get("ban_reason", "No reason")
        return False, None
    async def get_banned_users(self):
        return await self.users.find({"banned": True}).to_list(None)
