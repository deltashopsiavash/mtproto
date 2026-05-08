#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
docker ps -a --filter label=managed-by=mtproto-panel -q | xargs -r docker rm -f
docker compose down
read -rp "Remove database and .env too? [y/N]: " x
[[ "$x" =~ ^[Yy]$ ]] && rm -rf data .env
