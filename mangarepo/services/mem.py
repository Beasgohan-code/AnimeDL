# Made by @codexnano from scratch.
# If you find any bugs, please let us know in the channel updates.
# You can 'git pull' to stay updated with the latest changes.

from datetime import datetime, timedelta
class MemCache:
    def __init__(self):
        self._data = {}
    def set(self, k, v, minutes=30):
        exp = datetime.now() + timedelta(minutes=minutes)
        self._data[k] = {'v': v, 'exp': exp}
    def get(self, k):
        item = self._data.get(k)
        if not item: return None
        if datetime.now() > item['exp']:
            del self._data[k]
            return None
        return item['v']
    def clear(self):
        self._data.clear()
mem = MemCache()
