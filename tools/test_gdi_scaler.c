/* SPDX-License-Identifier: MIT */
#define PD2_SCALER_CORE_ONLY
#include "pd2_gdi_scaler.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <windows.h>

static uint8_t  g_src8[1068 * 768 + 4096];
static uint16_t g_src16[1068 * 768 + 4096];
static uint32_t g_src32[1068 * 768 + 4096];
static uint8_t  g_pal[256 * 4];

static void set_pal(int idx, uint8_t r, uint8_t g, uint8_t b)
{
    g_pal[idx * 4 + 0] = b;
    g_pal[idx * 4 + 1] = g;
    g_pal[idx * 4 + 2] = r;
    g_pal[idx * 4 + 3] = 0;
}

static void test_solid_identity(void)
{
    int i, y, x;
    /* 32bpp solid identity across 800x600 -> 640x480 and 1024x768 -> 640x480 */
    const uint32_t colors32[] = { 0x00000000u, 0x00FFFFFFu, 0x00FF0000u, 0x0000FF00u, 0x000000FFu, 0x00A55A3Cu };
    for (i = 0; i < (int)(sizeof(colors32) / sizeof(colors32[0])); i++)
    {
        uint32_t c = colors32[i];
        for (y = 0; y < 600; y++)
            for (x = 0; x < 800; x++)
                g_src32[y * 800 + x] = c;
        memset(s_pd2_scaled32, 0xAA, sizeof(s_pd2_scaled32));
        pd2_down_800x600_32((const uint8_t*)g_src32, 800 * 4u, s_pd2_scaled32);
        for (y = 0; y < 640 * 480; y++)
            assert(s_pd2_scaled32[y] == c);

        for (y = 0; y < 768; y++)
            for (x = 0; x < 1024; x++)
                g_src32[y * 1024 + x] = c;
        pd2_down_bilinear_32((const uint8_t*)g_src32, 1024 * 4u, 1024, 768, s_pd2_scaled32, 640, 480, 0);
        for (y = 0; y < 640 * 480; y++)
            assert(s_pd2_scaled32[y] == c);
    }

    /* 8bpp solid identity + palette animation check */
    set_pal(0, 0, 0, 0);
    set_pal(1, 255, 255, 255);
    set_pal(2, 200, 150, 90);
    pd2_scale_palette_rgb(g_pal);
    memset(g_src8, 2, 800 * 600);
    pd2_down_800x600_8(g_src8, 800, s_pd2_scaled32);
    for (y = 0; y < 640 * 480; y++)
        assert(s_pd2_scaled32[y] == 0x00C8965Au);
    set_pal(2, 40, 210, 120);
    pd2_scale_palette_rgb(g_pal);
    pd2_down_800x600_8(g_src8, 800, s_pd2_scaled32);
    for (y = 0; y < 640 * 480; y++)
        assert(s_pd2_scaled32[y] == 0x0028D278u);

    /* 16bpp RGB565 and RGB555 solid identity */
    {
        const uint16_t c565[] = { 0x0000u, 0xFFFFu, 0xF800u, 0x07E0u, 0x001Fu, 0xAD55u };
        for (i = 0; i < (int)(sizeof(c565) / sizeof(c565[0])); i++)
        {
            for (y = 0; y < 800 * 600; y++) g_src16[y] = c565[i];
            pd2_down_800x600_16((const uint8_t*)g_src16, 800 * 2u, s_pd2_scaled16, 0);
            for (y = 0; y < 640 * 480; y++) assert(s_pd2_scaled16[y] == c565[i]);
        }
        const uint16_t c555[] = { 0x0000u, 0x7FFFu, 0x7C00u, 0x03E0u, 0x001Fu, 0x5294u };
        for (i = 0; i < (int)(sizeof(c555) / sizeof(c555[0])); i++)
        {
            for (y = 0; y < 800 * 600; y++) g_src16[y] = c555[i];
            pd2_down_800x600_16((const uint8_t*)g_src16, 800 * 2u, s_pd2_scaled16, 1);
            for (y = 0; y < 640 * 480; y++) assert(s_pd2_scaled16[y] == c555[i]);
        }
    }
}

static void test_1px_stroke_preservation(void)
{
    int phase, x, y;
    set_pal(0, 0, 0, 0);
    set_pal(1, 255, 255, 255);
    pd2_scale_palette_rgb(g_pal);

    /* Every 1px vertical & horizontal line phase (0..4) must survive in 8bpp, 16bpp, 32bpp. */
    for (phase = 0; phase < 5; phase++)
    {
        int col = 100 + phase;
        int row = 100 + phase;
        uint32_t max_col = 0, max_row = 0;
        memset(g_src8, 0, 800 * 600);
        for (y = 0; y < 600; y++) g_src8[y * 800 + col] = 1;
        for (x = 0; x < 800; x++) g_src8[row * 800 + x] = 1;
        pd2_down_800x600_8(g_src8, 800, s_pd2_scaled32);
        for (x = 0; x < 640; x++)
        {
            uint32_t v = s_pd2_scaled32[200 * 640 + x] & 0xFFu;
            if (v > max_col) max_col = v;
        }
        for (y = 0; y < 480; y++)
        {
            uint32_t v = s_pd2_scaled32[y * 640 + 200] & 0xFFu;
            if (v > max_row) max_row = v;
        }
        assert(max_col >= 80);
        assert(max_row >= 80);
    }

    /* Check 1024x768 -> 640x480 and 1068x600 -> 640x360 across all 8 phases. */
    for (phase = 0; phase < 8; phase++)
    {
        int col = 200 + phase;
        uint32_t max_col = 0;
        memset(g_src8, 0, 1024 * 768);
        for (y = 0; y < 768; y++) g_src8[y * 1024 + col] = 1;
        pd2_down_bilinear_32(g_src8, 1024, 1024, 768, s_pd2_scaled32, 640, 480, 1);
        for (x = 0; x < 640; x++)
        {
            uint32_t v = s_pd2_scaled32[100 * 640 + x] & 0xFFu;
            if (v > max_col) max_col = v;
        }
        assert(max_col >= 16);
    }
    for (phase = 0; phase < 5; phase++)
    {
        int col = 200 + phase;
        uint32_t max_col = 0;
        memset(g_src8, 0, 1068 * 600);
        for (y = 0; y < 600; y++) g_src8[y * 1068 + col] = 1;
        pd2_down_bilinear_32(g_src8, 1068, 1068, 600, s_pd2_scaled32, 640, 360, 1);
        for (x = 0; x < 640; x++)
        {
            uint32_t v = s_pd2_scaled32[100 * 640 + x] & 0xFFu;
            if (v > max_col) max_col = v;
        }
        assert(max_col >= 16);
    }
}

static void test_custom_pitch_and_guards(void)
{
    int y, x;
    /* Padded pitch (864 bytes instead of 800) must not skew rows. */
    set_pal(0, 0, 0, 0);
    set_pal(1, 240, 120, 60);
    pd2_scale_palette_rgb(g_pal);
    memset(g_src8, 0, sizeof(g_src8));
    for (y = 0; y < 600; y++)
        for (x = 0; x < 800; x++)
            g_src8[y * 864 + x] = 1;
    pd2_down_800x600_8(g_src8, 864, s_pd2_scaled32);
    for (y = 0; y < 640 * 480; y++)
        assert(s_pd2_scaled32[y] == 0x00F0783Cu);

    assert(pd2_scale_select(800, 600, 16, 640, 480, 1600, g_src16, NULL) == 1);
    assert(pd2_scale_select(800, 600, 32, 640, 480, 3200, g_src32, NULL) == 2);
    assert(pd2_scale_select(800, 600, 8, 640, 480, 800, g_src8, g_pal) == 3);
    assert(pd2_scale_select(1024, 768, 16, 640, 480, 2048, g_src16, NULL) == 4);
    assert(pd2_scale_select(1024, 768, 32, 640, 480, 4096, g_src32, NULL) == 5);
    assert(pd2_scale_select(1068, 600, 8, 640, 360, 1068, g_src8, g_pal) == 6);

    assert(pd2_scale_select(1024, 768, 8, 800, 600, 1024, g_src8, g_pal) == 6);
    assert(pd2_scale_select(640, 480, 16, 960, 720, 1280, g_src16, NULL) == 4);
    assert(pd2_scale_select(1068, 600, 32, 1280, 720, 4272, g_src32, NULL) == 5);
    assert(pd2_scale_select(800, 600, 16, 720, 540, 1600, g_src16, NULL) == 4);
    assert(pd2_scale_select(640, 480, 16, 427, 320, 1280, g_src16, NULL) == 4);

    /* Guard rejections must return 0 (safe fallback to StretchDIBits). */
    assert(pd2_scale_select(800, 600, 8, 640, 480, 800, NULL, g_pal) == 0);
    assert(pd2_scale_select(800, 600, 8, 640, 480, 800, g_src8, NULL) == 0);
    assert(pd2_scale_select(800, 600, 8, 640, 480, 799, g_src8, g_pal) == 0);
    assert(pd2_scale_select(800, 600, 24, 640, 480, 2400, g_src8, g_pal) == 0);
    assert(pd2_scale_select(640, 480, 16, 640, 480, 1280, g_src16, NULL) == 0);
    assert(pd2_scale_select(800, 600, 32, 3841, 2160, 3200, g_src32, NULL) == 0);
    assert(pd2_scale_select(800, 600, 32, 1920, 2161, 3200, g_src32, NULL) == 0);

    /* Multi-device upscale + odd-width 16bpp DWORD-aligned stride verification. */
    {
        uint16_t* up16 = (uint16_t*)malloc(960u * 720u * sizeof(uint16_t));
        uint16_t* odd16 = (uint16_t*)malloc(428u * 320u * sizeof(uint16_t));
        int i;
        assert(up16 && odd16);
        for (i = 0; i < 640 * 480; i++)
            g_src16[i] = 0x52AAu;
        pd2_down_bilinear_16((const uint8_t*)g_src16, 640u * 2u, 640, 480, up16, 960, 720, 0);
        for (i = 0; i < 960 * 720; i++)
            assert(up16[i] == 0x52AAu);
        memset(odd16, 0xCC, 428u * 320u * sizeof(uint16_t));
        pd2_down_bilinear_16((const uint8_t*)g_src16, 640u * 2u, 640, 480, odd16, 427, 320, 0);
        for (y = 0; y < 320; y++)
            for (x = 0; x < 427; x++)
                assert(odd16[(size_t)y * 428u + (size_t)x] == 0x52AAu);
        free(up16);
        free(odd16);
    }
}

static void benchmark(void)
{
    LARGE_INTEGER freq, t0, t1;
    int iter;
    QueryPerformanceFrequency(&freq);
    set_pal(1, 200, 160, 120);
    pd2_scale_palette_rgb(g_pal);

    QueryPerformanceCounter(&t0);
    for (iter = 0; iter < 100; iter++)
        pd2_down_800x600_8(g_src8, 800, s_pd2_scaled32);
    QueryPerformanceCounter(&t1);
    printf("8bpp 800x600->640x480: %.1f us/frame\n",
           (double)(t1.QuadPart - t0.QuadPart) * 1e6 / (double)freq.QuadPart / 100.0);

    QueryPerformanceCounter(&t0);
    for (iter = 0; iter < 100; iter++)
        pd2_down_800x600_16((const uint8_t*)g_src16, 1600, s_pd2_scaled16, 0);
    QueryPerformanceCounter(&t1);
    printf("16bpp 800x600->640x480: %.1f us/frame\n",
           (double)(t1.QuadPart - t0.QuadPart) * 1e6 / (double)freq.QuadPart / 100.0);

    QueryPerformanceCounter(&t0);
    for (iter = 0; iter < 100; iter++)
        pd2_down_800x600_32((const uint8_t*)g_src32, 3200, s_pd2_scaled32);
    QueryPerformanceCounter(&t1);
    printf("32bpp 800x600->640x480: %.1f us/frame\n",
           (double)(t1.QuadPart - t0.QuadPart) * 1e6 / (double)freq.QuadPart / 100.0);
}

int main(void)
{
    test_solid_identity();
    test_1px_stroke_preservation();
    test_custom_pitch_and_guards();
    benchmark();
    puts("pd2_gdi_scaler native tests passed");
    return 0;
}
