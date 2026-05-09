#!/bin/bash
set -e

APP_DIR="/opt/delta-proxy-panel"
BACKUP_DIR="/opt/delta-backups"
TMP_DIR="/tmp/delta-mtproto-update"
REPO_ZIP="https://github.com/deltashopsiavash/mtproto/archive/refs/heads/main.zip"

echo "=== Delta MTProto Update ==="
apt update
apt install -y curl wget unzip git rsync python3 python3-pip python3-venv

mkdir -p "$BACKUP_DIR"
if [ -d "$APP_DIR" ]; then
  cp -r "$APP_DIR" "$BACKUP_DIR/backup-$(date +%F-%H%M%S)" || true
fi

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
wget -O "$TMP_DIR/src.zip" "$REPO_ZIP"
unzip -o "$TMP_DIR/src.zip" -d "$TMP_DIR"
SRC_DIR="$TMP_DIR/mtproto-main"

rsync -av --delete \
  --exclude ".env" \
  --exclude "data" \
  --exclude "backups" \
  --exclude "venv" \
  "$SRC_DIR/" "$APP_DIR/"

cd "$APP_DIR"
if [ ! -d venv ]; then python3 -m venv venv; fi
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt || true

cp "$APP_DIR"/systemd/*.service /etc/systemd/system/ 2>/dev/null || true
systemctl daemon-reload
systemctl restart delta-panel delta-sub 2>/dev/null || true
echo "clean-v1" > "$APP_DIR/VERSION"
echo "Update completed. Version:"
cat "$APP_DIR/VERSION"
