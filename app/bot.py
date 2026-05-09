import threading, time, requests, re
from .config import load_env
from .db import db, now_ts, log
from .proxy import make_secret, restart_proxy, mtproto_link, public_host

STATE = {}

def gb(n): return int(float(n) * 1024**3)
def mb(n): return int(float(n) * 1024**2)

def send(token, chat_id, text, keyboard=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        data["reply_markup"] = keyboard
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json=data, timeout=10)
    except Exception:
        pass

def kb(rows):
    return {"keyboard": rows, "resize_keyboard": True}

def main_menu():
    return kb([[{"text":"➕ ساخت پروکسی"},{"text":"📋 لیست پروکسی‌ها"}],
               [{"text":"📊 وضعیت سرور"},{"text":"⚙️ تنظیمات"}],
               [{"text":"💾 بکاپ"}]])

def bot_loop():
    env = load_env()
    token = env.get("BOT_TOKEN", "")
    admin = str(env.get("BOT_ADMIN_ID", ""))
    if not token or not admin:
        return
    offset = 0
    while True:
        try:
            r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", params={"timeout": 30, "offset": offset}, timeout=40).json()
            for upd in r.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                chat = str((msg.get("chat") or {}).get("id", ""))
                text = (msg.get("text") or "").strip()
                if chat != admin:
                    continue
                handle_msg(token, chat, text)
        except Exception as e:
            time.sleep(5)

def handle_msg(token, chat, text):
    st = STATE.get(chat)
    if text == "/start" or text == "🏠 منو":
        STATE.pop(chat, None)
        return send(token, chat, "پنل ربات آماده است.", main_menu())

    if text == "➕ ساخت پروکسی":
        STATE[chat] = {"step": "days"}
        return send(token, chat, "چند روز اعتبار داشته باشد؟", kb([[{"text":"30"},{"text":"60"},{"text":"90"}],[{"text":"لغو"}]]))

    if text == "📋 لیست پروکسی‌ها":
        with db() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY id DESC LIMIT 50").fetchall()
        if not rows:
            return send(token, chat, "پروکسی‌ای ساخته نشده.", main_menu())
        buttons = [[{"text": f"👤 {r['name']}"}] for r in rows]
        buttons.append([{"text":"🏠 منو"}])
        return send(token, chat, "یکی را انتخاب کن:", kb(buttons))

    if text.startswith("👤 "):
        name = text[2:].strip()
        with db() as conn:
            r = conn.execute("SELECT * FROM users WHERE name=?", (name,)).fetchone()
        if not r:
            return send(token, chat, "پیدا نشد.", main_menu())
        env = load_env()
        host = env.get("PUBLIC_HOST") or "SERVER-IP"
        link = mtproto_link(host, env.get("PROXY_PORT", "8800"), r["secret"])
        remain = "نامحدود" if not r["limit_bytes"] else f"{max(0, r['limit_bytes']-r['used_bytes'])/1024**3:.2f} GB"
        status = "فعال" if r["active"] else "غیرفعال"
        return send(token, chat, f"<b>{r['name']}</b>\nوضعیت: {status}\nمانده حجم: {remain}\n\n<code>{link}</code>", main_menu())

    if text == "💾 بکاپ":
        return send(token, chat, "بکاپ از داخل پنل: Settings > Download Backup", main_menu())

    if text == "لغو":
        STATE.pop(chat, None)
        return send(token, chat, "لغو شد.", main_menu())

    if st:
        try:
            if st["step"] == "days":
                st["days"] = int(text)
                st["step"] = "unit"
                return send(token, chat, "واحد حجم؟", kb([[{"text":"GB"},{"text":"MB"}],[{"text":"لغو"}]]))
            if st["step"] == "unit":
                if text.upper() not in ("GB","MB"):
                    raise ValueError()
                st["unit"] = text.upper()
                st["step"] = "volume"
                return send(token, chat, "حجم را عددی وارد کن:", kb([[{"text":"10"},{"text":"50"},{"text":"100"}],[{"text":"لغو"}]]))
            if st["step"] == "volume":
                st["volume"] = float(text)
                st["step"] = "name"
                return send(token, chat, "اسم کاربر را وارد کن:", kb([[{"text":"لغو"}]]))
            if st["step"] == "name":
                name = re.sub(r"[^a-zA-Z0-9_\\-آ-ی]", "", text)[:32]
                if not name:
                    raise ValueError()
                limit = gb(st["volume"]) if st["unit"] == "GB" else mb(st["volume"])
                expire = now_ts() + int(st["days"]) * 86400
                secret = make_secret()
                token_sub = __import__("secrets").token_hex(16)
                ts = now_ts()
                with db() as conn:
                    conn.execute("INSERT INTO users(name,secret,limit_bytes,used_bytes,expire_at,active,sub_token,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                 (name, secret, limit, 0, expire, 1, token_sub, ts, ts))
                restart_proxy()
                STATE.pop(chat, None)
                env = load_env()
                host = env.get("PUBLIC_HOST") or "SERVER-IP"
                link = mtproto_link(host, env.get("PROXY_PORT", "8800"), secret)
                return send(token, chat, f"ساخته شد:\n<code>{link}</code>", main_menu())
        except Exception:
            return send(token, chat, "مقدار درست نیست. دوباره وارد کن یا لغو را بزن.")

def start_bot_thread():
    t = threading.Thread(target=bot_loop, daemon=True)
    t.start()
