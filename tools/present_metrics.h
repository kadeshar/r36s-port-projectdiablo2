/* SPDX-License-Identifier: MIT
 * Presentation diagnostics only: no access to surfaces, input or game memory.
 * Integer values: event 1=sample, 2=backend entry, 3=first successful present.
 * Backend 1=GDI, 2=OpenGL. First-present emitted once per backend per process.
 */
#ifndef PD2_PRESENT_METRICS_H
#define PD2_PRESENT_METRICS_H
#include <stdint.h>
#include <stdio.h>
#define PD2_PRESENT_LIMIT 262144u
#define PD2_PRESENT_LINE 192u

typedef struct {
    uint64_t start, frequency;
    unsigned frames, backend;
} pd2_metrics;

static __inline void pd2_metrics_init(pd2_metrics *m, uint64_t now, uint64_t frequency, unsigned backend)
{
    m->start = now;
    m->frequency = frequency <= 1000000000ULL ? frequency : 0;
    m->frames = 0;
    m->backend = backend;
}

/* Returns a complete bounded numeric JSON line only after one elapsed second.
 * Failed presentations advance time but are never counted. No catch-up bursts.
 * Width/height describe the render target, not the source surface.
 */
static __inline unsigned pd2_metrics_frame(pd2_metrics *m, uint64_t now, int success,
    unsigned width, unsigned height, char *line, unsigned capacity)
{
    uint64_t delta, ms;
    int n;
    if (!m->frequency || (m->backend != 1 && m->backend != 2) || now < m->start)
        return 0;
    if (success && m->frames < 1000000000u) ++m->frames;
    delta = now - m->start;
    if (delta < m->frequency) return 0;
    ms = delta / m->frequency;
    if (ms > 86400 || !width || !height || width > 65535 || height > 65535) {
        m->frames = 0;
        m->start = now;
        return 0;
    }
    ms = ms * 1000 + (delta % m->frequency) * 1000 / m->frequency;
    n = snprintf(line, capacity,
        "{\"event\":1,\"backend\":%u,\"frames\":%u,\"duration_ms\":%llu,\"width\":%u,\"height\":%u}\n",
        m->backend, m->frames, (unsigned long long)ms, width, height);
    m->frames = 0;
    m->start = now;
    return n > 0 && (unsigned)n < capacity ? (unsigned)n : 0;
}

static __inline unsigned pd2_metrics_status(unsigned backend, unsigned width, unsigned height,
    char *line, unsigned capacity)
{
    int n;
    if ((backend != 1 && backend != 2) || !width || !height || width > 65535 || height > 65535)
        return 0;
    n = snprintf(line, capacity,
        "{\"event\":2,\"backend\":%u,\"frames\":0,\"duration_ms\":0,\"width\":%u,\"height\":%u}\n",
        backend, width, height);
    return n > 0 && (unsigned)n < capacity ? (unsigned)n : 0;
}

static __inline unsigned pd2_metrics_first_present(unsigned backend, unsigned width, unsigned height,
    char *line, unsigned capacity)
{
    int n;
    if ((backend != 1 && backend != 2) || !width || !height || width > 65535 || height > 65535)
        return 0;
    n = snprintf(line, capacity,
        "{\"event\":3,\"backend\":%u,\"frames\":1,\"duration_ms\":0,\"width\":%u,\"height\":%u}\n",
        backend, width, height);
    return n > 0 && (unsigned)n < capacity ? (unsigned)n : 0;
}

#ifndef PD2_PRESENT_CORE_ONLY
void pd2_present_start(unsigned backend, unsigned width, unsigned height);
void pd2_present_frame(unsigned backend, int success, unsigned width, unsigned height);
#ifdef PD2_PRESENT_IMPLEMENTATION
#include <windows.h>
static volatile LONG pd2_present_lock;
static int pd2_present_disabled;
static HANDLE pd2_present_file = INVALID_HANDLE_VALUE;
static unsigned pd2_present_bytes;
static unsigned pd2_present_seen; /* Process lifetime; never reset on backend entry. */
static pd2_metrics pd2_present_state;

/* Called only with the nonblocking global gate held. CREATE_NEW never follows
 * or truncates an existing symlink/file. Fixed basename, no environment/config.
 * Holding this handle denies other Windows writers/deleters until process exit.
 */
static void pd2_present_setup(unsigned backend, uint64_t now)
{
    LARGE_INTEGER frequency;
    if (!QueryPerformanceFrequency(&frequency) || frequency.QuadPart <= 0) {
        pd2_present_disabled = 1;
        return;
    }
    if (pd2_present_file == INVALID_HANDLE_VALUE) {
        pd2_present_file = CreateFileW(L"pd2-present.jsonl", GENERIC_WRITE,
            FILE_SHARE_READ, NULL, CREATE_NEW, FILE_ATTRIBUTE_TEMPORARY |
            FILE_FLAG_OPEN_REPARSE_POINT, NULL);
        if (pd2_present_file == INVALID_HANDLE_VALUE) {
            pd2_present_disabled = 1;
            return;
        }
    }
    pd2_metrics_init(&pd2_present_state, now, (uint64_t)frequency.QuadPart, backend);
}

/* Gate held; reserve before I/O so any short/failed write permanently stops. */
static void pd2_present_write(const char *line, unsigned length)
{
    DWORD written;
    if (!length || pd2_present_disabled) return;
    if (length > PD2_PRESENT_LIMIT - pd2_present_bytes) {
        pd2_present_disabled = 1;
    } else {
        pd2_present_bytes += length;
        if (!WriteFile(pd2_present_file, line, length, &written, NULL) || written != length)
            pd2_present_disabled = 1;
    }
    if (pd2_present_disabled && pd2_present_file != INVALID_HANDLE_VALUE) {
        CloseHandle(pd2_present_file);
        pd2_present_file = INVALID_HANDLE_VALUE;
    }
}

void pd2_present_start(unsigned backend, unsigned width, unsigned height)
{
    LARGE_INTEGER now;
    char line[PD2_PRESENT_LINE];
    unsigned length;
    if (InterlockedCompareExchange(&pd2_present_lock, 1, 0)) return;
    if (!pd2_present_disabled && QueryPerformanceCounter(&now)) {
        pd2_present_setup(backend, (uint64_t)now.QuadPart);
        length = pd2_metrics_status(backend, width, height, line, sizeof(line));
        pd2_present_write(line, length);
    }
    InterlockedExchange(&pd2_present_lock, 0);
}

void pd2_present_frame(unsigned backend, int success, unsigned width, unsigned height)
{
    LARGE_INTEGER now;
    char line[PD2_PRESENT_LINE];
    unsigned length;
    if (InterlockedCompareExchange(&pd2_present_lock, 1, 0)) return;
    if (pd2_present_disabled || !QueryPerformanceCounter(&now)) goto done;
    if (pd2_present_file == INVALID_HANDLE_VALUE || pd2_present_state.backend != backend)
        pd2_present_setup(backend, (uint64_t)now.QuadPart);
    if (pd2_present_disabled) goto done;
    if (success && (backend == 1 || backend == 2) && !(pd2_present_seen & (1u << backend))) {
        length = pd2_metrics_first_present(backend, width, height, line, sizeof(line));
        if (length) {
            pd2_present_seen |= 1u << backend;
            pd2_present_write(line, length);
            if (pd2_present_disabled) goto done;
        }
    }
    length = pd2_metrics_frame(&pd2_present_state, (uint64_t)now.QuadPart,
        success, width, height, line, sizeof(line));
    pd2_present_write(line, length);
done:
    if (pd2_present_disabled && pd2_present_file != INVALID_HANDLE_VALUE) {
        CloseHandle(pd2_present_file);
        pd2_present_file = INVALID_HANDLE_VALUE;
    }
    InterlockedExchange(&pd2_present_lock, 0);
}
#endif
#endif
#endif
