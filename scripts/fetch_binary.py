#!/usr/bin/env python3
"""
Fetch the correct N_m3u8DL-RE build for the current platform.

The repo bundles the Linux x86_64 build under binary/. For other platforms
(Windows, macOS, Linux ARM), run:

    python scripts/fetch_binary.py

Builds are pulled from the official N_m3u8DL-RE releases (nilaoda/N_m3u8DL-RE).
"""

import os
import platform
import sys
import urllib.request

RELEASE_BASE = (
    "https://github.com/nilaoda/N_m3u8DL-RE/releases/download/"
    "v20241203/N_m3u8DL-RE_v20241203_"
)

MAP = {
    ("windows", "amd64"): "win-x64.zip",
    ("linux", "x86_64"): "linux-x64_20241203.tar.gz",
    ("linux", "aarch64"): "linux-arm64.tar.gz",
    ("darwin", "x86_64"): "osx-x64.tar.gz",
    ("darwin", "arm64"): "osx-arm64.tar.gz",
}


def main() -> int:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows" and machine in ("amd64", "x86_64"):
        machine = "amd64"
    key = (system, machine)
    asset = MAP.get(key)
    if not asset:
        print(f"No prebuilt N_m3u8DL-RE for {system}/{machine}.")
        print("Grab one manually from https://github.com/nilaoda/N_m3u8DL-RE/releases")
        return 1

    url = RELEASE_BASE + asset
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "binary")
    os.makedirs(out_dir, exist_ok=True)
    archive = os.path.join(out_dir, asset)
    print(f"Downloading {url} …")
    urllib.request.urlretrieve(url, archive)
    print(f"Saved to {archive}")
    print("Extract it and keep the N_m3u8DL-RE executable inside the binary/ directory.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
