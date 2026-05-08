import os, secrets, re, socket
from typing import Optional, Iterable
import docker

IMAGE = os.getenv("MTPROXY_IMAGE", "delta-proxy-panel-mtproxy:latest")
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "")
PROXY_PORT = int(os.getenv("PROXY_PORT", "8443"))
CONTAINER_NAME = "mtproto_shared_proxy"
SAFE = re.compile(r"[^a-zA-Z0-9_.-]+")

def client():
    return docker.from_env()

def gen_secret() -> str:
    # official MTProxy expects raw 16-byte hex secrets with -S; clients can use dd<secret> for random padding.
    return secrets.token_hex(16)

def container_name(name: str) -> str:
    # kept for DB compatibility; one shared proxy container is used.
    return "mtproto_user_" + SAFE.sub("_", name.lower())[:70]

def public_host() -> str:
    return PUBLIC_HOST or socket.gethostbyname(socket.gethostname())

def link(host: str, port: int, secret: str) -> str:
    # Match the working MTPulse/official MTProxy format: the same raw 16-byte hex
    # secret passed with -S is sent to Telegram clients without dd/ee prefix.
    client_secret = secret[2:] if secret.startswith("dd") and len(secret) == 34 else secret
    return f"tg://proxy?server={host}&port={port}&secret={client_secret}"

def _args_for_users(users: Iterable) -> list[str]:
    args = []
    active_users = [u for u in users if getattr(u, "active", False)]
    for u in active_users:
        raw_secret = (u.secret or "")
        if raw_secret.startswith("dd") and len(raw_secret) == 34:
            raw_secret = raw_secret[2:]
        if raw_secret:
            args += ["-S", raw_secret]
    # Official MTProxy has one global sponsor tag (-P), not a different tag per secret.
    first_tag = next((u.sponsor_tag for u in active_users if getattr(u, "sponsor_tag", None)), None)
    if first_tag:
        args += ["-P", first_tag]
    return args

def reload_shared_proxy(users: Iterable):
    c = client()
    try:
        old = c.containers.get(CONTAINER_NAME)
        old.remove(force=True)
    except Exception:
        pass
    args = _args_for_users(users)
    return c.containers.run(
        IMAGE,
        command=args,
        name=CONTAINER_NAME,
        detach=True,
        restart_policy={"Name": "unless-stopped"},
        environment={"PROXY_PORT": str(PROXY_PORT)},
        ports={f"{PROXY_PORT}/tcp": PROXY_PORT},
        volumes={"mtproto_proxy_config": {"bind": "/data", "mode": "rw"}},
        labels={"managed-by": "delta-proxy-panel", "proxy-mode": "shared-single-port"},
    )

def start_proxy(u, public_host: Optional[str] = None):
    # compatibility wrapper; main.py calls reload_shared_proxy with all active users.
    return None

def stop_proxy(u):
    return None

def remove_proxy(u):
    return None

def inspect_proxy(u=None):
    try:
        cont = client().containers.get(CONTAINER_NAME)
        cont.reload()
        return {"status": cont.status, "id": cont.short_id}
    except Exception:
        return {"status": "missing", "id": None}

def container_traffic_bytes(u=None) -> int:
    try:
        cont = client().containers.get(CONTAINER_NAME)
        stats = cont.stats(stream=False)
        total = 0
        for iface in stats.get("networks", {}).values():
            total += int(iface.get("rx_bytes", 0)) + int(iface.get("tx_bytes", 0))
        return total
    except Exception:
        return 0
