# Optional Cortex-A35 Box86

This is a side-by-side build of upstream Box86 commit
`fa59e748f91cee8542cfc996214bc4d582e4d6dd` (same source revision as the stock
runtime), not a Wine upgrade or a claimed FPS improvement.

## ISA and provenance

The upstream `GOA_CLONE` profile expresses Cortex-A35 intent, but its
`armv8-a+crc+simd+crypto` architecture flags assume optional instructions.
This build replaces that profile's C and assembly flags with:

```
-march=armv8-a -mtune=cortex-a35 -mfpu=neon-fp-armv8 -mfloat-abi=hard -marm
```

No optional CRC or cryptographic extensions are requested. This controls the
compiled emulator; the runtime dynarec's host-feature detection remains upstream
code and still requires validation on the physical R36S.

The source archive is authenticated with SHA256
`ed172675183984cc8d65d3fb8f795c32aae3d85a05511f0f22524cda8f801a26`.
The other source change supplies the exact revision in the generated version
header because the authenticated archive does not contain Git metadata.

The manifest records the resulting ELF hash/size, actual tool versions,
installed package versions, dependency/GLIBC floor and QEMU smoke outcome.
Base image and source are pinned; apt package resolution is not. **Bit-for-bit
reproducibility is not claimed.** No device benchmark or dynarec performance
claim follows from QEMU interpreter smoke tests.

## Published artifact and validation

- Size: 7,822,456 bytes; SHA256:
  `45fa17057d5b23b3580d8a0af444f194a333d08b4a4774c0e5232af693ef6774`.
- GCC 10.2.1, GNU binutils 2.35.2, CMake 3.18.4, QEMU 5.2.0.
- ELF32 little-endian ARM EABI5 hard-float; ARMv8/NEON/VFP register ABI;
  interpreter `/lib/ld-linux-armhf.so.3`; highest imported GLIBC version 2.29.
- QEMU reports `Box86 with Dynarec v0.3.9 fa59e74`; upstream i386 test01
  passes with `BOX86_DYNAREC=0`. Device dynarec, game performance and audio
  remain unvalidated.

## Known upstream time64 limitation

GCC correctly warns about an overread in upstream `stat64_helper.c`.
That file defines `_TIME_BITS=64` then assumes the ARMhf time64 `struct stat`
layout has 112 bytes. The build's glibc 2.31 headers predate this time64 switch;
the actual structure differs, so the hardcoded conversion (including the
16-byte copy from offset 96) is unsafe if called. This is not an innocuous
warning, and the A35 flags do not cause or fix it. The exact same upstream
source revision contains this defect; the separately supplied stock binary's
build options and reachability have not been established.

The affected entry points are `__stat64_time64`, `__fstat64_time64`,
`__fstatat64_time64` and `__lstat64_time64`. An ELF32 dynamic-symbol scan of all
42 ELF binaries/libraries in the currently shipped Wine 8.0 archive found no
undefined imports or raw name mentions of these four symbols. Thus the
current pinned Wine payload does not directly request these entry points;
this is not a universal runtime non-reachability proof (for example, newly
loaded guest libraries can change it).

Keep this module opt-in and tied to the existing Wine payload. Do not upgrade
guest Unix libraries or advertise general time64 support on this build.
No silent source fix was applied: a field-wise time32-to-time64 conversion,
proper failure handling and dedicated ABI tests belong in an explicitly
patched revision if these entry points become required. Do not suppress the
warning or merely shorten the final memcpy: earlier fields also depend on
the assumed layout.

## Build

From the project root, with Docker Desktop running:

```
python -B tools/build_box86_a35.py --fetch
docker build -t pd2-box86-a35-builder -f tools/box86-a35.Dockerfile .
python -B tools/build_box86_a35.py --build
```

The build runs offline after the source archive and builder image exist. It
checks ELF32 ARM EABI5 hard-float, interpreter path, VFP calling convention and
maximum GLIBC version 2.31, then runs a version check and upstream i386 test01
under QEMU with Box86's dynarec disabled. These are compatibility smoke tests,
not validation of hardware rendering, Wine, sound or the physical dynarec.

After an intentional rebuild, review the manifest and update the selector's
hardcoded hash/size pins before packaging; never trust a new manifest alone.

## Integration contract

```
python3 -B scripts/box_variant.py --variant stock --port "$PD2_PORT" --session "$PD2_RUN"
python3 -B scripts/box_variant.py --variant a35 --port "$PD2_PORT" --session "$PD2_RUN"
```

`stock` succeeds without copying anything: keep the existing authenticated
`PD2_BOX`. `a35` authenticates the hardcoded binary hash/size and source
identity in the bounded manifest, refuses links/hardlinks and unsafe directories,
and exclusively creates `$PD2_RUN/box86-a35` with mode 0700. On success use that
exact path as `PD2_BOX`. Failure returns 1 with fixed `unavailable` JSON; do not
silently claim the A35 variant ran. The caller supplies its private owned
session directory and serializes setup with execution. Each session is fresh;
a repeated A35 preparation refuses an existing destination rather than
replacing it. No installed runtime file or prefix is changed.

Select independently from the renderer. Preserve SAFEFLAGS1/CALLRET0/BIGBLOCK1
for setup and the approved safe game defaults. All Wine invocations and
wineserver cleanup for a session must use the same selected executable.
