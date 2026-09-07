#!/usr/bin/env bash
set -euo pipefail
container=$(docker run --detach --network none \
    -e FLASK_SKIP_SCHEDULER=true -e WIZARR_DISABLE_SCHEDULER=true \
    -e GUNICORN_WORKERS=1 "${1:?Pass the locally built image tag}")
cleanup() {
    status=$?
    if [[ $status -ne 0 ]]; then docker logs "$container"; fi
    docker rm --force "$container" >/dev/null
    exit "$status"
}
trap cleanup EXIT
for _attempt in {1..60}; do
    if docker exec "$container" curl --fail --silent http://127.0.0.1:5690/health >/dev/null; then
        break
    fi
    [[ $(docker inspect --format '{{.State.Running}}' "$container") == true ]]
    sleep 1
done
docker exec -i "$container" /app/.venv/bin/python - <<'CHECK'
import json
import sqlite3
import urllib.request

with sqlite3.connect("/data/database/database.db") as database:
    tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"invitation", "media_server", "wizard_step", "admin_account"} <= tables
    assert database.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
origin = "http://127.0.0.1:5690"
with urllib.request.urlopen(origin + "/health", timeout=5) as response:
    assert response.status == 200
    assert json.load(response)["status"] == "ok"
for path in ["/", "/static/css/main.css", "/static/js/tiny-mde.min.js", "/static/node_modules/htmx.org/dist/htmx.min.js"]:
    with urllib.request.urlopen(origin + path, timeout=5) as response:
        assert response.status == 200
        assert response.read(), path
print("Migrated production health, onboarding HTML and generated browser assets passed.")
CHECK
