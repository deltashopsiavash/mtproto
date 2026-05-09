#!/usr/bin/env python3
import io, json, os, secrets, sqlite3, subprocess, time, threading, traceback
from datetime import datetime, date, timedelta
from functools import wraps
from pathlib import Path

import psutil
from flask import Flask, request, redirect, session, flash, render_template_string, send_file, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.serving import make_server

APP_DIR = Path('/opt/mtproto-panel')
ETC_DIR = Path('/etc/mtproto-panel')
DB_PATH = ETC_DIR / 'panel.db'
CONFIG_PATH = ETC_DIR / 'config.json'
MTPROXY_DIR = ETC_DIR / 'mtproxy'

app = Flask(__name__)
app.secret_key = os.environ.get('MTPANEL_SECRET_KEY', secrets.token_hex(32))

CSS = r'''
:root{--bg:#0f172a;--card:#111c33;--muted:#94a3b8;--txt:#e5e7eb;--acc:#38bdf8;--bad:#fb7185;--ok:#34d399;--warn:#fbbf24;--border:#25324a;--input:#0b1220}body.theme-light{--bg:#f4f7fb;--card:#fff;--muted:#64748b;--txt:#0f172a;--acc:#0284c7;--bad:#e11d48;--ok:#059669;--warn:#d97706;--border:#e2e8f0;--input:#f8fafc}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top right,rgba(56,189,248,.14),transparent 35%),linear-gradient(135deg,var(--bg),var(--bg));color:var(--txt);font-family:Tahoma,Arial,sans-serif;direction:rtl;min-height:100vh}.wrap{max-width:1200px;margin:0 auto;padding:18px}.nav{display:flex;gap:12px;align-items:center;justify-content:space-between;margin-bottom:18px;flex-wrap:wrap}.brand{font-size:21px;font-weight:900}.menu{display:flex;gap:8px;flex-wrap:wrap}.menu a,.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:9px 13px;border-radius:14px;text-decoration:none;background:var(--card);color:var(--txt);border:1px solid var(--border);cursor:pointer;min-height:40px}.icon-btn{width:36px;height:36px;min-height:36px;padding:0;font-size:17px;border-radius:12px}.menu a:hover,.btn:hover{border-color:var(--acc)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}.card{background:color-mix(in srgb,var(--card) 94%,transparent);border:1px solid var(--border);border-radius:22px;padding:16px;box-shadow:0 10px 28px rgba(0,0,0,.14)}.big{font-size:27px;font-weight:900;margin-top:7px}.muted{color:var(--muted);font-size:12px}.bar{height:10px;background:color-mix(in srgb,var(--muted) 25%,transparent);border-radius:20px;overflow:hidden;margin-top:9px}.bar span{display:block;height:100%;background:linear-gradient(90deg,#38bdf8,#34d399)}table{width:100%;border-collapse:collapse;background:var(--card);border-radius:18px;overflow:hidden}td,th{padding:10px;border-bottom:1px solid var(--border);text-align:right;vertical-align:top}th{color:var(--acc);font-size:13px}.table-wrap{width:100%;overflow-x:auto;border-radius:18px}.pill{padding:5px 9px;border-radius:999px;background:color-mix(in srgb,var(--muted) 18%,transparent);font-size:12px}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}input,select{width:100%;padding:11px;border-radius:13px;border:1px solid var(--border);background:var(--input);color:var(--txt);margin-top:6px}label{display:block;margin-bottom:12px}.actions{display:flex;gap:7px;flex-wrap:wrap}.danger{background:#3b1420;color:#fff}.flash{margin:10px 0;padding:12px;border-radius:14px;background:color-mix(in srgb,var(--acc) 18%,transparent);border:1px solid var(--border)}.login{max-width:420px;margin:8vh auto}.ltr{direction:ltr;text-align:left;font-family:monospace;font-size:12px;word-break:break-all}.copy-row{display:flex;gap:7px;align-items:center;margin:6px 0;direction:ltr}.copy-row code{flex:1;background:var(--input);border:1px solid var(--border);border-radius:11px;padding:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.copy-btn{font-size:12px;padding:7px 10px;min-height:32px}hr{border:0;border-top:1px solid var(--border);margin:16px 0}
.sub-page{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px;position:relative;overflow:hidden;font-family:Tahoma,Arial,sans-serif}.sub-page .particle{position:absolute;top:-10%;font-size:22px;opacity:.65;animation:fall linear infinite;pointer-events:none}.sub-page .bird{animation:fly linear infinite}.sub-page .wind{animation:drift linear infinite}.sub-page .rain{width:2px;height:22px;background:#dbeafe;border-radius:99px;opacity:.65}.sub-page .sand{width:7px;height:7px;border-radius:50%;background:#fde68a;opacity:.55}@keyframes fall{to{transform:translateY(120vh) rotate(360deg)}}@keyframes fly{to{transform:translateX(120vw) translateY(-30vh)}}@keyframes drift{to{transform:translateX(80vw) translateY(-20vh) rotate(220deg)}}.theme-rain{background:linear-gradient(135deg,#0f172a,#075985,#111827)}.theme-flower{background:linear-gradient(135deg,#fdf2f8,#f9a8d4,#fb7185)}.theme-bird{background:linear-gradient(135deg,#dbeafe,#60a5fa,#2563eb)}.theme-heart{background:linear-gradient(135deg,#4c0519,#be123c,#fb7185)}.theme-desert{background:linear-gradient(135deg,#78350f,#f59e0b,#fde68a)}.sub-card{width:min(520px,100%);background:rgba(255,255,255,.82);backdrop-filter:blur(18px);color:#182b2f;border-radius:24px;padding:18px;box-shadow:0 18px 48px rgba(0,0,0,.22);direction:rtl;position:relative;z-index:2}.sub-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.avatar{width:58px;height:58px;border-radius:50%;background:linear-gradient(135deg,#bfdbfe,#60a5fa);border:3px solid rgba(255,255,255,.8);flex:0 0 auto}.sub-name{font-size:22px;font-weight:900}.sub-box{margin-top:16px;background:rgba(255,255,255,.72);border:1px solid rgba(255,255,255,.5);border-radius:22px;padding:18px;text-align:center}.sub-title{font-size:22px;font-weight:900;margin-bottom:12px}.sub-stats{display:grid;grid-template-columns:1fr 1fr;gap:10px}.sub-num{font-size:26px;font-weight:900}.battery{height:28px;border-radius:9px;background:#263238;padding:4px;margin:9px auto 0;max-width:92px}.battery span{display:block;height:100%;border-radius:7px;background:#65a30d;transition:.3s}.percent{font-size:12px;color:#475569;margin-top:5px}.sub-link{margin-top:14px;background:#172033;color:white;border-radius:15px;padding:11px;direction:ltr;word-break:break-all;font-family:monospace;font-size:11px}.theme-dots{position:fixed;bottom:16px;left:0;right:0;display:flex;gap:12px;justify-content:center;z-index:4}.theme-dot{width:23px;height:23px;border-radius:50%;border:2px solid #fff;box-shadow:0 5px 18px #0005;cursor:pointer}.theme-dot:nth-child(1){background:linear-gradient(135deg,#0f172a,#38bdf8)}.theme-dot:nth-child(2){background:linear-gradient(135deg,#fdf2f8,#fb7185)}.theme-dot:nth-child(3){background:linear-gradient(135deg,#dbeafe,#2563eb)}.theme-dot:nth-child(4){background:linear-gradient(135deg,#4c0519,#fb7185)}.theme-dot:nth-child(5){background:linear-gradient(135deg,#78350f,#fde68a)}
@media(max-width:700px){.wrap{padding:11px}.brand{font-size:18px}.menu a,.btn{padding:8px 10px;font-size:13px}.grid{grid-template-columns:1fr}.card{border-radius:17px;padding:13px}td,th{padding:8px;font-size:12px}.copy-row{flex-direction:column;align-items:stretch}.copy-row code{white-space:normal}.table-wrap table{min-width:860px}.sub-card{padding:14px;border-radius:20px}.avatar{width:48px;height:48px}.sub-name{font-size:19px}.sub-box{padding:14px}.sub-title{font-size:19px}.sub-stats{grid-template-columns:1fr}.sub-num{font-size:23px}.sub-link{font-size:10px}.theme-dots{bottom:10px}}
'''


BASE = '''<!doctype html><html lang="fa"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MTProto Panel</title><style>{{css}}</style><script>function copyText(t,b){const done=()=>{let o=b.innerText;b.innerText='کپی شد ✓';setTimeout(()=>b.innerText=o,1200)}; if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(done).catch(()=>fallbackCopy(t,done))}else{fallbackCopy(t,done)}}function fallbackCopy(t,cb){let x=document.createElement('textarea');x.value=t;document.body.appendChild(x);x.select();document.execCommand('copy');x.remove();cb&&cb()}</script></head><body class="theme-{{theme}}"><div class="wrap"><div class="nav"><div class="brand">⚡ MTProto Panel</div>{% if session.get('auth') %}<div class="menu"><a href="/">Overview</a><a href="/users">کاربران</a><a href="/settings">تنظیمات</a><a href="/logout">خروج</a></div>{% endif %}</div>{% for m in get_flashed_messages() %}<div class="flash">{{m}}</div>{% endfor %}{{body|safe}}</div></body></html>'''

def sh(cmd, check=False):
    return subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)

def cfg():
    if not CONFIG_PATH.exists(): return {}
    return json.loads(CONFIG_PATH.read_text())

def save_cfg(c):
    ETC_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(c, ensure_ascii=False, indent=2))

def db():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; return conn

def add_col(con, table, col, spec):
    cols = [r['name'] for r in con.execute(f'pragma table_info({table})').fetchall()]
    if col not in cols: con.execute(f'alter table {table} add column {col} {spec}')

def init_db():
    ETC_DIR.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.execute('''create table if not exists users(id integer primary key autoincrement,username text unique not null,port integer unique not null,secret text not null,quota_gb real not null default 0,expires_at text not null,enabled integer not null default 1,created_at text not null,note text default '')''')
        add_col(con,'users','sub_token','text')
        add_col(con,'users','used_reset_bytes','integer not null default 0')
        rows = con.execute('select id from users where sub_token is null or sub_token=""').fetchall()
        for r in rows: con.execute('update users set sub_token=? where id=?', (secrets.token_urlsafe(16), r['id']))

def service_name(username):
    safe = ''.join(c for c in username if c.isalnum() or c in ('-', '_'))
    return f'mtproxy-user-{safe}.service'

def public_host():
    return cfg().get('server_host') or cfg().get('public_ip') or sh('curl -s --max-time 2 https://api.ipify.org || true').stdout.strip()

def proxy_link(row): return f"tg://proxy?server={public_host()}&port={row['port']}&secret={row['secret']}"

def sub_link(row):
    c=cfg(); host=public_host(); port=int(c.get('sub_port') or c.get('panel_port',8080)); return f"http://{host}:{port}/s/{row['sub_token']}"

def used_bytes_raw(port):
    # Real traffic counter per proxy port. Counts INPUT/OUTPUT bytes with iptables.
    # If counters are missing, they are created and current usage starts from now.
    try:
        ensure_traffic_rule(port)
    except Exception:
        pass
    total = 0
    patterns = [
        f"iptables -nvxL INPUT 2>/dev/null | awk '/mtptraffic-{port}-in/ {{s+=$2}} END{{print s+0}}'",
        f"iptables -nvxL OUTPUT 2>/dev/null | awk '/mtptraffic-{port}-out/ {{s+=$2}} END{{print s+0}}'",
        f"iptables-legacy -nvxL INPUT 2>/dev/null | awk '/mtptraffic-{port}-in/ {{s+=$2}} END{{print s+0}}'",
        f"iptables-legacy -nvxL OUTPUT 2>/dev/null | awk '/mtptraffic-{port}-out/ {{s+=$2}} END{{print s+0}}'",
        f"iptables-nft -nvxL INPUT 2>/dev/null | awk '/mtptraffic-{port}-in/ {{s+=$2}} END{{print s+0}}'",
        f"iptables-nft -nvxL OUTPUT 2>/dev/null | awk '/mtptraffic-{port}-out/ {{s+=$2}} END{{print s+0}}'",
    ]
    seen = []
    for cmd in patterns:
        out=(sh(cmd).stdout or '0').strip() or '0'
        try:
            val=int(float(out.splitlines()[-1] if out.splitlines() else 0))
            if val and val not in seen:
                total += val; seen.append(val)
        except Exception:
            pass
    return total

def used_bytes(row): return max(0, used_bytes_raw(row['port']) - int(row['used_reset_bytes'] or 0))

def fmt_bytes(n):
    n=float(n or 0)
    if n < 1024**2: return f"{n/1024:.2f} KB"
    if n < 1024**3: return f"{n/1024**2:.2f} MB"
    return f"{n/1024**3:.2f} GB"


def js_str(value):
    return json.dumps(str(value), ensure_ascii=False)

def online_count(port):
    out = sh(f"ss -Htan state established '( sport = :{port} )' 2>/dev/null | wc -l").stdout.strip()
    try: return int(out or 0)
    except ValueError: return 0

def ensure_traffic_rule(port):
    # Accounting-only rules; no accept/drop target, firewall behavior unchanged.
    for bin_name in ('iptables','iptables-legacy','iptables-nft'):
        if not sh(f"command -v {bin_name} >/dev/null 2>&1").returncode == 0:
            continue
        for proto in ('tcp','udp'):
            sh(f"{bin_name} -C INPUT -p {proto} --dport {port} -m comment --comment mtptraffic-{port}-in >/dev/null 2>&1 || {bin_name} -I INPUT 1 -p {proto} --dport {port} -m comment --comment mtptraffic-{port}-in >/dev/null 2>&1 || true")
            sh(f"{bin_name} -C OUTPUT -p {proto} --sport {port} -m comment --comment mtptraffic-{port}-out >/dev/null 2>&1 || {bin_name} -I OUTPUT 1 -p {proto} --sport {port} -m comment --comment mtptraffic-{port}-out >/dev/null 2>&1 || true")

def create_service(row):
    MTPROXY_DIR.mkdir(parents=True, exist_ok=True); ensure_traffic_rule(row['port'])
    unit = f'''[Unit]\nDescription=MTProto Proxy for {row['username']}\nAfter=network.target\n\n[Service]\nType=simple\nExecStart=/usr/local/bin/mtproto-proxy -u nobody -p {9000 + int(row['id'])} -H {row['port']} -S {row['secret']} --aes-pwd {MTPROXY_DIR}/proxy-secret {MTPROXY_DIR}/proxy-multi.conf -M 1\nRestart=always\nRestartSec=3\nLimitNOFILE=65535\n\n[Install]\nWantedBy=multi-user.target\n'''
    path = Path('/etc/systemd/system') / service_name(row['username']); path.write_text(unit)
    sh('systemctl daemon-reload'); sh(f'systemctl enable --now {path.name}')

def stop_service(username):
    svc=service_name(username); sh(f'systemctl disable --now {svc} >/dev/null 2>&1 || true')
    try: (Path('/etc/systemd/system')/svc).unlink()
    except FileNotFoundError: pass
    sh('systemctl daemon-reload')

def enforce_limits():
    today=date.today().isoformat()
    with db() as con:
        for r in con.execute('select * from users where enabled=1').fetchall():
            expired = r['expires_at'] < today
            over = r['quota_gb'] > 0 and used_bytes(r) >= int(r['quota_gb']*1024**3)
            if expired or over:
                con.execute('update users set enabled=0 where id=?',(r['id'],)); stop_service(r['username'])

def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get('auth'): return redirect('/login')
        enforce_limits(); return fn(*a, **kw)
    return wrapper

def api_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        token = request.headers.get('X-API-Token') or request.args.get('token')
        if not token or token != cfg().get('api_token'): return jsonify({'ok':False,'error':'unauthorized'}), 401
        enforce_limits(); return fn(*a, **kw)
    return wrapper

def page(body): return render_template_string(BASE, body=body, css=CSS, theme=cfg().get('theme','dark'))

@app.route('/login', methods=['GET','POST'])
def login():
    c=cfg()
    if request.method=='POST':
        if request.form.get('username') == c.get('admin_username') and check_password_hash(c.get('admin_password_hash',''), request.form.get('password','')):
            session['auth']=True; return redirect('/')
        flash('یوزرنیم یا پسورد اشتباه است.')
    return page('<div class="login card"><h2>ورود به پنل</h2><form method="post"><label>یوزرنیم<input name="username" required></label><label>پسورد<input name="password" type="password" required></label><button class="btn">ورود</button></form></div>')

@app.route('/logout')
def logout(): session.clear(); return redirect('/login')

@app.route('/')
@login_required
def overview():
    vm=psutil.virtual_memory(); du=psutil.disk_usage('/'); cpu=psutil.cpu_percent(interval=.2)
    with db() as con:
        rows=con.execute('select * from users').fetchall(); total=len(rows); active=sum(1 for r in rows if r['enabled']); online=sum(online_count(r['port']) for r in rows if r['enabled'])
    c=cfg(); uptime=int(time.time()-psutil.boot_time())
    body=render_template_string('''<h2>Overview</h2><div class="grid"><div class="card"><div class="muted">CPU</div><div class="big">{{cpu}}%</div><div class="bar"><span style="width:{{cpu}}%"></span></div></div><div class="card"><div class="muted">RAM</div><div class="big">{{ram}}%</div><div class="muted">{{ram_used}} / {{ram_total}} GB</div><div class="bar"><span style="width:{{ram}}%"></span></div></div><div class="card"><div class="muted">Disk</div><div class="big">{{disk}}%</div><div class="muted">{{disk_used}} / {{disk_total}} GB</div><div class="bar"><span style="width:{{disk}}%"></span></div></div><div class="card"><div class="muted">آنلاین‌های لحظه‌ای</div><div class="big ok">{{online}}</div></div><div class="card"><div class="muted">Users</div><div class="big">{{active}} / {{total}}</div><div class="muted">فعال / کل</div></div><div class="card"><div class="muted">Panel/Sub Port</div><div class="big">{{port}} / {{sub}}</div></div><div class="card"><div class="muted">Server Host</div><div class="big" style="font-size:18px">{{host}}</div></div><div class="card"><div class="muted">Uptime</div><div class="big">{{uptime_h}}h</div></div></div>''', cpu=cpu, ram=vm.percent, ram_used=round(vm.used/1024**3,2), ram_total=round(vm.total/1024**3,2), disk=du.percent, disk_used=round(du.used/1024**3,2), disk_total=round(du.total/1024**3,2), online=online, active=active,total=total,port=c.get('panel_port'),sub=c.get('sub_port',c.get('panel_port')),host=public_host(),uptime_h=uptime//3600)
    return page(body)

@app.route('/users')
@login_required
def users():
    with db() as con: rows=con.execute('select * from users order by id desc').fetchall()
    body='<div class="actions"><a class="btn" href="/users/new">+ ساخت کاربر جدید</a></div><br><div class="table-wrap"><table><tr><th>کاربر</th><th>پورت</th><th>آنلاین</th><th>حجم</th><th>مصرف واقعی</th><th>انقضا</th><th>وضعیت</th><th>لینک‌ها</th><th>عملیات</th></tr>'
    for r in rows:
        used=used_bytes(r); quota='نامحدود' if r['quota_gb']==0 else f"{r['quota_gb']} GB"; status='<span class="ok">فعال</span>' if r['enabled'] else '<span class="bad">غیرفعال</span>'
        pl=proxy_link(r); sl=sub_link(r)
        links = f"""<div class=\"copy-row\"><code>{pl}</code><button type=\"button\" class=\"btn copy-btn\" onclick='copyText({js_str(pl)},this)'>کپی پروکسی</button></div><div class=\"copy-row\"><code>{sl}</code><button type=\"button\" class=\"btn copy-btn\" onclick='copyText({js_str(sl)},this)'>کپی ساب</button></div>"""
        toggle_icon = '🚫' if r['enabled'] else '✅'
        body += f"""<tr><td>{r['username']}</td><td>{r['port']}</td><td><span class=\"pill\">{online_count(r['port'])}</span></td><td>{quota}</td><td>{fmt_bytes(used)}</td><td>{r['expires_at']}</td><td>{status}</td><td>{links}</td><td><div class=\"actions\"><a class=\"btn icon-btn\" title=\"ویرایش\" href=\"/users/{r['id']}/edit\">✏️</a><a class=\"btn icon-btn\" title=\"فعال/غیرفعال\" href=\"/users/{r['id']}/toggle\">{toggle_icon}</a><a class=\"btn icon-btn danger\" title=\"حذف\" href=\"/users/{r['id']}/delete\" onclick=\"return confirm('حذف شود؟')\">🗑️</a></div></td></tr>"""
    return page(body+'</table></div>')

@app.route('/users/new', methods=['GET','POST'])
@login_required
def new_user():
    all_ports=[int(p.strip()) for p in cfg().get('proxy_ports','').split(',') if p.strip().isdigit()]
    with db() as con:
        used_ports={int(x['port']) for x in con.execute('select port from users').fetchall()}
    ports=[p for p in all_ports if p not in used_ports]
    if request.method=='POST':
        try:
            username=request.form['username'].strip()
            port=int(request.form['port'])
            quota=float(request.form.get('quota_gb') or 0)
            days=int(request.form.get('expiry_days') or 30)
            expires=(date.today()+timedelta(days=days)).isoformat()
            mode=request.form.get('secret_mode','auto')
            manual=(request.form.get('secret') or '').strip()
            secret = manual if mode == 'manual' and manual else secrets.token_hex(16)
            if not username: raise ValueError('نام کاربر خالی است')
            if port in used_ports: raise ValueError('این پورت قبلاً استفاده شده است')
            with db() as con:
                con.execute('insert into users(username,port,secret,quota_gb,expires_at,enabled,created_at,note,sub_token,used_reset_bytes) values(?,?,?,?,?,1,?,?,?,?)',(username,port,secret,quota,expires,datetime.utcnow().isoformat(),request.form.get('note',''),secrets.token_urlsafe(16),used_bytes_raw(port)))
                row=con.execute('select * from users where username=?',(username,)).fetchone()
            create_service(row); flash('کاربر و پروکسی اختصاصی ساخته شد.')
            return redirect('/users')
        except Exception as e:
            flash('خطا در ساخت پروکسی: '+str(e))
    return page(render_template_string('''<div class="card"><h2>ساخت کاربر جدید</h2><form method="post"><label>نام کاربر<input name="username" required pattern="[A-Za-z0-9_-]+"></label><label>پورت پروکسی<select name="port">{% for p in ports %}<option value="{{p}}">{{p}}</option>{% endfor %}</select></label><label>Secret<select name="secret_mode"><option value="auto">خودکار بساز</option><option value="manual">دستی وارد می‌کنم</option></select></label><label>Secret دستی، فقط اگر حالت دستی را انتخاب کردی<input name="secret" placeholder="مثلا 32 کاراکتر hex"></label><label>حجم GB، صفر یعنی نامحدود<input name="quota_gb" type="number" step="0.001" value="0"></label><label>مدت اعتبار به روز، مثلا 30 یعنی 30 روز<input name="expiry_days" type="number" min="1" value="30" required></label><label>یادداشت<input name="note"></label><button class="btn">ساخت پروکسی</button></form>{% if not ports %}<p class="bad">هیچ پورت آزادی باقی نمانده. از Settings/نصب، پورت‌های بیشتری اضافه کن.</p>{% endif %}</div>''', ports=ports))

@app.route('/users/<int:uid>/edit', methods=['GET','POST'])
@login_required
def edit_user(uid):
    with db() as con: r=con.execute('select * from users where id=?',(uid,)).fetchone()
    if not r: return redirect('/users')
    if request.method=='POST':
        old_secret=r['secret']; quota=float(request.form.get('quota_gb') or 0); days=int(request.form.get('expiry_days') or 30); expires=(date.today()+timedelta(days=days)).isoformat(); note=request.form.get('note',''); enabled=1 if request.form.get('enabled')=='on' else 0; secret=(request.form.get('secret') or old_secret).strip(); reset_usage=1 if request.form.get('reset_usage')=='on' else 0; reset_base=used_bytes_raw(r['port']) if reset_usage else r['used_reset_bytes']
        with db() as con:
            con.execute('update users set secret=?, quota_gb=?, expires_at=?, note=?, enabled=?, used_reset_bytes=? where id=?',(secret,quota,expires,note,enabled,reset_base,uid)); nr=con.execute('select * from users where id=?',(uid,)).fetchone()
        if enabled: create_service(nr)
        else: stop_service(nr['username'])
        flash('اطلاعات کاربر بروزرسانی شد.'); return redirect('/users')
    return page(render_template_string('''<div class="card"><h2>ویرایش کاربر {{r['username']}}</h2><form method="post"><label>Secret<input name="secret" value="{{r['secret']}}"></label><label>حجم GB، صفر یعنی نامحدود<input name="quota_gb" type="number" step="0.001" value="{{r['quota_gb']}}"></label><label>تمدید/تنظیم اعتبار از امروز به تعداد روز<input name="expiry_days" type="number" min="1" value="30"></label><div class="muted">تاریخ انقضای فعلی: {{r['expires_at']}}</div><br><label>یادداشت<input name="note" value="{{r['note'] or ''}}"></label><label><input style="width:auto" type="checkbox" name="reset_usage"> صفر کردن مصرف فعلی</label><label><input style="width:auto" type="checkbox" name="enabled" {% if r['enabled'] %}checked{% endif %}> فعال باشد</label><button class="btn">ذخیره تغییرات</button></form></div>''', r=r))

@app.route('/settings', methods=['GET','POST'])
@login_required
def settings():
    c=cfg()
    if request.method=='POST':
        action=request.form.get('action')
        if action=='account':
            if request.form.get('admin_username','').strip(): c['admin_username']=request.form.get('admin_username').strip()
            if request.form.get('admin_password'): c['admin_password_hash']=generate_password_hash(request.form.get('admin_password'))
            save_cfg(c); flash('اطلاعات ورود پنل ذخیره شد.')
        elif action=='server':
            c['server_host']=request.form.get('server_host','').strip(); c['sub_port']=int(request.form.get('sub_port') or c.get('panel_port',8080)); c['theme']=request.form.get('theme','dark'); save_cfg(c); flash('تنظیمات سرور/تم ذخیره شد. برای تغییر پورت ساب، سرویس را ریستارت کن یا mtp-update بزن.')
        elif action=='api':
            c['api_token']=request.form.get('api_token','').strip() or secrets.token_urlsafe(24); c['telegram_bot_token']=request.form.get('telegram_bot_token','').strip(); save_cfg(c); flash('API تلگرام بات ذخیره شد.')
        return redirect('/settings')
    body=render_template_string('''<h2>تنظیمات</h2><div class="grid"><div class="card"><h3>ورود پنل</h3><form method="post"><input type="hidden" name="action" value="account"><label>نام کاربری پنل<input name="admin_username" value="{{c.get('admin_username','')}}"></label><label>رمز جدید، اگر خالی بماند تغییر نمی‌کند<input name="admin_password" type="password"></label><button class="btn">ذخیره</button></form></div><div class="card"><h3>سرور و ظاهر</h3><form method="post"><input type="hidden" name="action" value="server"><label>دامنه یا IP برای لینک‌ها<input name="server_host" value="{{host}}"></label><label>پورت ساب لینک<input name="sub_port" type="number" value="{{c.get('sub_port', c.get('panel_port',8080))}}"></label><label>تم<select name="theme"><option value="dark" {% if c.get('theme','dark')=='dark' %}selected{% endif %}>Dark حرفه‌ای</option><option value="light" {% if c.get('theme')=='light' %}selected{% endif %}>Light حرفه‌ای</option></select></label><button class="btn">ذخیره سرور</button></form></div><div class="card"><h3>API تلگرام بات</h3><form method="post"><input type="hidden" name="action" value="api"><label>Telegram Bot Token<input name="telegram_bot_token" value="{{c.get('telegram_bot_token','')}}"></label><label>API Token<input name="api_token" value="{{c.get('api_token','')}}" placeholder="خالی بماند خودکار ساخته می‌شود"></label><button class="btn">ذخیره API</button></form><hr><div class="muted ltr">GET /api/users?token=API_TOKEN<br>GET /api/user/USERNAME?token=API_TOKEN</div></div><div class="card"><h3>Backup</h3><p class="muted">بکاپ شامل تنظیمات پنل و همه کاربران/پروکسی‌هاست.</p><div class="actions"><a class="btn" href="/settings/backup/export">دانلود بکاپ</a></div><hr><form method="post" action="/settings/backup/import" enctype="multipart/form-data"><label>Import backup JSON<input type="file" name="backup" accept="application/json" required></label><button class="btn danger" onclick="return confirm('ایمپورت، کاربران فعلی را جایگزین می‌کند. ادامه می‌دهید؟')">ایمپورت بکاپ</button></form></div></div>''', c=c, host=public_host())
    return page(body)

@app.route('/settings/backup/export')
@login_required
def export_backup():
    with db() as con: users=[dict(x) for x in con.execute('select * from users order by id').fetchall()]
    data={'version':2,'created_at':datetime.utcnow().isoformat(),'config':cfg(),'users':users}
    b=io.BytesIO(json.dumps(data,ensure_ascii=False,indent=2).encode())
    return send_file(b,mimetype='application/json',as_attachment=True,download_name='mtproto-panel-backup.json')

@app.route('/settings/backup/import', methods=['POST'])
@login_required
def import_backup():
    f=request.files.get('backup')
    if not f: flash('فایل بکاپ انتخاب نشده است.'); return redirect('/settings')
    data=json.loads(f.read().decode()); users=data.get('users',[]); new_cfg=data.get('config') or {}
    if new_cfg:
        current=cfg(); current.update(new_cfg); save_cfg(current)
    with db() as con:
        for r in con.execute('select username from users').fetchall(): stop_service(r['username'])
        con.execute('delete from users')
        for u in users:
            con.execute('insert into users(username,port,secret,quota_gb,expires_at,enabled,created_at,note,sub_token,used_reset_bytes) values(?,?,?,?,?,?,?,?,?,?)',(u['username'],int(u['port']),u['secret'],float(u.get('quota_gb') or 0),u.get('expires_at') or date.today().isoformat(),int(u.get('enabled',1)),u.get('created_at') or datetime.utcnow().isoformat(),u.get('note',''),u.get('sub_token') or secrets.token_urlsafe(16),int(u.get('used_reset_bytes') or 0)))
        rows=con.execute('select * from users where enabled=1').fetchall()
    for r in rows: create_service(r)
    flash('بکاپ ایمپورت شد.'); return redirect('/users')

@app.route('/users/<int:uid>/toggle')
@login_required
def toggle(uid):
    with db() as con:
        r=con.execute('select * from users where id=?',(uid,)).fetchone()
        if not r: return redirect('/users')
        new=0 if r['enabled'] else 1; con.execute('update users set enabled=? where id=?',(new,uid))
    if new: create_service({**dict(r),'enabled':1})
    else: stop_service(r['username'])
    return redirect('/users')

@app.route('/users/<int:uid>/delete')
@login_required
def delete(uid):
    with db() as con:
        r=con.execute('select * from users where id=?',(uid,)).fetchone()
        if r: stop_service(r['username']); con.execute('delete from users where id=?',(uid,))
    return redirect('/users')

@app.route('/s/<token>')
def subscription(token):
    enforce_limits()
    with db() as con: r=con.execute('select * from users where sub_token=?',(token,)).fetchone()
    if not r: return 'Not found',404
    used=used_bytes(r)
    quota_bytes=int(r['quota_gb']*1024**3) if r['quota_gb'] else 0
    remain=max(0, quota_bytes-used) if quota_bytes else 0
    days=max(0,(datetime.fromisoformat(r['expires_at']).date()-date.today()).days)
    total_days=max(1,(datetime.fromisoformat(r['expires_at']).date()-datetime.fromisoformat(r['created_at']).date()).days) if r['created_at'] else 30
    used_percent=0 if not quota_bytes else min(100, round((used/quota_bytes)*100,1))
    remain_percent=100 if not quota_bytes else max(0, round((remain/quota_bytes)*100,1))
    day_percent=max(0, min(100, round(days*100/total_days,1)))
    day_used_percent=max(0, round(100-day_percent,1))
    title=f"{r['username']}"
    link=proxy_link(r)
    return render_template_string('''<!doctype html><html lang="fa"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{r['username']}}</title><style>{{css}}</style><script>
function copyText(t,b){const done=()=>{let o=b.innerText;b.innerText='کپی شد ✓';setTimeout(()=>b.innerText=o,1200)}; if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(done).catch(()=>fallbackCopy(t,done))}else{fallbackCopy(t,done)}}
function fallbackCopy(t,cb){let x=document.createElement('textarea');x.value=t;document.body.appendChild(x);x.select();document.execCommand('copy');x.remove();cb&&cb()}
const maps={rain:['rain','',45],flower:['particle','🌸',26],bird:['particle bird','🕊️',18],heart:['particle','💗',28],desert:['sand wind','',42]};
function particles(kind){let page=document.querySelector('.sub-page');page.querySelectorAll('.particle,.rain,.sand').forEach(e=>e.remove());let m=maps[kind];for(let i=0;i<m[2];i++){let e=document.createElement('span');e.className=m[0];e.textContent=m[1];e.style.left=(Math.random()*105-5)+'vw';e.style.animationDuration=(5+Math.random()*9)+'s';e.style.animationDelay=(-Math.random()*8)+'s';e.style.fontSize=(14+Math.random()*18)+'px';if(kind==='bird'){e.style.top=(20+Math.random()*70)+'vh';e.style.left='-8vw'}page.appendChild(e)}}
function setSubTheme(t){let page=document.querySelector('.sub-page');page.className='sub-page theme-'+t;localStorage.setItem('mtp_sub_theme',t);particles(t)}
window.addEventListener('load',()=>setSubTheme(localStorage.getItem('mtp_sub_theme')||'rain'));
</script></head><body><div class="sub-page theme-rain"><div class="sub-card"><div class="sub-head"><div style="display:flex;gap:10px;align-items:center"><div class="avatar"></div><div><div class="sub-name">{{title}}</div><div class="muted">Port {{r['port']}} · آنلاین {{online}}</div></div></div><div class="pill">وضعیت</div></div><div class="sub-box"><div class="sub-title">مانده سرویس</div><div class="sub-stats"><div><div><span class="sub-num">{{days}}</span> روز</div><div class="battery"><span style="width:{{day_percent}}%"></span></div><div class="percent">{{day_percent}}٪ مانده · {{day_used_percent}}٪ گذشته</div></div><div><div><span class="sub-num">{{remain_text}}</span></div><div class="battery"><span style="width:{{remain_percent}}%"></span></div><div class="percent">{{remain_percent}}٪ مانده · {{used_percent}}٪ مصرف شده</div></div></div><div class="sub-link">{{link}}</div><br><button class="btn" onclick='copyText({{link_js}},this)'>کپی لینک پروکسی</button></div></div><div class="theme-dots"><button class="theme-dot" onclick="setSubTheme('rain')" title="باران"></button><button class="theme-dot" onclick="setSubTheme('flower')" title="گل"></button><button class="theme-dot" onclick="setSubTheme('bird')" title="پرنده"></button><button class="theme-dot" onclick="setSubTheme('heart')" title="قلب"></button><button class="theme-dot" onclick="setSubTheme('desert')" title="صحرا"></button></div></div></body></html>''', css=CSS, r=r, online=online_count(r['port']), title=title, days=days, remain_text=('∞' if not quota_bytes else fmt_bytes(remain)), used_percent=used_percent, remain_percent=remain_percent, day_percent=day_percent, day_used_percent=day_used_percent, link=link, link_js=js_str(link))

@app.route('/api/users')
@api_required
def api_users():
    with db() as con: rows=con.execute('select * from users order by id desc').fetchall()
    return jsonify({'ok':True,'users':[api_user_dict(r) for r in rows]})

def api_user_dict(r):
    used=used_bytes(r); quota=int(r['quota_gb']*1024**3) if r['quota_gb'] else 0
    return {'username':r['username'],'port':r['port'],'enabled':bool(r['enabled']),'online':online_count(r['port']),'used_bytes':used,'used_human':fmt_bytes(used),'quota_gb':r['quota_gb'],'remaining_bytes':(max(0,quota-used) if quota else None),'expires_at':r['expires_at'],'proxy_link':proxy_link(r),'sub_link':sub_link(r)}

@app.route('/api/user/<username>')
@api_required
def api_user(username):
    with db() as con: r=con.execute('select * from users where username=?',(username,)).fetchone()
    if not r: return jsonify({'ok':False,'error':'not_found'}),404
    return jsonify({'ok':True,'user':api_user_dict(r)})

if __name__ == '__main__':
    init_db(); c=cfg(); host=c.get('panel_host','0.0.0.0'); panel=int(c.get('panel_port',8080)); sub=int(c.get('sub_port') or panel)
    if sub != panel:
        srv = make_server(host, sub, app)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    app.run(host=host, port=panel)
