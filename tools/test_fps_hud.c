/* SPDX-License-Identifier: MIT; native deterministic synthetic renderer-core tests. */
#include <assert.h>
#include <stdio.h>
#include "fps_hud_core.h"
static void sampling(void) {
    fps_hud h; int i;
    fps_hud_reset(&h,1000000);
    assert(!h.valid);
    fps_hud_present(&h,1000000);
    for(i=1;i<=24;++i) fps_hud_present(&h,1000000+i*20000);
    assert(!h.valid);
    fps_hud_present(&h,1500000);
    assert(h.valid && h.value==50);
    for(i=1;i<=10;++i) fps_hud_present(&h,1500000+i*50000);
    assert(h.value==20);
    fps_hud_present(&h,1);
    assert(!h.valid);
    fps_hud_reset(&h,0); fps_hud_present(&h,1000); assert(!h.valid);
}
static void pixels(int bpp) {
    fps_hud h;
    unsigned char buf[160*32*4], original[sizeof(buf)];
    uint32_t palette[256]; int i, bytes=bpp/8, pitch=160*bytes;
    memset(buf,0x3a,sizeof(buf)); memcpy(original,buf,sizeof(buf));
    for(i=0;i<256;++i) palette[i]=0x777777;
    palette[17]=0; palette[39]=0xffffff;
    fps_hud_reset(&h,1000);
    assert(fps_hud_draw(&h,buf,pitch,160,32,bpp,palette,4,4));
    /* Exact F top stroke: foreground (6,6); background (4,4).
     * Dash begins at character #5 => x=46, y=10. */
    assert(buf[4*pitch+4*bytes]==(bpp==8?17:0));
    assert(buf[6*pitch+6*bytes]==(bpp==8?39:255));
    assert(buf[10*pitch+46*bytes]==(bpp==8?39:255));
    fps_hud_restore(&h,buf,pitch); assert(!memcmp(buf,original,sizeof(buf)));
    h.valid=1; h.value=50;
    assert(fps_hud_draw(&h,buf,pitch,160,32,bpp,palette,4,4));
    assert(buf[6*pitch+46*bytes]==(bpp==8?39:255)); /* '5', not '--' */
    fps_hud_restore(&h,buf,pitch); assert(!memcmp(buf,original,sizeof(buf)));
    /* Clipping, pitch padding, tiny target, all restored exactly. */
    assert(fps_hud_draw(&h,buf,pitch,7,8,bpp,palette,4,4));
    fps_hud_restore(&h,buf,pitch); assert(!memcmp(buf,original,sizeof(buf)));
    assert(!fps_hud_draw(&h,buf,1,160,32,bpp,palette,4,4));
}
int main(void) {
    sampling(); pixels(8); pixels(16); pixels(32);
    puts("PASS: 50/20 FPS cadence, warmup, clock reset, invalid clock, 8/16/32-bit exact glyph pixels, palette selection, clipping, pitch, byte-exact restore");
    return 0;
}
