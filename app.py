#!/usr/bin/env python3
import json, os, secrets, sqlite3, subprocess, time
from datetime import datetime, date
from functools import wraps
from pathlib import Path

import psutil
from flask import Flask, request, redirect, session, url_for, flash, render_template_string
from werkzeug.security import check_password_hash, generate_password_hash

APP_DIR = Path('/opt/mtproto-panel')
ETC_DIR = Path('/etc/mtproto-panel')
DB_PATH = ETC_DIR / 'panel.db'
CONFIG_PATH = ETC_DIR / 'config.json'
MTPROXY_DIR = ETC_DIR / 'mtproxy'

app = Flask(__name__)
app.secret_key = os.environ.get('MTPANEL_SECRET_KEY', secrets.token_hex(32))

CSS = r'''
:root{--bg:#0f172a;--card:#111c33;--muted:#94a3b8;--txt:#e5e7eb;--acc:#38bdf8;--bad:#fb7185;--ok:#34d399;--warn:#fbbf24}*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#0f172a,#111827);color:var(--txt);font-family:Tahoma,Arial,sans-serif;direction:rtl}.wrap{max-width:1180px;margin:0 auto;padding:24px}.nav{display:flex;gap:12px;align-items:center;justify-content:space-between;margin-bottom:22px}.brand{font-size:22px;font-weight:800}.menu a,.btn{display:inline-block;padding:10px 14px;border-radius:14px;text-decoration:none;background:#1f2937;color:var(--txt);border:1px solid #334155}.menu a:hover,.btn:hover{border-color:var(--acc)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}.card{background:rgba(17,28,51,.85);border:1px solid #25324a;border-radius:22px;padding:18px;box-shadow:0 10px 30px rgba(0,0,0,.25)}.big{font-size:28px;font-weight:800;margin-top:8px}.muted{color:var(--muted);font-size:13px}.bar{height:9px;background:#263449;border-radius:20px;overflow:hidden;margin-top:10px}.bar span{display:block;height:100%;background:linear-gradient(90deg,#38bdf8,#34d399)}table{width:100%;border-collapse:collapse;background:rgba(17,28,51,.8);border-radius:20px;overflow:hidden}td,th{padding:12px;border-bottom:1px solid #25324a;text-align:right}th{color:#bae6fd}.pill{padding:5px 9px;border-radius:999px;background:#1f2937;font-size:12px}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}input,select{width:100%;padding:12px;border-radius:14px;border:1px solid #334155;background:#0b1220;color:var(--txt);margin-top:6px}label{display:block;margin-bottom:12px}.actions{display:flex;gap:8px;flex-wrap:wrap}.danger{background:#3b1420}.flash{margin:10px 0;padding:12px;border-radius:14px;background:#172554}.login{max-width:420px;margin:8vh auto}.ltr{direction:ltr;text-align:left;font-family:monospace;font-size:12px;word-break:break-all}
'''

BASE = '''<!doctype html><html lang="fa"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MTProto Panel</title><style>{{css}}</style></head><body><div class="wrap"><div class="nav"><div class="brand">⚡ MTProto Panel</div>{% if session.get('auth') %}<div class="menu"><a href="/">Overview</a><a href="/users">کاربران</a><a href="/logout">خروج</a></div>{% endif %}</div>{% for m in get_flashed_messages() %}<div class="flash">{{m}}</div>{% endfor %}{{body|safe}}</div></body></html>'''

def sh(cmd, check=False):
    return subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)

def cfg():
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text())

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    ETC_DIR.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.execute('''create table if not exists users(
            id integer primary key autoincrement,
            username text unique not null,
            port integer unique not null,
            secret text not null,
            quota_gb real not null default 0,
            expires_at text not null,
            enabled integer not null default 1,
            created_at text not null,
            note text default ''
        )''')

def service_name(username):
    safe = ''.join(c for c in username if c.isalnum() or c in ('-', '_'))
    return f'mtproxy-user-{safe}.service'

def proxy_link(row):
    public_ip = cfg().get('public_ip') or sh("curl -s --max-time 2 https://api.ipify.org || true").stdout.strip()
    return f"tg://proxy?server={public_ip}&port={row['port']}&secret={row['secret']}"

def used_bytes(port):
    # Requires root/systemd service. Counters survive until iptables rules are reset.
    out = sh(f"iptables -L INPUT -v -n -x | awk '$8==\"dpt:{port}\" {{print $2; exit}}'").stdout.strip()
    try: return int(out or 0)
    except ValueError: return 0

def ensure_traffic_rule(port):
    sh(f"iptables -C INPUT -p tcp --dport {port} -j ACCEPT >/dev/null 2>&1 || iptables -A INPUT -p tcp --dport {port} -j ACCEPT")

def create_service(row):
    MTPROXY_DIR.mkdir(parents=True, exist_ok=True)
    ensure_traffic_rule(row['port'])
    unit = f'''[Unit]\nDescription=MTProto Proxy for {row['username']}\nAfter=network.target\n\n[Service]\nType=simple\nExecStart=/usr/local/bin/mtproto-proxy -u nobody -p {9000 + int(row['id'])} -H {row['port']} -S {row['secret']} --aes-pwd {MTPROXY_DIR}/proxy-secret {MTPROXY_DIR}/proxy-multi.conf -M 1\nRestart=always\nRestartSec=3\nLimitNOFILE=65535\n\n[Install]\nWantedBy=multi-user.target\n'''
    path = Path('/etc/systemd/system') / service_name(row['username'])
    path.write_text(unit)
    sh('systemctl daemon-reload')
    sh(f'systemctl enable --now {path.name}')

def stop_service(username):
    svc = service_name(username)
    sh(f'systemctl disable --now {svc} >/dev/null 2>&1 || true')
    try: (Path('/etc/systemd/system') / svc).unlink()
    except FileNotFoundError: pass
    sh('systemctl daemon-reload')

def enforce_limits():
    today = date.today().isoformat()
    with db() as con:
        rows = con.execute('select * from users where enabled=1').fetchall()
        for r in rows:
            expired = r['expires_at'] < today
            over = r['quota_gb'] > 0 and used_bytes(r['port']) >= int(r['quota_gb'] * 1024**3)
            if expired or over:
                con.execute('update users set enabled=0 where id=?', (r['id'],))
                stop_service(r['username'])

def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get('auth'):
            return redirect('/login')
        enforce_limits()
        return fn(*a, **kw)
    return wrapper

def page(body):
    return render_template_string(BASE, body=body, css=CSS)

@app.route('/login', methods=['GET','POST'])
def login():
    c = cfg()
    if request.method == 'POST':
        if request.form.get('username') == c.get('admin_username') and check_password_hash(c.get('admin_password_hash',''), request.form.get('password','')):
            session['auth'] = True
            return redirect('/')
        flash('یوزرنیم یا پسورد اشتباه است.')
    return page(render_template_string('''<div class="login card"><h2>ورود به پنل</h2><form method="post"><label>یوزرنیم<input name="username" required></label><label>پسورد<input name="password" type="password" required></label><button class="btn">ورود</button></form></div>'''))

@app.route('/logout')
def logout():
    session.clear(); return redirect('/login')

@app.route('/')
@login_required
def overview():
    vm = psutil.virtual_memory(); du = psutil.disk_usage('/'); cpu = psutil.cpu_percent(interval=.2)
    with db() as con:
        total = con.execute('select count(*) c from users').fetchone()['c']
        active = con.execute('select count(*) c from users where enabled=1').fetchone()['c']
    uptime = int(time.time() - psutil.boot_time())
    body = render_template_string('''<h2>Overview</h2><div class="grid">
    <div class="card"><div class="muted">CPU</div><div class="big">{{cpu}}%</div><div class="bar"><span style="width:{{cpu}}%"></span></div></div>
    <div class="card"><div class="muted">RAM</div><div class="big">{{ram}}%</div><div class="muted">{{ram_used}} / {{ram_total}} GB</div><div class="bar"><span style="width:{{ram}}%"></span></div></div>
    <div class="card"><div class="muted">Disk</div><div class="big">{{disk}}%</div><div class="muted">{{disk_used}} / {{disk_total}} GB</div><div class="bar"><span style="width:{{disk}}%"></span></div></div>
    <div class="card"><div class="muted">Uptime</div><div class="big">{{uptime_h}}h</div></div>
    <div class="card"><div class="muted">Users</div><div class="big">{{active}} / {{total}}</div><div class="muted">فعال / کل</div></div>
    <div class="card"><div class="muted">Panel Port</div><div class="big">{{port}}</div></div></div>''', cpu=cpu, ram=vm.percent, ram_used=round(vm.used/1024**3,2), ram_total=round(vm.total/1024**3,2), disk=du.percent, disk_used=round(du.used/1024**3,2), disk_total=round(du.total/1024**3,2), uptime_h=uptime//3600, active=active, total=total, port=cfg().get('panel_port'))
    return page(body)

@app.route('/users')
@login_required
def users():
    with db() as con:
        rows = con.execute('select * from users order by id desc').fetchall()
    body = '''<div class="actions"><a class="btn" href="/users/new">+ ساخت کاربر جدید</a></div><br><table><tr><th>کاربر</th><th>پورت</th><th>حجم</th><th>مصرف</th><th>انقضا</th><th>وضعیت</th><th>لینک</th><th>عملیات</th></tr>'''
    for r in rows:
        used_gb = round(used_bytes(r['port'])/1024**3, 3)
        status = '<span class="ok">فعال</span>' if r['enabled'] else '<span class="bad">غیرفعال</span>'
        body += f'''<tr><td>{r['username']}</td><td>{r['port']}</td><td>{r['quota_gb']} GB</td><td>{used_gb} GB</td><td>{r['expires_at']}</td><td>{status}</td><td class="ltr">{proxy_link(r)}</td><td><div class="actions"><a class="btn" href="/users/{r['id']}/toggle">فعال/غیرفعال</a><a class="btn danger" href="/users/{r['id']}/delete" onclick="return confirm('حذف شود؟')">حذف</a></div></td></tr>'''
    body += '</table>'
    return page(body)

@app.route('/users/new', methods=['GET','POST'])
@login_required
def new_user():
    ports = [int(p.strip()) for p in cfg().get('proxy_ports','').split(',') if p.strip().isdigit()]
    if request.method == 'POST':
        username = request.form['username'].strip()
        port = int(request.form['port'])
        quota = float(request.form.get('quota_gb') or 0)
        expires = request.form['expires_at']
        secret = secrets.token_hex(16)
        with db() as con:
            con.execute('insert into users(username,port,secret,quota_gb,expires_at,enabled,created_at,note) values(?,?,?,?,?,1,?,?)', (username, port, secret, quota, expires, datetime.utcnow().isoformat(), request.form.get('note','')))
            row = con.execute('select * from users where username=?', (username,)).fetchone()
        create_service(row)
        flash('کاربر و پروکسی اختصاصی ساخته شد.')
        return redirect('/users')
    return page(render_template_string('''<div class="card"><h2>ساخت کاربر جدید</h2><form method="post"><label>نام کاربر<input name="username" required pattern="[A-Za-z0-9_-]+"></label><label>پورت پروکسی<select name="port">{% for p in ports %}<option value="{{p}}">{{p}}</option>{% endfor %}</select></label><label>حجم GB، صفر یعنی نامحدود<input name="quota_gb" type="number" step="0.1" value="0"></label><label>تاریخ انقضا<input name="expires_at" type="date" required></label><label>یادداشت<input name="note"></label><button class="btn">ساخت پروکسی</button></form></div>''', ports=ports))

@app.route('/users/<int:uid>/toggle')
@login_required
def toggle(uid):
    with db() as con:
        r = con.execute('select * from users where id=?', (uid,)).fetchone()
        if not r: return redirect('/users')
        new = 0 if r['enabled'] else 1
        con.execute('update users set enabled=? where id=?', (new, uid))
    if new: create_service({**dict(r), 'enabled': 1})
    else: stop_service(r['username'])
    return redirect('/users')

@app.route('/users/<int:uid>/delete')
@login_required
def delete(uid):
    with db() as con:
        r = con.execute('select * from users where id=?', (uid,)).fetchone()
        if r:
            stop_service(r['username'])
            con.execute('delete from users where id=?', (uid,))
    return redirect('/users')

if __name__ == '__main__':
    init_db()
    c = cfg()
    app.run(host=c.get('panel_host','0.0.0.0'), port=int(c.get('panel_port',8080)))
