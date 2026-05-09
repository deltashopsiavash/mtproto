#!/bin/bash
set -e

APP_DIR="/opt/delta-proxy-panel"
TMP_DIR="/tmp/delta-mtproto-install"
REPO_ZIP="https://github.com/deltashopsiavash/mtproto/archive/refs/heads/main.zip"

echo "=== Delta MTProto Clean Install ==="
apt update
apt install -y curl wget unzip git rsync python3 python3-pip python3-venv build-essential

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
wget -O "$TMP_DIR/src.zip" "$REPO_ZIP"
unzip -o "$TMP_DIR/src.zip" -d "$TMP_DIR"

SRC_DIR="$TMP_DIR/mtproto-main"
if [ ! -d "$SRC_DIR" ]; then echo "Source not found"; exit 1; fi

systemctl stop delta-panel delta-sub 2>/dev/null || true

rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
rsync -av "$SRC_DIR/" "$APP_DIR/"

cd "$APP_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

read -p "Panel Port [8080]: " PANEL_PORT
PANEL_PORT=${PANEL_PORT:-8080}
read -p "Panel Username [admin]: " PANEL_USER
PANEL_USER=${PANEL_USER:-admin}
read -p "Panel Password: " PANEL_PASS
PANEL_PASS=${PANEL_PASS:-admin}
read -p "Shared Proxy Port [8800]: " PROXY_PORT
PROXY_PORT=${PROXY_PORT:-8800}
read -p "Sub Link Port [2096]: " SUB_PORT
SUB_PORT=${SUB_PORT:-2096}
read -p "Public Domain/IP: " PUBLIC_HOST

cat > "$APP_DIR/.env" <<EOF
PANEL_PORT=$PANEL_PORT
SUB_PORT=$SUB_PORT
PROXY_PORT=$PROXY_PORT
PANEL_USER=$PANEL_USER
PANEL_PASS=$PANEL_PASS
PUBLIC_HOST=$PUBLIC_HOST
BOT_TOKEN=
BOT_ADMIN_ID=
EOF

cp "$APP_DIR"/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable delta-panel delta-sub
systemctl restart delta-panel delta-sub

echo "clean-v1" > "$APP_DIR/VERSION"
echo "Installed: http://SERVER-IP:$PANEL_PORT"
