import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import subprocess
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


def init_db() -> None:
    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)")
        conn.execute(
            """
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
            """
        )
        existing_admin = conn.execute('SELECT v FROM settings WHERE k="admin_username"').fetchone()
        if not existing_admin:
            set_setting(conn, "admin_username", ADMIN_USERNAME)
            set_setting(conn, "admin_hash", pass_hash(ADMIN_PASSWORD))
        defaults = {
            "public_host": ENV_PUBLIC_HOST,
            "proxy_port": str(ENV_PROXY_PORT),
            "panel_title": "DELTA MTProto",
        }
        for k, v in defaults.items():
            if not conn.execute("SELECT 1 FROM settings WHERE k=?", (k,)).fetchone():
                set_setting(conn, k, v)
        conn.commit()


def is_authed(req: Request) -> bool:
    token = req.cookies.get("delta_session", "")
    good = hmac.new(SECRET_KEY.encode(), b"login", hashlib.sha256).hexdigest()
    return hmac.compare_digest(token, good)


def require(req: Request) -> None:
    if not is_authed(req):
        raise HTTPException(status_code=401, detail="unauthorized")


def parse_expire_days(days: Optional[str]) -> Optional[str]:
    if days is None or str(days).strip() == "":
        return None
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
        return max(0, (end - datetime.now(timezone.utc)).days)
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


def proxy_port() -> int:
    try:
        return int(setting("proxy_port", str(ENV_PROXY_PORT)))
    except Exception:
        return ENV_PROXY_PORT


def proxy_link(secret: str) -> str:
    return f"tg://proxy?server={proxy_host()}&port={proxy_port()}&secret={secret}"


def active_secrets() -> list[str]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM users WHERE enabled=1 ORDER BY id ASC").fetchall()
    return [row["secret"] for row in rows if is_not_expired(row["expire_at"])]


def render_proxy_service() -> None:
    secrets_list = active_secrets()
    service = Path("/etc/systemd/system/mtpulse.service")
    if not secrets_list:
        if service.exists():
            subprocess.run(["systemctl", "disable", "--now", "mtpulse"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return
    s_args = " ".join(f"-S {s}" for s in secrets_list)
    p_arg = f" -P {SPONSOR_TAG}" if SPONSOR_TAG else ""
    exec_start = (
        f"/usr/local/bin/mtproto-proxy -u nobody -p 8888 -H {proxy_port()} "
        f"{s_args}{p_arg} --aes-pwd /etc/mtpulse/proxy-secret /etc/mtpulse/proxy-multi.conf -M 1"
    )
    service.write_text(f"""[Unit]
Description=MTPulse/DELTA MTProto Proxy
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
    subprocess.run(["systemctl", "enable", "--now", "mtpulse"], check=False)
    subprocess.run(["systemctl", "restart", "mtpulse"], check=False)


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
    disk = psutil.disk_usage("/")
    mem = psutil.virtual_memory()
    net = psutil.net_io_counters()
    load1, load5, load15 = os.getloadavg()
    active = subprocess.run(["systemctl", "is-active", "mtpulse"], text=True, capture_output=True, check=False).stdout.strip()
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        enabled = conn.execute("SELECT COUNT(*) n FROM users WHERE enabled=1").fetchone()["n"]
        used = conn.execute("SELECT COALESCE(SUM(used_gb),0) n FROM users").fetchone()["n"]
        quota = conn.execute("SELECT COALESCE(SUM(quota_gb),0) n FROM users").fetchone()["n"]
    return {"cpu": psutil.cpu_percent(interval=0.1), "load": [load1, load5, load15], "cores": psutil.cpu_count(), "ram_percent": mem.percent, "ram_total": mem.total, "ram_used": mem.used, "disk_percent": disk.percent, "disk_total": disk.total, "disk_used": disk.used, "rx": net.bytes_recv, "tx": net.bytes_sent, "proxy_status": active or "inactive", "users_total": total, "users_enabled": enabled, "quota_total": quota, "used_total": used, "public_host": proxy_host(), "proxy_port": proxy_port(), "uptime_seconds": int(datetime.now().timestamp() - psutil.boot_time())}


@app.get("/api/users")
def users(req: Request):
    require(req)
    with db() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()]
    for row in rows:
        row["link"] = proxy_link(row["secret"])
        row["expired"] = not is_not_expired(row.get("expire_at"))
        row["days_left"] = days_left(row.get("expire_at"))
        q = float(row.get("quota_gb") or 0)
        u = float(row.get("used_gb") or 0)
        row["usage_percent"] = 0 if q <= 0 else min(100, round((u / q) * 100, 1))
    return rows


@app.post("/api/users")
def add_user(req: Request, name: str = Form(...), expire_days: Optional[str] = Form(None), quota_gb: float = Form(0), note: str = Form("")):
    require(req)
    if not name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    expire_at = parse_expire_days(expire_days)
    secret = secrets.token_hex(16)
    with db() as conn:
        conn.execute("INSERT INTO users(name, secret, enabled, expire_at, quota_gb, used_gb, note, created_at) VALUES (?,?,?,?,?,?,?,?)", (name.strip(), secret, 1, expire_at, max(0, quota_gb), 0, note.strip(), now_iso()))
        conn.commit()
    render_proxy_service()
    return {"ok": True, "secret": secret, "link": proxy_link(secret)}


@app.post("/api/users/{uid}/update")
def update_user(uid: int, req: Request, name: str = Form(...), expire_days: Optional[str] = Form(None), quota_gb: float = Form(0), used_gb: float = Form(0), note: str = Form(""), enabled: int = Form(1)):
    require(req)
    if not name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    expire_at = parse_expire_days(expire_days)
    with db() as conn:
        conn.execute("UPDATE users SET name=?, expire_at=?, quota_gb=?, used_gb=?, note=?, enabled=? WHERE id=?", (name.strip(), expire_at, max(0, quota_gb), max(0, used_gb), note.strip(), 1 if enabled else 0, uid))
        conn.commit()
    render_proxy_service()
    return {"ok": True}


@app.post("/api/users/{uid}/toggle")
def toggle(uid: int, req: Request):
    require(req)
    with db() as conn:
        conn.execute("UPDATE users SET enabled=CASE enabled WHEN 1 THEN 0 ELSE 1 END WHERE id=?", (uid,))
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
    return {"public_host": proxy_host(), "proxy_port": proxy_port(), "admin_username": setting("admin_username", ADMIN_USERNAME), "panel_title": setting("panel_title", "DELTA MTProto")}


@app.post("/api/settings/server")
def save_server(req: Request, public_host: str = Form(...), proxy_port_value: int = Form(...)):
    require(req)
    with db() as conn:
        set_setting(conn, "public_host", public_host.strip())
        set_setting(conn, "proxy_port", str(proxy_port_value))
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


@app.get("/api/backup/export")
def export_backup(req: Request):
    require(req)
    with db() as conn:
        data = {
            "version": 2,
            "created_at": now_iso(),
            "settings": {r["k"]: r["v"] for r in conn.execute("SELECT * FROM settings").fetchall()},
            "users": [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()],
        }
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": "attachment; filename=delta-mtproto-backup.json"})


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
            if k in {"public_host", "proxy_port", "panel_title", "admin_username", "admin_hash"}:
                set_setting(conn, k, str(v))
        conn.execute("DELETE FROM users")
        for u in users_data:
            conn.execute("INSERT INTO users(name, secret, enabled, expire_at, quota_gb, used_gb, note, created_at) VALUES (?,?,?,?,?,?,?,?)", (u.get("name", "user"), u.get("secret") or secrets.token_hex(16), int(u.get("enabled", 1)), u.get("expire_at"), float(u.get("quota_gb") or 0), float(u.get("used_gb") or 0), u.get("note", ""), u.get("created_at") or now_iso()))
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
    proc = subprocess.run(["journalctl", "-u", "mtpulse", "-n", "160", "--no-pager"], text=True, capture_output=True, check=False)
    return JSONResponse({"logs": proc.stdout[-20000:]})
