#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "Please run as root"; exit 1; fi
if docker compose version >/dev/null 2>&1; then docker compose down; fi
docker rm -f mtproto_shared_proxy 2>/dev/null || true
read -rp "Remove data directory too? [y/N]: " ANS
if [[ "${ANS,,}" == "y" ]]; then rm -rf data mtproxy-data; docker volume rm mtproto_proxy_config 2>/dev/null || true; fi
echo "Uninstalled."
