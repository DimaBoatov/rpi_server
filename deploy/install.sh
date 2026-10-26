#!/usr/bin/env bash
# Run on Raspberry Pi OS: bash deploy/install.sh [--with-gpio]
# Run on Ubuntu: bash deploy/install.sh [--with-gpio]
set -euo pipefail

WITH_GPIO=0
case "${1:-}" in
  '') ;;
  --with-gpio) WITH_GPIO=1 ;;
  *) echo 'Usage: bash deploy/install.sh [--with-gpio]' >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
  echo 'Too many arguments' >&2
  exit 2
fi
if [ "$(uname -s)" != Linux ] || ! command -v apt-get >/dev/null || ! command -v systemctl >/dev/null; then
  echo 'Цей скрипт призначений для Raspberry Pi OS / Debian із systemd.' >&2
  exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
  exec sudo bash "$0" "$@"
fi

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR=/opt/antenna
for file in server.py config.json static/index.html deploy/antenna.service; do
  if [ ! -f "$SOURCE_DIR/$file" ]; then
    echo "Відсутній файл: $SOURCE_DIR/$file" >&2
    exit 1
  fi
done

echo 'Встановлення системних пакетів…'
apt-get update
apt-get install -y python3
if [ "$WITH_GPIO" -eq 1 ]; then
  apt-get install -y python3-gpiozero python3-lgpio
fi
/usr/bin/python3 -c 'import sys; assert sys.version_info >= (3, 9), "Потрібен Python 3.9+"'
/usr/bin/python3 - "$SOURCE_DIR" "$DEST_DIR" <<'PY'
import json
from pathlib import Path
import sys
source, dest = map(Path, sys.argv[1:])
compile((source / 'server.py').read_text(), 'server.py', 'exec')
config = dest / 'config.json' if (dest / 'config.json').exists() else source / 'config.json'
data = json.loads(config.read_text())
if not isinstance(data, dict):
    raise SystemExit('config.json має містити JSON-об’єкт')
if data.get('motor') == 'servo':
    import gpiozero  # fail before stopping service if dependencies are missing
PY

getent group gpio >/dev/null || groupadd --system gpio
getent group antenna >/dev/null || groupadd --system antenna
if ! id antenna >/dev/null 2>&1; then
  useradd --system --gid antenna --no-create-home --shell /usr/sbin/nologin antenna
fi
usermod -a -G gpio antenna

# Stop the old worker before replacing files; never start two motor controllers.
if systemctl is-active --quiet antenna.service; then
  systemctl stop antenna.service
fi
install -d -m 0755 "$DEST_DIR" "$DEST_DIR/static"
install -m 0644 "$SOURCE_DIR/server.py" "$DEST_DIR/server.py"
install -m 0644 "$SOURCE_DIR/static/index.html" "$DEST_DIR/static/index.html"
if [ ! -f "$DEST_DIR/config.json" ]; then
  install -m 0644 "$SOURCE_DIR/config.json" "$DEST_DIR/config.json"
else
  echo 'Наявний /opt/antenna/config.json збережено.'
fi
install -m 0644 "$SOURCE_DIR/deploy/antenna.service" /etc/systemd/system/antenna.service
systemctl daemon-reload
systemctl enable antenna.service
systemctl restart antenna.service

echo 'Перевірка HTTP API…'
if ! /usr/bin/python3 - "$DEST_DIR/config.json" <<'PY'
import json
import sys
import time
from urllib.request import urlopen
config = json.load(open(sys.argv[1]))
host = config['host']
if host == '0.0.0.0':
    host = '127.0.0.1'
elif host == '::':
    host = '::1'
if ':' in host:
    host = f'[{host}]'
url = f"http://{host}:{config['port']}/api/state"
for _ in range(15):
    try:
        with urlopen(url, timeout=1) as response:
            state = json.load(response)
        if state['mode'] != config['motor']:
            raise ValueError('Unexpected server mode')
        print(f"API працює. Режим: {state['mode']}")
        break
    except (OSError, ValueError, KeyError):
        time.sleep(1)
else:
    raise SystemExit('API не відповідає')
PY
then
  journalctl -u antenna.service -n 30 --no-pager
  exit 1
fi
if ! systemctl is-active --quiet antenna.service; then
  journalctl -u antenna.service -n 30 --no-pager
  exit 1
fi
echo "Готово. Відкрийте http://$(hostname -s).local:$(/usr/bin/python3 -c 'import json; print(json.load(open("/opt/antenna/config.json"))["port"])')"
echo "IP-адреси Pi: $(hostname -I)"
echo 'Логи: sudo journalctl -u antenna -f'
echo 'Налаштування: sudo nano /opt/antenna/config.json'
