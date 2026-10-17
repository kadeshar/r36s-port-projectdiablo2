/* SPDX-License-Identifier: MIT
 * Independent palette-only gate. Writer releases before testing primary/signal;
 * renderer snapshots only 256 entries, releases before driver calls. No lock
 * acquisition by writer of dd.cs/surface.cs, so no new reverse lock ordering.
 */
#ifndef PD2_GLES2_PALETTE_H
#define PD2_GLES2_PALETTE_H
#include <windows.h>
extern SRWLOCK pd2_gles2_palette_gate;
#endif
