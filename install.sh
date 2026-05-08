#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/delta-proxy-panel"
ENV_FILE="$APP_DIR/.env"
SERVICE_PANEL="/etc/systemd/system/delta-panel.service"
SERVICE_SUB="/etc/systemd/system/delta-sub.service"
REPO_URL="https://github.com/deltashopsiavash/mtproto"
TMP_DIR=""

red(){ echo -e "\033[0;31m$*\033[0m"; }
green(){ echo -e "\033[0;32m$*\033[0m"; }
yellow(){ echo -e "\033[1;33m$*\033[0m"; }

if [ "$(id -u)" -ne 0 ]; then
  red "Please run as root"
  exit 1
fi

if [ -f /etc/os-release ]; then
  . /etc/os-release
  if [[ "${ID:-}" != "ubuntu" && "${ID:-}" != "debian" ]]; then
    red "Only Ubuntu/Debian are supported. Detected: ${PRETTY_NAME:-unknown}"
    exit 1
  fi
fi

echo "=== DELTA MTProto Panel Installer ==="
read -rp "Panel port [8080]: " PANEL_PORT; PANEL_PORT=${PANEL_PORT:-8080}
read -rp "Admin username [admin]: " ADMIN_USERNAME; ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
read -rsp "Admin password: " ADMIN_PASSWORD; echo
if [ -z "$ADMIN_PASSWORD" ]; then red "Password cannot be empty"; exit 1; fi

DEFAULT_IP=$(curl -s --max-time 3 https://api.ipify.org || hostname -I | awk '{print $1}')
read -rp "Public server IP/domain [$DEFAULT_IP]: " PUBLIC_HOST; PUBLIC_HOST=${PUBLIC_HOST:-$DEFAULT_IP}
read -rp "MTProto proxy port [443]: " PROXY_PORT; PROXY_PORT=${PROXY_PORT:-443}
read -rp "Subscription status port [2096]: " SUB_PORT; SUB_PORT=${SUB_PORT:-2096}
read -rp "Sponsor tag/adtag optional [empty]: " SPONSOR_TAG; SPONSOR_TAG=${SPONSOR_TAG:-}

case "$PANEL_PORT" in (*[!0-9]*|'') red "Invalid panel port"; exit 1;; esac
case "$PROXY_PORT" in (*[!0-9]*|'') red "Invalid proxy port"; exit 1;; esac
case "$SUB_PORT" in (*[!0-9]*|'') red "Invalid sub port"; exit 1;; esac

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git curl build-essential libssl-dev zlib1g-dev python3 python3-venv python3-pip xxd ufw ca-certificates

if [ ! -x /usr/local/bin/mtproto-proxy ]; then
  yellow "Compiling official Telegram MTProxy..."
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

mkdir -p /etc/mtpulse "$APP_DIR"
curl -fsSL https://core.telegram.org/getProxySecret -o /etc/mtpulse/proxy-secret
curl -fsSL https://core.telegram.org/getProxyConfig -o /etc/mtpulse/proxy-multi.conf
echo "$PUBLIC_HOST" > /etc/mtpulse/public_ip

if [ -f "./app/main.py" ]; then
  cp -r ./app "$APP_DIR/"
  cp ./requirements.txt "$APP_DIR/requirements.txt" 2>/dev/null || true
else
  TMP_DIR=$(mktemp -d)
  git clone --depth=1 "$REPO_URL" "$TMP_DIR/repo"
  cp -r "$TMP_DIR/repo/app" "$APP_DIR/"
  cp "$TMP_DIR/repo/requirements.txt" "$APP_DIR/requirements.txt" 2>/dev/null || true
  rm -rf "$TMP_DIR"
fi

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip >/dev/null
if [ -f "$APP_DIR/requirements.txt" ]; then
  "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" >/dev/null
else
  "$APP_DIR/venv/bin/pip" install fastapi 'uvicorn[standard]' python-multipart psutil >/dev/null
fi

ADMIN_PASSWORD_B64=$(printf '%s' "$ADMIN_PASSWORD" | base64 -w0)
cat > "$ENV_FILE" <<ENV
APP_DIR=$APP_DIR
DB_PATH=$APP_DIR/delta.db
PUBLIC_HOST=$PUBLIC_HOST
PROXY_PORT=$PROXY_PORT
SUB_PORT=$SUB_PORT
SPONSOR_TAG=$SPONSOR_TAG
ADMIN_USERNAME=$ADMIN_USERNAME
ADMIN_PASSWORD_B64=$ADMIN_PASSWORD_B64
ENV
chmod 600 "$ENV_FILE"

cat > "$SERVICE_PANEL" <<SERVICE
[Unit]
Description=DELTA MTProto Web Panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PANEL_PORT
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICE

cat > "$SERVICE_SUB" <<SERVICE
[Unit]
Description=DELTA MTProto Public Subscription Pages
After=network-online.target delta-panel.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $SUB_PORT
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICE

ufw allow "$PANEL_PORT"/tcp >/dev/null 2>&1 || true
ufw allow "$PROXY_PORT"/tcp >/dev/null 2>&1 || true
ufw allow "$SUB_PORT"/tcp >/dev/null 2>&1 || true
systemctl daemon-reload
systemctl enable --now delta-panel delta-sub
systemctl restart delta-panel delta-sub

green "Installed successfully."
echo "Panel: http://$PUBLIC_HOST:$PANEL_PORT"
echo "Username: $ADMIN_USERNAME"
echo "Sub status pages: http://$PUBLIC_HOST:$SUB_PORT/s/<secret>"
echo "Proxy starts after creating at least one active user in the panel."
