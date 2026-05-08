#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/delta-proxy-panel
ENV_FILE="$APP_DIR/.env"
SERVICE_PANEL=/etc/systemd/system/delta-panel.service
SERVICE_PROXY=/etc/systemd/system/mtpulse.service

echo "=== DELTA PROXY PANEL Installer - MTPulse Core ==="
if [ "$(id -u)" -ne 0 ]; then echo "Run as root"; exit 1; fi

read -rp "Panel port [8080]: " PANEL_PORT; PANEL_PORT=${PANEL_PORT:-8080}
read -rp "Admin username [admin]: " ADMIN_USERNAME; ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
read -rsp "Admin password: " ADMIN_PASSWORD; echo
if [ -z "$ADMIN_PASSWORD" ]; then echo "Password cannot be empty"; exit 1; fi
DEFAULT_IP=$(curl -s --max-time 3 https://api.ipify.org || hostname -I | awk '{print $1}')
read -rp "Public server IP/domain [$DEFAULT_IP]: " PUBLIC_HOST; PUBLIC_HOST=${PUBLIC_HOST:-$DEFAULT_IP}
read -rp "MTProto proxy port [443]: " PROXY_PORT; PROXY_PORT=${PROXY_PORT:-443}
read -rp "Sponsor tag/adtag optional [empty]: " SPONSOR_TAG; SPONSOR_TAG=${SPONSOR_TAG:-}

mkdir -p "$APP_DIR"
if [ -f "./app/main.py" ]; then
  cp -r ./app "$APP_DIR/"
else
  echo "Installer must be run from repo root when local. For GitHub curl install, cloning..."
  TMP=$(mktemp -d)
  git clone --depth=1 https://github.com/deltashopsiavash/mtproto "$TMP/repo"
  cp -r "$TMP/repo/app" "$APP_DIR/"
  rm -rf "$TMP"
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y git curl build-essential libssl-dev zlib1g-dev python3 python3-venv python3-pip xxd ufw

# Install official Telegram MTProxy exactly like MTPulse: compile native binary on host
if [ ! -x /usr/local/bin/mtproto-proxy ]; then
  cd /tmp
  rm -rf MTProxy
  git clone --depth=1 https://github.com/TelegramMessenger/MTProxy.git
  cd MTProxy
  make -j"$(nproc)"
  cp objs/bin/mtproto-proxy /usr/local/bin/mtproto-proxy
  chmod +x /usr/local/bin/mtproto-proxy
  cd /
  rm -rf /tmp/MTProxy
fi

mkdir -p /etc/mtpulse
curl -fsSL https://core.telegram.org/getProxySecret -o /etc/mtpulse/proxy-secret
curl -fsSL https://core.telegram.org/getProxyConfig -o /etc/mtpulse/proxy-multi.conf
echo "$PUBLIC_HOST" > /etc/mtpulse/public_ip

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip >/dev/null
"$APP_DIR/venv/bin/pip" install fastapi uvicorn python-multipart psutil >/dev/null

ADMIN_PASSWORD_B64=$(printf '%s' "$ADMIN_PASSWORD" | base64 -w0)
cat > "$ENV_FILE" <<EOF
PANEL_PORT=$PANEL_PORT
ADMIN_USERNAME=$ADMIN_USERNAME
ADMIN_PASSWORD_B64=$ADMIN_PASSWORD_B64
PUBLIC_HOST=$PUBLIC_HOST
PROXY_PORT=$PROXY_PORT
SPONSOR_TAG=$SPONSOR_TAG
APP_DIR=$APP_DIR
DB_PATH=$APP_DIR/delta.db
EOF
chmod 600 "$ENV_FILE"

cat > "$SERVICE_PANEL" <<EOF
[Unit]
Description=DELTA Proxy Panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PANEL_PORT
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
EOF

# open firewall if active
ufw allow "$PANEL_PORT"/tcp >/dev/null 2>&1 || true
ufw allow "$PROXY_PORT"/tcp >/dev/null 2>&1 || true

systemctl daemon-reload
systemctl enable --now delta-panel
sleep 2
systemctl restart delta-panel

echo ""
echo "Installed. Panel: http://$PUBLIC_HOST:$PANEL_PORT"
echo "Username: $ADMIN_USERNAME"
echo "Proxy service will start after you create at least one active user in the panel."
