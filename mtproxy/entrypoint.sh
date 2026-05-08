#!/bin/sh
set -e
: "${PROXY_PORT:=8443}"
: "${STATS_PORT:=8888}"
: "${WORKERS:=1}"

if [ ! -s /data/proxy-secret ]; then
  curl -fsSL https://core.telegram.org/getProxySecret -o /data/proxy-secret
fi
if [ ! -s /data/proxy-multi.conf ]; then
  curl -fsSL https://core.telegram.org/getProxyConfig -o /data/proxy-multi.conf
fi

if [ "$#" -eq 0 ]; then
  echo "No secrets provided. Sleeping until panel creates the first user."
  tail -f /dev/null
fi

exec mtproto-proxy -u mtproxy -p "$STATS_PORT" -H "$PROXY_PORT" "$@" --aes-pwd /data/proxy-secret /data/proxy-multi.conf -M "$WORKERS"
