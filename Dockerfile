FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md ./
COPY drop_alerts ./drop_alerts
RUN python -m pip wheel --only-binary=:all: --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_PATH=/data/drop-alerts.db \
    HEARTBEAT_PATH=/data/heartbeat.json \
    CONFIG_PATH=/app/config.toml
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 dropalerts \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin dropalerts \
    && mkdir -p /data \
    && chown 10001:10001 /data
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels drop-alerts \
    && rm -rf /wheels
COPY config.example.toml /app/config.toml
USER 10001:10001
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-m", "drop_alerts", "health"]
ENTRYPOINT ["python", "-m", "drop_alerts"]
CMD ["run"]
