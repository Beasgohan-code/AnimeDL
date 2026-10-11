# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
Auto-update module.

Checks GitHub for new versions and updates the bot automatically.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_URL = "https://github.com/Beasgohan-code/AnimeDL.git"
REPO_DIR = str(Path(__file__).parent.parent)


def _run(cmd: str) -> tuple:
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60, cwd=REPO_DIR)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"
    except Exception as e:
        return -1, "", str(e)


def get_local_version() -> str:
    """Get the current local version from config.py."""
    try:
        import config
        return getattr(config, "VERSION", "unknown")
    except Exception:
        return "unknown"


def get_local_commit() -> str:
    """Get the current local git commit hash."""
    code, stdout, _ = _run("git rev-parse --short HEAD")
    return stdout if code == 0 else "unknown"


def get_remote_commit() -> str:
    """Fetch and get the latest remote commit hash."""
    _run("git fetch origin main --quiet")
    code, stdout, _ = _run("git rev-parse --short origin/main")
    return stdout if code == 0 else "unknown"


def check_for_updates() -> dict:
    """
    Check if updates are available.

    Returns:
        dict with keys: available (bool), local (str), remote (str), behind (int)
    """
    local = get_local_commit()
    remote = get_remote_commit()

    if local == "unknown" or remote == "unknown":
        return {"available": False, "local": local, "remote": remote, "behind": 0, "error": "Could not check"}

    if local == remote:
        return {"available": False, "local": local, "remote": remote, "behind": 0}

    # Count commits behind
    code, stdout, _ = _run(f"git rev-list --count {local}..{remote}")
    behind = int(stdout) if code == 0 and stdout.isdigit() else 0

    return {
        "available": behind > 0,
        "local": local,
        "remote": remote,
        "behind": behind,
    }


def get_changelog_since(local_commit: str) -> str:
    """Get commit messages since local commit."""
    code, stdout, _ = _run(f"git log --oneline {local_commit}..origin/main")
    if code == 0 and stdout:
        return stdout
    return ""


def perform_update() -> dict:
    """
    Pull latest changes and reinstall dependencies.

    Returns:
        dict with keys: success (bool), message (str), new_commit (str)
    """
    logger.info("Starting auto-update...")

    # Pull latest
    code, stdout, stderr = _run("git pull origin main")
    if code != 0:
        return {"success": False, "message": f"Git pull failed: {stderr[:200]}", "new_commit": ""}

    if "Already up to date" in stdout:
        return {"success": True, "message": "Already up to date", "new_commit": get_local_commit()}

    # Reinstall dependencies
    logger.info("Reinstalling dependencies...")
    _run("pip3 install -q --no-cache-dir -r requirements.txt")

    new_commit = get_local_commit()
    logger.info(f"Updated to {new_commit}")

    return {
        "success": True,
        "message": f"Updated successfully\n```\n{stdout}\n```",
        "new_commit": new_commit,
    }
