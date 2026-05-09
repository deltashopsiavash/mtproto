from fastapi import FastAPI, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import os, time, secrets, psutil, subprocess
from pathlib import Path
from .config import APP_DIR, DATA_DIR, BACKUP_DIR, load_env, save_env
from .db import init_db, db, now_ts, log
from .proxy import make_secret, mtproto_link, public_host, restart_proxy, disable_exhausted, is_valid_user
from .backup import create_backup_zip, list_backups, restore_backup
from .bot import start_bot_thread

app = FastAPI(title="Delta MTProto Panel")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", secrets.token_hex(32)))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

def fmt_bytes(n):
    n = int(n or 0)
    if n >= 1024**3: return f"{n/1024**3:.2f} GB"
    if n >= 1024**2: return f"{n/1024**2:.2f} MB"
    if n >= 1024: return f"{n/1024:.2f} KB"
    return f"{n} B"

def require_login(request):
    if not request.session.get("login"):
        raise HTTPException(status_code=401, detail="login required")

@app.on_event("startup")
def startup():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    disable_exhausted()
    start_bot_thread()

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not request.session.get("login"):
        return RedirectResponse("/login")
    return FileResponse(str(Path(__file__).parent / "templates" / "panel.html"))

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return FileResponse(str(Path(__file__).parent / "templates" / "login.html"))

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    env = load_env()
    if username == env.get("PANEL_USER") and password == env.get("PANEL_PASS"):
        request.session["login"] = True
        return RedirectResponse("/", status_code=302)
    return RedirectResponse("/login?err=1", status_code=302)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")

@app.get("/api/me")
def api_me(request: Request):
    require_login(request)
    env = load_env()
    return {"username": env.get("PANEL_USER"), "proxy_port": env.get("PROXY_PORT"), "sub_port": env.get("SUB_PORT")}

@app.get("/api/overview")
def overview(request: Request):
    require_login(request)
    vm = psutil.virtual_memory()
    du = psutil.disk_usage("/")
    disable_exhausted()
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        active = conn.execute("SELECT COUNT(*) c FROM users WHERE active=1").fetchone()["c"]
    return {
        "cpu": psutil.cpu_percent(),
        "ram_percent": vm.percent,
        "ram_used": fmt_bytes(vm.used),
        "ram_total": fmt_bytes(vm.total),
        "disk_percent": du.percent,
        "disk_used": fmt_bytes(du.used),
        "disk_total": fmt_bytes(du.total),
        "users_total": total,
        "users_active": active,
        "uptime": int(time.time() - psutil.boot_time())
    }

def user_json(r, request=None):
    env = load_env()
    host = env.get("PUBLIC_HOST") or public_host(request)
    port = env.get("PROXY_PORT", "8800")
    sub_port = env.get("SUB_PORT", "2096")
    limit = int(r["limit_bytes"] or 0)
    used = int(r["used_bytes"] or 0)
    return {
        "id": r["id"], "name": r["name"], "secret": r["secret"],
        "limit_bytes": limit, "used_bytes": used,
        "limit": "نامحدود" if not limit else fmt_bytes(limit),
        "used": fmt_bytes(used),
        "remaining": "نامحدود" if not limit else fmt_bytes(max(0, limit-used)),
        "expire_at": r["expire_at"], "active": bool(r["active"]),
        "link": mtproto_link(host, port, r["secret"]),
        "sub_link": f"http://{host}:{sub_port}/s/{r['sub_token']}",
        "valid": is_valid_user(r)
    }

@app.get("/api/users")
def list_users(request: Request):
    require_login(request)
    disable_exhausted()
    with db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    return [user_json(r, request) for r in rows]

@app.post("/api/users")
def create_user(request: Request, name: str = Form(...), days: int = Form(30), volume: float = Form(0), unit: str = Form("GB")):
    require_login(request)
    name = "".join(ch for ch in name.strip() if ch.isalnum() or ch in "_-")[:32]
    if not name: raise HTTPException(400, "bad name")
    limit = 0
    if volume > 0:
        limit = int(volume * (1024**3 if unit.upper()=="GB" else 1024**2))
    expire = 0 if days <= 0 else now_ts() + days*86400
    ts = now_ts()
    with db() as conn:
        conn.execute("INSERT INTO users(name,secret,limit_bytes,used_bytes,expire_at,active,sub_token,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     (name, make_secret(), limit, 0, expire, 1, secrets.token_hex(16), ts, ts))
    restart_proxy()
    return {"ok": True}

@app.post("/api/users/{uid}")
def update_user(request: Request, uid: int, name: str = Form(None), days: int = Form(None), volume: float = Form(None), unit: str = Form("GB"), active: int = Form(None), used_gb: float = Form(None)):
    require_login(request)
    updates=[]; vals=[]
    if name is not None:
        clean = "".join(ch for ch in name.strip() if ch.isalnum() or ch in "_-")[:32]
        updates.append("name=?"); vals.append(clean)
    if days is not None:
        exp = 0 if days <= 0 else now_ts() + int(days)*86400
        updates.append("expire_at=?"); vals.append(exp)
    if volume is not None:
        lim = 0 if volume <= 0 else int(float(volume) * (1024**3 if unit.upper()=="GB" else 1024**2))
        updates.append("limit_bytes=?"); vals.append(lim)
    if used_gb is not None:
        updates.append("used_bytes=?"); vals.append(int(float(used_gb)*1024**3))
    if active is not None:
        updates.append("active=?"); vals.append(1 if int(active) else 0)
    updates.append("updated_at=?"); vals.append(now_ts())
    vals.append(uid)
    with db() as conn:
        conn.execute(f"UPDATE users SET {','.join(updates)} WHERE id=?", vals)
    restart_proxy()
    return {"ok": True}

@app.delete("/api/users/{uid}")
def delete_user(request: Request, uid: int):
    require_login(request)
    with db() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
    restart_proxy()
    return {"ok": True}

@app.post("/api/users/{uid}/reset")
def reset_user(request: Request, uid: int):
    require_login(request)
    with db() as conn:
        conn.execute("UPDATE users SET used_bytes=0, active=1, updated_at=? WHERE id=?", (now_ts(), uid))
    restart_proxy()
    return {"ok": True}

@app.get("/api/settings")
def get_settings(request: Request):
    require_login(request)
    env = load_env()
    safe = {k:v for k,v in env.items() if k != "PANEL_PASS"}
    return safe

@app.post("/api/settings")
def set_settings(request: Request, panel_user: str = Form(None), panel_pass: str = Form(None), public_host: str = Form(None), bot_token: str = Form(None), bot_admin_id: str = Form(None), proxy_port: int = Form(None), sub_port: int = Form(None)):
    require_login(request)
    data = {}
    if panel_user: data["PANEL_USER"] = panel_user
    if panel_pass: data["PANEL_PASS"] = panel_pass
    if public_host is not None: data["PUBLIC_HOST"] = public_host
    if bot_token is not None: data["BOT_TOKEN"] = bot_token
    if bot_admin_id is not None: data["BOT_ADMIN_ID"] = bot_admin_id
    if proxy_port: data["PROXY_PORT"] = proxy_port
    if sub_port: data["SUB_PORT"] = sub_port
    save_env(data)
    restart_proxy()
    return {"ok": True}

@app.get("/api/backup/download")
def backup_download(request: Request):
    require_login(request)
    path = create_backup_zip()
    return FileResponse(str(path), filename=path.name, media_type="application/zip")

@app.get("/api/backups")
def backups(request: Request):
    require_login(request)
    return list_backups()

@app.post("/api/backup/import")
def backup_import(request: Request, file: UploadFile = File(...)):
    require_login(request)
    restore_backup(file.file)
    restart_proxy()
    return {"ok": True}

@app.get("/api/restart")
def api_restart(request: Request):
    require_login(request)
    restart_proxy()
    return {"ok": True}

@app.get("/s/{token}", response_class=HTMLResponse)
def public_sub(token: str, request: Request):
    disable_exhausted()
    with db() as conn:
        r = conn.execute("SELECT * FROM users WHERE sub_token=?", (token,)).fetchone()
    if not r:
        return HTMLResponse("Not Found", status_code=404)
    u = user_json(r, request)
    html = (Path(__file__).parent / "templates" / "sub.html").read_text()
    for k, v in u.items():
        html = html.replace("{{"+k+"}}", str(v))
    days = "نامحدود"
    if r["expire_at"]:
        days = str(max(0, int((r["expire_at"] - now_ts())/86400)))
    html = html.replace("{{days_left}}", days)
    return HTMLResponse(html)
