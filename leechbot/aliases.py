# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
Command alias system for the bot owner.

This module registers a lightweight pre-processor that rewrites aliased
command messages into their target commands before the real command handlers
run. A set of useful shortcuts is built-in, and the owner can add custom
aliases via /alias. Aliases are persisted to a JSON file so they survive
restarts.

Examples:
    /dl https://...       -> behaves like /tupload
    /yt https://...       -> behaves like /ytupload
    /alias dl tupload     -> create or override an alias
"""

import json
import logging
from pathlib import Path

from pyrogram import filters

from leechbot import app, OWNER
import config

logger = logging.getLogger(__name__)

ALIASES_FILE: Path = config.BASE_DIR / "aliases.json"

# Built-in shortcuts for common commands. Users can override or extend these
# via /alias; custom aliases are stored in aliases.json.
DEFAULT_ALIASES: dict = {
    "dl": "tupload",
    "tg": "tupload",
    "gd": "gdupload",
    "yt": "ytupload",
    "gal": "glupload",
    "dir": "drupload",
    "h": "help",
    "s": "settings",
    "q": "queue",
    "st": "stats",
    "cn": "cancel",
    "ca": "cancel_all",
    "fmt": "format",
    "spd": "speed",
    "sn": "setname",
    "zp": "zipaswd",
    "uzp": "unzipaswd",
}


def _load_aliases() -> dict:
    """Load alias map from disk and merge with built-in defaults."""
    aliases = dict(DEFAULT_ALIASES)
    if not ALIASES_FILE.exists():
        return aliases
    try:
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k, v in data.items():
                aliases[str(k).lower()] = str(v).lower().lstrip("/")
    except Exception as e:
        logger.warning("Failed to load aliases: %s", e)
    return aliases


def _save_aliases(aliases: dict):
    """Persist alias map to disk (only user-defined aliases are saved)."""
    try:
        user_aliases = {k: v for k, v in aliases.items() if k not in DEFAULT_ALIASES or DEFAULT_ALIASES[k] != v}
        ALIASES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ALIASES_FILE, "w", encoding="utf-8") as f:
            json.dump(user_aliases, f, indent=2)
    except Exception as e:
        logger.error("Failed to save aliases: %s", e)


# In-memory alias map (loaded at import time)
_ALIASES: dict = _load_aliases()


def get_aliases() -> dict:
    """Return the current alias map."""
    return _ALIASES.copy()


def set_alias(name: str, target: str) -> bool:
    """Add or update an alias. Returns True on success."""
    name = name.lower().lstrip("/")
    target = target.lower().lstrip("/")
    if not name or not target:
        return False
    if name == target:
        return False  # avoid trivial loops
    _ALIASES[name] = target
    _save_aliases(_ALIASES)
    return True


def remove_alias(name: str) -> bool:
    """Remove an alias. Returns True if it existed."""
    name = name.lower().lstrip("/")
    if name in _ALIASES:
        del _ALIASES[name]
        _save_aliases(_ALIASES)
        return True
    return False


@app.on_message(filters.private & filters.text)
async def alias_preprocessor(client, message):
    """
    Rewrite aliased commands into their target commands.

    This handler is intentionally registered before the real command handlers
    so that `message.continue_propagation()` passes the rewritten message to
    the proper `@app.on_message(filters.command(...))` handler.
    """
    text = message.text or ""
    parts = text.strip().split()
    if not parts or not parts[0].startswith("/"):
        return await message.continue_propagation()

    alias_name = parts[0][1:].lower()
    target = _ALIASES.get(alias_name)
    if not target:
        return await message.continue_propagation()

    # Preserve arguments
    args = " ".join(parts[1:])
    message.text = f"/{target}" + (f" {args}" if args else "")
    logger.debug("Alias rewrite: /%s -> %s", alias_name, message.text)
    return await message.continue_propagation()
