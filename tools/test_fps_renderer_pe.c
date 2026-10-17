/* SPDX-License-Identifier: MIT
 * Synthetic PE/DirectDraw integration probe: no game, chat, hotkeys or hooks.
 * Run in a disposable directory with ddraw.ini selecting GDI, windowed 640x480.
 * argv[1] is the optional DLL's absolute filename. Tests 8-bit palette output.
 */
#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <ddraw.h>
#include <stdio.h>
#include <string.h>
#include "fps_hud_core.h"
typedef HRESULT (WINAPI *create_fn)(GUID *, LPDIRECTDRAW *, IUnknown *);
static void require(int ok, const char *what) {
    if (!ok) {fprintf(stderr,"FAIL: %s (Win32=%lu)\n",what,GetLastError()); ExitProcess(1);}
}
static void pump(void) {
    MSG msg;
    while(PeekMessage(&msg,NULL,0,0,PM_REMOVE)) {TranslateMessage(&msg); DispatchMessage(&msg);}
}
static void fill(LPDIRECTDRAWSURFACE surface) {
    DDSURFACEDESC d; unsigned y;
    memset(&d,0,sizeof(d)); d.dwSize=sizeof(d);
    require(IDirectDrawSurface_Lock(surface,NULL,&d,DDLOCK_WAIT,NULL)==DD_OK,"Lock");
    for(y=0;y<d.dwHeight;++y) memset((char*)d.lpSurface+y*d.lPitch,77,d.dwWidth);
    require(IDirectDrawSurface_Unlock(surface,NULL)==DD_OK,"Unlock");
}
static unsigned glyph_at(HDC dc,int x) {
    unsigned bits=0; int row,col;
    for(row=0;row<5;++row) for(col=0;col<3;++col) {
        COLORREF c=GetPixel(dc,x+col*2,6+row*2);
        require(c!=CLR_INVALID,"GetPixel readable renderer output");
        bits=(bits<<1)|((GetRValue(c)>200 && GetGValue(c)>200 && GetBValue(c)>200)?1:0);
    }
    return bits;
}
int main(int argc,char **argv) {
    HMODULE dll,user; create_fn create;
    LPDIRECTDRAW dd=NULL; LPDIRECTDRAWSURFACE surface=NULL; LPDIRECTDRAWPALETTE palette=NULL;
    DDSURFACEDESC d; PALETTEENTRY colors[256]; HWND window; WNDCLASS wc;
    HDC (WINAPI *real_get_dc)(HWND); int (WINAPI *real_release_dc)(HWND,HDC);
    HDC dc; int i,rate=0,digits=0; unsigned bits;
    /* Reference core functions too, keeping /W4 clean; deterministic suite tests them. */
    fps_hud unused; unsigned char scratch[4]={0};
    fps_hud_reset(&unused,1000); fps_hud_present(&unused,0);
    fps_hud_draw(&unused,scratch,4,1,1,32,NULL,0,0); fps_hud_restore(&unused,scratch,4);
    require(argc==2,"usage: fps-renderer-probe.exe absolute-ddraw.dll");
    memset(&wc,0,sizeof(wc)); wc.lpfnWndProc=DefWindowProc; wc.hInstance=GetModuleHandle(NULL); wc.lpszClassName="PD2FPSProbe";
    require(RegisterClass(&wc)!=0,"RegisterClass");
    window=CreateWindow(wc.lpszClassName,"Synthetic FPS renderer probe",WS_OVERLAPPEDWINDOW|WS_VISIBLE,80,80,656,519,NULL,NULL,wc.hInstance,NULL);
    require(window!=NULL,"CreateWindow");
    { char config[MAX_PATH]; require(GetFullPathName("ddraw.ini",MAX_PATH,config,NULL)>0,"probe config path");
      require(SetEnvironmentVariable("CNC_DDRAW_CONFIG_FILE",config),"select isolated GDI probe config"); }
    dll=LoadLibrary(argv[1]); require(dll!=NULL,"Load optional renderer DLL");
    create=(create_fn)GetProcAddress(dll,"DirectDrawCreate"); require(create!=NULL,"DirectDrawCreate export");
    require(create(NULL,&dd,NULL)==DD_OK,"DirectDrawCreate");
    require(IDirectDraw_SetCooperativeLevel(dd,window,DDSCL_NORMAL)==DD_OK,"SetCooperativeLevel");
    require(IDirectDraw_SetDisplayMode(dd,640,480,8)==DD_OK,"SetDisplayMode");
    memset(&d,0,sizeof(d)); d.dwSize=sizeof(d); d.dwFlags=DDSD_CAPS; d.ddsCaps.dwCaps=DDSCAPS_PRIMARYSURFACE;
    require(IDirectDraw_CreateSurface(dd,&d,&surface,NULL)==DD_OK,"Create primary");
    memset(colors,0,sizeof(colors));
    for(i=0;i<256;++i) colors[i].peRed=colors[i].peGreen=colors[i].peBlue=80;
    colors[17].peRed=colors[17].peGreen=colors[17].peBlue=0;
    colors[39].peRed=colors[39].peGreen=colors[39].peBlue=255;
    colors[77].peRed=0; colors[77].peGreen=160; colors[77].peBlue=0;
    require(IDirectDraw_CreatePalette(dd,DDPCAPS_8BIT|DDPCAPS_ALLOW256,colors,&palette,NULL)==DD_OK,"Create palette");
    require(IDirectDrawSurface_SetPalette(surface,palette)==DD_OK,"Set palette");
    user=GetModuleHandle("user32.dll");
    real_get_dc=(HDC(WINAPI*)(HWND))GetProcAddress(user,"GetDC");
    real_release_dc=(int(WINAPI*)(HWND,HDC))GetProcAddress(user,"ReleaseDC");
    fill(surface); for(i=0;i<80;++i) {pump(); Sleep(10);}
    dc=real_get_dc(window); require(dc!=NULL,"real window DC");
    require(glyph_at(dc,6)==fps_hud_glyph('F'),"immediate FPS label pixels");
    require(glyph_at(dc,46)==fps_hud_glyph('-'),"initial FPS: --, not invented value");
    real_release_dc(window,dc);
    for(i=0;i<60;++i) {fill(surface); pump(); Sleep(50);}
    dc=real_get_dc(window);
    require(glyph_at(dc,6)==fps_hud_glyph('F'),"persistent FPS label");
    for(i=0;i<5;++i) {
        int j; bits=glyph_at(dc,46+i*8);
        if(!bits) break;
        for(j=0;j<10;++j) if(bits==fps_hud_glyph((char)('0'+j))) break;
        require(j<10,"FPS value consists of real numeric glyphs"); rate=rate*10+j; ++digits;
    }
    require(digits>0 && rate>=12 && rate<=27,"controlled 20 FPS cadence within scheduler tolerance");
    real_release_dc(window,dc);
    memset(&d,0,sizeof(d)); d.dwSize=sizeof(d);
    require(IDirectDrawSurface_Lock(surface,NULL,&d,DDLOCK_WAIT,NULL)==DD_OK,"final Lock");
    require(((unsigned char*)d.lpSurface)[6*d.lPitch+6]==77,"HUD leaves game primary pixels unchanged");
    IDirectDrawSurface_Unlock(surface,NULL);
    printf("PASS: PE GDI DirectDraw, immediate FPS: --, palette-correct glyphs, measured %d FPS at 20 FPS input, restored primary\n",rate);
    IDirectDrawSurface_Release(surface); IDirectDrawPalette_Release(palette); IDirectDraw_Release(dd);
    DestroyWindow(window); return 0;
}
