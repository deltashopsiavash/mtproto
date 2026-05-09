#!/usr/bin/env bash
set -Eeuo pipefail
GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; RESET='\033[0m'
APP_DIR="/opt/mtproto-panel"
ETC_DIR="/etc/mtproto-panel"
REPO_URL="${MTPANEL_REPO_URL:-https://github.com/deltashopsiavash/mtproto.git}"
[ "$(id -u)" -eq 0 ] || { echo -e "${RED}Please run as root.${RESET}"; exit 1; }
if [ -f "$ETC_DIR/config.json" ]; then
  REPO_URL=$(python3 - <<PY
import json
c=json.load(open('$ETC_DIR/config.json'))
print(c.get('repo_url') or '$REPO_URL')
PY
)
fi
mkdir -p /root/mtproto-panel-backup
[ -f "$ETC_DIR/config.json" ] && cp -f "$ETC_DIR/config.json" /root/mtproto-panel-backup/config.json
[ -f "$ETC_DIR/panel.db" ] && cp -f "$ETC_DIR/panel.db" /root/mtproto-panel-backup/panel.db
apt-get update -y >/dev/null
apt-get install -y git curl python3 python3-venv python3-pip >/dev/null
rm -rf "$APP_DIR.new"
git clone "$REPO_URL" "$APP_DIR.new"
mkdir -p "$APP_DIR"
rsync -a --delete --exclude 'venv' "$APP_DIR.new/" "$APP_DIR/" 2>/dev/null || { rm -rf "$APP_DIR"/*; cp -a "$APP_DIR.new"/. "$APP_DIR/"; }
rm -rf "$APP_DIR.new"
[ -d "$APP_DIR/venv" ] || python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip >/dev/null
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" >/dev/null
"$APP_DIR/venv/bin/python" -c "import sys; sys.path.insert(0,'$APP_DIR'); import app; app.init_db()"
systemctl daemon-reload
systemctl restart mtproto-panel.service
systemctl list-units 'mtproxy-user-*' --no-legend 2>/dev/null | awk '{print $1}' | xargs -r systemctl restart || true
cat > /usr/local/bin/mtp-update <<'EOF'
#!/usr/bin/env bash
bash <(curl -Ls https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/update.sh)
EOF
chmod +x /usr/local/bin/mtp-update
echo -e "${GREEN}MTProto Panel updated successfully.${RESET}"
echo -e "Backup: ${CYAN}/root/mtproto-panel-backup${RESET}"
