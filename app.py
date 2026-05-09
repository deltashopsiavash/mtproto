#!/usr/bin/env python3
import io, json, os, secrets, sqlite3, subprocess, time, threading
from datetime import datetime, date, timedelta
from functools import wraps
from pathlib import Path
import psutil
from flask import Flask, request, redirect, session, flash, render_template_string, send_file, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.serving import make_server

APP_DIR=Path('/opt/mtproto-panel'); ETC_DIR=Path('/etc/mtproto-panel'); DB_PATH=ETC_DIR/'panel.db'; CONFIG_PATH=ETC_DIR/'config.json'; MTPROXY_DIR=ETC_DIR/'mtproxy'
app=Flask(__name__); app.secret_key=os.environ.get('MTPANEL_SECRET_KEY', secrets.token_hex(32))

def sh(cmd, check=False): return subprocess.run(cmd,shell=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=check)
def cfg():
    if not CONFIG_PATH.exists(): return {}
    return json.loads(CONFIG_PATH.read_text())
def save_cfg(c): ETC_DIR.mkdir(parents=True,exist_ok=True); CONFIG_PATH.write_text(json.dumps(c,ensure_ascii=False,indent=2))
def db():
    con=sqlite3.connect(DB_PATH); con.row_factory=sqlite3.Row; return con
def add_col(con,t,c,s):
    cols=[r['name'] for r in con.execute(f'pragma table_info({t})').fetchall()]
    if c not in cols: con.execute(f'alter table {t} add column {c} {s}')
def shared_proxy_port():
    c=cfg();
    if c.get('shared_proxy_port'): return int(c['shared_proxy_port'])
    ps=[int(x.strip()) for x in str(c.get('proxy_ports','')).split(',') if x.strip().isdigit()]
    return ps[0] if ps else int(c.get('proxy_port',443))
def public_host(): return cfg().get('server_host') or cfg().get('public_ip') or sh('curl -s --max-time 2 https://api.ipify.org || true').stdout.strip()
def quota_bytes(r):
    try: return int(r['quota_bytes'] or 0)
    except Exception: return int(float(r['quota_gb'] or 0)*1024**3)
def proxy_link(r): return f"tg://proxy?server={public_host()}&port={shared_proxy_port()}&secret={r['secret']}"
def sub_link(r):
    c=cfg(); return f"http://{public_host()}:{int(c.get('sub_port') or c.get('panel_port',8080))}/s/{r['sub_token']}"
def fmt_bytes(n):
    n=float(n or 0)
    if n<1024**2: return f'{n/1024:.2f} KB'
    if n<1024**3: return f'{n/1024**2:.2f} MB'
    return f'{n/1024**3:.2f} GB'
def js(x): return json.dumps(str(x),ensure_ascii=False)
def online_count(port):
    try: return int((sh(f"ss -Htan state established '( sport = :{port} )' 2>/dev/null | wc -l").stdout or 0))
    except Exception: return 0

def ensure_traffic_rule(port):
    for b in ('iptables','iptables-legacy','iptables-nft'):
        if sh(f'command -v {b} >/dev/null 2>&1').returncode: continue
        for proto in ('tcp','udp'):
            sh(f"{b} -C INPUT -p {proto} --dport {port} -m comment --comment mtptraffic-{port}-in >/dev/null 2>&1 || {b} -I INPUT 1 -p {proto} --dport {port} -m comment --comment mtptraffic-{port}-in >/dev/null 2>&1 || true")
            sh(f"{b} -C OUTPUT -p {proto} --sport {port} -m comment --comment mtptraffic-{port}-out >/dev/null 2>&1 || {b} -I OUTPUT 1 -p {proto} --sport {port} -m comment --comment mtptraffic-{port}-out >/dev/null 2>&1 || true")
def used_bytes_raw(port):
    try: ensure_traffic_rule(port)
    except Exception: pass
    total=0; seen=[]
    for b in ('iptables','iptables-legacy','iptables-nft'):
        for chain,lab in (('INPUT','in'),('OUTPUT','out')):
            out=(sh(f"{b} -nvxL {chain} 2>/dev/null | awk '/mtptraffic-{port}-{lab}/ {{s+=$2}} END{{print s+0}}'").stdout or '0').strip()
            try:
                val=int(float(out.splitlines()[-1] if out.splitlines() else 0))
                if val and val not in seen: total+=val; seen.append(val)
            except Exception: pass
    return total
def used_bytes(r): return max(0, used_bytes_raw(shared_proxy_port())-int(r['used_reset_bytes'] or 0))

def init_db():
    ETC_DIR.mkdir(parents=True,exist_ok=True)
    with db() as con:
        con.execute("""create table if not exists users(id integer primary key autoincrement,username text unique not null,port integer not null,secret text not null,quota_gb real not null default 0,quota_bytes integer not null default 0,expires_at text not null,enabled integer not null default 1,created_at text not null,note text default '',sub_token text,used_reset_bytes integer not null default 0)""")
        cols=[r['name'] for r in con.execute('pragma table_info(users)').fetchall()]
        if 'quota_bytes' not in cols:
            con.execute('alter table users add column quota_bytes integer not null default 0')
            con.execute('update users set quota_bytes=cast(quota_gb*1073741824 as integer) where quota_bytes=0')
        idxs=con.execute('pragma index_list(users)').fetchall(); port_unique=False
        for idx in idxs:
            if idx['unique'] and [x['name'] for x in con.execute(f"pragma index_info({idx['name']})").fetchall()]==['port']: port_unique=True
        if port_unique:
            con.execute('alter table users rename to users_old')
            con.execute("""create table users(id integer primary key autoincrement,username text unique not null,port integer not null,secret text not null,quota_gb real not null default 0,quota_bytes integer not null default 0,expires_at text not null,enabled integer not null default 1,created_at text not null,note text default '',sub_token text,used_reset_bytes integer not null default 0)""")
            oc=[r['name'] for r in con.execute('pragma table_info(users_old)').fetchall()]
            qb='quota_bytes' if 'quota_bytes' in oc else 'cast(quota_gb*1073741824 as integer)'
            con.execute(f"""insert into users(id,username,port,secret,quota_gb,quota_bytes,expires_at,enabled,created_at,note,sub_token,used_reset_bytes) select id,username,port,secret,quota_gb,{qb},expires_at,enabled,created_at,note,sub_token,used_reset_bytes from users_old""")
            con.execute('drop table users_old')
        add_col(con,'users','sub_token','text'); add_col(con,'users','used_reset_bytes','integer not null default 0'); add_col(con,'users','quota_bytes','integer not null default 0')
        con.execute('update users set port=?',(shared_proxy_port(),)); con.execute('update users set quota_bytes=cast(quota_gb*1073741824 as integer) where quota_bytes=0 and quota_gb>0')
        for r in con.execute('select id from users where sub_token is null or sub_token=""').fetchall(): con.execute('update users set sub_token=? where id=?',(secrets.token_urlsafe(16),r['id']))

def q(x): return "'"+str(x).replace("'","'\\''")+"'"
def restart_shared_proxy():
    port=shared_proxy_port(); ensure_traffic_rule(port); MTPROXY_DIR.mkdir(parents=True,exist_ok=True)
    with db() as con: rows=con.execute('select secret from users where enabled=1').fetchall()
    args=' '.join('-S '+q(r['secret']) for r in rows if r['secret'])
    if not args: sh('systemctl disable --now mtproxy-shared.service >/dev/null 2>&1 || true'); return
    unit=f"""[Unit]\nDescription=Shared MTProto Proxy Multi Secret\nAfter=network.target\n\n[Service]\nType=simple\nExecStart=/usr/local/bin/mtproto-proxy -u nobody -p 9000 -H {port} {args} --aes-pwd {MTPROXY_DIR}/proxy-secret {MTPROXY_DIR}/proxy-multi.conf -M 1\nRestart=always\nRestartSec=3\nLimitNOFILE=65535\n\n[Install]\nWantedBy=multi-user.target\n"""
    path=Path('/etc/systemd/system/mtproxy-shared.service'); path.write_text(unit); sh('systemctl daemon-reload'); sh('systemctl enable --now mtproxy-shared.service'); sh('systemctl restart mtproxy-shared.service')
def create_service(r=None): restart_shared_proxy()
def stop_service(u=None): restart_shared_proxy()

def enforce_limits():
    today=date.today().isoformat(); changed=False
    with db() as con:
        for r in con.execute('select * from users where enabled=1').fetchall():
            if r['expires_at']<today or (quota_bytes(r)>0 and used_bytes(r)>=quota_bytes(r)):
                con.execute('update users set enabled=0 where id=?',(r['id'],)); changed=True
    if changed: restart_shared_proxy()

def login_required(fn):
    @wraps(fn)
    def w(*a,**k):
        if not session.get('auth'): return redirect('/login')
        enforce_limits(); return fn(*a,**k)
    return w
def api_required(fn):
    @wraps(fn)
    def w(*a,**k):
        t=request.headers.get('X-API-Token') or request.args.get('token')
        if not t or t!=cfg().get('api_token'): return jsonify({'ok':False,'error':'unauthorized'}),401
        enforce_limits(); return fn(*a,**k)
    return w

CSS=r'''
:root{--bg:#0f172a;--card:#111c33;--muted:#94a3b8;--txt:#e5e7eb;--acc:#38bdf8;--bad:#fb7185;--ok:#34d399;--warn:#fbbf24;--border:#25324a;--input:#0b1220}body.theme-light{--bg:#f4f7fb;--card:#fff;--muted:#64748b;--txt:#0f172a;--acc:#0284c7;--bad:#e11d48;--ok:#059669;--warn:#d97706;--border:#e2e8f0;--input:#f8fafc}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top right,rgba(56,189,248,.14),transparent 35%),linear-gradient(135deg,var(--bg),var(--bg));color:var(--txt);font-family:Tahoma,Arial,sans-serif;direction:rtl;min-height:100vh}.wrap{max-width:1200px;margin:0 auto;padding:18px}.nav{display:flex;gap:12px;align-items:center;justify-content:space-between;margin-bottom:18px;flex-wrap:wrap}.brand{font-size:21px;font-weight:900}.menu{display:flex;gap:8px;flex-wrap:wrap}.menu a,.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:9px 13px;border-radius:14px;text-decoration:none;background:var(--card);color:var(--txt);border:1px solid var(--border);cursor:pointer;min-height:40px}.icon-btn{width:36px;height:36px;min-height:36px;padding:0;font-size:17px;border-radius:12px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}.card{background:color-mix(in srgb,var(--card) 94%,transparent);border:1px solid var(--border);border-radius:22px;padding:16px;box-shadow:0 10px 28px rgba(0,0,0,.14)}.big{font-size:27px;font-weight:900;margin-top:7px}.muted{color:var(--muted);font-size:12px}.bar{height:10px;background:color-mix(in srgb,var(--muted) 25%,transparent);border-radius:20px;overflow:hidden;margin-top:9px}.bar span{display:block;height:100%;background:linear-gradient(90deg,#38bdf8,#34d399)}table{width:100%;border-collapse:collapse;background:var(--card);border-radius:18px;overflow:hidden}td,th{padding:10px;border-bottom:1px solid var(--border);text-align:right;vertical-align:top}th{color:var(--acc);font-size:13px}.table-wrap{width:100%;overflow-x:auto;border-radius:18px}.pill{padding:5px 9px;border-radius:999px;background:color-mix(in srgb,var(--muted) 18%,transparent);font-size:12px}.ok{color:var(--ok)}.bad{color:var(--bad)}input,select{width:100%;padding:11px;border-radius:13px;border:1px solid var(--border);background:var(--input);color:var(--txt);margin-top:6px}label{display:block;margin-bottom:12px}.actions{display:flex;gap:7px;flex-wrap:wrap}.danger{background:#3b1420;color:#fff}.flash{margin:10px 0;padding:12px;border-radius:14px;background:color-mix(in srgb,var(--acc) 18%,transparent);border:1px solid var(--border)}.login{max-width:420px;margin:8vh auto}.copy-row{display:flex;gap:7px;align-items:center;margin:6px 0;direction:ltr}.copy-row code{flex:1;background:var(--input);border:1px solid var(--border);border-radius:11px;padding:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.copy-btn{font-size:12px;padding:7px 10px;min-height:32px}hr{border:0;border-top:1px solid var(--border);margin:16px 0}
.sub-page{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px;position:relative;overflow:hidden;font-family:Tahoma,Arial,sans-serif}.sub-page .particle{position:absolute;top:-10%;font-size:20px;opacity:.68;animation:fall linear infinite;pointer-events:none}.sub-page .bird{animation:fly linear infinite}.sub-page .wind{animation:drift linear infinite}.sub-page .rain{position:absolute;top:-10%;width:2px;height:24px;background:#dbeafe;border-radius:99px;opacity:.58;animation:fall linear infinite}.sub-page .sand{position:absolute;width:7px;height:7px;border-radius:50%;background:#fde68a;opacity:.55;animation:drift linear infinite}@keyframes fall{to{transform:translateY(120vh) rotate(360deg)}}@keyframes fly{to{transform:translateX(120vw) translateY(-24vh)}}@keyframes drift{to{transform:translateX(80vw) translateY(-20vh) rotate(220deg)}}@keyframes bgMove{0%,100%{background-position:0% 50%}50%{background-position:100% 50%}}.theme-rain{background:linear-gradient(135deg,#0b1220,#164e63,#1e293b)}.theme-flower{background:linear-gradient(135deg,#fff1f2,#fbcfe8,#fb7185)}.theme-bird{background:linear-gradient(135deg,#ecfeff,#bae6fd,#38bdf8)}.theme-heart{background:linear-gradient(135deg,#4c0519,#be123c,#fb7185)}.theme-desert{background:linear-gradient(135deg,#7c2d12,#f59e0b,#fde68a)}.theme-aurora{background:linear-gradient(120deg,#020617,#0f766e,#7c3aed,#020617);background-size:300% 300%;animation:bgMove 10s ease infinite}.theme-snow{background:linear-gradient(135deg,#e0f2fe,#f8fafc,#bae6fd)}.theme-star{background:radial-gradient(circle at 30% 20%,#fef3c7,transparent 18%),linear-gradient(135deg,#111827,#312e81,#020617)}.sub-card{width:min(470px,100%);background:rgba(255,255,255,.84);backdrop-filter:blur(18px);color:#182b2f;border-radius:22px;padding:16px;box-shadow:0 18px 48px rgba(0,0,0,.22);direction:rtl;position:relative;z-index:2}.sub-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.avatar{width:50px;height:50px;border-radius:50%;background:linear-gradient(135deg,#bfdbfe,#60a5fa);border:3px solid rgba(255,255,255,.8)}.sub-name{font-size:20px;font-weight:900}.sub-box{margin-top:13px;background:rgba(255,255,255,.72);border:1px solid rgba(255,255,255,.5);border-radius:19px;padding:14px;text-align:center}.sub-title{font-size:18px;font-weight:900;margin-bottom:10px}.sub-stats{display:grid;grid-template-columns:1fr 1fr;gap:10px}.sub-num{font-size:23px;font-weight:900}.battery{height:25px;border-radius:9px;background:#263238;padding:4px;margin:8px auto 0;max-width:92px}.battery span{display:block;height:100%;border-radius:7px;background:#65a30d}.percent{font-size:11px;color:#475569;margin-top:5px}.sub-link{margin-top:12px;background:#172033;color:white;border-radius:14px;padding:10px;direction:ltr;word-break:break-all;font-family:monospace;font-size:10px}.theme-dots{position:fixed;bottom:14px;left:0;right:0;display:flex;gap:10px;justify-content:center;z-index:4}.theme-dot{width:22px;height:22px;border-radius:50%;border:2px solid #fff;box-shadow:0 5px 18px #0005;cursor:pointer}.theme-dot:nth-child(1){background:linear-gradient(135deg,#0f172a,#38bdf8)}.theme-dot:nth-child(2){background:linear-gradient(135deg,#fdf2f8,#fb7185)}.theme-dot:nth-child(3){background:linear-gradient(135deg,#dbeafe,#2563eb)}.theme-dot:nth-child(4){background:linear-gradient(135deg,#4c0519,#fb7185)}.theme-dot:nth-child(5){background:linear-gradient(135deg,#78350f,#fde68a)}.theme-dot:nth-child(6){background:linear-gradient(135deg,#0f766e,#7c3aed)}.theme-dot:nth-child(7){background:linear-gradient(135deg,#f8fafc,#38bdf8)}.theme-dot:nth-child(8){background:linear-gradient(135deg,#111827,#fef3c7)}
@media(max-width:700px){.wrap{padding:11px}.brand{font-size:18px}.menu a,.btn{padding:8px 10px;font-size:13px}.grid{grid-template-columns:1fr}.card{border-radius:17px;padding:13px}td,th{padding:8px;font-size:12px}.copy-row{flex-direction:column;align-items:stretch}.copy-row code{white-space:normal}.table-wrap table{min-width:860px}.sub-card{padding:13px;border-radius:18px}.avatar{width:44px;height:44px}.sub-name{font-size:18px}.sub-box{padding:12px}.sub-title{font-size:17px}.sub-stats{grid-template-columns:1fr}.sub-num{font-size:21px}.sub-link{font-size:10px}.theme-dots{bottom:8px;gap:7px}.theme-dot{width:20px;height:20px}}
'''
BASE='''<!doctype html><html lang="fa"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MTProto Panel</title><style>{{css}}</style><script>function copyText(t,b){const done=()=>{let o=b.innerText;b.innerText='کپی شد ✓';setTimeout(()=>b.innerText=o,1200)}; if(navigator.clipboard){navigator.clipboard.writeText(t).then(done).catch(()=>fallbackCopy(t,done))}else fallbackCopy(t,done)}function fallbackCopy(t,cb){let x=document.createElement('textarea');x.value=t;document.body.appendChild(x);x.select();document.execCommand('copy');x.remove();cb&&cb()}</script></head><body class="theme-{{theme}}"><div class="wrap"><div class="nav"><div class="brand">⚡ MTProto Panel</div>{% if session.get('auth') %}<div class="menu"><a href="/">Overview</a><a href="/users">کاربران</a><a href="/settings">تنظیمات</a><a href="/logout">خروج</a></div>{% endif %}</div>{% for m in get_flashed_messages() %}<div class="flash">{{m}}</div>{% endfor %}{{body|safe}}</div></body></html>'''
def page(body): return render_template_string(BASE,body=body,css=CSS,theme=cfg().get('theme','dark'))

@app.route('/login',methods=['GET','POST'])
def login():
    c=cfg()
    if request.method=='POST' and request.form.get('username')==c.get('admin_username') and check_password_hash(c.get('admin_password_hash',''),request.form.get('password','')):
        session['auth']=True; return redirect('/')
    if request.method=='POST': flash('یوزرنیم یا پسورد اشتباه است.')
    return page('<div class="login card"><h2>ورود به پنل</h2><form method="post"><label>یوزرنیم<input name="username" required></label><label>پسورد<input name="password" type="password" required></label><button class="btn">ورود</button></form></div>')
@app.route('/logout')
def logout(): session.clear(); return redirect('/login')
@app.route('/')
@login_required
def overview():
    vm=psutil.virtual_memory(); du=psutil.disk_usage('/'); cpu=psutil.cpu_percent(interval=.2)
    with db() as con: rows=con.execute('select * from users').fetchall(); total=len(rows); active=sum(1 for r in rows if r['enabled'])
    body=render_template_string('''<h2>Overview</h2><div class="grid"><div class="card"><div class="muted">CPU</div><div class="big">{{cpu}}%</div><div class="bar"><span style="width:{{cpu}}%"></span></div></div><div class="card"><div class="muted">RAM</div><div class="big">{{ram}}%</div><div class="muted">{{ru}} / {{rt}} GB</div></div><div class="card"><div class="muted">آنلاین‌های لحظه‌ای</div><div class="big ok">{{online}}</div></div><div class="card"><div class="muted">Users</div><div class="big">{{active}} / {{total}}</div></div><div class="card"><div class="muted">پورت مشترک پروکسی</div><div class="big">{{sport}}</div></div><div class="card"><div class="muted">Server Host</div><div class="big" style="font-size:18px">{{host}}</div></div></div>''',cpu=cpu,ram=vm.percent,ru=round(vm.used/1024**3,2),rt=round(vm.total/1024**3,2),online=online_count(shared_proxy_port()),active=active,total=total,sport=shared_proxy_port(),host=public_host())
    return page(body)
@app.route('/users')
@login_required
def users():
    with db() as con: rows=con.execute('select * from users order by id desc').fetchall()
    body='<div class="actions"><a class="btn" href="/users/new">+ ساخت کاربر جدید</a></div><br><div class="table-wrap"><table><tr><th>کاربر</th><th>پورت مشترک</th><th>آنلاین</th><th>حجم</th><th>مصرف واقعی</th><th>انقضا</th><th>وضعیت</th><th>لینک‌ها</th><th>عملیات</th></tr>'
    for r in rows:
        pl=proxy_link(r); sl=sub_link(r); qb=quota_bytes(r); status='<span class="ok">فعال</span>' if r['enabled'] else '<span class="bad">غیرفعال</span>'; toggle='🚫' if r['enabled'] else '✅'
        links=f"<div class='copy-row'><code>{pl}</code><button type='button' class='btn copy-btn' onclick='copyText({js(pl)},this)'>کپی پروکسی</button></div><div class='copy-row'><code>{sl}</code><button type='button' class='btn copy-btn' onclick='copyText({js(sl)},this)'>کپی ساب</button></div>"
        body+=f"<tr><td>{r['username']}</td><td>{shared_proxy_port()}</td><td><span class='pill'>{online_count(shared_proxy_port())}</span></td><td>{'نامحدود' if qb==0 else fmt_bytes(qb)}</td><td>{fmt_bytes(used_bytes(r))}</td><td>{r['expires_at']}</td><td>{status}</td><td>{links}</td><td><div class='actions'><a class='btn icon-btn' title='ویرایش' href='/users/{r['id']}/edit'>✏️</a><a class='btn icon-btn' title='فعال/غیرفعال' href='/users/{r['id']}/toggle'>{toggle}</a><a class='btn icon-btn danger' title='حذف' href='/users/{r['id']}/delete' onclick=\"return confirm('حذف شود؟')\">🗑️</a></div></td></tr>"
    return page(body+'</table></div>')
@app.route('/users/new',methods=['GET','POST'])
@login_required
def new_user():
    port=shared_proxy_port()
    if request.method=='POST':
        try:
            username=request.form['username'].strip(); unit=request.form.get('quota_unit','gb'); qv=float(request.form.get('quota_amount') or 0); qb=int(qv*(1024**2 if unit=='mb' else 1024**3)) if qv>0 else 0; qgb=qb/1024**3 if qb else 0; days=int(request.form.get('expiry_days') or 30); expires=(date.today()+timedelta(days=days)).isoformat(); manual=(request.form.get('secret') or '').strip(); secret=manual if request.form.get('secret_mode')=='manual' and manual else secrets.token_hex(16)
            with db() as con:
                con.execute('insert into users(username,port,secret,quota_gb,quota_bytes,expires_at,enabled,created_at,note,sub_token,used_reset_bytes) values(?,?,?,?,?,?,?,?,?,?,?)',(username,port,secret,qgb,qb,expires,1,datetime.utcnow().isoformat(),request.form.get('note',''),secrets.token_urlsafe(16),used_bytes_raw(port)))
            restart_shared_proxy(); flash('کاربر ساخته شد و Secret روی پورت مشترک فعال شد.'); return redirect('/users')
        except Exception as e: flash('خطا در ساخت پروکسی: '+str(e))
    return page(render_template_string('''<div class="card"><h2>ساخت کاربر جدید</h2><p class="muted">همه کاربران روی یک پورت مشترک ساخته می‌شوند و قطع/وصل با Secret انجام می‌شود.</p><form method="post"><label>نام کاربر<input name="username" required pattern="[A-Za-z0-9_-]+"></label><label>پورت مشترک<input value="{{port}}" disabled></label><label>Secret<select name="secret_mode"><option value="auto">خودکار بساز</option><option value="manual">دستی وارد می‌کنم</option></select></label><label>Secret دستی<input name="secret"></label><div class="grid"><label>حجم<input name="quota_amount" type="number" step="0.001" value="0"></label><label>واحد حجم<select name="quota_unit"><option value="gb">GB</option><option value="mb">MB</option></select></label></div><label>مدت اعتبار به روز<input name="expiry_days" type="number" min="1" value="30" required></label><label>یادداشت<input name="note"></label><button class="btn">ساخت پروکسی</button></form></div>''',port=port))
@app.route('/users/<int:uid>/edit',methods=['GET','POST'])
@login_required
def edit_user(uid):
    with db() as con: r=con.execute('select * from users where id=?',(uid,)).fetchone()
    if not r: return redirect('/users')
    if request.method=='POST':
        unit=request.form.get('quota_unit','gb'); qv=float(request.form.get('quota_amount') or 0); qb=int(qv*(1024**2 if unit=='mb' else 1024**3)) if qv>0 else 0; qgb=qb/1024**3 if qb else 0; days=int(request.form.get('expiry_days') or 30); expires=(date.today()+timedelta(days=days)).isoformat(); enabled=1 if request.form.get('enabled')=='on' else 0; reset=used_bytes_raw(shared_proxy_port()) if request.form.get('reset_usage')=='on' else r['used_reset_bytes']; secret=(request.form.get('secret') or r['secret']).strip()
        with db() as con: con.execute('update users set port=?,secret=?,quota_gb=?,quota_bytes=?,expires_at=?,note=?,enabled=?,used_reset_bytes=? where id=?',(shared_proxy_port(),secret,qgb,qb,expires,request.form.get('note',''),enabled,reset,uid))
        restart_shared_proxy(); flash('اطلاعات کاربر بروزرسانی شد.'); return redirect('/users')
    cur=round(quota_bytes(r)/1024**3,3) if quota_bytes(r) else 0
    return page(render_template_string('''<div class="card"><h2>ویرایش {{r['username']}}</h2><form method="post"><label>Secret<input name="secret" value="{{r['secret']}}"></label><div class="grid"><label>حجم<input name="quota_amount" type="number" step="0.001" value="{{cur}}"></label><label>واحد حجم<select name="quota_unit"><option value="gb">GB</option><option value="mb">MB</option></select></label></div><label>اعتبار از امروز به روز<input name="expiry_days" type="number" min="1" value="30"></label><div class="muted">انقضای فعلی: {{r['expires_at']}}</div><label>یادداشت<input name="note" value="{{r['note'] or ''}}"></label><label><input style="width:auto" type="checkbox" name="reset_usage"> صفر کردن مصرف</label><label><input style="width:auto" type="checkbox" name="enabled" {% if r['enabled'] %}checked{% endif %}> فعال باشد</label><button class="btn">ذخیره</button></form></div>''',r=r,cur=cur))
@app.route('/users/<int:uid>/toggle')
@login_required
def toggle(uid):
    with db() as con:
        r=con.execute('select * from users where id=?',(uid,)).fetchone()
        if r: con.execute('update users set enabled=? where id=?',(0 if r['enabled'] else 1,uid))
    restart_shared_proxy(); return redirect('/users')
@app.route('/users/<int:uid>/delete')
@login_required
def delete(uid):
    with db() as con: con.execute('delete from users where id=?',(uid,))
    restart_shared_proxy(); return redirect('/users')
@app.route('/settings',methods=['GET','POST'])
@login_required
def settings():
    c=cfg()
    if request.method=='POST':
        a=request.form.get('action')
        if a=='account':
            if request.form.get('admin_username','').strip(): c['admin_username']=request.form['admin_username'].strip()
            if request.form.get('admin_password'): c['admin_password_hash']=generate_password_hash(request.form['admin_password'])
        elif a=='server':
            c['server_host']=request.form.get('server_host','').strip(); c['sub_port']=int(request.form.get('sub_port') or c.get('panel_port',8080)); c['shared_proxy_port']=int(request.form.get('shared_proxy_port') or shared_proxy_port()); c['proxy_ports']=str(c['shared_proxy_port']); c['theme']=request.form.get('theme','dark')
            with db() as con: con.execute('update users set port=?',(c['shared_proxy_port'],))
            save_cfg(c); restart_shared_proxy(); flash('تنظیمات ذخیره شد.'); return redirect('/settings')
        elif a=='api': c['api_token']=request.form.get('api_token','').strip() or secrets.token_urlsafe(24); c['telegram_bot_token']=request.form.get('telegram_bot_token','').strip()
        save_cfg(c); flash('ذخیره شد.'); return redirect('/settings')
    body=render_template_string('''<h2>تنظیمات</h2><div class="grid"><div class="card"><h3>ورود پنل</h3><form method="post"><input type="hidden" name="action" value="account"><label>نام کاربری<input name="admin_username" value="{{c.get('admin_username','')}}"></label><label>رمز جدید<input name="admin_password" type="password"></label><button class="btn">ذخیره</button></form></div><div class="card"><h3>سرور</h3><form method="post"><input type="hidden" name="action" value="server"><label>دامنه/IP لینک‌ها<input name="server_host" value="{{host}}"></label><label>پورت مشترک پروکسی‌ها<input name="shared_proxy_port" type="number" value="{{sport}}"></label><label>پورت ساب<input name="sub_port" type="number" value="{{c.get('sub_port',c.get('panel_port',8080))}}"></label><label>تم پنل<select name="theme"><option value="dark" {% if c.get('theme','dark')=='dark' %}selected{% endif %}>Dark</option><option value="light" {% if c.get('theme')=='light' %}selected{% endif %}>Light</option></select></label><button class="btn">ذخیره</button></form></div><div class="card"><h3>API تلگرام بات</h3><form method="post"><input type="hidden" name="action" value="api"><label>Bot Token<input name="telegram_bot_token" value="{{c.get('telegram_bot_token','')}}"></label><label>API Token<input name="api_token" value="{{c.get('api_token','')}}"></label><button class="btn">ذخیره</button></form></div><div class="card"><h3>Backup</h3><a class="btn" href="/settings/backup/export">دانلود بکاپ</a><hr><form method="post" action="/settings/backup/import" enctype="multipart/form-data"><label>Import JSON<input type="file" name="backup" accept="application/json" required></label><button class="btn danger">ایمپورت</button></form></div></div>''',c=c,host=public_host(),sport=shared_proxy_port())
    return page(body)
@app.route('/settings/backup/export')
@login_required
def export_backup():
    with db() as con: users=[dict(x) for x in con.execute('select * from users order by id')]
    return send_file(io.BytesIO(json.dumps({'version':3,'created_at':datetime.utcnow().isoformat(),'config':cfg(),'users':users},ensure_ascii=False,indent=2).encode()),mimetype='application/json',as_attachment=True,download_name='mtproto-panel-backup.json')
@app.route('/settings/backup/import',methods=['POST'])
@login_required
def import_backup():
    data=json.loads(request.files['backup'].read().decode()); c=cfg(); c.update(data.get('config') or {}); save_cfg(c)
    with db() as con:
        con.execute('delete from users')
        for u in data.get('users',[]):
            qgb=float(u.get('quota_gb') or 0); qb=int(u.get('quota_bytes') or qgb*1024**3)
            con.execute('insert into users(username,port,secret,quota_gb,quota_bytes,expires_at,enabled,created_at,note,sub_token,used_reset_bytes) values(?,?,?,?,?,?,?,?,?,?,?)',(u['username'],shared_proxy_port(),u['secret'],qgb,qb,u.get('expires_at') or date.today().isoformat(),int(u.get('enabled',1)),u.get('created_at') or datetime.utcnow().isoformat(),u.get('note',''),u.get('sub_token') or secrets.token_urlsafe(16),int(u.get('used_reset_bytes') or 0)))
    restart_shared_proxy(); flash('بکاپ ایمپورت شد.'); return redirect('/users')
@app.route('/s/<token>')
def subscription(token):
    enforce_limits()
    with db() as con: r=con.execute('select * from users where sub_token=?',(token,)).fetchone()
    if not r: return 'Not found',404
    used=used_bytes(r); qb=quota_bytes(r); remain=max(0,qb-used) if qb else 0; days=max(0,(datetime.fromisoformat(r['expires_at']).date()-date.today()).days); total=max(1,(datetime.fromisoformat(r['expires_at']).date()-datetime.fromisoformat(r['created_at']).date()).days) if r['created_at'] else 30; up=0 if not qb else min(100,round(used*100/qb,1)); rp=100 if not qb else max(0,round(remain*100/qb,1)); dp=max(0,min(100,round(days*100/total,1))); link=proxy_link(r)
    return render_template_string('''<!doctype html><html lang="fa"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{r['username']}}</title><style>{{css}}</style><script>function copyText(t,b){let o=b.innerText;let done=()=>{b.innerText='کپی شد ✓';setTimeout(()=>b.innerText=o,1200)};if(navigator.clipboard)navigator.clipboard.writeText(t).then(done).catch(()=>fallbackCopy(t,done));else fallbackCopy(t,done)}function fallbackCopy(t,cb){let x=document.createElement('textarea');x.value=t;document.body.appendChild(x);x.select();document.execCommand('copy');x.remove();cb&&cb()}const maps={rain:['rain','',60],flower:['particle','🌸',34],bird:['particle bird','🐦',22],heart:['particle','♡',36],desert:['sand wind','',55],aurora:['particle wind','✦',28],snow:['particle','❄',44],star:['particle','✦',38]};function particles(k){let p=document.querySelector('.sub-page');p.querySelectorAll('.particle,.rain,.sand').forEach(e=>e.remove());let m=maps[k];for(let i=0;i<m[2];i++){let e=document.createElement('span');e.className=m[0];e.textContent=m[1];e.style.left=(Math.random()*105-5)+'vw';e.style.animationDuration=(5+Math.random()*9)+'s';e.style.animationDelay=(-Math.random()*8)+'s';e.style.fontSize=(13+Math.random()*16)+'px';if(k==='bird'){e.style.top=(25+Math.random()*55)+'vh';e.style.left='-8vw'}p.appendChild(e)}}function setSubTheme(t){let p=document.querySelector('.sub-page');p.className='sub-page theme-'+t;localStorage.setItem('mtp_sub_theme',t);particles(t)}window.addEventListener('load',()=>setSubTheme(localStorage.getItem('mtp_sub_theme')||'rain'));</script></head><body><div class="sub-page theme-rain"><div class="sub-card"><div class="sub-head"><div style="display:flex;gap:10px;align-items:center"><div class="avatar"></div><div><div class="sub-name">{{r['username']}}</div><div class="muted">Port {{sport}} · آنلاین {{online}}</div></div></div><div class="pill">{{'فعال' if r['enabled'] else 'غیرفعال'}}</div></div><div class="sub-box"><div class="sub-title">مانده سرویس</div><div class="sub-stats"><div><div><span class="sub-num">{{days}}</span> روز</div><div class="battery"><span style="width:{{dp}}%"></span></div><div class="percent">{{dp}}٪ مانده · {{100-dp}}٪ گذشته</div></div><div><div><span class="sub-num">{{remain}}</span></div><div class="battery"><span style="width:{{rp}}%"></span></div><div class="percent">{{rp}}٪ مانده · {{up}}٪ مصرف شده</div></div></div><div class="sub-link">{{link}}</div><br><button class="btn" onclick='copyText({{linkjs}},this)'>کپی لینک پروکسی</button></div></div><div class="theme-dots"><button class="theme-dot" onclick="setSubTheme('rain')"></button><button class="theme-dot" onclick="setSubTheme('flower')"></button><button class="theme-dot" onclick="setSubTheme('bird')"></button><button class="theme-dot" onclick="setSubTheme('heart')"></button><button class="theme-dot" onclick="setSubTheme('desert')"></button><button class="theme-dot" onclick="setSubTheme('aurora')"></button><button class="theme-dot" onclick="setSubTheme('snow')"></button><button class="theme-dot" onclick="setSubTheme('star')"></button></div></div></body></html>''',css=CSS,r=r,sport=shared_proxy_port(),online=online_count(shared_proxy_port()),days=days,dp=dp,remain=('∞' if not qb else fmt_bytes(remain)),rp=rp,up=up,link=link,linkjs=js(link))
def api_user_dict(r):
    used=used_bytes(r); qb=quota_bytes(r)
    return {'username':r['username'],'port':shared_proxy_port(),'enabled':bool(r['enabled']),'online':online_count(shared_proxy_port()),'used_bytes':used,'used_human':fmt_bytes(used),'quota_bytes':qb,'quota_human':('unlimited' if not qb else fmt_bytes(qb)),'remaining_bytes':(max(0,qb-used) if qb else None),'expires_at':r['expires_at'],'proxy_link':proxy_link(r),'sub_link':sub_link(r)}
@app.route('/api/users')
@api_required
def api_users():
    with db() as con: rows=con.execute('select * from users order by id desc').fetchall()
    return jsonify({'ok':True,'users':[api_user_dict(r) for r in rows]})
@app.route('/api/user/<username>')
@api_required
def api_user(username):
    with db() as con: r=con.execute('select * from users where username=?',(username,)).fetchone()
    if not r: return jsonify({'ok':False,'error':'not_found'}),404
    return jsonify({'ok':True,'user':api_user_dict(r)})
if __name__=='__main__':
    init_db(); c=cfg(); panel=int(c.get('panel_port',8080)); sub=int(c.get('sub_port') or panel); host=c.get('panel_host','0.0.0.0')
    if sub!=panel:
        srv=make_server(host,sub,app); threading.Thread(target=srv.serve_forever,daemon=True).start()
    app.run(host=host,port=panel)
