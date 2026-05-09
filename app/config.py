import os
from pathlib import Path

APP_DIR = Path(os.getenv("APP_DIR", "/opt/delta-proxy-panel"))
DATA_DIR = APP_DIR / "data"
BACKUP_DIR = APP_DIR / "backups"
DB_PATH = DATA_DIR / "panel.db"
ENV_PATH = APP_DIR / ".env"

PROXY_CONFIG = Path("/etc/mtpulse/proxy-multi.conf")
PROXY_SERVICE = "mtproto-proxy"

DEFAULTS = {
    "PANEL_PORT": "8080",
    "SUB_PORT": "2096",
    "PROXY_PORT": "8800",
    "PANEL_USER": "admin",
    "PANEL_PASS": "admin",
    "PUBLIC_HOST": "",
    "BOT_TOKEN": "",
    "BOT_ADMIN_ID": "",
}

def load_env():
    env = DEFAULTS.copy()
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env

def save_env(data):
    env = load_env()
    env.update({k: str(v) for k, v in data.items() if v is not None})
    ENV_PATH.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n")
    return env
