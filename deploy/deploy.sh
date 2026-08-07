#!/usr/bin/env bash
# Deploy Papers Radar to the server: rsync the repo, refresh the venv,
# restart services. Never touches /srv/papersradar/.env or the DB.
#
#   DEPLOY_HOST=ubuntu@papersradar.com ./deploy/deploy.sh
#
# Optional: DEPLOY_PATH (default /srv/papersradar), DEPLOY_SSH_OPTS.
set -euo pipefail

HOST="${DEPLOY_HOST:?set DEPLOY_HOST, e.g. DEPLOY_HOST=ubuntu@papersradar.com}"
DEST="${DEPLOY_PATH:-/srv/papersradar}"
SSH_OPTS="${DEPLOY_SSH_OPTS:-}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> rsync code -> $HOST:$DEST/app"
rsync -az --delete $SSH_OPTS \
    --exclude '.git' --exclude '.venv' --exclude 'data' --exclude 'logs' \
    --exclude '.env' --exclude '__pycache__' --exclude '.pytest_cache' \
    "$REPO/" "$HOST:$DEST/app/"

echo "==> refresh venv (idempotent)"
ssh $SSH_OPTS "$HOST" "set -e
    cd $DEST
    [ -d venv ] || python3 -m venv venv
    ./venv/bin/pip install -q -r app/project_admin/requirements.txt
"

echo "==> restart web service"
ssh $SSH_OPTS "$HOST" "sudo systemctl restart papersradar-web && sleep 2 \
    && systemctl --no-pager --lines=0 status papersradar-web | head -5 \
    && curl -fsS -o /dev/null -w 'local smoke: HTTP %{http_code}\n' http://127.0.0.1:8000/"

echo "==> done. Public smoke: curl -I https://papersradar.com/"
