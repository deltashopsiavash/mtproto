#!/bin/bash
set -e

APP_DIR="/opt/delta-proxy-panel"
TMP_DIR="/tmp/mtproto-install-src"
TMP_FILE="/tmp/mtproto-install.zip"
REPO_ZIP="https://github.com/deltashopsiavash/mtproto/archive/refs/heads/main.zip"

echo "=== Delta MTProto Panel Install ==="

apt update
apt install -y curl wget unzip git rsync python3 python3-pip python3-venv

rm -rf "$TMP_DIR" "$TMP_FILE" "$APP_DIR"
mkdir -p "$TMP_DIR" "$APP_DIR"

wget -O "$TMP_FILE" "$REPO_ZIP"
unzip -o "$TMP_FILE" -d "$TMP_DIR"

SRC_DIR="$TMP_DIR/mtproto-main"

if [ ! -d "$SRC_DIR" ]; then
  echo "ERROR: Source directory not found after unzip."
  exit 1
fi

rsync -av "$SRC_DIR/" "$APP_DIR/"

cd "$APP_DIR"

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt || true

read -p "Panel Port: " PANEL_PORT
read -p "Panel Username: " PANEL_USER
read -p "Panel Password: " PANEL_PASS
read -p "Proxy Port: " PROXY_PORT
read -p "Sub Link Port: " SUB_PORT

cat > "$APP_DIR/.env" <<EOF
PANEL_PORT=$PANEL_PORT
PANEL_USER=$PANEL_USER
PANEL_PASS=$PANEL_PASS
PROXY_PORT=$PROXY_PORT
SUB_PORT=$SUB_PORT
EOF

if [ -d "$APP_DIR/systemd" ]; then
  cp "$APP_DIR"/systemd/*.service /etc/systemd/system/ 2>/dev/null || true
fi

systemctl daemon-reload
systemctl enable delta-panel 2>/dev/null || true
systemctl enable delta-sub 2>/dev/null || true
systemctl restart delta-panel 2>/dev/null || true
systemctl restart delta-sub 2>/dev/null || true

echo "Install completed successfully."
