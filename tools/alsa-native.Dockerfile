FROM debian:bullseye-slim@sha256:e5b6442dd2e9684cf5e87d8338b5968f3b348636fc0be6d7850a381e3731a2bd
# Use the main suite for this isolated, old-glibc build environment; the
# bullseye security mirror no longer serves all indexed package versions.
RUN sed -i '/security/d' /etc/apt/sources.list && apt-get update && apt-get install -y --no-install-recommends gcc-arm-linux-gnueabihf gcc-aarch64-linux-gnu qemu-user binutils-arm-linux-gnueabihf binutils-aarch64-linux-gnu libc6-dev-armhf-cross libc6-dev-arm64-cross make xz-utils && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y --allow-downgrades --no-install-recommends gcc libc6-dev libc6=2.31-13+deb11u11 libc-bin=2.31-13+deb11u11 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
