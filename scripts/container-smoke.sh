#!/usr/bin/env bash
# Offline runtime check for a locally built or registry-pulled image.
# Usage: timeout 60s bash scripts/container-smoke.sh IMAGE_REFERENCE
set -euo pipefail

image="${1:-drop-alerts:ci}"
container="drop-alerts-smoke-$$"
volume="drop-alerts-smoke-data-$$"
smoke_dir="$(mktemp -d)"
deadline=$((SECONDS + 50))

cleanup() {
    result=$?
    if [ "$result" -ne 0 ]; then
        docker logs "$container" 2>/dev/null || true
    fi
    docker rm -f "$container" >/dev/null 2>&1 || true
    docker volume rm "$volume" >/dev/null 2>&1 || true
    rm -f -- "$smoke_dir/config.toml"
    rmdir -- "$smoke_dir" 2>/dev/null || true
    return "$result"
}
trap cleanup EXIT

cat > "$smoke_dir/config.toml" <<'CONFIG'
[sources.secret_lair_eu]
enabled = false
[sources.magic_news]
enabled = false
CONFIG
chmod 644 "$smoke_dir/config.toml"

test "$(docker image inspect --format '{{.Config.User}}' "$image")" = '10001:10001'
docker volume create "$volume" >/dev/null
docker run -d --name "$container" \
    --network none --read-only --init \
    --cap-drop ALL --security-opt no-new-privileges:true \
    --tmpfs /tmp:size=16m,mode=1777 \
    --mount "type=volume,source=$volume,target=/data" \
    --mount "type=bind,source=$smoke_dir/config.toml,target=/app/config.toml,readonly" \
    --env LLM_ENABLED=false --env DISCORD_WEBHOOK_URL= \
    --health-interval 1s --health-timeout 5s --health-start-period 0s \
    "$image" >/dev/null

wait_healthy() {
    while [ "$SECONDS" -lt "$deadline" ]; do
        state="$(docker inspect --format '{{.State.Status}}' "$container")"
        health="$(docker inspect --format '{{.State.Health.Status}}' "$container")"
        if [ "$state" != running ]; then
            echo 'Container stopped before becoming healthy' >&2
            return 1
        fi
        if [ "$health" = healthy ]; then
            return 0
        fi
        sleep 1
    done
    echo 'Container did not become healthy within the runtime budget' >&2
    return 1
}

wait_healthy
docker exec "$container" python -c '
import os, sqlite3
assert os.getuid() == 10001
db = sqlite3.connect("/data/drop-alerts.db")
assert db.execute("SELECT value FROM meta WHERE key=?", ("schema_version",)).fetchone() == ("2",)
db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", ("container_smoke", "retained"))
db.commit()
db.close()
'
docker stop --time 10 "$container" >/dev/null
test "$(docker inspect --format '{{.State.ExitCode}}' "$container")" = 0

# Read the stopped service's volume without starting sources or contacting a server.
docker run --rm --network none --read-only \
    --mount "type=volume,source=$volume,target=/data" \
    --entrypoint python "$image" -c '
from pathlib import Path
import sqlite3
assert not Path("/data/heartbeat.json").exists(), "Unclean shutdown left a heartbeat"
db = sqlite3.connect("file:/data/drop-alerts.db?mode=ro", uri=True)
assert db.execute("SELECT value FROM meta WHERE key=?", ("container_smoke",)).fetchone() == ("retained",)
db.close()
'

docker start "$container" >/dev/null
wait_healthy
docker exec "$container" python -c '
import sqlite3
db = sqlite3.connect("file:/data/drop-alerts.db?mode=ro", uri=True)
assert db.execute("SELECT value FROM meta WHERE key=?", ("container_smoke",)).fetchone() == ("retained",)
db.close()
'
docker stop --time 10 "$container" >/dev/null
test "$(docker inspect --format '{{.State.ExitCode}}' "$container")" = 0
echo 'Offline container smoke passed: non-root, read-only root, SQLite volume, health and graceful restart'
