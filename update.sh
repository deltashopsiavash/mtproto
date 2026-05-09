#!/bin/bash
set -e

APP_DIR="/opt/delta-proxy-panel"
BACKUP_DIR="/opt/delta-backups"
TMP_DIR="/tmp/mtproto-update-src"
TMP_FILE="/tmp/mtproto-update.zip"
REPO_ZIP="https://github.com/deltashopsiavash/mtproto/archive/refs/heads/main.zip"

echo "=== Delta MTProto Panel Update ==="

apt update
apt install -y curl wget unzip git rsync python3 python3-pip python3-venv

mkdir -p "$BACKUP_DIR"
DATE=$(date +%F-%H%M%S)

if [ -d "$APP_DIR" ]; then
  echo "Creating backup: $BACKUP_DIR/backup-$DATE"
  cp -r "$APP_DIR" "$BACKUP_DIR/backup-$DATE" 2>/dev/null || true
fi

echo "Downloading latest source from GitHub main branch..."
rm -rf "$TMP_DIR" "$TMP_FILE"
mkdir -p "$TMP_DIR"

wget -O "$TMP_FILE" "$REPO_ZIP"
unzip -o "$TMP_FILE" -d "$TMP_DIR"

SRC_DIR="$TMP_DIR/mtproto-main"

if [ ! -d "$SRC_DIR" ]; then
  echo "ERROR: Source directory not found after unzip."
  exit 1
fi

mkdir -p "$APP_DIR"

echo "Updating files..."
rsync -av --delete \
  --exclude '.env' \
  --exclude 'database.db' \
  --exclude 'backups' \
  --exclude 'venv' \
  "$SRC_DIR/" "$APP_DIR/"

cd "$APP_DIR"

if [ ! -d "venv" ]; then
  echo "Creating Python venv..."
  python3 -m venv venv
fi

source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt || true

echo "v23-backup-update-fixed" > "$APP_DIR/VERSION"

systemctl daemon-reload
systemctl restart delta-panel 2>/dev/null || true
systemctl restart delta-sub 2>/dev/null || true

echo ""
echo "Update completed successfully."
echo "Installed version:"
cat "$APP_DIR/VERSION"
echo ""
echo "IMPORTANT: This updater installs whatever is currently pushed to GitHub main."
echo "If you changed files locally or downloaded a ZIP from ChatGPT, upload/push those files to GitHub first."
