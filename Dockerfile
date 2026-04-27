FROM python:3.12-slim

# Don't write .pyc files, flush stdout/stderr immediately
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System packages: tzdata for proper timezone handling, ca-certificates for HTTPS
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for cache friendliness
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Then app code
COPY app /app/app
COPY config /app/config

# Run as a non-root user; ensure /data exists and is writable
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 ichi \
    && mkdir -p /data \
    && chown -R ichi:ichi /app /data
USER ichi

VOLUME ["/data"]

CMD ["python", "-m", "app.main"]
