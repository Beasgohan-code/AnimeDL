# AnimeDL — shared bot client
# Single Pyrogram client shared by the anime downloader (cantarella/) and the
# leech engine (leechbot/). Both register their handlers on this one instance,
# so the whole bot runs as a single Telegram session / single process.
#
# License: GPL-3.0 (anime core), MIT (leech core) — see LICENSE and LICENSES/.

import pyrogram.utils as pyro_utils

# Support modern 64-bit channel IDs (patch from the leech module)
pyro_utils.MIN_CHANNEL_ID = -100999999999999

import logging

from pyrogram import Client
from pyrogram.enums import ParseMode

import config

logger = logging.getLogger(__name__)

app = Client(
    name="animedl_session",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    workdir=str(config.SESSIONS_PATH),
    workers=100,
    parse_mode=ParseMode.HTML,
    max_concurrent_transmissions=10,
    # Anime command/callback plugins are auto-loaded from this package;
    # the leech module registers its handlers explicitly at import time.
    plugins=dict(root="cantarella.telegram.plugins"),
)

logger.info("Shared AnimeDL client created")


def anime_admin_pending(user_id) -> bool:
    """True while the anime core is waiting for a text input from this admin
    (ban/unban/add-channel prompts). Used by the leech URL filter so admin
    link inputs are not hijacked by the leech downloader."""
    try:
        from cantarella.telegram.plugins.callbacks.admin import admin_states
        return user_id in admin_states
    except Exception:
        return False
