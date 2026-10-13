# Made by @codexnano from scratch.
# If you find any bugs, please let us know in the channel updates.
# You can 'git pull' to stay updated with the latest changes.

from .base import BaseDB
from .users import UsersMixin
from .subs import SubsMixin
from .cache import CacheMixin
from .config import ConfigMixin
from .tasks import TasksMixin
from .admin import AdminMixin
class DB(BaseDB, UsersMixin, SubsMixin, CacheMixin, ConfigMixin, TasksMixin, AdminMixin):
    pass
db = DB()
