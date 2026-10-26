# Project Documentation Index

This directory centralizes technical guides, diagnostic procedures, and historical port documentation for the Project Diablo 2 R36S port, keeping the `sdcard/ports/` runtime payload clean of unnecessary markdown files.

## Documentation Contents

- **[`PORT-README.md`](PORT-README.md):** Comprehensive port manual and technical history covering versions 0.1.0 through 0.1.18, PortMaster installation steps, directory mapping, video configuration, and controls. Includes current GDI deployment and hardware acceptance checks; older experimental profiles are explicitly historical.
- **[`PERFORMANCE-OVERLAY.md`](PERFORMANCE-OVERLAY.md):** Portable R36S performance overlay manual, level specifications (0–4), X11 double-buffered architecture, and guide for porting to other PortMaster/Linux games.
- **[`DIAGNOSTICS-1.md`](DIAGNOSTICS-1.md):** Historical diagnostic battery (tests A–F), rendering-pipeline investigations, and safe log export procedures; removed GL game profiles are not current instructions.

- **[`PAYLOAD-AUDIT.md`](PAYLOAD-AUDIT.md):** Pełny audyt plików karty SD, usunięte warianty, duże wymagane artefakty i możliwości dalszego odchudzenia.

## Root Architecture and Reference Docs

- **[`README.md`](../README.md):** Main project overview, quick-start installation, controls, and performance recommendations.
- **[`AGENTS.md`](../AGENTS.md):** Hardware specs, runtime software stack, code integrity rules, and AI agent guidelines (including mandatory caveman skill usage).
- **[`MEMORY.md`](../MEMORY.md):** Chronological log of engineering investigations, root cause analyses (audio ENOTTY, stutter, black screen), and solutions.
