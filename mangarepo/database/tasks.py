# Made by @codexnano from scratch.
# If you find any bugs, please let us know in the channel updates.
# You can 'git pull' to stay updated with the latest changes.

from datetime import datetime
class TasksMixin:
    async def add_task(self, name, data, run_at):
        await self.db.tasks.insert_one({
            "name": name,
            "data": data,
            "run_at": run_at
        })
    async def get_tasks(self, name=None):
        q = {"run_at": {"$lte": datetime.utcnow()}}
        if name:
            q["name"] = name
        return await self.db.tasks.find(q).to_list(None)
    async def del_task(self, tid):
        from bson import ObjectId
        await self.db.tasks.delete_one({"_id": ObjectId(tid) if isinstance(tid, str) else tid})
