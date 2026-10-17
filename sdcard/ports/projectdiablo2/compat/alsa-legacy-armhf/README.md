# Session-local ARM32 ALSA experiment

Unmodified alsa-lib 1.2.8, built with the ARM hard-float glibc 2.31 toolchain
without time64 defines. The build asserts 32-bit time_t, a 132-byte sync_ptr
and SNDRV_PCM_IOCTL_SYNC_PTR == 0xc0844123 (instead of 0xc0884123).

Build: `python tools/build_alsa_legacy.py`, using the existing isolated
`pd2-alsa-native-builder` image. Source and license are included in the update.
Only AUDIO TEST ON selects an authenticated copy from private volatile work.
No system library, configuration or kernel replacement is performed.
