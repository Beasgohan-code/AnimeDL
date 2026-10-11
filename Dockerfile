# ============================================================================
#  AnimeDL — Docker image (anime downloader + leech engine)
#  Base: python:3.11-slim (Debian trixie)
#  NOTE: Debian trixie dropped the non-free `unrar` package; we install the
#        free `unrar-free` + `unar` and ship a compatibility shim so the
#        bot's `unrar x …` calls keep working (docker/unrar-wrapper.sh).
# ============================================================================
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# System dependencies:
#   ffmpeg        — video/audio processing (anime core + leech converter)
#   aria2         — HTTP/FTP/torrent downloads (leech engine)
#   p7zip-full    — zip/7z/tar archive handling
#   unrar-free    — free RAR extraction (trixie has no non-free unrar)
#   unar          — second free RAR/archiver fallback
#   unzip         — zip extraction
#   curl, tini    — health checks + proper PID 1 signal handling
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        aria2 \
        p7zip-full \
        unrar-free \
        unar \
        unzip \
        curl \
        tini \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Bundle the N_m3u8DL-RE binary with exec permission, upgrade it to the
# newest tagged release when the build has network (bundled v0.5.1 stays as
# fallback), and install the unrar compatibility shim (bot code calls
# `unrar`, trixie only has `unrar-free`)
RUN chmod +x binary/N_m3u8DL-RE 2>/dev/null || true && \
    (python scripts/fetch_binary.py || echo "keeping bundled N_m3u8DL-RE") && \
    chmod +x binary/N_m3u8DL-RE 2>/dev/null || true && \
    chmod +x docker/unrar-wrapper.sh && \
    ln -sf /app/docker/unrar-wrapper.sh /usr/local/bin/unrar

EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:${PORT:-8080}/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "main.py"]
