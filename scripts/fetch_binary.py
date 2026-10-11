#!/usr/bin/env python3
"""
Fetch the correct N_m3u8DL-RE build for the current platform and install it
into binary/.

The repo bundles the Linux x86_64 build under binary/ as a fallback. Running
this script (the Dockerfile does it on every build) upgrades that binary to
the newest tagged release from nilaoda/N_m3u8DL-RE. If the download or the
version check fails, the bundled binary stays untouched.

    python scripts/fetch_binary.py            # fetch + install + verify
"""

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from urllib.request import urlopen

RELEASE_TAG = "v0.6.0-beta"        # 2026-06-29 — flags verified against source
STAMP = "20260629"

ASSETS = {
    ("windows", "amd64"): f"N_m3u8DL-RE_{RELEASE_TAG}_win-x64_{STAMP}.zip",
    ("linux", "x86_64"): f"N_m3u8DL-RE_{RELEASE_TAG}_linux-x64_{STAMP}.tar.gz",
    ("linux", "aarch64"): f"N_m3u8DL-RE_{RELEASE_TAG}_linux-arm64_{STAMP}.tar.gz",
    ("darwin", "x86_64"): f"N_m3u8DL-RE_{RELEASE_TAG}_osx-x64_{STAMP}.tar.gz",
    ("darwin", "arm64"): f"N_m3u8DL-RE_{RELEASE_TAG}_osx-arm64_{STAMP}.tar.gz",
}


def _asset_for(system: str, machine: str):
    if system == "windows" and machine in ("amd64", "x86_64"):
        machine = "amd64"
    return ASSETS.get((system, machine))


def _extract(archive: str, dest: str):
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive, "r:*") as t:
            t.extractall(dest)


def _find_executable(dest: str):
    for root, _dirs, files in os.walk(dest):
        for f in files:
            if f in ("N_m3u8DL-RE", "N_m3u8DL-RE.exe"):
                return os.path.join(root, f)
    return None


def _verify(path: str) -> bool:
    try:
        out = subprocess.run([path, "--version"], capture_output=True,
                             text=True, timeout=15).stdout
        print(f"  version check: {out.strip()[:60]}")
        return out.strip() != ""
    except Exception as e:
        print(f"  version check FAILED: {e}")
        return False


def main() -> int:
    system = platform.system().lower()
    machine = platform.machine().lower()
    asset = _asset_for(system, machine)
    if not asset:
        print(f"No prebuilt N_m3u8DL-RE for {system}/{machine} — keeping bundled binary.")
        return 1

    url = (f"https://github.com/nilaoda/N_m3u8DL-RE/releases/"
           f"download/{RELEASE_TAG}/{asset}")
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(repo, "binary")
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, "N_m3u8DL-RE.exe" if system == "windows"
                          else "N_m3u8DL-RE")

    print(f"Downloading {url} …")
    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, asset)
        try:
            with urlopen(url, timeout=60) as resp, open(archive, "wb") as fh:
                shutil.copyfileobj(resp, fh)
        except Exception as e:
            print(f"Download failed ({e}) — keeping bundled binary.")
            return 1
        try:
            _extract(archive, tmp)
        except Exception as e:
            print(f"Extraction failed ({e}) — keeping bundled binary.")
            return 1
        exe = _find_executable(tmp)
        if not exe:
            print("No executable in the archive — keeping bundled binary.")
            return 1
        staging = target + ".new"
        shutil.copyfile(exe, staging)
        os.chmod(staging, 0o755)
        if not _verify(staging):
            os.unlink(staging)
            print("Keeping bundled binary.")
            return 1
        os.replace(staging, target)
    print(f"Installed {RELEASE_TAG} → {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
