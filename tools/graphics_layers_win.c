/* SPDX-License-Identifier: MIT
 * Standalone synthetic paletted DirectDraw probe. No game assets. Parent owns
 * a 15s Wine-session deadline. Never persists registry/config/display changes.
 */
#define WIN32_LEAN_AND_MEAN
#define COBJMACROS
#define DIRECTDRAW_VERSION 0x0300
#include <windows.h>
#include <ddraw.h>
#include <stdio.h>
#include <string.h>
static void event(const char *stage,int code,unsigned frame) {
    printf("PD2_EVENT {\"event\":\"graphics_layer\",\"schema\":1,\"probe\":\"ddraw\",\"stage\":\"%s\",\"status\":\"%s\",\"backend\":\"windows\",\"renderer\":\"unknown\",\"frame\":%u,\"code\":%d}\n",stage,code?"failed":"ok",frame,code);
    fflush(stdout);
}
int main(void) {
    HMODULE lib=NULL; HWND window=NULL; LPDIRECTDRAW dd=NULL;
    LPDIRECTDRAWSURFACE primary=NULL; LPDIRECTDRAWPALETTE palette=NULL;
    HRESULT (WINAPI *create)(GUID *,LPDIRECTDRAW *,IUnknown *);
    DDSURFACEDESC desc; DDBLTFX fill; PALETTEENTRY colors[256];
    char cwd[MAX_PATH],expected[MAX_PATH],loaded[MAX_PATH];
    int code=0,exclusive=0,display=0; unsigned i; DWORD start; MSG msg;
    event("start",0,0);
    if (!GetCurrentDirectoryA(MAX_PATH,cwd) || strlen(cwd)>MAX_PATH-12) {code=9;goto out;}
    strcpy(expected,cwd); strcat(expected,"\\ddraw.dll");
    if (GetFileAttributesA(expected)==INVALID_FILE_ATTRIBUTES || !SetDllDirectoryA(cwd)) {code=1;goto out;}
    lib=LoadLibraryA("ddraw.dll");
    if (!lib || !GetModuleFileNameA(lib,loaded,MAX_PATH) || _stricmp(expected,loaded)) {code=1;goto out;}
    /* memcpy avoids nonportable function/object pointer casts under /W4. */
    { FARPROC address=GetProcAddress(lib,"DirectDrawCreate"); memcpy(&create,&address,sizeof(create)); }
    if (!create) {code=2;goto out;}
    event("library",0,0);
    window=CreateWindowExA(0,"STATIC","PD2 synthetic RGB",WS_POPUP|WS_VISIBLE,0,0,640,480,NULL,NULL,GetModuleHandleA(NULL),NULL);
    if (!window) {code=5;goto out;}
    if (FAILED(create(NULL,&dd,NULL))) {code=10;goto out;}
    if (FAILED(IDirectDraw_SetCooperativeLevel(dd,window,DDSCL_EXCLUSIVE|DDSCL_FULLSCREEN))) {code=11;goto out;} exclusive=1;
    if (FAILED(IDirectDraw_SetDisplayMode(dd,640,480,8))) {code=12;goto out;} display=1;
    ZeroMemory(&desc,sizeof(desc)); desc.dwSize=sizeof(desc); desc.dwFlags=DDSD_CAPS; desc.ddsCaps.dwCaps=DDSCAPS_PRIMARYSURFACE;
    if (FAILED(IDirectDraw_CreateSurface(dd,&desc,&primary,NULL))) {code=13;goto out;}
    ZeroMemory(colors,sizeof(colors)); colors[1].peRed=255; colors[2].peGreen=255; colors[3].peBlue=255;
    if (FAILED(IDirectDraw_CreatePalette(dd,DDPCAPS_8BIT|DDPCAPS_ALLOW256,colors,&palette,NULL)) ||
        FAILED(IDirectDrawSurface_SetPalette(primary,palette))) {code=14;goto out;}
    event("context",0,0);
    for (i=1;i<=3;++i) {
        ZeroMemory(&fill,sizeof(fill)); fill.dwSize=sizeof(fill); fill.dwFillColor=i;
        if (FAILED(IDirectDrawSurface_Blt(primary,NULL,NULL,NULL,DDBLT_COLORFILL|DDBLT_WAIT,&fill))) {code=15;goto out;}
        event("frame",0,i); start=GetTickCount();
        while (GetTickCount()-start<2000) {
            while (PeekMessageA(&msg,NULL,0,0,PM_REMOVE)) {TranslateMessage(&msg);DispatchMessageA(&msg);}
            Sleep(10);
        }
    }
out:
    if (primary) IDirectDrawSurface_Release(primary);
    if (palette) IDirectDrawPalette_Release(palette);
    if (display) IDirectDraw_RestoreDisplayMode(dd);
    if (exclusive) IDirectDraw_SetCooperativeLevel(dd,window,DDSCL_NORMAL);
    if (dd) IDirectDraw_Release(dd);
    if (window) DestroyWindow(window);
    if (lib) FreeLibrary(lib);
    event(code?"error":"done",code,0); return code;
}
