#!/bin/sh
set -e
: "${PROXY_PORT:=8443}"
: "${STATS_PORT:=8888}"
: "${WORKERS:=1}"

mkdir -p /data

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

# Same launch style as MTPulse/official MTProxy:
# mtproto-proxy -u nobody -p 8888 -H <port> -S <secret> --aes-pwd proxy-secret proxy-multi.conf -M 1
echo "Starting official MTProxy on host port ${PROXY_PORT} with args: $*"
exec mtproto-proxy \
  -u nobody \
  -p "$STATS_PORT" \
  -H "$PROXY_PORT" \
  "$@" \
  --aes-pwd /data/proxy-secret /data/proxy-multi.conf \
  -M "$WORKERS"
