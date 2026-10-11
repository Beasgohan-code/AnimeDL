#!/usr/bin/env bash
# ============================================================================
#  AnimeDL — launcher (Linux / VPS / PaaS)
# ============================================================================
set -e
cd "$(dirname "$0")"

# Ensure the N_m3u8DL-RE binary is present and executable
if [ ! -f binary/N_m3u8DL-RE ]; then
    echo "[AnimeDL] N_m3u8DL-RE missing — fetching…"
    python3 scripts/fetch_binary.py
fi
chmod +x binary/N_m3u8DL-RE 2>/dev/null || true

# Ensure system tools used by the leech engine exist (best effort on VPS)
for tool in ffmpeg aria2c 7z unzip; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "[AnimeDL] warning: '$tool' not found — some leech features may fail."
    fi
done

exec python3 main.py
