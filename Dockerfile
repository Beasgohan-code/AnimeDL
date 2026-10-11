# ============================================================================
#  AnimeDL — Docker image (anime downloader + leech engine)
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
#   p7zip/unrar   — archive handling
#   curl, tini    — health checks + proper PID 1 signal handling
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        aria2 \
        p7zip-full \
        unrar \
        unzip \
        curl \
        tini \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Bundle the Linux N_m3u8DL-RE binary with exec permission
RUN chmod +x binary/N_m3u8DL-RE || true

EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:8080/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "main.py"]
