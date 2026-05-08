import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psutil
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

APP_DIR = Path(os.getenv("APP_DIR", "/opt/delta-proxy-panel"))
DB_PATH = Path(os.getenv("DB_PATH", str(APP_DIR / "delta.db")))
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "")
PROXY_PORT = int(os.getenv("PROXY_PORT", "443"))
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
        conn.execute("INSERT OR REPLACE INTO settings(k,v) VALUES (?,?)", ("admin_username", ADMIN_USERNAME))
        conn.execute("INSERT OR REPLACE INTO settings(k,v) VALUES (?,?)", ("admin_hash", pass_hash(ADMIN_PASSWORD)))
        conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_authed(req: Request) -> bool:
    token = req.cookies.get("delta_session", "")
    good = hmac.new(SECRET_KEY.encode(), b"login", hashlib.sha256).hexdigest()
    return hmac.compare_digest(token, good)


def require(req: Request) -> None:
    if not is_authed(req):
        raise HTTPException(status_code=401, detail="unauthorized")


def is_not_expired(expire_at: Optional[str]) -> bool:
    if not expire_at:
        return True
    try:
        return datetime.fromisoformat(expire_at.replace("Z", "+00:00")) > datetime.now(timezone.utc)
    except Exception:
        return True


def proxy_link(secret: str) -> str:
    return f"tg://proxy?server={PUBLIC_HOST}&port={PROXY_PORT}&secret={secret}"


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
        f"/usr/local/bin/mtproto-proxy -u nobody -p 8888 -H {PROXY_PORT} "
        f"{s_args}{p_arg} --aes-pwd /etc/mtpulse/proxy-secret /etc/mtpulse/proxy-multi.conf -M 1"
    )
    service.write_text(
        f"""[Unit]
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
"""
    )
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
        resp.set_cookie(
            "delta_session",
            hmac.new(SECRET_KEY.encode(), b"login", hashlib.sha256).hexdigest(),
            httponly=True,
            samesite="lax",
        )
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
    return {
        "cpu": psutil.cpu_percent(interval=0.1),
        "load": [load1, load5, load15],
        "cores": psutil.cpu_count(),
        "ram_percent": mem.percent,
        "ram_total": mem.total,
        "ram_used": mem.used,
        "disk_percent": disk.percent,
        "disk_total": disk.total,
        "disk_used": disk.used,
        "rx": net.bytes_recv,
        "tx": net.bytes_sent,
        "proxy_status": active or "inactive",
        "users_total": total,
        "users_enabled": enabled,
        "public_host": PUBLIC_HOST,
        "proxy_port": PROXY_PORT,
        "uptime_seconds": int(datetime.now().timestamp() - psutil.boot_time()),
    }


@app.get("/api/users")
def users(req: Request):
    require(req)
    with db() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()]
    for row in rows:
        row["link"] = proxy_link(row["secret"])
        row["expired"] = not is_not_expired(row.get("expire_at"))
    return rows


@app.post("/api/users")
def add_user(
    req: Request,
    name: str = Form(...),
    expire_at: Optional[str] = Form(None),
    quota_gb: float = Form(0),
    note: str = Form(""),
):
    require(req)
    if not name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    secret = secrets.token_hex(16)
    if expire_at == "":
        expire_at = None
    with db() as conn:
        conn.execute(
            "INSERT INTO users(name, secret, enabled, expire_at, quota_gb, note, created_at) VALUES (?,?,?,?,?,?,?)",
            (name.strip(), secret, 1, expire_at, quota_gb, note.strip(), now_iso()),
        )
        conn.commit()
    render_proxy_service()
    return {"ok": True, "secret": secret, "link": proxy_link(secret)}


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


@app.post("/api/proxy/restart")
def restart(req: Request):
    require(req)
    render_proxy_service()
    return {"ok": True}


@app.get("/api/proxy/logs")
def logs(req: Request):
    require(req)
    proc = subprocess.run(["journalctl", "-u", "mtpulse", "-n", "120", "--no-pager"], text=True, capture_output=True, check=False)
    return JSONResponse({"logs": proc.stdout[-16000:]})
