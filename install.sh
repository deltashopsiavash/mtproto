#!/bin/bash
set -e

APP_DIR="/opt/delta-proxy-panel"
TMP_FILE="/tmp/mtproto.zip"

apt update
apt install -y python3 python3-venv python3-pip unzip curl wget git rsync

rm -rf $APP_DIR
mkdir -p $APP_DIR

wget -O $TMP_FILE https://github.com/deltashopsiavash/mtproto/archive/refs/heads/main.zip

rm -rf /tmp/mtproto-main
unzip -o $TMP_FILE -d /tmp/

cp -r /tmp/mtproto-main/* $APP_DIR/

cd $APP_DIR

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

read -p "Panel Port: " PANEL_PORT
read -p "Panel Username: " PANEL_USER
read -p "Panel Password: " PANEL_PASS
read -p "Proxy Port: " PROXY_PORT
read -p "Sub Link Port: " SUB_PORT

cat > $APP_DIR/.env <<EOF
PANEL_PORT=$PANEL_PORT
PANEL_USER=$PANEL_USER
PANEL_PASS=$PANEL_PASS
PROXY_PORT=$PROXY_PORT
SUB_PORT=$SUB_PORT
EOF

if [ -d "$APP_DIR/systemd" ]; then
cp $APP_DIR/systemd/*.service /etc/systemd/system/ 2>/dev/null || true
fi

systemctl daemon-reload
systemctl enable delta-panel 2>/dev/null || true
systemctl enable delta-sub 2>/dev/null || true
systemctl restart delta-panel 2>/dev/null || true
systemctl restart delta-sub 2>/dev/null || true

echo "Installation Completed"
