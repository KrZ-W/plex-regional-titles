# syntax=docker/dockerfile:1.7
FROM python:3.14-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CONFIG_DIR=/config \
    PUID=1000 \
    PGID=1000 \
    UMASK=022 \
    TZ=UTC

# tzdata for TZ, setpriv (util-linux) to drop privileges, ca-certificates for HTTPS datasets
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata ca-certificates util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1000 app && useradd -u 1000 -g app -d /app -M -s /usr/sbin/nologin app

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . && rm -rf /root/.cache

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && mkdir -p /config && chown app:app /config

VOLUME ["/config"]

HEALTHCHECK --interval=15m --timeout=30s --start-period=2h --retries=3 \
    CMD ["setpriv", "--reuid=app", "--regid=app", "--clear-groups", "plex-regional-titles", "healthcheck"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["cron"]
