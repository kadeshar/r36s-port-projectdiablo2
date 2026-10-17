FROM debian:bullseye-slim@sha256:e5b6442dd2e9684cf5e87d8338b5968f3b348636fc0be6d7850a381e3731a2bd
# Isolated build only: no installation on the device or host. Package versions
# are recorded in manifest; apt resolution means this is not bit-reproducible.
RUN sed -i '/security/d' /etc/apt/sources.list && apt-get update && apt-get install -y --no-install-recommends gcc-arm-linux-gnueabihf binutils-arm-linux-gnueabihf libc6-dev-armhf-cross cmake make python3 qemu-user && rm -rf /var/lib/apt/lists/*
WORKDIR /project
