#!/usr/bin/env bash
# Run once on Raspberry Pi OS: bash deploy/enable-autoupdate.sh
set -euo pipefail
if [ "$(uname -s)" != Linux ] || ! command -v systemctl >/dev/null; then
  echo 'Потрібна Raspberry Pi OS / Debian із systemd.' >&2
  exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
  exec sudo bash "$0" "$@"
fi
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPOSITORY=https://github.com/DimaBoatov/rpi_server.git
apt-get update
apt-get install -y git python3 util-linux
systemctl stop antenna-update.timer 2>/dev/null || true
systemctl stop antenna-update.service 2>/dev/null || true
if [ ! -d /opt/antenna-source ]; then
  git clone --branch master --single-branch "$REPOSITORY" /opt/antenna-source
fi
if [ "$(git -C /opt/antenna-source remote get-url origin)" != "$REPOSITORY" ]; then
  echo '/opt/antenna-source має інший origin; встановлення зупинено.' >&2
  exit 1
fi
install -m 0755 "$SOURCE_DIR/deploy/update.sh" /usr/local/sbin/antenna-update
install -m 0644 "$SOURCE_DIR/deploy/antenna-update.service" /etc/systemd/system/antenna-update.service
install -m 0644 "$SOURCE_DIR/deploy/antenna-update.timer" /etc/systemd/system/antenna-update.timer
systemctl daemon-reload
systemctl enable --now antenna-update.timer
systemctl start antenna-update.service
echo 'Автооновлення увімкнено: перевірка master приблизно щохвилини.'
echo 'Логи: sudo journalctl -u antenna-update.service -n 50 --no-pager'
