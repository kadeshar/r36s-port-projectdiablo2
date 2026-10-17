/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef PD2_AUDIO_METRICS_API_H
#define PD2_AUDIO_METRICS_API_H
#include <stdint.h>
enum pd2_am_op { PD2_AM_WRITE, PD2_AM_MMAP_BEGIN, PD2_AM_MMAP_COMMIT,
 PD2_AM_PARAMS, PD2_AM_START, PD2_AM_PREPARE, PD2_AM_RESUME, PD2_AM_DROP, PD2_AM_DRAIN,
 PD2_AM_RECOVER, PD2_AM_CLOSE };
/* Hidden cross-TU helpers, never part of libasound's public symbol surface. */
int __attribute__((visibility("hidden"))) pd2_am_enter(void);
void __attribute__((visibility("hidden"))) pd2_am_leave(void);
void __attribute__((visibility("hidden"))) pd2_am_result(void *, enum pd2_am_op, int64_t, uint64_t, int);
#endif
