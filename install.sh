#!/usr/bin/env bash
set -Eeuo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[0;33m'; RESET='\033[0m'
REPO_URL="${MTPANEL_REPO_URL:-https://github.com/deltashopsiavash/mtproto.git}"
APP_DIR="/opt/mtproto-panel"
ETC_DIR="/etc/mtproto-panel"
MTPROXY_DIR="$ETC_DIR/mtproxy"
SERVICE="/etc/systemd/system/mtproto-panel.service"

need_root(){ [ "$(id -u)" -eq 0 ] || { echo -e "${RED}Please run as root.${RESET}"; exit 1; }; }
check_os(){ . /etc/os-release; [[ "$ID" == "ubuntu" || "$ID" == "debian" ]] || { echo -e "${RED}Only Ubuntu/Debian supported.${RESET}"; exit 1; }; }
ask_port(){ local prompt="$1" def="$2" val; while true; do read -rp "$prompt [$def]: " val; val=${val:-$def}; [[ "$val" =~ ^[0-9]+$ ]] && ((val>=1 && val<=65535)) && { echo "$val"; return; }; echo "Invalid port"; done; }
ask_nonempty(){ local prompt="$1" val; while true; do read -rp "$prompt: " val; [ -n "$val" ] && { echo "$val"; return; }; done; }
install_deps(){ apt-get update -y; apt-get install -y git curl wget build-essential zlib1g-dev libssl-dev python3 python3-venv python3-pip iptables rsync haproxy; }
install_mtproxy(){
  if command -v mtproto-proxy >/dev/null 2>&1; then return; fi
  echo -e "${CYAN}Compiling Telegram MTProxy...${RESET}"
  cd /tmp
  rm -rf MTProxy
  git clone https://github.com/TelegramMessenger/MTProxy.git
  cd MTProxy
  make >/tmp/mtproxy_make.log 2>&1 || { tail -40 /tmp/mtproxy_make.log; exit 1; }
  cp objs/bin/mtproto-proxy /usr/local/bin/mtproto-proxy
  chmod +x /usr/local/bin/mtproto-proxy
  cd /tmp && rm -rf MTProxy
}
fetch_proxy_files(){
  mkdir -p "$MTPROXY_DIR"
  curl -fsSL https://core.telegram.org/getProxySecret -o "$MTPROXY_DIR/proxy-secret"
  curl -fsSL https://core.telegram.org/getProxyConfig -o "$MTPROXY_DIR/proxy-multi.conf"
}
copy_source(){
  rm -rf "$APP_DIR.tmp"
  if [ -d "$(pwd)/.git" ] || [ -f "$(pwd)/app.py" ]; then
    mkdir -p "$APP_DIR.tmp" && cp -a . "$APP_DIR.tmp/"
  else
    git clone "$REPO_URL" "$APP_DIR.tmp"
  fi
  mkdir -p "$APP_DIR"
  rsync -a --delete --exclude 'venv' "$APP_DIR.tmp/" "$APP_DIR/" 2>/dev/null || { rm -rf "$APP_DIR"/*; cp -a "$APP_DIR.tmp"/. "$APP_DIR/"; }
  rm -rf "$APP_DIR.tmp"
}
write_config(){
  mkdir -p "$ETC_DIR"
  local panel_port sub_port username password proxy_ports hash public_ip api_token
  panel_port=$(ask_port "Panel login port" "8080")
  sub_port=$(ask_port "Subscription status port" "8081")
  username=$(ask_nonempty "Panel username")
  read -rsp "Panel password: " password; echo
  read -rp "Proxy ports, comma separated [443,8443,9443]: " proxy_ports; proxy_ports=${proxy_ports:-443,8443,9443}
  public_ip=$(curl -s --max-time 3 https://api.ipify.org || true)
  api_token=$(openssl rand -hex 24 2>/dev/null || date +%s%N | sha256sum | cut -d" " -f1)
  hash=$(PANEL_PASSWORD="$password" "$APP_DIR/venv/bin/python" - <<PY
import os
from werkzeug.security import generate_password_hash
print(generate_password_hash(os.environ["PANEL_PASSWORD"]))
PY
)
  cat > "$ETC_DIR/config.json" <<EOF
{
  "panel_host": "0.0.0.0",
  "panel_port": $panel_port,
  "sub_port": $sub_port,
  "admin_username": "$username",
  "admin_password_hash": "$hash",
  "proxy_ports": "$proxy_ports",
  "repo_url": "$REPO_URL",
  "public_ip": "$public_ip",
  "server_host": "$public_ip",
  "theme": "dark",
  "api_token": "$api_token",
  "telegram_bot_token": "",
  "telegram_admin_id": ""
}
EOF
}
setup_python(){ python3 -m venv "$APP_DIR/venv"; "$APP_DIR/venv/bin/pip" install --upgrade pip; "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"; }
write_service(){
  cat > "$SERVICE" <<EOF
[Unit]
Description=MTProto Web Panel
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/app.py
Restart=always
RestartSec=3
User=root
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now mtproto-panel.service
}

write_bot_service(){
  cat > /etc/systemd/system/mtproto-bot.service <<EOF
[Unit]
Description=MTProto Telegram Bot
After=network.target mtproto-panel.service

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/bot.py
Restart=always
RestartSec=5
User=root
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable mtproto-bot.service >/dev/null 2>&1 || true
  # It starts automatically after bot token/admin id are saved in Settings.
  systemctl restart mtproto-bot.service >/dev/null 2>&1 || true
}

install_update_cmd(){
  cat > /usr/local/bin/mtp-update <<EOF
#!/usr/bin/env bash
bash <(curl -Ls https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/update.sh)
EOF
  chmod +x /usr/local/bin/mtp-update
}
main(){
  need_root; check_os
  echo -e "${GREEN}MTProto Panel installer${RESET}"
  install_deps
  install_mtproxy
  fetch_proxy_files
  copy_source
  setup_python
  write_config
  "$APP_DIR/venv/bin/python" -c "import sys; sys.path.insert(0,'$APP_DIR'); import app; app.init_db()"
  write_service
  write_bot_service
  install_update_cmd
  local port; port=$(python3 - <<PY
import json; print(json.load(open('$ETC_DIR/config.json'))['panel_port'])
PY
)
  echo -e "${GREEN}Installed successfully.${RESET}"
  echo -e "Panel: ${CYAN}http://SERVER_IP:$port${RESET}"
  echo -e "Update command: ${YELLOW}mtp-update${RESET}"
}
main "$@"
