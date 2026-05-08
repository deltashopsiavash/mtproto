# DELTA MTProto Panel

A lightweight web panel around Telegram MTProxy/MTPulse-style installation.

## Install

```bash
bash <(curl -Ls https://raw.githubusercontent.com/deltashopsiavash/mtproto/main/install.sh)
```

Installer asks for:
- panel port
- admin username
- admin password
- public IP/domain
- proxy port
- optional sponsor tag

## Features in this first version

- Login protected admin panel
- Overview: CPU, RAM, disk, network, proxy status, host/port
- Users: create one MTProto secret/link per user
- Per-user expiry date and quota field
- Enable/disable/delete users
- Rebuild/restart MTProxy systemd service automatically

> Note: Official MTProxy does not provide accurate built-in per-secret traffic quota enforcement. Quota is stored for management now; real traffic enforcement can be added in the next phase with firewall/accounting or a traffic proxy layer.
