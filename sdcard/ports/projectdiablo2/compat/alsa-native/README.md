# Native ARM32/AArch64 ALSA comparison and syscall trace

Source: `tools/alsa_native.c`. Build with `python tools/build_alsa_native.py`
after building the isolated `pd2-alsa-native-builder` Docker image from
`tools/alsa-native.Dockerfile`. Requires no compiler on the handheld.

Loads `libasound.so.2` dynamically; opens playback PCM in nonblocking mode,
then closes it. No audio writes, mixer changes or persistent configuration.
The launcher authenticates each ELF and copies it to private volatile storage
before direct execution. Box86 is not involved in these tests. Baselines run
without ptrace; additional runs under the bundled AArch64 strace 6.1 capture
only open/openat/ioctl/close. The tracer's ARM32 child library environment is
kept separate from its own AArch64 environment. Raw trace stays in bounded RAM.

Build strace with `python tools/build_audio_trace.py`. Its unmodified source
is included as `strace-6.1.tar.xz`; license: `licenses/LICENSE-strace.txt`.
Helper requirements: ARM32 GLIBC_2.4 / AArch64 GLIBC_2.17. The dynamic tracer
requires AArch64 GLIBC_2.28; loader or ptrace failure is reported as unavailable.
