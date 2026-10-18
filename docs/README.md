# Project Documentation Index

This directory centralizes technical guides, diagnostic procedures, and historical port documentation for the Project Diablo 2 R36S port, keeping the `sdcard/ports/` runtime payload clean of unnecessary markdown files.

## Documentation Contents

- **[`PORT-README.md`](PORT-README.md):** Comprehensive port manual and technical history covering versions 0.1.0 through 0.1.18, PortMaster installation steps, directory mapping, video configuration, and controls. Includes [PortMaster adaptation and isolated GLX trial](<PORT-README.md#portmaster-adaptation--isolated-glx-trial>), host cleanup, direct SD deployment, and hardware acceptance checks.
- **[`DIAGNOSTICS-1.md`](DIAGNOSTICS-1.md):** Diagnostic test battery (tests A–F), rendering pipeline validation (SDL → GLX → Wine/DirectDraw), and safe log export procedures.
- **[`GPU-RUNTIME-1.md`](GPU-RUNTIME-1.md):** Guide for the experimental GLES2 / GLSL 1.10 GPU renderer, 8-bit palette offloading, and the optional Box86 Cortex-A35 variant.
- **[`AUDIO-FIX-1.md`](AUDIO-FIX-1.md):** Audio testing protocol, A/B comparison matrix (Variants A–D), DirectSound buffer tuning, and PCM underrun telemetry analysis on R36S.

## Root Architecture and Reference Docs

- **[`README.md`](../README.md):** Main project overview, quick-start installation, controls, and performance recommendations.
- **[`AGENTS.md`](../AGENTS.md):** Hardware specs, runtime software stack, code integrity rules, and AI agent guidelines (including mandatory caveman skill usage).
- **[`MEMORY.md`](../MEMORY.md):** Chronological log of engineering investigations, root cause analyses (audio ENOTTY, stutter, black screen), and solutions.
