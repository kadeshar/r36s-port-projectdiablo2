#!/bin/sh
# SPDX-License-Identifier: LGPL-2.1-or-later
# Run ONLY inside the existing pd2-alsa-native-builder container.
set -eu
sha256sum -c /src/.state/audio-metrics-build/prepared-inputs.sha256
: > /src/.state/audio-metrics-build/verified-artifact.sha256
buildroot=$(mktemp -d /tmp/pd2-audio-metrics.XXXXXX)
case "$buildroot" in /tmp/pd2-audio-metrics.*) ;; *) exit 2;; esac
cleanup() { [ ! -L "$buildroot" ] && [ -d "$buildroot" ] && rm -rf -- "$buildroot"; }
trap cleanup EXIT HUP INT TERM
# Extract upstream natively: Windows bind mounts cannot represent configure's
# include/alsa symlink reliably. Copy ONLY authenticated prepared modified files.
tar -xf /src/.state/audio-metrics-build/alsa.tar -C "$buildroot"
cd "$buildroot/alsa-lib-1.2.8"
for source in pcm.c pcm_mmap.c pd2_audio_metrics_core.h audio_metrics_api.h; do
 cp "/src/.state/audio-metrics-build/alsa-lib-1.2.8/src/pcm/$source" "src/pcm/$source"
done
CC=arm-linux-gnueabihf-gcc CFLAGS="-Os -fno-ident" LDFLAGS="-Wl,--build-id=none" \
 ./configure --host=arm-linux-gnueabihf --prefix=/usr --libdir=/usr/lib/arm-linux-gnueabihf \
 --with-configdir=/usr/share/alsa --with-plugindir=/usr/lib/arm-linux-gnueabihf/alsa-lib \
 --disable-maintainer-mode --disable-static --enable-shared --disable-python
arm-linux-gnueabihf-gcc -std=c11 -D__bitwise= -Iinclude -fsyntax-only /src/tools/alsa_legacy_abi.c
if [ "${1:-}" != --tests-only ]; then
 make -s -j4
 arm-linux-gnueabihf-strip -o /src/sdcard/ports/projectdiablo2/compat/audio-metrics/libasound.so.2 src/.libs/libasound.so.2.0.0
fi
# No new public symbols: versioned ALSA exports must remain byte-for-byte named.
arm-linux-gnueabihf-nm -D --defined-only /src/sdcard/ports/projectdiablo2/compat/alsa-legacy-armhf/libasound.so.2 | awk '{print $2 " " $3}' | sort > /src/.state/audio-metrics-build/stock-symbols.txt
arm-linux-gnueabihf-nm -D --defined-only /src/sdcard/ports/projectdiablo2/compat/audio-metrics/libasound.so.2 | awk '{print $2 " " $3}' | sort > /src/.state/audio-metrics-build/metrics-symbols.txt
diff -u /src/.state/audio-metrics-build/stock-symbols.txt /src/.state/audio-metrics-build/metrics-symbols.txt
printf 'pcm.null { type null }\n' > "$buildroot/alsa.conf"
# Core tests native and ARMhf; actual dlsym/null-PCM integration ARMhf under QEMU.
gcc -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -Wno-unused-function -Wno-unused-variable -pthread /src/tools/audio_metrics_test.c -o /src/.state/audio-metrics-build/core-test
/src/.state/audio-metrics-build/core-test
arm-linux-gnueabihf-gcc -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -Wno-unused-function -Wno-unused-variable -pthread /src/tools/audio_metrics_test.c -o /src/.state/audio-metrics-build/core-test.armhf
qemu-arm -L /usr/arm-linux-gnueabihf /src/.state/audio-metrics-build/core-test.armhf
arm-linux-gnueabihf-gcc -std=c11 -DPD2_ARM_ABI -D__bitwise= -Wall -Wextra -Werror -Iinclude /src/tools/audio_metrics_abi_test.c -ldl -pthread -o /src/.state/audio-metrics-build/abi-test.armhf
ALSA_CONFIG_PATH="$buildroot/alsa.conf" qemu-arm -L /usr/arm-linux-gnueabihf /src/.state/audio-metrics-build/abi-test.armhf /src/sdcard/ports/projectdiablo2/compat/audio-metrics/libasound.so.2 > /src/.state/audio-metrics-build/abi-test.txt
arm-linux-gnueabihf-readelf -d -V /src/sdcard/ports/projectdiablo2/compat/audio-metrics/libasound.so.2
if [ "${1:-}" != --tests-only ]; then
 sha256sum /src/sdcard/ports/projectdiablo2/compat/audio-metrics/libasound.so.2 > /src/.state/audio-metrics-build/verified-artifact.sha256
fi
printf 'ARMhf audio metrics build and tests passed\n'
