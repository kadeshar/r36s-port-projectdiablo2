/* SPDX-License-Identifier: MIT; included privately by each upstream renderer.
 * Snapshot only: NEVER replace a game's surface pointer or touch its pixels. */
#include "dd.h"
#include "ddsurface.h"
#include "fps_hud_core.h"
static fps_hud pd2_hud;
static HWND pd2_window;
static IDirectDrawSurfaceImpl *pd2_primary;
static int pd2_width, pd2_height, pd2_bpp, pd2_render_width, pd2_render_height;
static int pd2_ready;
static unsigned char *pd2_snapshot;
static SIZE_T pd2_capacity;
static void pd2_reset(void) {
    LARGE_INTEGER frequency;
    frequency.QuadPart=0; QueryPerformanceFrequency(&frequency);
    fps_hud_reset(&pd2_hud,frequency.QuadPart);
    pd2_window=NULL; pd2_primary=NULL; pd2_ready=0;
    if (pd2_snapshot) HeapFree(GetProcessHeap(),0,pd2_snapshot);
    pd2_snapshot=NULL; pd2_capacity=0;
}
static void pd2_begin(void) {
    IDirectDrawSurfaceImpl *s=g_ddraw.primary;
    SIZE_T size;
    if (!s->pitch || s->height > ((SIZE_T)-1)/s->pitch) {pd2_ready=0; return;}
    size=(SIZE_T)s->pitch*s->height;
    if (pd2_window!=g_ddraw.hwnd || pd2_primary!=s ||
        pd2_width!=g_ddraw.width || pd2_height!=g_ddraw.height || pd2_bpp!=g_ddraw.bpp ||
        pd2_render_width!=g_ddraw.render.width || pd2_render_height!=g_ddraw.render.height) {
        pd2_reset(); pd2_window=g_ddraw.hwnd; pd2_primary=s;
        pd2_width=g_ddraw.width; pd2_height=g_ddraw.height; pd2_bpp=g_ddraw.bpp;
        pd2_render_width=g_ddraw.render.width; pd2_render_height=g_ddraw.render.height;
    }
    if (size>pd2_capacity) {
        unsigned char *p=(unsigned char *)HeapAlloc(GetProcessHeap(),0,size);
        if (!p) {pd2_ready=0; return;}
        if (pd2_snapshot) HeapFree(GetProcessHeap(),0,pd2_snapshot);
        pd2_snapshot=p; pd2_capacity=size;
    }
    if (!size || !s->surface) {pd2_ready=0; return;}
    memcpy(pd2_snapshot,s->surface,size);
    pd2_ready=fps_hud_draw(&pd2_hud,pd2_snapshot,s->pitch,s->width,s->height,s->bpp,
        s->palette ? (const uint32_t *)s->palette->data_rgb : NULL,4,4);
    /* HUD changes independently of game damage notifications. */
    InterlockedExchange(&g_ddraw.render.surface_updated,TRUE);
}
static void *pd2_pixels(void) {
    return pd2_ready ? pd2_snapshot : g_ddraw.primary->surface;
}
static void pd2_present(void) {
    LARGE_INTEGER now;
    if (pd2_ready && !g_ddraw.bnet_active && QueryPerformanceCounter(&now))
        fps_hud_present(&pd2_hud,now.QuadPart);
    pd2_ready=0;
}
