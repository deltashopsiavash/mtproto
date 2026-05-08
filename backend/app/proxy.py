import os, secrets, re
from datetime import datetime
from typing import Optional
import docker

IMAGE = os.getenv("MTPROXY_IMAGE", "nineseconds/mtg:stable")
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "")
PORT_START = int(os.getenv("USER_PORT_START", "20000"))
PORT_END = int(os.getenv("USER_PORT_END", "20999"))
NETWORK_NAME = os.getenv("COMPOSE_PROJECT_NAME", "mtproto-panel") + "_default"

SAFE = re.compile(r"[^a-zA-Z0-9_.-]+")

def client():
    return docker.from_env()

def gen_secret() -> str:
    return "dd" + secrets.token_hex(16)

def container_name(name: str) -> str:
    return "mtproto_user_" + SAFE.sub("_", name.lower())[:70]

def link(host: str, port: int, secret: str) -> str:
    return f"tg://proxy?server={host}&port={port}&secret={secret}"

def start_proxy(u, public_host: Optional[str] = None):
    c = client()
    try:
        old = c.containers.get(u.container_name)
        old.remove(force=True)
    except Exception:
        pass
    args = [u.secret]
    if u.sponsor_tag:
        args.append(u.sponsor_tag)
    ports = {"3128/tcp": u.port, "3129/tcp": None}
    return c.containers.run(
        IMAGE,
        command=args,
        name=u.container_name,
        detach=True,
        restart_policy={"Name": "unless-stopped"},
        ports=ports,
        labels={"managed-by": "mtproto-panel", "proxy-user": u.name},
    )

def stop_proxy(u):
    c = client()
    try:
        cont = c.containers.get(u.container_name)
        cont.stop(timeout=5)
    except Exception:
        pass

def remove_proxy(u):
    c = client()
    try:
        cont = c.containers.get(u.container_name)
        cont.remove(force=True)
    except Exception:
        pass

def inspect_proxy(u):
    try:
        cont = client().containers.get(u.container_name)
        cont.reload()
        return {"status": cont.status, "id": cont.short_id}
    except Exception:
        return {"status": "missing", "id": None}

def container_traffic_bytes(u) -> int:
    try:
        cont = client().containers.get(u.container_name)
        stats = cont.stats(stream=False)
        total = 0
        for iface in stats.get("networks", {}).values():
            total += int(iface.get("rx_bytes", 0)) + int(iface.get("tx_bytes", 0))
        return total
    except Exception:
        return int(u.traffic_used_bytes or 0)

