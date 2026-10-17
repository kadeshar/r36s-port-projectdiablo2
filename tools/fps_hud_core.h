/* SPDX-License-Identifier: MIT
 * Optional renderer-only HUD. No input, game inspection or persistent surface writes. */
#ifndef FPS_HUD_CORE_H
#define FPS_HUD_CORE_H
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#define FPS_HUD_W 124
#define FPS_HUD_H 16
typedef struct fps_hud {
    int64_t start, frequency;
    unsigned frames, value;
    int started, valid;
    unsigned char saved[FPS_HUD_W * FPS_HUD_H * 4];
    int width, height, bytes, x, y;
} fps_hud;
static void fps_hud_reset(fps_hud *h, int64_t frequency) {
    memset(h, 0, sizeof(*h)); h->frequency = frequency;
}
/* Called ONLY after a completed renderer presentation. First completion is origin,
 * subsequent completions count intervals; startup latency is never called FPS. */
static void fps_hud_present(fps_hud *h, int64_t now) {
    int64_t elapsed;
    if (h->frequency <= 0) return;
    if (!h->started || now < h->start) {
        h->start = now; h->frames = 0; h->started = 1; h->valid = 0; return;
    }
    ++h->frames;
    elapsed = now - h->start;
    if (elapsed >= h->frequency / 2 && elapsed > 0) {
        double rate = (double)h->frames * (double)h->frequency / (double)elapsed;
        h->value = rate > 99999 ? 99999 : (unsigned)(rate + 0.5);
        h->valid = 1; h->frames = 0; h->start = now;
    }
}
static unsigned fps_hud_glyph(char c) {
    /* 3x5 row-major, top row at bits 14..12. */
    static const unsigned digits[] = {31599,11415,29671,29647,23497,31183,31215,29257,31727,31695};
    if (c >= '0' && c <= '9') return digits[c-'0'];
    switch (c) {
    case 'F': return 31140; case 'P': return 31716; case 'S': return 31183;
    case ':': return 1040; case '-': return 448; default: return 0;
    }
}
/* Caller holds renderer/global + primary-surface locks across draw/upload/restore.
 * Palette is an array of little-endian RGBQUADs. Choose existing light/dark indices,
 * never mutate the game's palette. 16-bit black/white works for both 555 and 565. */
static int fps_hud_draw(fps_hud *h, void *pixels, int pitch, int width, int height,
                        int bpp, const uint32_t *palette, int x, int y) {
    char text[24]; unsigned fg = 0xffffff, bg = 0; int xx, yy, n, k, length;
    unsigned char *p = (unsigned char *)pixels;
    h->width = h->height = 0;
    if (!p || x < 0 || y < 0 || width <= x || height <= y ||
        (bpp != 8 && bpp != 16 && bpp != 32) || pitch < width*(bpp/8)) return 0;
    if (bpp == 8) {
        unsigned lo = ~0u, hi = 0; if (!palette) return 0;
        for (k=0;k<256;++k) {
            unsigned rgb = palette[k];
            unsigned light = ((rgb>>16)&255)*299 + ((rgb>>8)&255)*587 + (rgb&255)*114;
            if (light < lo) {lo=light; bg=(unsigned)k;}
            if (light >= hi) {hi=light; fg=(unsigned)k;}
        }
    } else if (bpp == 16) fg = 0xffff;
    h->bytes=bpp/8; h->x=x; h->y=y;
    h->width=width-x < FPS_HUD_W ? width-x : FPS_HUD_W;
    h->height=height-y < FPS_HUD_H ? height-y : FPS_HUD_H;
    if (h->valid) sprintf(text,"FPS: %u",h->value); else strcpy(text,"FPS: --");
    length=(int)strlen(text);
    for (yy=0;yy<h->height;++yy) {
        unsigned char *row=p+(y+yy)*pitch+x*h->bytes;
        memcpy(h->saved+yy*FPS_HUD_W*4,row,h->width*h->bytes);
        for (xx=0;xx<h->width;++xx) {
            unsigned color=bg;
            n=(xx-2)/8;
            if (xx>=2 && yy>=2 && yy<12 && n<length && ((xx-2)%8)<6) {
                unsigned glyph=fps_hud_glyph(text[n]);
                if (glyph & (1u << (14-((yy-2)/2)*3-((xx-2)%8)/2))) color=fg;
            }
            memcpy(row+xx*h->bytes,&color,h->bytes);
        }
    }
    return 1;
}
static void fps_hud_restore(fps_hud *h, void *pixels, int pitch) {
    int y;
    for (y=0;y<h->height;++y)
        memcpy((unsigned char *)pixels+(h->y+y)*pitch+h->x*h->bytes,
               h->saved+y*FPS_HUD_W*4,h->width*h->bytes);
    h->height=0;
}
#endif
