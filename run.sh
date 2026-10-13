#!/usr/bin/env bash
# ============================================================================
#  AnimeDL — launcher (Linux / VPS / PaaS)
#  Includes a process-level watchdog: restarts the bot on crashes with
#  exponential-ish backoff, resetting after a stable run.
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

# ── Watchdog loop ──────────────────────────────────────────────────────────
# Env knobs: MAX_RESTARTS (0 = unlimited, default 10), RESTART_BACKOFF_S (5)
MAX_RESTARTS="${MAX_RESTARTS:-10}"
BACKOFF="${RESTART_BACKOFF_S:-5}"
RESTART_COUNT=0
LAST_START=$(date +%s)

while true; do
    LAST_START=$(date +%s)
    set +e
    python3 main.py
    EXIT_CODE=$?
    set -e

    # Exit code 0 = clean/intentional shutdown — do not restart
    if [ "$EXIT_CODE" -eq 0 ]; then
        echo "[watchdog] clean exit — staying down."
        exit 0
    fi

    # Reset the crash counter after 10 stable minutes
    NOW=$(date +%s)
    if [ $((NOW - LAST_START)) -ge 600 ]; then
        RESTART_COUNT=0
    fi

    RESTART_COUNT=$((RESTART_COUNT + 1))
    echo "[watchdog] bot exited with code $EXIT_CODE (crash #$RESTART_COUNT)"

    if [ "$MAX_RESTARTS" -gt 0 ] && [ "$RESTART_COUNT" -gt "$MAX_RESTARTS" ]; then
        echo "[watchdog] giving up after $MAX_RESTARTS consecutive restarts."
        exit 1
    fi

    # Backoff grows with consecutive crashes (5s, 10s, 15s… capped at 120s)
    WAIT=$((BACKOFF * RESTART_COUNT))
    [ "$WAIT" -gt 120 ] && WAIT=120
    echo "[watchdog] restarting in ${WAIT}s…"
    sleep "$WAIT"
done
