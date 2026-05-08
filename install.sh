#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "Please run as root"; exit 1; fi
cd "$(dirname "$0")"
echo "=== MTProto Full Panel Installer ==="
read -rp "Panel port [8080]: " PANEL_PORT; PANEL_PORT=${PANEL_PORT:-8080}
read -rp "Admin username [admin]: " ADMIN_USERNAME; ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
read -rsp "Admin password: " ADMIN_PASSWORD; echo
if [[ -z "$ADMIN_PASSWORD" ]]; then echo "Password cannot be empty"; exit 1; fi
DEFAULT_IP=$(curl -4 -s https://api.ipify.org || hostname -I | awk '{print $1}')
read -rp "Public server IP/domain [$DEFAULT_IP]: " PUBLIC_HOST; PUBLIC_HOST=${PUBLIC_HOST:-$DEFAULT_IP}
read -rp "User proxy port start [20000]: " USER_PORT_START; USER_PORT_START=${USER_PORT_START:-20000}
read -rp "User proxy port end [20999]: " USER_PORT_END; USER_PORT_END=${USER_PORT_END:-20999}
SECRET=$(openssl rand -hex 32)
cat > .env <<ENV
PANEL_PORT=$PANEL_PORT
ADMIN_USERNAME=$ADMIN_USERNAME
ADMIN_PASSWORD=$ADMIN_PASSWORD
PANEL_SECRET_KEY=$SECRET
PUBLIC_HOST=$PUBLIC_HOST
USER_PORT_START=$USER_PORT_START
USER_PORT_END=$USER_PORT_END
MTPROXY_IMAGE=nineseconds/mtg:stable
COMPOSE_PROJECT_NAME=mtproto-panel
ENV
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else echo "Docker Compose plugin missing"; exit 1; fi
mkdir -p data
$COMPOSE up -d --build
if command -v ufw >/dev/null 2>&1; then
  ufw allow "$PANEL_PORT"/tcp || true
  ufw allow "$USER_PORT_START:$USER_PORT_END"/tcp || true
fi
cat <<DONE

Installed successfully.
Panel: http://$PUBLIC_HOST:$PANEL_PORT
Username: $ADMIN_USERNAME
Password: [the password you entered]
Proxy user ports: $USER_PORT_START-$USER_PORT_END

Useful commands:
  docker compose logs -f
  docker compose restart
  ./uninstall.sh
DONE
