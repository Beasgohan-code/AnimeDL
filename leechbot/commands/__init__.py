"""Command handlers package."""

# Import submodules to register Pyrogram handlers.
# NOTE: `start_help` is intentionally NOT imported as a handler module —
# in the merged AnimeDL bot, /start and /help are owned by the anime
# downloader's command plugins. The helpers inside start_help.py
# (_send_welcome, _handle_help_*) are still used by leech callbacks.
from . import admin
from . import autorename
from . import downloads
from . import nyaa
from . import tosho
from . import options
from . import rss
from . import screenshot
from . import settings
from . import status

# Re-export helpers used by other packages (imported WITHOUT registering
# its message handlers — those are disabled inside the module itself).
from .start_help import _send_welcome  # noqa
