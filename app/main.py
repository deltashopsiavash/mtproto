import base64, hashlib, hmac, os, secrets, sqlite3, subprocess, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psutil
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

APP_DIR = Path(os.getenv('APP_DIR', '/opt/delta-proxy-panel'))
DB_PATH = os.getenv('DB_PATH', str(APP_DIR / 'delta.db'))
PUBLIC_HOST = os.getenv('PUBLIC_HOST', '')
PROXY_PORT = int(os.getenv('PROXY_PORT', '443'))
SPONSOR_TAG = os.getenv('SPONSOR_TAG', '').strip()
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = base64.b64decode(os.getenv('ADMIN_PASSWORD_B64', '').encode() or b'').decode(errors='ignore')
SECRET_KEY = hashlib.sha256((ADMIN_USERNAME + ADMIN_PASSWORD + str(APP_DIR)).encode()).hexdigest()

app = FastAPI(title='DELTA PROXY PANEL')
app.mount('/static', StaticFiles(directory=str(Path(__file__).parent / 'static')), name='static')

def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.execute('create table if not exists settings (k text primary key, v text)')
        c.execute('''create table if not exists users (
            id integer primary key autoincrement,
            name text not null,
            secret text not null unique,
            enabled integer not null default 1,
            expire_at text,
            quota_gb real default 0,
            used_gb real default 0,
            note text,
            created_at text not null
        )''')
        c.execute('insert or replace into settings(k,v) values (?,?)', ('admin_username', ADMIN_USERNAME))
        c.execute('insert or replace into settings(k,v) values (?,?)', ('admin_hash', pass_hash(ADMIN_PASSWORD)))
        c.commit()

def pass_hash(pw):
    return hashlib.sha256(('delta:'+pw).encode()).hexdigest()

def is_authed(req: Request):
    token = req.cookies.get('delta_session','')
    good = hmac.new(SECRET_KEY.encode(), b'login', hashlib.sha256).hexdigest()
    return hmac.compare_digest(token, good)

def require(req: Request):
    if not is_authed(req):
        raise HTTPException(401, 'unauthorized')

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def is_not_expired(exp):
    if not exp: return True
    try:
        return datetime.fromisoformat(exp.replace('Z','+00:00')) > datetime.now(timezone.utc)
    except Exception:
        return True

def proxy_link(secret):
    return f'tg://proxy?server={PUBLIC_HOST}&port={PROXY_PORT}&secret={secret}'

def active_secrets():
    with db() as c:
        rows = c.execute('select * from users where enabled=1').fetchall()
    return [r['secret'] for r in rows if is_not_expired(r['expire_at'])]

def render_proxy_service():
    secrets_list = active_secrets()
    service = Path('/etc/systemd/system/mtpulse.service')
    if not secrets_list:
        if service.exists():
            subprocess.run(['systemctl','disable','--now','mtpulse'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    s_args = ' '.join(f'-S {s}' for s in secrets_list)
    p_arg = f' -P {SPONSOR_TAG}' if SPONSOR_TAG else ''
    # Exactly MTPulse style: official binary, host systemd, -u nobody -p 8888 -H PORT -S SECRET --aes-pwd ... -M 1
    exec_start = f'/usr/local/bin/mtproto-proxy -u nobody -p 8888 -H {PROXY_PORT} {s_args}{p_arg} --aes-pwd /etc/mtpulse/proxy-secret /etc/mtpulse/proxy-multi.conf -M 1'
    service.write_text(f'''[Unit]\nDescription=MTPulse/DELTA MTProto Proxy\nAfter=network-online.target\nWants=network-online.target\n\n[Service]\nType=simple\nExecStart={exec_start}\nRestart=always\nRestartSec=3\nLimitNOFILE=65536\n\n[Install]\nWantedBy=multi-user.target\n''')
    subprocess.run(['systemctl','daemon-reload'], check=False)
    subprocess.run(['systemctl','enable','--now','mtpulse'], check=False)
    subprocess.run(['systemctl','restart','mtpulse'], check=False)

@app.on_event('startup')
def startup(): init_db()

@app.get('/', response_class=HTMLResponse)
def index(req: Request):
    page = 'panel.html' if is_authed(req) else 'login.html'
    return (Path(__file__).parent / 'static' / page).read_text()

@app.post('/api/login')
def login(username: str = Form(...), password: str = Form(...)):
    with db() as c:
        u = c.execute('select v from settings where k="admin_username"').fetchone()['v']
        h = c.execute('select v from settings where k="admin_hash"').fetchone()['v']
    if username == u and pass_hash(password) == h:
        r = RedirectResponse('/', status_code=303)
        r.set_cookie('delta_session', hmac.new(SECRET_KEY.encode(), b'login', hashlib.sha256).hexdigest(), httponly=True, samesite='lax')
        return r
    return RedirectResponse('/?err=1', status_code=303)

@app.post('/api/logout')
def logout():
    r=RedirectResponse('/',303); r.delete_cookie('delta_session'); return r

@app.get('/api/overview')
def overview(req: Request):
    require(req)
    disk=psutil.disk_usage('/')
    mem=psutil.virtual_memory()
    net=psutil.net_io_counters()
    active = subprocess.run(['systemctl','is-active','mtpulse'], text=True, capture_output=True).stdout.strip()
    with db() as c:
        total=c.execute('select count(*) n from users').fetchone()['n']
        enabled=c.execute('select count(*) n from users where enabled=1').fetchone()['n']
    return dict(cpu=psutil.cpu_percent(), ram_percent=mem.percent, ram_total=mem.total, disk_percent=disk.percent, disk_total=disk.total, rx=net.bytes_recv, tx=net.bytes_sent, proxy_status=active or 'inactive', users_total=total, users_enabled=enabled, public_host=PUBLIC_HOST, proxy_port=PROXY_PORT)

@app.get('/api/users')
def users(req: Request):
    require(req)
    with db() as c:
        rows=[dict(r) for r in c.execute('select * from users order by id desc').fetchall()]
    for r in rows: r['link']=proxy_link(r['secret'])
    return rows

@app.post('/api/users')
def add_user(req: Request, name: str = Form(...), expire_at: Optional[str] = Form(None), quota_gb: float = Form(0), note: str = Form('')):
    require(req)
    secret = secrets.token_hex(16)  # same MTPulse format: 16 random bytes hex
    if expire_at == '': expire_at = None
    with db() as c:
        c.execute('insert into users(name,secret,enabled,expire_at,quota_gb,note,created_at) values (?,?,?,?,?,?,?)', (name, secret, 1, expire_at, quota_gb, note, now_iso()))
        c.commit()
    render_proxy_service()
    return {'ok': True, 'secret': secret, 'link': proxy_link(secret)}

@app.post('/api/users/{uid}/toggle')
def toggle(uid:int, req: Request):
    require(req)
    with db() as c:
        c.execute('update users set enabled=case enabled when 1 then 0 else 1 end where id=?',(uid,)); c.commit()
    render_proxy_service(); return {'ok':True}

@app.post('/api/users/{uid}/delete')
def delete(uid:int, req: Request):
    require(req)
    with db() as c:
        c.execute('delete from users where id=?',(uid,)); c.commit()
    render_proxy_service(); return {'ok':True}

@app.post('/api/proxy/restart')
def restart(req: Request):
    require(req); render_proxy_service(); return {'ok': True}

@app.get('/api/proxy/logs')
def logs(req: Request):
    require(req)
    p=subprocess.run(['journalctl','-u','mtpulse','-n','80','--no-pager'], text=True, capture_output=True)
    return JSONResponse({'logs': p.stdout[-12000:]})
