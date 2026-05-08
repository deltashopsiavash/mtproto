#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "Please run as root"; exit 1; fi

REPO_URL="${REPO_URL:-https://github.com/deltashopsiavash/mtproto.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/mtproto-panel}"

# When executed via: bash <(curl .../install.sh), $0 is /dev/fd/* and there is no repo directory.
# In that case we clone/update the GitHub repo into /opt/mtproto-panel first.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
if [[ -z "$SCRIPT_DIR" || "$SCRIPT_DIR" == "/dev/fd" || ! -f "$SCRIPT_DIR/docker-compose.yml" ]]; then
  apt-get update -y
  apt-get install -y git curl openssl ca-certificates
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" pull --ff-only
  else
    rm -rf "$INSTALL_DIR"
    git clone "$REPO_URL" "$INSTALL_DIR"
  fi
  cd "$INSTALL_DIR"
else
  cd "$SCRIPT_DIR"
fi

echo "=== MTProto Full Panel Installer ==="
read -rp "Panel port [8080]: " PANEL_PORT; PANEL_PORT=${PANEL_PORT:-8080}
read -rp "Admin username [admin]: " ADMIN_USERNAME; ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
read -rsp "Admin password: " ADMIN_PASSWORD; echo
if [[ -z "$ADMIN_PASSWORD" ]]; then echo "Password cannot be empty"; exit 1; fi
DEFAULT_IP=$(curl -4 -s https://api.ipify.org || hostname -I | awk '{print $1}')
read -rp "Public server IP/domain [$DEFAULT_IP]: " PUBLIC_HOST; PUBLIC_HOST=${PUBLIC_HOST:-$DEFAULT_IP}
read -rp "MTProto shared proxy port [8443]: " PROXY_PORT; PROXY_PORT=${PROXY_PORT:-8443}
SECRET=$(openssl rand -hex 32)

cat > .env <<ENV
PANEL_PORT=$PANEL_PORT
ADMIN_USERNAME=$ADMIN_USERNAME
ADMIN_PASSWORD=$ADMIN_PASSWORD
PANEL_SECRET_KEY=$SECRET
PUBLIC_HOST=$PUBLIC_HOST
PROXY_PORT=$PROXY_PORT
MTPROXY_IMAGE=mtproto-panel-mtproxy:latest
COMPOSE_PROJECT_NAME=mtproto-panel
ENV

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else echo "Docker Compose plugin missing"; exit 1; fi

mkdir -p data mtproxy-data

docker build -t mtproto-panel-mtproxy:latest ./mtproxy
$COMPOSE up -d --build

if command -v ufw >/dev/null 2>&1; then
  ufw allow "$PANEL_PORT"/tcp || true
  ufw allow "$PROXY_PORT"/tcp || true
fi

cat <<DONE

Installed successfully.
Panel: http://$PUBLIC_HOST:$PANEL_PORT
Username: $ADMIN_USERNAME
Password: [the password you entered]
Shared MTProto port: $PROXY_PORT

Useful commands:
  cd $(pwd)
  docker compose logs -f
  docker compose restart
  ./uninstall.sh
DONE
