from fastapi.responses import FileResponse
import shutil
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import psutil
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

APP_DIR = Path(os.getenv("APP_DIR", "/opt/delta-proxy-panel"))
DB_PATH = Path(os.getenv("DB_PATH", str(APP_DIR / "delta.db")))
ENV_PUBLIC_HOST = os.getenv("PUBLIC_HOST", "")
ENV_PROXY_PORT = int(os.getenv("PROXY_PORT", "443"))
ENV_SUB_PORT = int(os.getenv("SUB_PORT", "2096"))
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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()




def parse_dt(value):
    """Parse saved ISO datetime values safely for public subscription pages.

    Older database rows may contain None, empty strings, timezone-aware ISO values,
    or naive ISO values. This helper normalizes them so the sub-link page never
    crashes with NameError or timezone comparison errors.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def setting(key: str, default: str = "") -> str:
    with db() as conn:
        row = conn.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
    return row["v"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO settings(k,v) VALUES (?,?)", (key, value))


def ensure_column(conn: sqlite3.Connection, table: str, col: str, ddl: str) -> None:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)")
        conn.execute("""
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
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_states (
                chat_id TEXT PRIMARY KEY,
                state TEXT,
                payload TEXT,
                updated_at TEXT
            )
        """)
        ensure_column(conn, "users", "port", "port INTEGER")
        ensure_column(conn, "users", "rx_bytes", "rx_bytes INTEGER DEFAULT 0")
        ensure_column(conn, "users", "tx_bytes", "tx_bytes INTEGER DEFAULT 0")
        ensure_column(conn, "users", "last_seen", "last_seen TEXT")
        ensure_column(conn, "users", "disabled_reason", "disabled_reason TEXT")
        ensure_column(conn, "users", "note", "note TEXT")
        ensure_column(conn, "users", "created_at", "created_at TEXT")
        conn.execute("UPDATE users SET created_at=? WHERE created_at IS NULL OR created_at=''", (now_iso(),))
        existing_admin = conn.execute('SELECT v FROM settings WHERE k="admin_username"').fetchone()
        if not existing_admin:
            set_setting(conn, "admin_username", ADMIN_USERNAME)
            set_setting(conn, "admin_hash", pass_hash(ADMIN_PASSWORD))
        defaults = {
            "public_host": ENV_PUBLIC_HOST,
            "proxy_port": str(ENV_PROXY_PORT),
            "sub_port": str(ENV_SUB_PORT),
            "panel_title": "DELTA MTProto",
            "theme": "dark",
            "telegram_bot_token": "",
            "telegram_chat_id": "",
            "telegram_bot_enabled": "1",
            "telegram_update_offset": "0",
        }
        for k, v in defaults.items():
            if not conn.execute("SELECT 1 FROM settings WHERE k=?", (k,)).fetchone():
                set_setting(conn, k, v)
        # migrate old users without a dedicated port
        base = int(setting("proxy_port", str(ENV_PROXY_PORT)) or ENV_PROXY_PORT)
        rows = conn.execute("SELECT id FROM users WHERE port IS NULL OR port=0 ORDER BY id ASC").fetchall()
        for i, r in enumerate(rows):
            conn.execute("UPDATE users SET port=? WHERE id=?", (next_free_port(conn, base + i, exclude_id=r["id"]), r["id"]))
        conn.commit()


def is_authed(req: Request) -> bool:
    token = req.cookies.get("delta_session", "")
    good = hmac.new(SECRET_KEY.encode(), b"login", hashlib.sha256).hexdigest()
    return hmac.compare_digest(token, good)


def require(req: Request) -> None:
    if not is_authed(req):
        raise HTTPException(status_code=401, detail="unauthorized")


def parse_expire_days(days: Optional[str], current: Optional[str] = None, keep_when_blank: bool = False) -> Optional[str]:
    if days is None or str(days).strip() == "":
        return current if keep_when_blank else None
    try:
        d = int(float(str(days).strip()))
    except ValueError:
        raise HTTPException(status_code=400, detail="expire_days must be a number")
    if d <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(days=d)).isoformat()


def days_left(expire_at: Optional[str]) -> Optional[int]:
    if not expire_at:
        return None
    try:
        end = datetime.fromisoformat(expire_at.replace("Z", "+00:00"))
        diff = end - datetime.now(timezone.utc)
        return max(0, diff.days + (1 if diff.seconds else 0))
    except Exception:
        return None


def is_not_expired(expire_at: Optional[str]) -> bool:
    if not expire_at:
        return True
    try:
        return datetime.fromisoformat(expire_at.replace("Z", "+00:00")) > datetime.now(timezone.utc)
    except Exception:
        return True


def proxy_host() -> str:
    return setting("public_host", ENV_PUBLIC_HOST) or ENV_PUBLIC_HOST


def base_proxy_port() -> int:
    try:
        return int(setting("proxy_port", str(ENV_PROXY_PORT)))
    except Exception:
        return ENV_PROXY_PORT


def sub_port() -> int:
    try:
        return int(setting("sub_port", str(ENV_SUB_PORT)))
    except Exception:
        return ENV_SUB_PORT


def sub_link(secret: str) -> str:
    return f"http://{proxy_host()}:{sub_port()}/s/{secret}"


def proxy_link(secret: str, port: int | None = None) -> str:
    # Shared Port mode: all users connect to one public port; user identity is the secret.
    return f"tg://proxy?server={proxy_host()}&port={base_proxy_port()}&secret={secret}"


def next_free_port(conn: sqlite3.Connection, start: int, exclude_id: Optional[int] = None) -> int:
    used = {int(r["port"]) for r in conn.execute("SELECT port FROM users WHERE port IS NOT NULL AND port>0").fetchall()}
    if exclude_id:
        row = conn.execute("SELECT port FROM users WHERE id=?", (exclude_id,)).fetchone()
        if row and row["port"]:
            used.discard(int(row["port"]))
    port = max(1, min(65535, int(start)))
    while port in used and port < 65535:
        port += 1
    if port > 65535:
        raise HTTPException(status_code=400, detail="no free port")
    return port


def quota_ok(row) -> bool:
    try:
        quota = float(row["quota_gb"] or 0)
        used = float(row["used_gb"] or 0)
        return quota <= 0 or used < quota
    except Exception:
        return True


def active_users() -> list[sqlite3.Row]:
    # Only users that are enabled, not expired, and not over quota are rendered into MTProxy config.
    # This is the actual enforcement layer: once a user is disabled/expired/over-quota,
    # their secret is removed from the shared MTProxy service and cannot connect anymore.
    with db() as conn:
        rows = conn.execute("SELECT * FROM users WHERE enabled=1 ORDER BY id ASC").fetchall()
    return [row for row in rows if is_not_expired(row["expire_at"]) and quota_ok(row)]



def create_user_core(name: str, expire_days: str = "", quota_gb: float = 0, note: str = "") -> dict:
    """Create a user/proxy from both web panel and Telegram bot."""
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("name is required")
    quota = float(quota_gb or 0)
    if quota < 0:
        raise ValueError("quota must be positive")
    expire_at = parse_expire_days(expire_days or "")
    secret = secrets.token_hex(16)
    port = base_proxy_port()  # v4+ shared-port mode: all users use one public port
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO users(name, secret, enabled, expire_at, quota_gb, used_gb, port, rx_bytes, tx_bytes, last_seen, disabled_reason, note, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (clean_name, secret, 1, expire_at, quota, 0, port, 0, 0, None, None, note or "", now_iso()),
        )
        conn.commit()
        uid = int(cur.lastrowid)
    render_proxy_service()
    return {"id": uid, "name": clean_name, "secret": secret, "enabled": 1, "expire_at": expire_at, "quota_gb": quota, "used_gb": 0, "port": port, "link": proxy_link(secret, port), "sub_link": sub_link(secret)}


def update_user_core(uid: int, name: Optional[str] = None, expire_days: Optional[str] = None, quota_gb: Optional[float] = None,
                     used_gb: Optional[float] = None, enabled: Optional[int] = None, note: Optional[str] = None) -> None:
    """Update a user/proxy from both web panel and Telegram bot."""
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            raise ValueError("user not found")
        updates = []
        values = []
        if name is not None:
            clean_name = str(name).strip()
            if not clean_name:
                raise ValueError("name is required")
            updates.append("name=?"); values.append(clean_name)
        if expire_days is not None:
            updates.append("expire_at=?"); values.append(parse_expire_days(expire_days or ""))
        if quota_gb is not None:
            q = float(quota_gb or 0)
            if q < 0:
                raise ValueError("quota must be positive")
            updates.append("quota_gb=?"); values.append(q)
        if used_gb is not None:
            u = float(used_gb or 0)
            if u < 0:
                raise ValueError("used must be positive")
            updates.append("used_gb=?"); values.append(u)
        if enabled is not None:
            updates.append("enabled=?"); values.append(1 if int(enabled) else 0)
            if int(enabled):
                updates.append("disabled_reason=?"); values.append(None)
        if note is not None:
            updates.append("note=?"); values.append(note)
        if updates:
            values.append(uid)
            conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id=?", values)
            conn.commit()
    render_proxy_service()

def svc_name(uid: int) -> str:
    return f"mtpulse-u{uid}"


def render_proxy_service() -> None:
    users = active_users()
    service_dir = Path("/etc/systemd/system")
    service_dir.mkdir(parents=True, exist_ok=True)

    # V4 Shared Port mode: one MTProxy instance, one public port, multiple -S secrets.
    # This keeps all users on the same port. Per-user traffic cannot be exact unless
    # MTProxy is patched/logged by secret; traffic below is total shared-port traffic.
    for service in service_dir.glob("mtpulse-u*.service"):
        subprocess.run(["systemctl", "disable", "--now", service.stem], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        try:
            service.unlink()
        except Exception:
            pass

    shared = service_dir / "mtpulse-shared.service"
    if not users:
        subprocess.run(["systemctl", "disable", "--now", "mtpulse-shared"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        try:
            shared.unlink()
        except Exception:
            pass
        subprocess.run(["systemctl", "daemon-reload"], check=False)
        return

    secrets_args = " ".join(f"-S {u['secret']}" for u in users)
    p_arg = f" -P {SPONSOR_TAG}" if SPONSOR_TAG else ""
    exec_start = (
        f"/usr/local/bin/mtproto-proxy -u nobody -p 8800 -H {base_proxy_port()} "
        f"{secrets_args}{p_arg} --aes-pwd /etc/mtpulse/proxy-secret /etc/mtpulse/proxy-multi.conf -M 1"
    )
    shared.write_text(f"""[Unit]
Description=DELTA MTProto shared-port service
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
""")
    subprocess.run(["systemctl", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "enable", "--now", "mtpulse-shared"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    subprocess.run(["systemctl", "restart", "mtpulse-shared"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    ensure_traffic_rules()


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, text=True, capture_output=True, check=False).stdout


def ensure_traffic_rules() -> None:
    if os.geteuid() != 0:
        return
    port = base_proxy_port()
    subprocess.run(["iptables", "-N", "DELTA_MTPROTO_TRAFFIC"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if subprocess.run(["iptables", "-C", "INPUT", "-j", "DELTA_MTPROTO_TRAFFIC"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode != 0:
        subprocess.run(["iptables", "-I", "INPUT", "1", "-j", "DELTA_MTPROTO_TRAFFIC"], check=False)
    if subprocess.run(["iptables", "-C", "OUTPUT", "-j", "DELTA_MTPROTO_TRAFFIC"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode != 0:
        subprocess.run(["iptables", "-I", "OUTPUT", "1", "-j", "DELTA_MTPROTO_TRAFFIC"], check=False)
    existing = run(["iptables", "-S", "DELTA_MTPROTO_TRAFFIC"])
    cin = f"delta-shared-in-{port}"
    cout = f"delta-shared-out-{port}"
    if cin not in existing:
        subprocess.run(["iptables", "-A", "DELTA_MTPROTO_TRAFFIC", "-p", "tcp", "--dport", str(port), "-m", "comment", "--comment", cin, "-j", "RETURN"], check=False)
    if cout not in existing:
        subprocess.run(["iptables", "-A", "DELTA_MTPROTO_TRAFFIC", "-p", "tcp", "--sport", str(port), "-m", "comment", "--comment", cout, "-j", "RETURN"], check=False)


def parse_iptables_counters() -> dict[int, dict[str, int]]:
    ensure_traffic_rules()
    port = base_proxy_port()
    out = run(["iptables", "-L", "DELTA_MTPROTO_TRAFFIC", "-v", "-x", "-n"])
    data: dict[int, dict[str, int]] = {port: {"rx": 0, "tx": 0}}
    for line in out.splitlines():
        m_in = re.search(r"^\s*\d+\s+(\d+).*dpt:(\d+).*delta-shared-in-(\d+)", line)
        m_out = re.search(r"^\s*\d+\s+(\d+).*spt:(\d+).*delta-shared-out-(\d+)", line)
        if m_in:
            data[port]["rx"] = int(m_in.group(1))
        if m_out:
            data[port]["tx"] = int(m_out.group(1))
    return data


def online_by_port() -> dict[int, int]:
    out = run(["ss", "-Htan", "state", "established"])
    counts: dict[int, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3]
        try:
            port = int(local.rsplit(":", 1)[-1])
            counts[port] = counts.get(port, 0) + 1
        except Exception:
            pass
    return counts


def _recent_dt(value: str | None, seconds: int = 900) -> bool:
    dt = parse_dt(value)
    if not dt:
        return False
    try:
        return (datetime.now() - dt).total_seconds() <= seconds
    except Exception:
        return False


def sync_traffic() -> None:
    counters = parse_iptables_counters()
    shared_port = base_proxy_port()
    c = counters.get(shared_port, {"rx": 0, "tx": 0})
    rx = int(c.get("rx") or 0)
    tx = int(c.get("tx") or 0)
    total_bytes = rx + tx

    needs_render = False
    with db() as conn:
        prev_total = int(setting("shared_total_bytes_last", "0") or 0)
        # iptables counters may reset after reboot/service changes. Never subtract.
        delta_bytes = max(0, total_bytes - prev_total) if total_bytes >= prev_total else 0

        owner = select_shared_owner(conn)
        if delta_bytes > 0 and owner:
            quota_bytes = gb_to_bytes(owner["quota_gb"])
            used_bytes = gb_to_bytes(owner["used_gb"])
            remaining_bytes = max(0, quota_bytes - used_bytes) if quota_bytes > 0 else delta_bytes
            charge_bytes = min(delta_bytes, remaining_bytes) if quota_bytes > 0 else delta_bytes
            new_used_bytes = used_bytes + charge_bytes
            new_used_gb = bytes_to_gb(new_used_bytes)
            conn.execute(
                "UPDATE users SET used_gb=?, rx_bytes=COALESCE(rx_bytes,0)+?, tx_bytes=COALESCE(tx_bytes,0)+?, last_seen=? WHERE id=?",
                (new_used_gb, charge_bytes, 0, now_iso(), owner["id"]),
            )
            if quota_bytes > 0 and new_used_bytes >= quota_bytes:
                conn.execute(
                    "UPDATE users SET enabled=0, disabled_reason=? WHERE id=?",
                    ("quota", owner["id"]),
                )
                set_setting(conn, "shared_current_owner_id", "0")
                needs_render = True
            if delta_bytes > charge_bytes:
                old_unassigned = int(setting("shared_unassigned_bytes", "0") or 0)
                set_setting(conn, "shared_unassigned_bytes", str(old_unassigned + (delta_bytes - charge_bytes)))
        elif delta_bytes > 0:
            # Ambiguous shared-port traffic is deliberately not charged to all users.
            # This prevents offline users losing traffic and prevents one secret from
            # silently consuming another secret's quota.
            old_unassigned = int(setting("shared_unassigned_bytes", "0") or 0)
            set_setting(conn, "shared_unassigned_bytes", str(old_unassigned + delta_bytes))

        rows = conn.execute("SELECT id,quota_gb,used_gb,enabled,expire_at FROM users").fetchall()
        for r in rows:
            over_quota = bool(r["quota_gb"] and float(r["used_gb"] or 0) >= float(r["quota_gb"]))
            expired = not is_not_expired(r["expire_at"])
            if int(r["enabled"] or 0) and (over_quota or expired):
                reason = "quota" if over_quota else "expired"
                conn.execute("UPDATE users SET enabled=0, disabled_reason=? WHERE id=?", (reason, r["id"]))
                if int(setting("shared_current_owner_id", "0") or 0) == int(r["id"]):
                    set_setting(conn, "shared_current_owner_id", "0")
                needs_render = True

        set_setting(conn, "shared_rx_bytes", str(rx))
        set_setting(conn, "shared_tx_bytes", str(tx))
        set_setting(conn, "shared_total_bytes_last", str(total_bytes))
        set_setting(conn, "traffic_accounting_mode", "shared_single_owner_strict")
        conn.commit()
    if needs_render:
        render_proxy_service()

def telegram_send(text: str) -> dict:
    chat_id = setting("telegram_chat_id", "").strip()
    if not chat_id:
        return {"ok": False, "error": "chat id is empty"}
    return telegram_send_to(chat_id, text)


def fmt_gb(v, zero_unlimited: bool = True) -> str:
    try:
        n = float(v or 0)
    except Exception:
        n = 0
    if n <= 0:
        return "نامحدود" if zero_unlimited else "0 MB"
    if n < 1:
        return f"{n * 1024:.0f} MB"
    return f"{n:.2f}".rstrip("0").rstrip(".") + " GB"


def gb_to_bytes(v) -> int:
    try:
        return int(float(v or 0) * 1024 * 1024 * 1024)
    except Exception:
        return 0


def bytes_to_gb(v) -> float:
    try:
        return round(int(v or 0) / 1024 / 1024 / 1024, 6)
    except Exception:
        return 0.0


def user_can_consume(row) -> bool:
    return int(row["enabled"] or 0) == 1 and is_not_expired(row["expire_at"]) and quota_ok(row)


def select_shared_owner(conn: sqlite3.Connection):
    """Choose exactly one accounting owner in shared-port mode.

    Stock Telegram MTProxy exposes only per-port traffic, not per-secret counters.
    To avoid the old bug where every offline user lost quota, this function never
    spreads bytes between users. It keeps one current owner while that secret is
    valid. If there is no owner, it selects the only recently opened sub-link user;
    if multiple users are recent, bytes remain unassigned until one is selected by
    opening/using that user's sub page.
    """
    owner_id = int(setting("shared_current_owner_id", "0") or 0)
    if owner_id:
        owner = conn.execute("SELECT * FROM users WHERE id=?", (owner_id,)).fetchone()
        if owner and user_can_consume(owner):
            return owner
        set_setting(conn, "shared_current_owner_id", "0")

    rows = conn.execute("SELECT * FROM users WHERE enabled=1 ORDER BY COALESCE(last_seen,'' ) DESC, id DESC").fetchall()
    recent = [r for r in rows if user_can_consume(r) and _recent_dt(r["last_seen"], 6 * 3600)]
    if len(recent) == 1:
        set_setting(conn, "shared_current_owner_id", str(recent[0]["id"]))
        return recent[0]

    active = [r for r in rows if user_can_consume(r)]
    if len(active) == 1:
        set_setting(conn, "shared_current_owner_id", str(active[0]["id"]))
        return active[0]
    return None


def bot_token() -> str:
    return setting("telegram_bot_token", "").strip()


def bot_allowed_chat() -> str:
    return setting("telegram_chat_id", "").strip()


def telegram_api(method: str, data: dict | None = None) -> dict:
    token = bot_token()
    if not token:
        return {"ok": False, "error": "bot token is empty"}
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        payload = urllib.parse.urlencode(data or {}).encode() if data is not None else None
        with urllib.request.urlopen(url, data=payload, timeout=20) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}



def tg_markup(buttons: list[list[tuple[str, str]]]) -> str:
    return json.dumps({"inline_keyboard": [[{"text": t, "callback_data": c} for t, c in row] for row in buttons]}, ensure_ascii=False)


def telegram_send_to(chat_id: str, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> dict:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "false"}
    if buttons:
        payload["reply_markup"] = tg_markup(buttons)
    return telegram_api("sendMessage", payload)


def telegram_edit(chat_id: str, message_id: int, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> dict:
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "false"}
    if buttons:
        payload["reply_markup"] = tg_markup(buttons)
    return telegram_api("editMessageText", payload)


def telegram_answer_callback(callback_id: str, text: str = "") -> dict:
    return telegram_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def set_bot_state(chat_id: str, state: str, payload: dict | None = None) -> None:
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO bot_states(chat_id,state,payload,updated_at) VALUES (?,?,?,?)", (chat_id, state, json.dumps(payload or {}, ensure_ascii=False), now_iso()))
        conn.commit()


def get_bot_state(chat_id: str) -> tuple[str, dict]:
    with db() as conn:
        row = conn.execute("SELECT state,payload FROM bot_states WHERE chat_id=?", (chat_id,)).fetchone()
    if not row:
        return "", {}
    try:
        return row["state"] or "", json.loads(row["payload"] or "{}")
    except Exception:
        return row["state"] or "", {}


def clear_bot_state(chat_id: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM bot_states WHERE chat_id=?", (chat_id,))
        conn.commit()


def main_menu_text() -> str:
    return "🤖 <b>DELTA MTProto Bot</b>\nاز دکمه‌های زیر پنل را مدیریت کن."


def main_menu_buttons() -> list[list[tuple[str, str]]]:
    return [
        [("➕ ساخت کاربر", "new:start"), ("👥 لیست پروکسی‌ها", "users:1")],
        [("📊 وضعیت سرور", "overview"), ("⚙️ تنظیمات", "settings")],
        [("📦 بکاپ", "backup"), ("🔄 ری‌استارت پروکسی", "restart")],
    ]


def settings_buttons() -> list[list[tuple[str, str]]]:
    return [
        [("🌐 سرور / دامنه", "settings:server"), ("🔐 ادمین پنل", "settings:admin")],
        [("🎨 تم سایت", "settings:theme"), ("🤖 تنظیمات ربات", "settings:bot")],
        [("📥 ایمپورت بکاپ", "settings:import"), ("⬅️ بازگشت", "menu")],
    ]


def user_detail_text(r: sqlite3.Row | dict) -> str:
    d = dict(r)
    used = float(d.get("used_gb") or 0); quota = float(d.get("quota_gb") or 0)
    remain = "نامحدود" if quota <= 0 else fmt_gb(max(0, quota - used))
    return (
        f"👤 <b>{d['name']}</b>  <code>#{d['id']}</code>\n"
        f"وضعیت: {'✅ فعال' if int(d.get('enabled') or 0) and is_not_expired(d.get('expire_at')) else '⛔️ غیرفعال'}\n"
        f"حجم کل: {fmt_gb(quota)}\n"
        f"مصرف شده: {fmt_gb(used, False)}\n"
        f"باقی‌مانده: {remain}\n"
        f"روزهای باقی‌مانده: {days_left(d.get('expire_at')) if d.get('expire_at') else '∞'}\n"
        f"پورت مشترک: <code>{base_proxy_port()}</code>\n\n"
        f"🔗 پروکسی:\n{proxy_link(d['secret'])}\n\n🌐 ساب لینک:\n{sub_link(d['secret'])}"
    )


def user_detail_buttons(uid: int) -> list[list[tuple[str, str]]]:
    return [
        [("➕ افزایش تاریخ", f"u:{uid}:days"), ("📦 تغییر حجم", f"u:{uid}:quota")],
        [("✏️ تغییر اسم", f"u:{uid}:name"), ("♻️ ریست مصرف", f"u:{uid}:reset")],
        [("✅/⛔️ فعال/غیرفعال", f"u:{uid}:toggle"), ("🗑 حذف", f"u:{uid}:delask")],
        [("⬅️ لیست", "users:1"), ("🏠 منو", "menu")],
    ]


def bot_overview_text() -> str:
    sync_traffic()
    mem = psutil.virtual_memory(); disk = psutil.disk_usage("/"); online = online_by_port().get(base_proxy_port(), 0)
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        enabled = conn.execute("SELECT COUNT(*) n FROM users WHERE enabled=1").fetchone()["n"]
    return f"📊 <b>وضعیت سرور</b>\nCPU: {psutil.cpu_percent(interval=0.1)}%\nRAM: {mem.percent}%\nDisk: {disk.percent}%\nUsers: {enabled}/{total}\nOnline: {online}\nHost: <code>{proxy_host()}</code>\nPort: <code>{base_proxy_port()}</code>"


def ask(chat_id: str, state: str, text: str, payload: dict | None = None) -> None:
    set_bot_state(chat_id, state, payload or {})
    telegram_send_to(chat_id, text, [[("لغو", "cancel")]])


def handle_bot_text_state(chat_id: str, text: str) -> bool:
    state, payload = get_bot_state(chat_id)
    if not state:
        return False
    try:
        if state == "new_days":
            days = int(float(text));
            if days <= 0: raise ValueError()
            payload["days"] = days
            set_bot_state(chat_id, "new_unit", payload)
            telegram_send_to(chat_id, "حجم را با چه واحدی وارد می‌کنی؟", [[("GB", "new:unit:gb"), ("MB", "new:unit:mb")], [("لغو", "cancel")]])
            return True
        if state == "new_unit":
            t = text.strip().lower()
            if t not in {"gb", "g", "گیگ", "mb", "m", "مگ"}:
                raise ValueError("unit")
            payload["unit"] = "gb" if t in {"gb", "g", "گیگ"} else "mb"
            set_bot_state(chat_id, "new_volume", payload)
            telegram_send_to(chat_id, f"حجم را وارد کن ({payload['unit'].upper()}):", [[("لغو", "cancel")]])
            return True
        if state == "new_volume":
            vol = float(text.replace(",", "."));
            if vol < 0: raise ValueError()
            unit = payload.get("unit", "gb")
            payload["quota_gb"] = vol if unit == "gb" else vol / 1024
            set_bot_state(chat_id, "new_name", payload)
            telegram_send_to(chat_id, "اسم کاربر را وارد کن:", [[("لغو", "cancel")]])
            return True
        if state == "new_name":
            name = text.strip()
            if not name: raise ValueError("name")
            u = create_user_core(name, str(payload.get("days", "")), float(payload.get("quota_gb") or 0), "created by button bot")
            clear_bot_state(chat_id)
            telegram_send_to(chat_id, f"✅ پروکسی ساخته شد\n\n" + user_detail_text({"id": u["id"], "name": u["name"], "secret": u["secret"], "enabled": 1, "expire_at": u["expire_at"], "quota_gb": u["quota_gb"], "used_gb": 0}), main_menu_buttons())
            return True
        if state.startswith("edit:"):
            uid = int(payload["uid"]); field = payload["field"]
            if field == "days":
                days = int(float(text)); update_user_core(uid, expire_days=str(days))
            elif field == "quota":
                val = float(text.replace(",", ".")); unit = payload.get("unit", "gb"); update_user_core(uid, quota_gb=(val if unit == "gb" else val/1024))
            elif field == "name":
                update_user_core(uid, name=text.strip())
            elif field == "used":
                update_user_core(uid, used_gb=float(text.replace(",", ".")))
            clear_bot_state(chat_id)
            with db() as conn: r = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            telegram_send_to(chat_id, "✅ تغییرات ذخیره شد.\n\n" + user_detail_text(r), user_detail_buttons(uid))
            return True
        if state == "set_server_host":
            with db() as conn: set_setting(conn, "public_host", text.strip()); conn.commit()
            clear_bot_state(chat_id); render_proxy_service()
            telegram_send_to(chat_id, "✅ دامنه/IP ذخیره شد.", settings_buttons()); return True
        if state == "set_server_port":
            port = int(text); assert 1 <= port <= 65535
            with db() as conn: set_setting(conn, "proxy_port", str(port)); conn.commit()
            clear_bot_state(chat_id); render_proxy_service()
            telegram_send_to(chat_id, "✅ پورت مشترک ذخیره شد.", settings_buttons()); return True
        if state == "set_admin_user":
            with db() as conn: set_setting(conn, "admin_username", text.strip()); conn.commit()
            clear_bot_state(chat_id); telegram_send_to(chat_id, "✅ نام کاربری پنل تغییر کرد.", settings_buttons()); return True
        if state == "set_admin_pass":
            with db() as conn: set_setting(conn, "admin_hash", pass_hash(text.strip())); conn.commit()
            clear_bot_state(chat_id); telegram_send_to(chat_id, "✅ رمز پنل تغییر کرد.", settings_buttons()); return True
        if state == "set_bot_token":
            with db() as conn: set_setting(conn, "telegram_bot_token", text.strip()); conn.commit()
            clear_bot_state(chat_id); telegram_send_to(chat_id, "✅ توکن ربات ذخیره شد.", settings_buttons()); return True
        if state == "set_bot_chat":
            with db() as conn: set_setting(conn, "telegram_chat_id", text.strip()); conn.commit()
            clear_bot_state(chat_id); telegram_send_to(chat_id, "✅ Chat ID ذخیره شد.", settings_buttons()); return True
        if state == "import_backup":
            data = json.loads(text)
            users_data = data.get("users", []); settings_data = data.get("settings", {})
            with db() as conn:
                for k, v in settings_data.items():
                    if k in {"public_host", "proxy_port", "sub_port", "panel_title", "admin_username", "admin_hash", "theme", "telegram_bot_token", "telegram_chat_id", "telegram_bot_enabled"}: set_setting(conn, k, str(v))
                conn.execute("DELETE FROM users")
                for u in users_data:
                    conn.execute("INSERT INTO users(name, secret, enabled, expire_at, quota_gb, used_gb, port, rx_bytes, tx_bytes, last_seen, disabled_reason, note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (u.get("name", "user"), u.get("secret") or secrets.token_hex(16), int(u.get("enabled", 1)), u.get("expire_at"), float(u.get("quota_gb") or 0), float(u.get("used_gb") or 0), base_proxy_port(), int(u.get("rx_bytes") or 0), int(u.get("tx_bytes") or 0), u.get("last_seen"), u.get("disabled_reason"), u.get("note", ""), u.get("created_at") or now_iso()))
                conn.commit()
            clear_bot_state(chat_id); render_proxy_service(); telegram_send_to(chat_id, f"✅ بکاپ ایمپورت شد. تعداد کاربران: {len(users_data)}", settings_buttons()); return True
    except Exception:
        telegram_send_to(chat_id, "❌ مقدار وارد شده درست نیست. دوباره وارد کن یا لغو را بزن.", [[("لغو", "cancel")]])
        return True
    return False


def handle_bot_callback(callback: dict) -> None:
    callback_id = callback.get("id", "")
    data = callback.get("data", "")
    msg = callback.get("message", {})
    chat_id = str(msg.get("chat", {}).get("id", ""))
    message_id = int(msg.get("message_id", 0) or 0)
    allowed = bot_allowed_chat()
    if allowed and chat_id != allowed:
        telegram_answer_callback(callback_id, "غیرمجاز")
        return
    telegram_answer_callback(callback_id)
    try:
        if data == "cancel":
            clear_bot_state(chat_id); telegram_edit(chat_id, message_id, main_menu_text(), main_menu_buttons()); return
        if data == "menu":
            clear_bot_state(chat_id); telegram_edit(chat_id, message_id, main_menu_text(), main_menu_buttons()); return
        if data == "new:start":
            clear_bot_state(chat_id); ask(chat_id, "new_days", "چند روز اعتبار داشته باشد؟\nمثلاً: <code>30</code>"); return
        if data.startswith("new:unit:"):
            state,payload=get_bot_state(chat_id); payload["unit"] = data.rsplit(":",1)[-1]
            ask(chat_id, "new_volume", f"حجم را وارد کن ({payload['unit'].upper()}):", payload); return
        if data == "overview":
            telegram_edit(chat_id, message_id, bot_overview_text(), [[("🔄 بروزرسانی", "overview")], [("⬅️ منو", "menu")]]); return
        if data.startswith("users:"):
            with db() as conn: rows = [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY id DESC LIMIT 60").fetchall()]
            if not rows:
                telegram_edit(chat_id, message_id, "هنوز پروکسی ساخته نشده.", [[("➕ ساخت کاربر", "new:start")], [("⬅️ منو", "menu")]]); return
            buttons=[]
            for r in rows:
                icon = "✅" if int(r.get("enabled") or 0) and is_not_expired(r.get("expire_at")) else "⛔️"
                buttons.append([(f"{icon} {r['name']} | {fmt_gb(r.get('used_gb'), False)}/{fmt_gb(r.get('quota_gb'))}", f"user:{r['id']}")])
            buttons.append([("➕ ساخت کاربر", "new:start"), ("⬅️ منو", "menu")])
            telegram_edit(chat_id, message_id, "👥 <b>لیست پروکسی‌های ساخته شده</b>", buttons); return
        if data.startswith("user:"):
            uid=int(data.split(":")[1])
            with db() as conn: r=conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not r: telegram_edit(chat_id, message_id, "کاربر پیدا نشد.", main_menu_buttons()); return
            telegram_edit(chat_id, message_id, user_detail_text(r), user_detail_buttons(uid)); return
        if data.startswith("u:"):
            _, uid_s, action = data.split(":",2); uid=int(uid_s)
            if action == "days": ask(chat_id, "edit:days", "چند روز از امروز تنظیم شود؟", {"uid":uid,"field":"days"}); return
            if action == "quota": set_bot_state(chat_id, "edit:quota_unit", {"uid":uid,"field":"quota"}); telegram_send_to(chat_id, "واحد حجم را انتخاب کن:", [[("GB", f"u:{uid}:quota_gb"), ("MB", f"u:{uid}:quota_mb")], [("لغو", "cancel")]]); return
            if action in {"quota_gb","quota_mb"}: ask(chat_id, "edit:quota", f"حجم جدید را وارد کن ({'GB' if action.endswith('gb') else 'MB'}):", {"uid":uid,"field":"quota","unit":"gb" if action.endswith("gb") else "mb"}); return
            if action == "name": ask(chat_id, "edit:name", "اسم جدید را وارد کن:", {"uid":uid,"field":"name"}); return
            if action == "reset": update_user_core(uid, used_gb=0); telegram_send_to(chat_id, "✅ مصرف ریست شد."); return
            if action == "toggle":
                with db() as conn: conn.execute("UPDATE users SET enabled=CASE enabled WHEN 1 THEN 0 ELSE 1 END, disabled_reason=NULL WHERE id=?", (uid,)); conn.commit()
                render_proxy_service(); telegram_send_to(chat_id, "✅ وضعیت تغییر کرد."); return
            if action == "delask": telegram_send_to(chat_id, "حذف این کاربر قطعی است؟", [[("بله حذف کن", f"u:{uid}:delete"), ("لغو", f"user:{uid}")]]); return
            if action == "delete":
                with db() as conn: conn.execute("DELETE FROM users WHERE id=?", (uid,)); conn.commit()
                render_proxy_service(); telegram_send_to(chat_id, "🗑 حذف شد.", main_menu_buttons()); return
        if data == "settings":
            telegram_edit(chat_id, message_id, "⚙️ <b>تنظیمات</b>", settings_buttons()); return
        if data == "settings:server":
            telegram_edit(chat_id, message_id, f"🌐 <b>سرور</b>\nHost: <code>{proxy_host()}</code>\nPort: <code>{base_proxy_port()}</code>", [[("تغییر دامنه/IP", "set:host"), ("تغییر پورت", "set:port")], [("⬅️ تنظیمات", "settings")]]); return
        if data == "settings:admin":
            telegram_edit(chat_id, message_id, "🔐 <b>ادمین پنل</b>", [[("تغییر نام کاربری", "set:admin_user"), ("تغییر رمز", "set:admin_pass")], [("⬅️ تنظیمات", "settings")]]); return
        if data == "settings:theme":
            telegram_edit(chat_id, message_id, "🎨 تم سایت را انتخاب کن:", [[("Dark", "theme:dark"), ("Light", "theme:light")], [("⬅️ تنظیمات", "settings")]]); return
        if data.startswith("theme:"):
            th=data.split(":")[1]
            with db() as conn: set_setting(conn,"theme",th); conn.commit()
            telegram_send_to(chat_id, "✅ تم ذخیره شد.", settings_buttons()); return
        if data == "settings:bot":
            telegram_edit(chat_id, message_id, f"🤖 <b>ربات</b>\nEnabled: <code>{setting('telegram_bot_enabled','1')}</code>\nChat ID: <code>{setting('telegram_chat_id','')}</code>", [[("تغییر توکن", "set:bot_token"), ("تغییر Chat ID", "set:bot_chat")], [("فعال/غیرفعال", "bot:toggle"), ("⬅️ تنظیمات", "settings")]]); return
        if data == "bot:toggle":
            with db() as conn:
                cur=setting('telegram_bot_enabled','1'); set_setting(conn,'telegram_bot_enabled','0' if cur=='1' else '1'); conn.commit()
            telegram_send_to(chat_id, "✅ وضعیت ربات تغییر کرد.", settings_buttons()); return
        if data == "set:host": ask(chat_id, "set_server_host", "دامنه یا IP جدید را وارد کن:"); return
        if data == "set:port": ask(chat_id, "set_server_port", "پورت مشترک پروکسی را وارد کن:"); return
        if data == "set:admin_user": ask(chat_id, "set_admin_user", "نام کاربری جدید پنل را وارد کن:"); return
        if data == "set:admin_pass": ask(chat_id, "set_admin_pass", "رمز جدید پنل را وارد کن:"); return
        if data == "set:bot_token": ask(chat_id, "set_bot_token", "توکن جدید ربات را وارد کن:"); return
        if data == "set:bot_chat": ask(chat_id, "set_bot_chat", "Chat ID ادمین را وارد کن:"); return
        if data == "backup":
            data_json=json.dumps(backup_payload(), ensure_ascii=False, indent=2)
            if len(data_json)<3500: telegram_edit(chat_id,message_id,f"📦 <b>Backup JSON</b>\n<code>{data_json}</code>", [[("⬅️ منو", "menu")]])
            else: telegram_edit(chat_id,message_id,"📦 بکاپ آماده است ولی برای تلگرام طولانی است. از سایت Export Backup بگیر.", [[("⬅️ منو", "menu")]])
            return
        if data == "settings:import": ask(chat_id, "import_backup", "محتوای JSON بکاپ را همینجا paste کن:"); return
        if data == "restart": render_proxy_service(); telegram_edit(chat_id,message_id,"✅ پروکسی ری‌استارت شد.", main_menu_buttons()); return
    except Exception as e:
        telegram_send_to(chat_id, f"❌ خطا: {str(e)}", main_menu_buttons())


def handle_bot_message(message: dict) -> None:
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    text = (message.get("text") or "").strip()
    allowed = bot_allowed_chat()
    if not chat_id or not text:
        return
    if allowed and chat_id != allowed:
        telegram_send_to(chat_id, "⛔️ این ربات فقط برای ادمین پنل فعال است.")
        return
    if not allowed:
        with db() as conn:
            set_setting(conn, "telegram_chat_id", chat_id)
            conn.commit()
    if text in {"/start", "/help", "منو", "menu"}:
        clear_bot_state(chat_id)
        telegram_send_to(chat_id, main_menu_text(), main_menu_buttons())
        return
    if handle_bot_text_state(chat_id, text):
        return
    telegram_send_to(chat_id, "برای مدیریت از دکمه‌ها استفاده کن.", main_menu_buttons())

def bot_poll_loop() -> None:
    last_token = ""
    while True:
        try:
            if setting("telegram_bot_enabled", "1") != "1" or not bot_token():
                time.sleep(5); continue
            token = bot_token()
            if token != last_token:
                last_token = token
            offset = int(setting("telegram_update_offset", "0") or 0)
            res = telegram_api("getUpdates", {"timeout": 25, "offset": offset, "allowed_updates": json.dumps(["message", "callback_query"])})
            if res.get("ok"):
                for upd in res.get("result", []):
                    update_id = int(upd.get("update_id", 0))
                    with db() as conn:
                        set_setting(conn, "telegram_update_offset", str(update_id + 1)); conn.commit()
                    if "message" in upd:
                        handle_bot_message(upd["message"])
                    if "callback_query" in upd:
                        handle_bot_callback(upd["callback_query"])
            else:
                time.sleep(8)
        except Exception:
            time.sleep(8)



def pct_used(used: float, quota: float) -> int:
    if quota <= 0:
        return 0
    return max(0, min(100, int(round((used / quota) * 100))))


def html_escape(x: str) -> str:
    return str(x or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#039;")


@app.get("/go/{secret}")
def connect_proxy(secret: str):
    conn = db()
    r = conn.execute("SELECT * FROM users WHERE secret=?", (secret,)).fetchone()
    if not r:
        conn.close()
        return HTMLResponse("<h2>Subscription not found</h2>", status_code=404)
    conn.execute("UPDATE users SET last_seen=? WHERE id=?", (now_iso(), r["id"]))
    if user_can_consume(r):
        set_setting(conn, "shared_current_owner_id", str(r["id"]))
    conn.commit()
    conn.close()
    return RedirectResponse(proxy_link(secret), status_code=302)


@app.get("/s/{secret}", response_class=HTMLResponse)
def public_sub(secret: str):
    conn = db()
    r = conn.execute("SELECT * FROM users WHERE secret=?", (secret,)).fetchone()
    if r:
        conn.execute("UPDATE users SET last_seen=? WHERE id=?", (now_iso(), r["id"]))
        if user_can_consume(r):
            set_setting(conn, "shared_current_owner_id", str(r["id"]))
        conn.commit()
    conn.close()
    if not r:
        return HTMLResponse("<h2 style='font-family:sans-serif;text-align:center;margin-top:20vh'>Subscription not found</h2>", status_code=404)
    now = datetime.now()
    expire = parse_dt(r["expire_at"])
    days = None if not expire else max(0, int((expire - now).total_seconds() // 86400) + (1 if expire > now else 0))
    created = parse_dt(r["created_at"] if "created_at" in r.keys() else None)
    total_days = 30
    if expire and created:
        total_days = max(1, int((expire-created).total_seconds()//86400))
    day_pct = 100 if days is None else max(0, min(100, int((days/total_days)*100)))
    quota = float(r["quota_gb"] or 0)
    used = float(r["used_gb"] or 0)
    remain = max(0, quota-used) if quota>0 else 0
    q_pct = 100 if quota<=0 else max(0, min(100, int((remain/quota)*100)))
    status = "فعال" if int(r["enabled"] or 0) and is_not_expired(r["expire_at"]) else "غیرفعال"
    safe_name = html_escape(r["name"])
    initial = html_escape((r["name"] or "U")[:1].upper())
    link = proxy_link(r["secret"], int(r["port"] or base_proxy_port()) if "port" in r.keys() else base_proxy_port())
    title = "نامحدود" if quota <= 0 else f"{fmt_gb(quota)}"
    duration = "بدون محدودیت زمانی" if days is None else f"{days} روز"
    remain_text = "∞" if quota <= 0 else fmt_gb(remain, False).replace(" GB", "").replace(" MB", " مگ")
    copy_link = json.dumps(link)
    return f"""<!doctype html><html lang=\"fa\" dir=\"rtl\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{safe_name}</title><style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;font-family:Tahoma,Arial,sans-serif;color:#223536;display:flex;align-items:center;justify-content:center;padding:22px;background:linear-gradient(145deg,#f6c071,#ef8730);transition:.25s;overflow:hidden;position:relative}}body.blue{{background:linear-gradient(145deg,#7cc7ff,#2276d9)}}body.yellow{{background:linear-gradient(145deg,#ffe68a,#f3a71f)}}body.green{{background:linear-gradient(145deg,#9be7a2,#20a86b)}}body:before,body:after{{content:"";position:fixed;inset:-20%;pointer-events:none;z-index:0;opacity:.38;background:radial-gradient(circle at 20% 30%,rgba(255,255,255,.85) 0 3px,transparent 4px),radial-gradient(circle at 70% 25%,rgba(255,255,255,.55) 0 2px,transparent 3px),radial-gradient(circle at 45% 80%,rgba(255,255,255,.65) 0 4px,transparent 5px),radial-gradient(circle at 85% 70%,rgba(255,255,255,.45) 0 3px,transparent 4px);background-size:140px 140px,190px 190px,230px 230px,170px 170px;animation:floatDrops 18s linear infinite}}body:after{{opacity:.22;filter:blur(1px);animation:floatLines 24s linear infinite reverse;background:repeating-linear-gradient(130deg,transparent 0 28px,rgba(255,255,255,.22) 29px 31px,transparent 32px 64px)}}@keyframes floatDrops{{from{{transform:translate3d(0,0,0) rotate(0deg)}}to{{transform:translate3d(90px,-120px,0) rotate(12deg)}}}}@keyframes floatLines{{from{{transform:translate3d(-80px,80px,0)}}to{{transform:translate3d(80px,-80px,0)}}}}.wrap{{width:min(760px,100%);position:relative;z-index:2}}.top{{display:flex;align-items:center;gap:18px;margin-bottom:22px;direction:ltr}}.avatar{{width:105px;height:105px;border-radius:50%;background:#f4eadf;border:2px solid rgba(255,255,255,.75);box-shadow:0 12px 30px rgba(0,0,0,.12);display:grid;place-items:center;font-size:44px;font-weight:900;color:#e18836}}.name{{font-size:38px;font-weight:900}}.port{{font-size:26px;opacity:.9}}.card{{background:rgba(235,126,37,.62);border:1px solid rgba(65,40,20,.20);border-radius:34px;padding:42px 28px;box-shadow:0 24px 70px rgba(91,45,9,.20), inset 0 1px 0 rgba(255,255,255,.2)}}body.blue .card{{background:rgba(34,118,217,.35)}}body.green .card{{background:rgba(32,168,107,.35)}}body.yellow .card{{background:rgba(243,167,31,.35)}}.inner{{background:#f6e9e2;border-radius:32px;padding:28px 24px;text-align:center;box-shadow:inset 0 1px 0 rgba(255,255,255,.9)}}h1{{font-size:34px;margin:0 0 22px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}.metric b{{font-size:38px;color:#0d1720}}.metric span{{font-size:25px}}.battery{{margin:15px auto 0;width:118px;height:48px;border-radius:13px;border:7px solid #99a2aa;background:#333943;position:relative;box-shadow:inset 0 0 0 3px rgba(255,255,255,.22)}}.battery:before{{content:"";position:absolute;right:-18px;top:13px;width:12px;height:18px;border-radius:4px;background:#8b969e}}.fill{{position:absolute;inset:5px;border-radius:6px;background:#55cf75;display:grid;place-items:center;color:#873951;font-weight:900;min-width:30px}}.dark .fill{{background:#23272f;color:#fff}}.actions{{display:flex;gap:10px;margin-top:18px;direction:ltr}}button,a.btn{{border:0;border-radius:16px;padding:13px 16px;background:#263838;color:#fff;text-decoration:none;font-weight:800;cursor:pointer;flex:1;text-align:center}}.sub{{margin-top:12px;text-align:center;color:#334;opacity:.82;line-height:1.9}}.hint{{margin-top:8px;color:#5b6770;font-size:13px;line-height:1.8}}.colors{{display:flex;justify-content:center;gap:12px;margin-top:18px;direction:ltr}}.color{{width:28px;height:28px;border-radius:999px;border:3px solid rgba(255,255,255,.8);box-shadow:0 8px 20px rgba(0,0,0,.18);cursor:pointer;padding:0;flex:none}}.c-blue{{background:#2276d9}}.c-yellow{{background:#f3a71f}}.c-green{{background:#20a86b}}.copied{{position:fixed;bottom:22px;left:50%;transform:translateX(-50%) translateY(20px);opacity:0;background:#263838;color:white;padding:12px 18px;border-radius:14px;transition:.2s}}.copied.show{{opacity:1;transform:translateX(-50%) translateY(0)}}@media(max-width:560px){{body{{padding:14px;align-items:flex-start;overflow:auto}}.wrap{{width:100%;padding-top:10px}}.top{{gap:10px;margin-bottom:14px;direction:rtl;justify-content:flex-start}}.avatar{{width:64px;height:64px;font-size:28px;border-radius:22px}}.name{{font-size:24px;line-height:1.3;word-break:break-word}}.port{{font-size:17px}}.card{{border-radius:28px;padding:18px 12px}}.inner{{border-radius:24px;padding:18px 14px}}.grid{{grid-template-columns:1fr;gap:14px}}h1{{font-size:23px;line-height:1.55;margin-bottom:14px}}.metric b{{font-size:30px}}.metric span{{font-size:19px}}.battery{{width:104px;height:42px;border-width:6px}}.actions{{flex-direction:column}}button,a.btn{{width:100%;padding:14px 12px}}.sub,.hint{{font-size:12px}}.colors{{margin-bottom:4px}}}}
</style></head><body><main class=\"wrap\"><div class=\"top\"><div class=\"avatar\">{initial}</div><div><div class=\"name\">{safe_name}</div><div class=\"port\">{int(r["port"] or base_proxy_port()) if "port" in r.keys() else base_proxy_port()}</div></div></div><section class=\"card\"><div class=\"inner\"><h1>{html_escape(duration)} {html_escape(title)}</h1><div class=\"grid\"><div class=\"metric\"><span><b>{'∞' if days is None else days}</b> روز باقی مانده</span><div class=\"battery\"><div class=\"fill\" style=\"width:{day_pct}%\">{day_pct}%</div></div></div><div class=\"metric\"><span><b>{remain_text}</b> گیگ باقی مانده</span><div class=\"battery dark\"><div class=\"fill\" style=\"width:{q_pct}%\">{q_pct}%</div></div></div></div><div class=\"sub\">وضعیت: {html_escape(status)} · مصرف شده: {fmt_gb(used, False)} از {fmt_gb(quota)}</div><div class=\"actions\"><button onclick='copyProxy()'>کپی لینک پروکسی</button><a class=\"btn\" href=\"{link}\">اتصال</a></div><div class=\"colors\"><button class=\"color c-blue\" onclick=\"setBg('blue')\" title=\"آبی\"></button><button class=\"color c-yellow\" onclick=\"setBg('yellow')\" title=\"زرد\"></button><button class=\"color c-green\" onclick=\"setBg('green')\" title=\"سبز\"></button></div></div></section></main><div id=\"copied\" class=\"copied\">کپی شد</div><script>
const proxyLink={copy_link};
function showCopied(t='کپی شد'){{const el=document.getElementById('copied');el.textContent=t;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),1800)}}
function fallbackCopy(t){{const ta=document.createElement('textarea');ta.value=t;ta.setAttribute('readonly','');ta.style.position='fixed';ta.style.left='-9999px';document.body.appendChild(ta);ta.select();ta.setSelectionRange(0,ta.value.length);try{{document.execCommand('copy');showCopied('لینک کپی شد')}}catch(e){{showCopied('کپی نشد؛ دستی کپی کن')}}ta.remove()}}
function copyProxy(){{if(navigator.clipboard&&window.isSecureContext){{navigator.clipboard.writeText(proxyLink).then(()=>showCopied('لینک کپی شد')).catch(()=>fallbackCopy(proxyLink))}}else fallbackCopy(proxyLink)}}
function setBg(c){{document.body.className=c;localStorage.setItem('sub-bg-color',c)}}
setBg(localStorage.getItem('sub-bg-color')||'yellow');
</script></body></html>"""

@app.on_event("startup")
def startup() -> None:
    init_db()
    threading.Thread(target=bot_poll_loop, daemon=True).start()


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
        resp.set_cookie("delta_session", hmac.new(SECRET_KEY.encode(), b"login", hashlib.sha256).hexdigest(), httponly=True, samesite="lax")
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
    sync_traffic()
    disk = psutil.disk_usage("/")
    mem = psutil.virtual_memory()
    net = psutil.net_io_counters()
    load1, load5, load15 = os.getloadavg()
    online = online_by_port()
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        enabled = conn.execute("SELECT COUNT(*) n FROM users WHERE enabled=1").fetchone()["n"]
        used = conn.execute("SELECT COALESCE(SUM(used_gb),0) n FROM users").fetchone()["n"]
        quota = conn.execute("SELECT COALESCE(SUM(quota_gb),0) n FROM users").fetchone()["n"]
        ports = [int(r["port"]) for r in conn.execute("SELECT port FROM users WHERE port IS NOT NULL").fetchall()]
    return {"cpu": psutil.cpu_percent(interval=0.1), "load": [load1, load5, load15], "cores": psutil.cpu_count(), "ram_percent": mem.percent, "ram_total": mem.total, "ram_used": mem.used, "disk_percent": disk.percent, "disk_total": disk.total, "disk_used": disk.used, "rx": net.bytes_recv, "tx": net.bytes_sent, "proxy_status": "shared active" if enabled else "inactive", "users_total": total, "users_enabled": enabled, "online_total": online.get(base_proxy_port(),0), "quota_total": quota, "used_total": used, "public_host": proxy_host(), "proxy_port": base_proxy_port(), "sub_port": sub_port(), "uptime_seconds": int(datetime.now().timestamp() - psutil.boot_time()), "theme": setting("theme", "dark"), "mode": "shared-port", "shared_rx_bytes": int(setting("shared_rx_bytes", "0") or 0), "shared_tx_bytes": int(setting("shared_tx_bytes", "0") or 0)}


@app.get("/api/users")
def users(req: Request):
    require(req)
    sync_traffic()
    online = online_by_port()
    with db() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()]
    for row in rows:
        row["link"] = proxy_link(row["secret"])
        row["sub_link"] = sub_link(row["secret"])
        row["expired"] = not is_not_expired(row.get("expire_at"))
        row["days_left"] = days_left(row.get("expire_at"))
        q = float(row.get("quota_gb") or 0)
        u = float(row.get("used_gb") or 0)
        row["usage_percent"] = 0 if q <= 0 else min(100, round((u / q) * 100, 1))
        row["online"] = int(online.get(base_proxy_port(), 0)) if row.get("enabled") else 0
        row["shared_port"] = base_proxy_port()
        row["traffic_mode"] = "shared_strict"
    return rows


@app.post("/api/users")
def add_user(req: Request, name: str = Form(...), expire_days: Optional[str] = Form(None), quota_gb: float = Form(0), note: str = Form("")):
    require(req)
    if not name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    u = create_user_core(name, expire_days or "", quota_gb, note)
    telegram_send(f"✅ پروکسی جدید ساخته شد\n👤 {u['name']}\n🔌 Shared Port: {u['port']}\n🔗 {u['link']}\n🌐 ساب: {u['sub_link']}")
    return {"ok": True, "secret": u["secret"], "port": u["port"], "link": u["link"], "sub_link": u["sub_link"]}


@app.post("/api/users/{uid}/update")
def update_user(uid: int, req: Request, name: str = Form(...), expire_days: Optional[str] = Form(None), keep_expire: int = Form(1), quota_gb: float = Form(0), used_gb: float = Form(0), note: str = Form(""), enabled: int = Form(1)):
    require(req)
    if not name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    try:
        update_user_core(uid, name=name, expire_days=(expire_days if not keep_expire else None), quota_gb=quota_gb, used_gb=used_gb, enabled=enabled, note=note)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@app.post("/api/users/{uid}/toggle")
def toggle(uid: int, req: Request):
    require(req)
    with db() as conn:
        conn.execute("UPDATE users SET enabled=CASE enabled WHEN 1 THEN 0 ELSE 1 END, disabled_reason=NULL WHERE id=?", (uid,))
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


@app.get("/api/settings")
def get_settings(req: Request):
    require(req)
    return {"public_host": proxy_host(), "proxy_port": base_proxy_port(), "sub_port": sub_port(), "admin_username": setting("admin_username", ADMIN_USERNAME), "panel_title": setting("panel_title", "DELTA MTProto"), "theme": setting("theme", "dark"), "telegram_bot_token": setting("telegram_bot_token", ""), "telegram_chat_id": setting("telegram_chat_id", ""), "telegram_bot_enabled": setting("telegram_bot_enabled", "1")}


@app.post("/api/settings/server")
def save_server(req: Request, public_host: str = Form(...), proxy_port_value: int = Form(...), sub_port_value: int = Form(2096), theme: str = Form("dark")):
    require(req)
    with db() as conn:
        set_setting(conn, "public_host", public_host.strip())
        set_setting(conn, "proxy_port", str(proxy_port_value))
        set_setting(conn, "sub_port", str(sub_port_value))
        set_setting(conn, "theme", "light" if theme == "light" else "dark")
        conn.commit()
    render_proxy_service()
    return {"ok": True}


@app.post("/api/settings/admin")
def save_admin(req: Request, username: str = Form(...), password: str = Form("")):
    require(req)
    if not username.strip():
        raise HTTPException(status_code=400, detail="username is required")
    with db() as conn:
        set_setting(conn, "admin_username", username.strip())
        if password.strip():
            set_setting(conn, "admin_hash", pass_hash(password.strip()))
        conn.commit()
    return {"ok": True}


@app.post("/api/settings/telegram")
def save_telegram(req: Request, telegram_bot_token: str = Form(""), telegram_chat_id: str = Form(""), telegram_bot_enabled: int = Form(1)):
    require(req)
    with db() as conn:
        set_setting(conn, "telegram_bot_token", telegram_bot_token.strip())
        set_setting(conn, "telegram_chat_id", telegram_chat_id.strip())
        set_setting(conn, "telegram_bot_enabled", "1" if int(telegram_bot_enabled) else "0")
        conn.commit()
    return {"ok": True}


@app.post("/api/telegram/test")
def telegram_test(req: Request):
    require(req)
    return telegram_send("✅ تست اتصال بات DELTA MTProto موفق بود.")


@app.get("/api/backup/export")
def export_backup(req: Request):
    require(req)
    data = backup_payload()
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": "attachment; filename=delta-mtproto-backup-v12.json"})


@app.post("/api/backup/import")
async def import_backup(req: Request, backup: UploadFile = File(...)):
    require(req)
    raw = await backup.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid backup file")
    users_data = data.get("users", [])
    settings_data = data.get("settings", {})
    with db() as conn:
        for k, v in settings_data.items():
            if k in {"public_host", "proxy_port", "sub_port", "panel_title", "admin_username", "admin_hash", "theme", "telegram_bot_token", "telegram_chat_id", "telegram_bot_enabled"}:
                set_setting(conn, k, str(v))
        conn.execute("DELETE FROM users")
        for u in users_data:
            conn.execute("INSERT INTO users(name, secret, enabled, expire_at, quota_gb, used_gb, port, rx_bytes, tx_bytes, last_seen, disabled_reason, note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (u.get("name", "user"), u.get("secret") or secrets.token_hex(16), int(u.get("enabled", 1)), u.get("expire_at"), float(u.get("quota_gb") or 0), float(u.get("used_gb") or 0), int(u.get("port") or next_free_port(conn, base_proxy_port())), int(u.get("rx_bytes") or 0), int(u.get("tx_bytes") or 0), u.get("last_seen"), u.get("disabled_reason"), u.get("note", ""), u.get("created_at") or now_iso()))
        conn.commit()
    render_proxy_service()
    return {"ok": True, "imported": len(users_data)}


@app.post("/api/proxy/restart")
def restart(req: Request):
    require(req)
    render_proxy_service()
    return {"ok": True}


@app.get("/api/proxy/logs")
def logs(req: Request):
    require(req)
    proc = subprocess.run(["journalctl", "-u", "mtpulse-shared", "-n", "220", "--no-pager"], text=True, capture_output=True, check=False)
    return JSONResponse({"logs": proc.stdout[-24000:]})


@app.get("/api/backup")
def create_backup():
    backup_dir = "/opt/delta-proxy-panel/backups"
    os.makedirs(backup_dir, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    backup_base = os.path.join(backup_dir, f"backup-{now}")
    zip_path = f"{backup_base}.zip"

    # Do not include venv/backups/cache/log files in the backup zip.
    staging = f"/tmp/delta-panel-backup-{now}"
    if os.path.exists(staging):
        shutil.rmtree(staging)

    os.makedirs(staging, exist_ok=True)

    for item in os.listdir("/opt/delta-proxy-panel"):
        if item in {"venv", "backups", "__pycache__", ".git"}:
            continue
        src_path = os.path.join("/opt/delta-proxy-panel", item)
        dst_path = os.path.join(staging, item)
        if os.path.isdir(src_path):
            shutil.copytree(src_path, dst_path, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.log"))
        else:
            shutil.copy2(src_path, dst_path)

    shutil.make_archive(backup_base, "zip", staging)
    shutil.rmtree(staging, ignore_errors=True)

    if not os.path.exists(zip_path):
        raise HTTPException(status_code=500, detail="Backup file was not created")

    return FileResponse(
        path=zip_path,
        filename=os.path.basename(zip_path),
        media_type="application/zip"
    )
