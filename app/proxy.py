import os, subprocess, secrets, time
from pathlib import Path
from .config import PROXY_CONFIG, PROXY_SERVICE, load_env
from .db import db, log, now_ts

def make_secret():
    # MTProxy secret: 16 bytes hex; dd prefix not used to keep simple.
    return secrets.token_hex(16)

def mtproto_link(host, port, secret):
    return f"https://t.me/proxy?server={host}&port={port}&secret={secret}"

def is_valid_user(row):
    if not row["active"]:
        return False
    if row["expire_at"] and int(row["expire_at"]) < now_ts():
        return False
    if row["limit_bytes"] and int(row["used_bytes"]) >= int(row["limit_bytes"]):
        return False
    return True

def public_host(request=None):
    env = load_env()
    h = env.get("PUBLIC_HOST") or ""
    if h:
        return h
    if request:
        return request.url.hostname or "127.0.0.1"
    return "127.0.0.1"

def render_config():
    env = load_env()
    port = int(env.get("PROXY_PORT") or 8800)
    PROXY_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    active_secrets = [r["secret"] for r in rows if is_valid_user(r)]
    lines = []
    # Format compatible-ish with common multi config loader in this project.
    # The installer also writes /etc/mtpulse/proxy-multi.conf for custom mtproxy service.
    for s in active_secrets:
        lines.append(f"{s}\n")
    PROXY_CONFIG.write_text("".join(lines))
    return len(active_secrets)

def restart_proxy():
    render_config()
    subprocess.run(["systemctl", "restart", PROXY_SERVICE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("proxy", "proxy config rendered and service restart requested")

def disable_exhausted():
    changed = False
    ts = now_ts()
    with db() as conn:
        rows = conn.execute("SELECT * FROM users WHERE active=1").fetchall()
        for r in rows:
            expired = r["expire_at"] and int(r["expire_at"]) < ts
            over = r["limit_bytes"] and int(r["used_bytes"]) >= int(r["limit_bytes"])
            if expired or over:
                conn.execute("UPDATE users SET active=0, updated_at=? WHERE id=?", (ts, r["id"]))
                changed = True
    if changed:
        restart_proxy()
    return changed

def shared_port_accounting_tick():
    # IMPORTANT:
    # Official MTProxy on one shared port does not expose per-secret traffic accounting.
    # To avoid stealing quota from other users, this clean build does NOT split total port traffic
    # across all users. Manual adjustment/API remains available. Expire/limit enforcement is real:
    # when used_bytes >= limit_bytes, that user's secret is removed from the config.
    disable_exhausted()
