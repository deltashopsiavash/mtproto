#!/bin/bash
set -e

APP_DIR="/opt/delta-proxy-panel"
TMP_FILE="/tmp/mtproto-install.zip"

apt update
apt install -y curl wget unzip git rsync python3 python3-pip python3-venv

rm -rf /tmp/mtproto-main
rm -f $TMP_FILE

wget -O $TMP_FILE https://github.com/deltashopsiavash/mtproto/archive/refs/heads/main.zip

unzip -o $TMP_FILE -d /tmp/

rm -rf $APP_DIR
mkdir -p $APP_DIR

cp -r /tmp/mtproto-main/* $APP_DIR/

cd $APP_DIR

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt || true

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

echo "Install Completed"
