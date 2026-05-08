import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import psutil
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

APP_DIR = Path(os.getenv("APP_DIR", "/opt/delta-proxy-panel"))
DB_PATH = Path(os.getenv("DB_PATH", str(APP_DIR / "delta.db")))
ENV_PUBLIC_HOST = os.getenv("PUBLIC_HOST", "")
ENV_PROXY_PORT = int(os.getenv("PROXY_PORT", "443"))
SPONSOR_TAG = os.getenv("SPONSOR_TAG", "").strip()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = base64.b64decode(os.getenv("ADMIN_PASSWORD_B64", "").encode() or b"").decode(errors="ignore")
SECRET_KEY = hashlib.sha256((ADMIN_USERNAME + ADMIN_PASSWORD + str(APP_DIR)).encode()).hexdigest()
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="DELTA MTProto Panel")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def db() -> sqlite3.Connection:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def pass_hash(password: str) -> str:
    return hashlib.sha256(("delta:" + password).encode()).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def setting(key: str, default: str = "") -> str:
    with db() as conn:
        row = conn.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
    return row["v"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO settings(k,v) VALUES (?,?)", (key, value))


def ensure_column(conn: sqlite3.Connection, table: str, col: str, ddl: str) -> None:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                secret TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                expire_at TEXT,
                quota_gb REAL DEFAULT 0,
                used_gb REAL DEFAULT 0,
                note TEXT,
                created_at TEXT NOT NULL
            )
        """)
        ensure_column(conn, "users", "port", "port INTEGER")
        ensure_column(conn, "users", "rx_bytes", "rx_bytes INTEGER DEFAULT 0")
        ensure_column(conn, "users", "tx_bytes", "tx_bytes INTEGER DEFAULT 0")
        ensure_column(conn, "users", "last_seen", "last_seen TEXT")
        ensure_column(conn, "users", "disabled_reason", "disabled_reason TEXT")
        existing_admin = conn.execute('SELECT v FROM settings WHERE k="admin_username"').fetchone()
        if not existing_admin:
            set_setting(conn, "admin_username", ADMIN_USERNAME)
            set_setting(conn, "admin_hash", pass_hash(ADMIN_PASSWORD))
        defaults = {
            "public_host": ENV_PUBLIC_HOST,
            "proxy_port": str(ENV_PROXY_PORT),
            "panel_title": "DELTA MTProto",
            "theme": "dark",
            "telegram_bot_token": "",
            "telegram_chat_id": "",
        }
        for k, v in defaults.items():
            if not conn.execute("SELECT 1 FROM settings WHERE k=?", (k,)).fetchone():
                set_setting(conn, k, v)
        # migrate old users without a dedicated port
        base = int(setting("proxy_port", str(ENV_PROXY_PORT)) or ENV_PROXY_PORT)
        rows = conn.execute("SELECT id FROM users WHERE port IS NULL OR port=0 ORDER BY id ASC").fetchall()
        for i, r in enumerate(rows):
            conn.execute("UPDATE users SET port=? WHERE id=?", (next_free_port(conn, base + i, exclude_id=r["id"]), r["id"]))
        conn.commit()


def is_authed(req: Request) -> bool:
    token = req.cookies.get("delta_session", "")
    good = hmac.new(SECRET_KEY.encode(), b"login", hashlib.sha256).hexdigest()
    return hmac.compare_digest(token, good)


def require(req: Request) -> None:
    if not is_authed(req):
        raise HTTPException(status_code=401, detail="unauthorized")


def parse_expire_days(days: Optional[str], current: Optional[str] = None, keep_when_blank: bool = False) -> Optional[str]:
    if days is None or str(days).strip() == "":
        return current if keep_when_blank else None
    try:
        d = int(float(str(days).strip()))
    except ValueError:
        raise HTTPException(status_code=400, detail="expire_days must be a number")
    if d <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(days=d)).isoformat()


def days_left(expire_at: Optional[str]) -> Optional[int]:
    if not expire_at:
        return None
    try:
        end = datetime.fromisoformat(expire_at.replace("Z", "+00:00"))
        diff = end - datetime.now(timezone.utc)
        return max(0, diff.days + (1 if diff.seconds else 0))
    except Exception:
        return None


def is_not_expired(expire_at: Optional[str]) -> bool:
    if not expire_at:
        return True
    try:
        return datetime.fromisoformat(expire_at.replace("Z", "+00:00")) > datetime.now(timezone.utc)
    except Exception:
        return True


def proxy_host() -> str:
    return setting("public_host", ENV_PUBLIC_HOST) or ENV_PUBLIC_HOST


def base_proxy_port() -> int:
    try:
        return int(setting("proxy_port", str(ENV_PROXY_PORT)))
    except Exception:
        return ENV_PROXY_PORT


def proxy_link(secret: str, port: int | None = None) -> str:
    # Shared Port mode: all users connect to one public port; user identity is the secret.
    return f"tg://proxy?server={proxy_host()}&port={base_proxy_port()}&secret={secret}"


def next_free_port(conn: sqlite3.Connection, start: int, exclude_id: Optional[int] = None) -> int:
    used = {int(r["port"]) for r in conn.execute("SELECT port FROM users WHERE port IS NOT NULL AND port>0").fetchall()}
    if exclude_id:
        row = conn.execute("SELECT port FROM users WHERE id=?", (exclude_id,)).fetchone()
        if row and row["port"]:
            used.discard(int(row["port"]))
    port = max(1, min(65535, int(start)))
    while port in used and port < 65535:
        port += 1
    if port > 65535:
        raise HTTPException(status_code=400, detail="no free port")
    return port


def active_users() -> list[sqlite3.Row]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM users WHERE enabled=1 ORDER BY id ASC").fetchall()
    return [row for row in rows if is_not_expired(row["expire_at"])]


def svc_name(uid: int) -> str:
    return f"mtpulse-u{uid}"


def render_proxy_service() -> None:
    users = active_users()
    service_dir = Path("/etc/systemd/system")
    service_dir.mkdir(parents=True, exist_ok=True)

    # V4 Shared Port mode: one MTProxy instance, one public port, multiple -S secrets.
    # This keeps all users on the same port. Per-user traffic cannot be exact unless
    # MTProxy is patched/logged by secret; traffic below is total shared-port traffic.
    for service in service_dir.glob("mtpulse-u*.service"):
        subprocess.run(["systemctl", "disable", "--now", service.stem], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        try:
            service.unlink()
        except Exception:
            pass

    shared = service_dir / "mtpulse-shared.service"
    if not users:
        subprocess.run(["systemctl", "disable", "--now", "mtpulse-shared"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        try:
            shared.unlink()
        except Exception:
            pass
        subprocess.run(["systemctl", "daemon-reload"], check=False)
        return

    secrets_args = " ".join(f"-S {u['secret']}" for u in users)
    p_arg = f" -P {SPONSOR_TAG}" if SPONSOR_TAG else ""
    exec_start = (
        f"/usr/local/bin/mtproto-proxy -u nobody -p 8800 -H {base_proxy_port()} "
        f"{secrets_args}{p_arg} --aes-pwd /etc/mtpulse/proxy-secret /etc/mtpulse/proxy-multi.conf -M 1"
    )
    shared.write_text(f"""[Unit]
Description=DELTA MTProto shared-port service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=always
RestartSec=3
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
""")
    subprocess.run(["systemctl", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "enable", "--now", "mtpulse-shared"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    subprocess.run(["systemctl", "restart", "mtpulse-shared"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    ensure_traffic_rules()


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, text=True, capture_output=True, check=False).stdout


def ensure_traffic_rules() -> None:
    if os.geteuid() != 0:
        return
    port = base_proxy_port()
    subprocess.run(["iptables", "-N", "DELTA_MTPROTO_TRAFFIC"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if subprocess.run(["iptables", "-C", "INPUT", "-j", "DELTA_MTPROTO_TRAFFIC"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode != 0:
        subprocess.run(["iptables", "-I", "INPUT", "1", "-j", "DELTA_MTPROTO_TRAFFIC"], check=False)
    if subprocess.run(["iptables", "-C", "OUTPUT", "-j", "DELTA_MTPROTO_TRAFFIC"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode != 0:
        subprocess.run(["iptables", "-I", "OUTPUT", "1", "-j", "DELTA_MTPROTO_TRAFFIC"], check=False)
    existing = run(["iptables", "-S", "DELTA_MTPROTO_TRAFFIC"])
    cin = f"delta-shared-in-{port}"
    cout = f"delta-shared-out-{port}"
    if cin not in existing:
        subprocess.run(["iptables", "-A", "DELTA_MTPROTO_TRAFFIC", "-p", "tcp", "--dport", str(port), "-m", "comment", "--comment", cin, "-j", "RETURN"], check=False)
    if cout not in existing:
        subprocess.run(["iptables", "-A", "DELTA_MTPROTO_TRAFFIC", "-p", "tcp", "--sport", str(port), "-m", "comment", "--comment", cout, "-j", "RETURN"], check=False)


def parse_iptables_counters() -> dict[int, dict[str, int]]:
    ensure_traffic_rules()
    port = base_proxy_port()
    out = run(["iptables", "-L", "DELTA_MTPROTO_TRAFFIC", "-v", "-x", "-n"])
    data: dict[int, dict[str, int]] = {port: {"rx": 0, "tx": 0}}
    for line in out.splitlines():
        m_in = re.search(r"^\s*\d+\s+(\d+).*dpt:(\d+).*delta-shared-in-(\d+)", line)
        m_out = re.search(r"^\s*\d+\s+(\d+).*spt:(\d+).*delta-shared-out-(\d+)", line)
        if m_in:
            data[port]["rx"] = int(m_in.group(1))
        if m_out:
            data[port]["tx"] = int(m_out.group(1))
    return data


def online_by_port() -> dict[int, int]:
    out = run(["ss", "-Htan", "state", "established"])
    counts: dict[int, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3]
        try:
            port = int(local.rsplit(":", 1)[-1])
            counts[port] = counts.get(port, 0) + 1
        except Exception:
            pass
    return counts


def sync_traffic() -> None:
    counters = parse_iptables_counters()
    online = online_by_port()
    shared_port = base_proxy_port()
    c = counters.get(shared_port, {"rx": 0, "tx": 0})
    total_gb = (int(c["rx"]) + int(c["tx"])) / (1024**3)
    last_seen = now_iso() if online.get(shared_port, 0) else None
    # Shared-port mode cannot attribute exact traffic per secret. Keep per-user traffic editable
    # and expose shared traffic separately in overview/users as approximate telemetry.
    with db() as conn:
        rows = conn.execute("SELECT id,quota_gb,used_gb,enabled FROM users").fetchall()
        active_count = max(1, len([r for r in rows if int(r['enabled'])]))
        approximate_each = total_gb / active_count
        for r in rows:
            if last_seen and int(r["enabled"]):
                conn.execute("UPDATE users SET last_seen=COALESCE(?, last_seen) WHERE id=?", (last_seen, r["id"]))
            if r["quota_gb"] and float(r["used_gb"] or 0) >= float(r["quota_gb"]) and int(r["enabled"]):
                conn.execute("UPDATE users SET enabled=0, disabled_reason='quota' WHERE id=?", (r["id"],))
        set_setting(conn, "shared_rx_bytes", str(c["rx"]))
        set_setting(conn, "shared_tx_bytes", str(c["tx"]))
        set_setting(conn, "shared_approx_gb_each", str(approximate_each))
        conn.commit()


def telegram_send(text: str) -> dict:
    token = setting("telegram_bot_token", "").strip()
    chat_id = setting("telegram_chat_id", "").strip()
    if not token or not chat_id:
        return {"ok": False, "error": "bot token or chat id is empty"}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
    try:
        with urllib.request.urlopen(url, data=payload, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def index(req: Request) -> str:
    page = "panel.html" if is_authed(req) else "login.html"
    return (STATIC_DIR / page).read_text(encoding="utf-8")


@app.post("/api/login")
def login(username: str = Form(...), password: str = Form(...)):
    with db() as conn:
        admin_user = conn.execute('SELECT v FROM settings WHERE k="admin_username"').fetchone()["v"]
        admin_hash = conn.execute('SELECT v FROM settings WHERE k="admin_hash"').fetchone()["v"]
    if username == admin_user and pass_hash(password) == admin_hash:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("delta_session", hmac.new(SECRET_KEY.encode(), b"login", hashlib.sha256).hexdigest(), httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/?err=1", status_code=303)


@app.post("/api/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("delta_session")
    return resp


@app.get("/api/overview")
def overview(req: Request):
    require(req)
    sync_traffic()
    disk = psutil.disk_usage("/")
    mem = psutil.virtual_memory()
    net = psutil.net_io_counters()
    load1, load5, load15 = os.getloadavg()
    online = online_by_port()
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        enabled = conn.execute("SELECT COUNT(*) n FROM users WHERE enabled=1").fetchone()["n"]
        used = conn.execute("SELECT COALESCE(SUM(used_gb),0) n FROM users").fetchone()["n"]
        quota = conn.execute("SELECT COALESCE(SUM(quota_gb),0) n FROM users").fetchone()["n"]
        ports = [int(r["port"]) for r in conn.execute("SELECT port FROM users WHERE port IS NOT NULL").fetchall()]
    return {"cpu": psutil.cpu_percent(interval=0.1), "load": [load1, load5, load15], "cores": psutil.cpu_count(), "ram_percent": mem.percent, "ram_total": mem.total, "ram_used": mem.used, "disk_percent": disk.percent, "disk_total": disk.total, "disk_used": disk.used, "rx": net.bytes_recv, "tx": net.bytes_sent, "proxy_status": "shared active" if enabled else "inactive", "users_total": total, "users_enabled": enabled, "online_total": online.get(base_proxy_port(),0), "quota_total": quota, "used_total": used, "public_host": proxy_host(), "proxy_port": base_proxy_port(), "uptime_seconds": int(datetime.now().timestamp() - psutil.boot_time()), "theme": setting("theme", "dark"), "mode": "shared-port", "shared_rx_bytes": int(setting("shared_rx_bytes", "0") or 0), "shared_tx_bytes": int(setting("shared_tx_bytes", "0") or 0)}


@app.get("/api/users")
def users(req: Request):
    require(req)
    sync_traffic()
    online = online_by_port()
    with db() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()]
    for row in rows:
        row["link"] = proxy_link(row["secret"])
        row["expired"] = not is_not_expired(row.get("expire_at"))
        row["days_left"] = days_left(row.get("expire_at"))
        q = float(row.get("quota_gb") or 0)
        u = float(row.get("used_gb") or 0)
        row["usage_percent"] = 0 if q <= 0 else min(100, round((u / q) * 100, 1))
        row["online"] = int(online.get(base_proxy_port(), 0)) if row.get("enabled") else 0
        row["shared_port"] = base_proxy_port()
        row["traffic_mode"] = "shared_approx"
    return rows


@app.post("/api/users")
def add_user(req: Request, name: str = Form(...), expire_days: Optional[str] = Form(None), quota_gb: float = Form(0), note: str = Form("")):
    require(req)
    if not name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    expire_at = parse_expire_days(expire_days)
    secret = secrets.token_hex(16)
    with db() as conn:
        conn.execute("INSERT INTO users(name, secret, enabled, expire_at, quota_gb, used_gb, port, rx_bytes, tx_bytes, note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (name.strip(), secret, 1, expire_at, max(0, quota_gb), 0, base_proxy_port(), 0, 0, note.strip(), now_iso()))
        conn.commit()
    render_proxy_service()
    link = proxy_link(secret)
    telegram_send(f"✅ پروکسی جدید ساخته شد\n👤 {name}\n🔌 Shared Port: {base_proxy_port()}\n🔗 {link}")
    return {"ok": True, "secret": secret, "port": base_proxy_port(), "link": link}


@app.post("/api/users/{uid}/update")
def update_user(uid: int, req: Request, name: str = Form(...), expire_days: Optional[str] = Form(None), keep_expire: int = Form(1), quota_gb: float = Form(0), used_gb: float = Form(0), note: str = Form(""), enabled: int = Form(1)):
    require(req)
    if not name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    with db() as conn:
        old = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not old:
            raise HTTPException(status_code=404, detail="user not found")
        expire_at = parse_expire_days(expire_days, old["expire_at"], bool(keep_expire))
        conn.execute("UPDATE users SET name=?, expire_at=?, quota_gb=?, used_gb=?, port=?, note=?, enabled=?, disabled_reason=NULL WHERE id=?", (name.strip(), expire_at, max(0, quota_gb), max(0, used_gb), base_proxy_port(), note.strip(), 1 if enabled else 0, uid))
        conn.commit()
    render_proxy_service()
    return {"ok": True}


@app.post("/api/users/{uid}/toggle")
def toggle(uid: int, req: Request):
    require(req)
    with db() as conn:
        conn.execute("UPDATE users SET enabled=CASE enabled WHEN 1 THEN 0 ELSE 1 END, disabled_reason=NULL WHERE id=?", (uid,))
        conn.commit()
    render_proxy_service()
    return {"ok": True}


@app.post("/api/users/{uid}/delete")
def delete(uid: int, req: Request):
    require(req)
    with db() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.commit()
    render_proxy_service()
    return {"ok": True}


@app.get("/api/settings")
def get_settings(req: Request):
    require(req)
    return {"public_host": proxy_host(), "proxy_port": base_proxy_port(), "admin_username": setting("admin_username", ADMIN_USERNAME), "panel_title": setting("panel_title", "DELTA MTProto"), "theme": setting("theme", "dark"), "telegram_bot_token": setting("telegram_bot_token", ""), "telegram_chat_id": setting("telegram_chat_id", "")}


@app.post("/api/settings/server")
def save_server(req: Request, public_host: str = Form(...), proxy_port_value: int = Form(...), theme: str = Form("dark")):
    require(req)
    with db() as conn:
        set_setting(conn, "public_host", public_host.strip())
        set_setting(conn, "proxy_port", str(proxy_port_value))
        set_setting(conn, "theme", "light" if theme == "light" else "dark")
        conn.commit()
    render_proxy_service()
    return {"ok": True}


@app.post("/api/settings/admin")
def save_admin(req: Request, username: str = Form(...), password: str = Form("")):
    require(req)
    if not username.strip():
        raise HTTPException(status_code=400, detail="username is required")
    with db() as conn:
        set_setting(conn, "admin_username", username.strip())
        if password.strip():
            set_setting(conn, "admin_hash", pass_hash(password.strip()))
        conn.commit()
    return {"ok": True}


@app.post("/api/settings/telegram")
def save_telegram(req: Request, telegram_bot_token: str = Form(""), telegram_chat_id: str = Form("")):
    require(req)
    with db() as conn:
        set_setting(conn, "telegram_bot_token", telegram_bot_token.strip())
        set_setting(conn, "telegram_chat_id", telegram_chat_id.strip())
        conn.commit()
    return {"ok": True}


@app.post("/api/telegram/test")
def telegram_test(req: Request):
    require(req)
    return telegram_send("✅ تست اتصال بات DELTA MTProto موفق بود.")


@app.get("/api/backup/export")
def export_backup(req: Request):
    require(req)
    with db() as conn:
        data = {"version": 4, "created_at": now_iso(), "settings": {r["k"]: r["v"] for r in conn.execute("SELECT * FROM settings").fetchall()}, "users": [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()]}
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": "attachment; filename=delta-mtproto-backup-v4.json"})


@app.post("/api/backup/import")
async def import_backup(req: Request, backup: UploadFile = File(...)):
    require(req)
    raw = await backup.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid backup file")
    users_data = data.get("users", [])
    settings_data = data.get("settings", {})
    with db() as conn:
        for k, v in settings_data.items():
            if k in {"public_host", "proxy_port", "panel_title", "admin_username", "admin_hash", "theme", "telegram_bot_token", "telegram_chat_id"}:
                set_setting(conn, k, str(v))
        conn.execute("DELETE FROM users")
        for u in users_data:
            conn.execute("INSERT INTO users(name, secret, enabled, expire_at, quota_gb, used_gb, port, rx_bytes, tx_bytes, last_seen, disabled_reason, note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (u.get("name", "user"), u.get("secret") or secrets.token_hex(16), int(u.get("enabled", 1)), u.get("expire_at"), float(u.get("quota_gb") or 0), float(u.get("used_gb") or 0), int(u.get("port") or next_free_port(conn, base_proxy_port())), int(u.get("rx_bytes") or 0), int(u.get("tx_bytes") or 0), u.get("last_seen"), u.get("disabled_reason"), u.get("note", ""), u.get("created_at") or now_iso()))
        conn.commit()
    render_proxy_service()
    return {"ok": True, "imported": len(users_data)}


@app.post("/api/proxy/restart")
def restart(req: Request):
    require(req)
    render_proxy_service()
    return {"ok": True}


@app.get("/api/proxy/logs")
def logs(req: Request):
    require(req)
    proc = subprocess.run(["journalctl", "-u", "mtpulse-shared", "-n", "220", "--no-pager"], text=True, capture_output=True, check=False)
    return JSONResponse({"logs": proc.stdout[-24000:]})
