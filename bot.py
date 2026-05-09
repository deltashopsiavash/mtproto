#!/usr/bin/env python3
import json, os, secrets, sqlite3, time, traceback
from datetime import date, datetime, timedelta
from pathlib import Path
import requests
import app as panel

CONFIG_PATH = panel.CONFIG_PATH
DB_PATH = panel.DB_PATH
STATE = {}
OFFSET = 0


def cfg():
    return panel.cfg()

def api(method, **data):
    token = cfg().get('telegram_bot_token','').strip()
    if not token:
        return None
    files = data.pop('files', None)
    url = f'https://api.telegram.org/bot{token}/{method}'
    try:
        return requests.post(url, data=data, files=files, timeout=30).json()
    except Exception:
        return None

def send(chat_id, text, kb=None):
    data={'chat_id':chat_id,'text':text,'parse_mode':'HTML','disable_web_page_preview':'true'}
    if kb: data['reply_markup']=json.dumps(kb, ensure_ascii=False)
    return api('sendMessage', **data)

def edit(chat_id, msg_id, text, kb=None):
    data={'chat_id':chat_id,'message_id':msg_id,'text':text,'parse_mode':'HTML','disable_web_page_preview':'true'}
    if kb: data['reply_markup']=json.dumps(kb, ensure_ascii=False)
    return api('editMessageText', **data)

def answer(cid, text=''):
    return api('answerCallbackQuery', callback_query_id=cid, text=text, show_alert='false')

def admin_id():
    v=str(cfg().get('telegram_admin_id','')).strip()
    return int(v) if v.isdigit() else 0

def allowed(uid):
    return int(uid)==admin_id() and admin_id()>0

def deny(chat_id):
    send(chat_id, '⛔ شما حق استفاده از این ربات را ندارید.')

def kb(rows):
    return {'inline_keyboard': rows}

def btn(text, data):
    return {'text': text, 'callback_data': data}

def main_menu():
    return kb([
        [btn('📊 Overview','overview'), btn('👥 Users','users')],
        [btn('➕ ساخت پروکسی','new'), btn('⚙️ Settings','settings')],
        [btn('🔄 Restart / Apply','restart'), btn('💾 Backup','backup')],
    ])

def row_user(uid):
    with panel.db() as con:
        return con.execute('select * from users where id=?',(uid,)).fetchone()

def all_users():
    with panel.db() as con:
        return con.execute('select * from users order by id desc').fetchall()

def overview_text():
    panel.enforce_limits()
    vm=panel.psutil.virtual_memory(); cpu=panel.psutil.cpu_percent(interval=0.2)
    rows=all_users(); active=sum(1 for r in rows if r['enabled'])
    return (f"⚡ <b>MTProto Panel</b>\n\n"
            f"CPU: <b>{cpu}%</b>\nRAM: <b>{vm.percent}%</b> ({round(vm.used/1024**3,2)} / {round(vm.total/1024**3,2)} GB)\n"
            f"Online: <b>{panel.online_count(panel.shared_proxy_port())}</b>\nUsers: <b>{active}/{len(rows)}</b>\n"
            f"Proxy Port: <code>{panel.shared_proxy_port()}</code>\nHost: <code>{panel.public_host()}</code>")

def user_text(r):
    used=panel.used_bytes(r); qb=panel.quota_bytes(r); rem=max(0,qb-used) if qb else 0
    try: days=max(0,(datetime.fromisoformat(r['expires_at']).date()-date.today()).days)
    except Exception: days=0
    return (f"👤 <b>{r['username']}</b>\n"
            f"Status: {'✅ فعال' if r['enabled'] else '🚫 غیرفعال'}\n"
            f"Port: <code>{panel.shared_proxy_port()}</code>\nSecret: <code>{r['secret']}</code>\n"
            f"Usage: <b>{panel.fmt_bytes(used)}</b> / {'∞' if not qb else panel.fmt_bytes(qb)}\n"
            f"Remaining: <b>{'∞' if not qb else panel.fmt_bytes(rem)}</b>\nDays left: <b>{days}</b>\n\n"
            f"Proxy:\n<code>{panel.proxy_link(r)}</code>\n\nSub:\n<code>{panel.sub_link(r)}</code>")

def user_kb(uid):
    return kb([
        [btn('✏️ ویرایش حجم/تاریخ','editq:'+str(uid)), btn('🔑 Secret','secret:'+str(uid))],
        [btn('✅/🚫 فعال/غیرفعال','toggle:'+str(uid)), btn('🗑 حذف','del:'+str(uid))],
        [btn('♻️ Reset Usage','resetu:'+str(uid)), btn('🔙 Users','users')],
    ])

def create_user(username, amount, unit, days, secret_mode='auto', secret_value=''):
    qb, qgb, unit = panel.parse_quota_form({'quota_amount':str(amount),'quota_unit':unit})
    exp=(date.today()+timedelta(days=int(days))).isoformat()
    now=datetime.utcnow().isoformat(); token=secrets.token_urlsafe(16)
    with panel.db() as con:
        cur=con.execute('insert into users(username,port,secret,quota_gb,quota_bytes,expires_at,enabled,created_at,note,sub_token,used_reset_bytes,local_port,sni_host) values(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (username, panel.shared_proxy_port(), 'pending', qgb, qb, exp, 1, now, '', token, 0, 0, ''))
        uid=cur.lastrowid
    lp=panel.user_local_port(uid); secret=panel.normalize_secret('' if secret_mode=='auto' else secret_value, username, uid); sni=panel.secret_sni(secret) or panel.make_sni(username, uid)
    baseline=panel.traffic_total(lp)
    with panel.db() as con:
        con.execute('update users set secret=?,local_port=?,sni_host=?,used_reset_bytes=? where id=?',(secret,lp,sni,baseline,uid))
    panel.restart_shared_proxy()
    with panel.db() as con:
        return con.execute('select * from users where username=?',(username,)).fetchone()

def show_users(chat_id, msg_id=None):
    rows=all_users()
    buttons=[]
    for r in rows[:50]:
        buttons.append([btn(('✅ ' if r['enabled'] else '🚫 ')+r['username'], 'user:'+str(r['id']))])
    buttons.append([btn('➕ ساخت پروکسی','new'), btn('🔙 منو','menu')])
    text='👥 <b>لیست پروکسی‌ها</b>\nبرای دیدن جزئیات روی کاربر بزن.' if rows else 'هنوز کاربری ساخته نشده.'
    return edit(chat_id,msg_id,text,kb(buttons)) if msg_id else send(chat_id,text,kb(buttons))

def settings_text():
    c=cfg()
    return (f"⚙️ <b>Settings</b>\n\nHost: <code>{panel.public_host()}</code>\n"
            f"Proxy Port: <code>{panel.shared_proxy_port()}</code>\nSub Port: <code>{c.get('sub_port', c.get('panel_port',8080))}</code>\n"
            f"Language: <code>{c.get('language','fa')}</code>\nBot Admin ID: <code>{c.get('telegram_admin_id','')}</code>")

def settings_kb():
    return kb([
        [btn('🌐 تغییر Host','sethost'), btn('🔌 تغییر پورت ساب','setsubport')],
        [btn('🇮🇷 فارسی','lang:fa'), btn('🇬🇧 English','lang:en')],
        [btn('🔄 Restart / Apply','restart'), btn('🔙 منو','menu')]
    ])

def handle_text(uid, chat_id, text):
    if not allowed(uid): return deny(chat_id)
    st=STATE.get(uid)
    if not st:
        return send(chat_id, 'از منو انتخاب کن:', main_menu())
    try:
        step=st.get('step')
        if step=='new_username':
            st['username']=text.strip(); st['step']='new_amount'; send(chat_id,'حجم را عددی بفرست. مثلا 50 یا 2')
        elif step=='new_amount':
            st['amount']=float(text.strip().replace(',','.')); st['step']='new_unit'; send(chat_id,'واحد حجم را انتخاب کن:', kb([[btn('MB','newunit:mb'),btn('GB','newunit:gb')]]))
        elif step=='new_days':
            st['days']=int(text.strip()); st['step']='new_secret'; send(chat_id,'Secret خودکار باشد یا دستی؟', kb([[btn('خودکار','newsecret:auto'),btn('دستی','newsecret:manual')]]))
        elif step=='new_secret_manual':
            r=create_user(st['username'], st['amount'], st['unit'], st['days'], 'manual', text.strip()); STATE.pop(uid,None); send(chat_id,'✅ پروکسی ساخته شد.'); send(chat_id,user_text(r),user_kb(r['id']))
        elif step=='editq':
            amount, unit, days = text.replace('،',',').split(',')[:3]
            qb,qgb,unit=panel.parse_quota_form({'quota_amount':amount.strip(),'quota_unit':unit.strip().lower()})
            exp=(date.today()+timedelta(days=int(days.strip()))).isoformat()
            with panel.db() as con: con.execute('update users set quota_gb=?,quota_bytes=?,expires_at=? where id=?',(qgb,qb,exp,st['uid']))
            panel.restart_shared_proxy(); r=row_user(st['uid']); STATE.pop(uid,None); send(chat_id,'✅ ویرایش شد.'); send(chat_id,user_text(r),user_kb(r['id']))
        elif step=='secret':
            sec=panel.normalize_secret(text.strip(), row_user(st['uid'])['username'], st['uid'])
            with panel.db() as con: con.execute('update users set secret=? where id=?',(sec,st['uid']))
            panel.restart_shared_proxy(); r=row_user(st['uid']); STATE.pop(uid,None); send(chat_id,'✅ Secret تغییر کرد.'); send(chat_id,user_text(r),user_kb(r['id']))
        elif step=='sethost':
            c=cfg(); c['server_host']=text.strip(); panel.save_cfg(c); STATE.pop(uid,None); send(chat_id,'✅ Host ذخیره شد.', settings_kb())
        elif step=='setsubport':
            c=cfg(); c['sub_port']=int(text.strip()); panel.save_cfg(c); STATE.pop(uid,None); send(chat_id,'✅ پورت ساب ذخیره شد.', settings_kb())
    except Exception as e:
        STATE.pop(uid,None); send(chat_id, '❌ خطا: '+str(e))

def handle_cb(cb):
    uid=cb['from']['id']; chat_id=cb['message']['chat']['id']; msg_id=cb['message']['message_id']; data=cb['data']
    answer(cb['id'])
    if not allowed(uid): return deny(chat_id)
    if data=='menu': STATE.pop(uid,None); return edit(chat_id,msg_id,'منوی مدیریت:',main_menu())
    if data=='overview': return edit(chat_id,msg_id,overview_text(),kb([[btn('🔙 منو','menu')]]))
    if data=='users': return show_users(chat_id,msg_id)
    if data=='new': STATE[uid]={'step':'new_username'}; return edit(chat_id,msg_id,'نام کاربر/پروکسی را بفرست:',kb([[btn('🔙 منو','menu')]]))
    if data.startswith('newunit:'):
        st=STATE.get(uid,{}) ; st['unit']=data.split(':',1)[1]; st['step']='new_days'; STATE[uid]=st
        return edit(chat_id,msg_id,'تعداد روز اعتبار را بفرست. مثلا 30',kb([[btn('🔙 منو','menu')]]))
    if data.startswith('newsecret:'):
        mode=data.split(':',1)[1]; st=STATE.get(uid,{})
        if mode=='auto':
            r=create_user(st['username'], st['amount'], st['unit'], st['days'], 'auto',''); STATE.pop(uid,None); send(chat_id,'✅ پروکسی ساخته شد.'); return edit(chat_id,msg_id,user_text(r),user_kb(r['id']))
        st['step']='new_secret_manual'; STATE[uid]=st; return edit(chat_id,msg_id,'Secret دستی را بفرست:',kb([[btn('🔙 منو','menu')]]))
    if data.startswith('user:'):
        r=row_user(int(data.split(':')[1])); return edit(chat_id,msg_id,user_text(r),user_kb(r['id'])) if r else edit(chat_id,msg_id,'Not found',kb([[btn('🔙 Users','users')]]))
    if data.startswith('toggle:'):
        uid2=int(data.split(':')[1]); r=row_user(uid2)
        with panel.db() as con: con.execute('update users set enabled=? where id=?',(0 if r['enabled'] else 1,uid2))
        panel.restart_shared_proxy(); r=row_user(uid2); return edit(chat_id,msg_id,user_text(r),user_kb(uid2))
    if data.startswith('del:'):
        uid2=int(data.split(':')[1])
        with panel.db() as con: con.execute('delete from users where id=?',(uid2,))
        panel.restart_shared_proxy(); return edit(chat_id,msg_id,'🗑 حذف شد و سرویس ریستارت شد.',kb([[btn('🔙 Users','users')]]))
    if data.startswith('resetu:'):
        uid2=int(data.split(':')[1]); panel.reset_user_usage(uid2); r=row_user(uid2); return edit(chat_id,msg_id,user_text(r),user_kb(uid2))
    if data.startswith('editq:'):
        uid2=int(data.split(':')[1]); STATE[uid]={'step':'editq','uid':uid2}; return edit(chat_id,msg_id,'برای ویرایش این فرمت را بفرست:\n<code>50,mb,30</code>\nیعنی 50MB برای 30 روز',kb([[btn('🔙 Users','users')]]))
    if data.startswith('secret:'):
        uid2=int(data.split(':')[1]); STATE[uid]={'step':'secret','uid':uid2}; return edit(chat_id,msg_id,'Secret جدید را بفرست:',kb([[btn('🔙 Users','users')]]))
    if data=='settings': return edit(chat_id,msg_id,settings_text(),settings_kb())
    if data=='sethost': STATE[uid]={'step':'sethost'}; return edit(chat_id,msg_id,'دامنه یا IP جدید را بفرست:',kb([[btn('🔙 Settings','settings')]]))
    if data=='setsubport': STATE[uid]={'step':'setsubport'}; return edit(chat_id,msg_id,'پورت ساب جدید را بفرست:',kb([[btn('🔙 Settings','settings')]]))
    if data.startswith('lang:'):
        c=cfg(); c['language']=data.split(':',1)[1]; panel.save_cfg(c); return edit(chat_id,msg_id,'✅ زبان ذخیره شد.\n'+settings_text(),settings_kb())
    if data=='restart': panel.restart_shared_proxy(); return edit(chat_id,msg_id,'✅ سرویس پروکسی ریستارت و تغییرات اعمال شد.',main_menu())
    if data=='backup':
        try:
            with panel.db() as con: users=[dict(x) for x in con.execute('select * from users order by id')]
            b=json.dumps({'version':4,'created_at':datetime.utcnow().isoformat(),'config':cfg(),'users':users},ensure_ascii=False,indent=2).encode()
            api('sendDocument', chat_id=chat_id, caption='💾 Backup', files={'document':('mtproto-panel-backup.json', b, 'application/json')})
        except Exception as e: send(chat_id,'❌ '+str(e))
        return

def poll():
    global OFFSET
    panel.init_db()
    while True:
        c=cfg(); token=c.get('telegram_bot_token','').strip(); adm=str(c.get('telegram_admin_id','')).strip()
        if not token or not adm:
            time.sleep(5); continue
        try:
            res=requests.get(f'https://api.telegram.org/bot{token}/getUpdates', params={'offset':OFFSET,'timeout':25}, timeout=35).json()
            for u in res.get('result',[]):
                OFFSET=max(OFFSET, u['update_id']+1)
                if 'message' in u:
                    m=u['message']; uid=m['from']['id']; chat=m['chat']['id']; text=m.get('text','')
                    if text.startswith('/start'):
                        if allowed(uid): send(chat,'✅ ربات مدیریت MTProto آماده است.',main_menu())
                        else: deny(chat)
                    else: handle_text(uid,chat,text)
                elif 'callback_query' in u:
                    handle_cb(u['callback_query'])
        except Exception:
            traceback.print_exc(); time.sleep(3)

if __name__=='__main__':
    poll()
