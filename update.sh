#!/bin/bash
set -e

APP_DIR="/opt/delta-proxy-panel"
BACKUP_DIR="/opt/delta-backups"
TMP_FILE="/tmp/mtproto-update.zip"

mkdir -p $BACKUP_DIR

DATE=$(date +%F-%H%M)

echo "Creating Backup..."
cp -r $APP_DIR "$BACKUP_DIR/backup-$DATE"

wget -O $TMP_FILE https://github.com/deltashopsiavash/mtproto/archive/refs/heads/main.zip

rm -rf /tmp/mtproto-main
unzip -o $TMP_FILE -d /tmp/

echo "Updating Source..."

rsync -av --delete --exclude '.env' --exclude 'database.db' --exclude 'backups' /tmp/mtproto-main/ $APP_DIR/

cd $APP_DIR

source venv/bin/activate

pip install -r requirements.txt

systemctl daemon-reload
systemctl restart delta-panel 2>/dev/null || true
systemctl restart delta-sub 2>/dev/null || true

echo "Update Completed"
