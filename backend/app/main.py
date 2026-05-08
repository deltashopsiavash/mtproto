import os, socket, subprocess
from datetime import datetime, timedelta
from typing import Optional
import psutil
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func
from .db import Base, engine, get_db
from .models import Admin, ProxyUser
from .security import hash_password, verify_password, create_token, current_admin
from .proxy import gen_secret, container_name, start_proxy, stop_proxy, remove_proxy, inspect_proxy, container_traffic_bytes, link, PORT_START, PORT_END

Base.metadata.create_all(bind=engine)
app = FastAPI(title="MTProto Full Panel", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

PUBLIC_HOST = os.getenv("PUBLIC_HOST", "")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

@app.on_event("startup")
def startup():
    db = next(get_db())
    try:
        if not db.query(Admin).first():
            db.add(Admin(username=ADMIN_USERNAME, password_hash=hash_password(ADMIN_PASSWORD)))
            db.commit()
    finally:
        db.close()

class LoginIn(BaseModel):
    username: str
    password: str

class UserIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    traffic_limit_gb: float = 0
    expires_days: int = 30
    sponsor_tag: Optional[str] = None
    port: Optional[int] = None

class UserPatch(BaseModel):
    active: Optional[bool] = None
    traffic_limit_gb: Optional[float] = None
    expires_days: Optional[int] = None
    sponsor_tag: Optional[str] = None

@app.post("/api/auth/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    admin = db.query(Admin).filter(Admin.username == data.username).first()
    if not admin or not verify_password(data.password, admin.password_hash):
        raise HTTPException(401, "Wrong username or password")
    return {"access_token": create_token(admin.username), "token_type": "bearer"}

def choose_port(db: Session) -> int:
    used = {x[0] for x in db.query(ProxyUser.port).all()}
    for p in range(PORT_START, PORT_END + 1):
        if p not in used:
            return p
    raise HTTPException(400, "No free ports")

def serialize(u: ProxyUser):
    used = container_traffic_bytes(u)
    u.traffic_used_bytes = max(int(u.traffic_used_bytes or 0), used)
    status = inspect_proxy(u)
    host = PUBLIC_HOST or socket.gethostbyname(socket.gethostname())
    expired = bool(u.expires_at and u.expires_at < datetime.utcnow())
    limited = bool(u.traffic_limit_bytes and u.traffic_used_bytes >= u.traffic_limit_bytes)
    return {
        "id": u.id, "name": u.name, "secret": u.secret, "port": u.port,
        "active": u.active, "status": status["status"], "container_id": status["id"],
        "traffic_limit_bytes": u.traffic_limit_bytes, "traffic_used_bytes": u.traffic_used_bytes,
        "expires_at": u.expires_at.isoformat() if u.expires_at else None,
        "expired": expired, "limited": limited, "sponsor_tag": u.sponsor_tag,
        "link": link(host, u.port, u.secret)
    }

@app.get("/api/overview")
def overview(_: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    du = psutil.disk_usage('/')
    net = psutil.net_io_counters()
    users = db.query(ProxyUser).all()
    active = 0
    for u in users:
        info = inspect_proxy(u)
        if info["status"] == "running" and u.active:
            active += 1
    return {
        "hostname": socket.gethostname(),
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "cpu_count": psutil.cpu_count(),
        "ram_total": psutil.virtual_memory().total,
        "ram_used": psutil.virtual_memory().used,
        "disk_total": du.total,
        "disk_used": du.used,
        "net_sent": net.bytes_sent,
        "net_recv": net.bytes_recv,
        "users_total": len(users),
        "users_active": active,
        "public_host": PUBLIC_HOST,
        "port_range": f"{PORT_START}-{PORT_END}",
        "now": datetime.utcnow().isoformat()
    }

@app.get("/api/users")
def list_users(_: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    out = [serialize(u) for u in db.query(ProxyUser).order_by(ProxyUser.id.desc()).all()]
    db.commit()
    return out

@app.post("/api/users")
def create_user(data: UserIn, _: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    if db.query(ProxyUser).filter(ProxyUser.name == data.name).first():
        raise HTTPException(400, "User exists")
    port = data.port or choose_port(db)
    if port < 1 or port > 65535:
        raise HTTPException(400, "Bad port")
    if db.query(ProxyUser).filter(ProxyUser.port == port).first():
        raise HTTPException(400, "Port already used")
    u = ProxyUser(
        name=data.name, secret=gen_secret(), port=port,
        traffic_limit_bytes=int(data.traffic_limit_gb * 1024**3) if data.traffic_limit_gb else 0,
        expires_at=datetime.utcnow() + timedelta(days=data.expires_days) if data.expires_days else None,
        sponsor_tag=data.sponsor_tag, container_name=container_name(data.name), active=True
    )
    db.add(u); db.commit(); db.refresh(u)
    start_proxy(u)
    return serialize(u)

@app.patch("/api/users/{uid}")
def update_user(uid: int, data: UserPatch, _: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(ProxyUser, uid)
    if not u: raise HTTPException(404, "Not found")
    if data.traffic_limit_gb is not None:
        u.traffic_limit_bytes = int(data.traffic_limit_gb * 1024**3) if data.traffic_limit_gb else 0
    if data.expires_days is not None:
        u.expires_at = datetime.utcnow() + timedelta(days=data.expires_days) if data.expires_days else None
    if data.sponsor_tag is not None:
        u.sponsor_tag = data.sponsor_tag or None
        if u.active: start_proxy(u)
    if data.active is not None:
        u.active = data.active
        start_proxy(u) if u.active else stop_proxy(u)
    db.commit(); db.refresh(u)
    return serialize(u)

@app.post("/api/users/{uid}/restart")
def restart_user(uid: int, _: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(ProxyUser, uid)
    if not u: raise HTTPException(404, "Not found")
    start_proxy(u); return serialize(u)

@app.post("/api/users/{uid}/reset-traffic")
def reset_traffic(uid: int, _: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(ProxyUser, uid)
    if not u: raise HTTPException(404, "Not found")
    u.traffic_used_bytes = 0
    if u.active: start_proxy(u)
    db.commit(); return serialize(u)

@app.delete("/api/users/{uid}")
def delete_user(uid: int, _: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(ProxyUser, uid)
    if not u: raise HTTPException(404, "Not found")
    remove_proxy(u); db.delete(u); db.commit(); return {"ok": True}

@app.post("/api/enforce")
def enforce(_: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    changed = []
    for u in db.query(ProxyUser).all():
        s = serialize(u)
        if u.active and (s["expired"] or s["limited"]):
            u.active = False; stop_proxy(u); changed.append(u.name)
    db.commit()
    return {"disabled": changed}

# lightweight automatic enforcement loop: disables expired or over-quota users
import threading, time

def _enforcer_loop():
    while True:
        time.sleep(60)
        db = next(get_db())
        try:
            for u in db.query(ProxyUser).all():
                used = container_traffic_bytes(u)
                u.traffic_used_bytes = max(int(u.traffic_used_bytes or 0), int(used or 0))
                expired = bool(u.expires_at and u.expires_at < datetime.utcnow())
                limited = bool(u.traffic_limit_bytes and u.traffic_used_bytes >= u.traffic_limit_bytes)
                if u.active and (expired or limited):
                    u.active = False
                    stop_proxy(u)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

threading.Thread(target=_enforcer_loop, daemon=True).start()
