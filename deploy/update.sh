#!/usr/bin/env bash
set -euo pipefail
# This checkout belongs exclusively to the updater, never edit it manually.
exec 9>/run/antenna-update.lock
flock -n 9 || exit 0
export GIT_TERMINAL_PROMPT=0
cd /opt/antenna-source
git fetch --no-tags origin master
target=$(git rev-parse FETCH_HEAD)
deployed=$(cat /opt/antenna-deployed-commit 2>/dev/null || true)
if [ "$target" = "$deployed" ]; then
  exit 0
fi
# Do not interrupt an active movement. Retry on the next timer tick.
if systemctl is-active --quiet antenna.service; then
  if ! python3 - <<'PY'
import json
from urllib.request import ProxyHandler, build_opener
config = json.load(open('/opt/antenna/config.json'))
host = config['host']
host = {'0.0.0.0': '127.0.0.1', '::': '::1'}.get(host, host)
if ':' in host:
    host = f'[{host}]'
with build_opener(ProxyHandler({})).open(
        f"http://{host}:{config['port']}/api/state", timeout=3) as response:
    state = json.load(response)
if state['moving']:
    raise SystemExit('Антена рухається; оновлення відкладено.')
PY
  then
    echo 'Оновлення відкладено до наступної перевірки.'
    exit 0
  fi
fi
git reset --hard "$target"
python3 -m unittest discover -s tests -v
bash deploy/install.sh
# Record only successful deployments; failed installs are retried.
printf '%s\n' "$target" > /opt/antenna-deployed-commit
echo "Встановлено коміт $target"
