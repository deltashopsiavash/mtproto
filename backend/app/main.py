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
from .proxy import gen_secret, container_name, reload_shared_proxy, inspect_proxy, container_traffic_bytes, link, PROXY_PORT

Base.metadata.create_all(bind=engine)
app = FastAPI(title="DELTA PROXY PANEL", version="1.0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

PUBLIC_HOST = os.getenv("PUBLIC_HOST", "")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

@app.on_event("startup")
def startup():
    """Create or reset the admin user from .env on every container start.

This avoids the common reinstall problem where the SQLite database keeps the
old admin password, while the installer has written a new ADMIN_PASSWORD.
"""
    db = next(get_db())
    try:
        admin = db.query(Admin).filter(Admin.username == ADMIN_USERNAME).first()
        if admin:
            admin.password_hash = hash_password(ADMIN_PASSWORD)
        else:
            admin = Admin(username=ADMIN_USERNAME, password_hash=hash_password(ADMIN_PASSWORD))
            db.add(admin)
        # Keep only the configured admin to avoid confusion after reinstall.
        for other in db.query(Admin).filter(Admin.username != ADMIN_USERNAME).all():
            db.delete(other)
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

def reload_all(db: Session):
    users = db.query(ProxyUser).all()
    return reload_shared_proxy(users)

def serialize(u: ProxyUser):
    status = inspect_proxy(u)
    host = PUBLIC_HOST or socket.gethostbyname(socket.gethostname())
    expired = bool(u.expires_at and u.expires_at < datetime.utcnow())
    # In single-port/multi-secret mode the official MTProxy does not expose reliable per-secret traffic counters.
    limited = False
    return {
        "id": u.id, "name": u.name, "secret": u.secret, "port": PROXY_PORT,
        "active": u.active, "status": status["status"], "container_id": status["id"],
        "traffic_limit_bytes": u.traffic_limit_bytes, "traffic_used_bytes": u.traffic_used_bytes,
        "expires_at": u.expires_at.isoformat() if u.expires_at else None,
        "expired": expired, "limited": limited, "sponsor_tag": u.sponsor_tag,
        "link": link(host, PROXY_PORT, u.secret)
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
        "proxy_port": PROXY_PORT,
        "port_range": str(PROXY_PORT),
        "shared_proxy_traffic_bytes": container_traffic_bytes(),
        "traffic_supported_per_user": False,
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
    port = PROXY_PORT
    u = ProxyUser(
        name=data.name, secret=gen_secret(), port=port,
        traffic_limit_bytes=int(data.traffic_limit_gb * 1024**3) if data.traffic_limit_gb else 0,
        expires_at=datetime.utcnow() + timedelta(days=data.expires_days) if data.expires_days else None,
        sponsor_tag=data.sponsor_tag, container_name=container_name(data.name), active=True
    )
    db.add(u); db.commit(); db.refresh(u)
    reload_all(db)
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
        reload_all(db)
    if data.active is not None:
        u.active = data.active
        reload_all(db)
    db.commit(); db.refresh(u)
    return serialize(u)

@app.post("/api/users/{uid}/restart")
def restart_user(uid: int, _: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(ProxyUser, uid)
    if not u: raise HTTPException(404, "Not found")
    reload_all(db); return serialize(u)

@app.post("/api/users/{uid}/reset-traffic")
def reset_traffic(uid: int, _: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(ProxyUser, uid)
    if not u: raise HTTPException(404, "Not found")
    u.traffic_used_bytes = 0
    if u.active: reload_all(db)
    db.commit(); return serialize(u)

@app.delete("/api/users/{uid}")
def delete_user(uid: int, _: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(ProxyUser, uid)
    if not u: raise HTTPException(404, "Not found")
    db.delete(u); db.commit(); reload_all(db); return {"ok": True}

@app.post("/api/enforce")
def enforce(_: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    changed = []
    for u in db.query(ProxyUser).all():
        s = serialize(u)
        if u.active and (s["expired"] or s["limited"]):
            u.active = False; changed.append(u.name)
    db.commit()
    if changed: reload_all(db)
    return {"disabled": changed}

# lightweight automatic enforcement loop: disables expired or over-quota users
import threading, time

def _enforcer_loop():
    while True:
        time.sleep(60)
        db = next(get_db())
        try:
            changed = False
            for u in db.query(ProxyUser).all():
                expired = bool(u.expires_at and u.expires_at < datetime.utcnow())
                if u.active and expired:
                    u.active = False
                    changed = True
            db.commit()
            if changed:
                reload_shared_proxy(db.query(ProxyUser).all())
        except Exception:
            db.rollback()
        finally:
            db.close()

threading.Thread(target=_enforcer_loop, daemon=True).start()
