#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
read -rp "Admin username [admin]: " ADMIN_USERNAME; ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
read -rsp "New admin password: " ADMIN_PASSWORD; echo
if [[ -z "$ADMIN_PASSWORD" ]]; then echo "Password cannot be empty"; exit 1; fi
ADMIN_PASSWORD_B64=$(printf "%s" "$ADMIN_PASSWORD" | base64 -w0)
if grep -q '^ADMIN_USERNAME=' .env; then sed -i "s|^ADMIN_USERNAME=.*|ADMIN_USERNAME=$ADMIN_USERNAME|" .env; else echo "ADMIN_USERNAME=$ADMIN_USERNAME" >> .env; fi
if grep -q '^ADMIN_PASSWORD_B64=' .env; then sed -i "s|^ADMIN_PASSWORD_B64=.*|ADMIN_PASSWORD_B64=$ADMIN_PASSWORD_B64|" .env; else echo "ADMIN_PASSWORD_B64=$ADMIN_PASSWORD_B64" >> .env; fi
docker compose up -d --build --force-recreate backend frontend
echo "Admin reset done. Try logging in again."
