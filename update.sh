#!/bin/bash
set -e

APP_DIR="/opt/delta-proxy-panel"
BACKUP_DIR="/opt/delta-backups"
TMP_FILE="/tmp/mtproto-update.zip"

apt update
apt install -y curl wget unzip git rsync python3 python3-pip python3-venv

mkdir -p $BACKUP_DIR

DATE=$(date +%F-%H%M)

echo "Creating Backup..."
cp -r $APP_DIR "$BACKUP_DIR/backup-$DATE" 2>/dev/null || true

rm -rf /tmp/mtproto-main
rm -f $TMP_FILE

wget -O $TMP_FILE https://github.com/deltashopsiavash/mtproto/archive/refs/heads/main.zip

unzip -o $TMP_FILE -d /tmp/

echo "Updating Files..."

mkdir -p $APP_DIR

rsync -av --delete \
--exclude '.env' \
--exclude 'database.db' \
--exclude 'backups' \
--exclude 'venv' \
/tmp/mtproto-main/ $APP_DIR/

cd $APP_DIR

if [ ! -d "venv" ]; then
python3 -m venv venv
fi

source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt || true

systemctl daemon-reload
systemctl restart delta-panel 2>/dev/null || true
systemctl restart delta-sub 2>/dev/null || true

echo "Update Completed Successfully"
