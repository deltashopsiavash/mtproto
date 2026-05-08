FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential libssl-dev zlib1g-dev ca-certificates curl xxd && rm -rf /var/lib/apt/lists/*
RUN git clone --depth=1 https://github.com/TelegramMessenger/MTProxy.git /src
WORKDIR /src
RUN make -j"$(nproc)"

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl xxd libssl3 zlib1g && rm -rf /var/lib/apt/lists/* && useradd -r -s /usr/sbin/nologin mtproxy
COPY --from=build /src/objs/bin/mtproto-proxy /usr/local/bin/mtproto-proxy
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
WORKDIR /data
ENTRYPOINT ["/entrypoint.sh"]
