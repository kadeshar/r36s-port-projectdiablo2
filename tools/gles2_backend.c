/* SPDX-License-Identifier: MIT
 * Opt-in cnc-ddraw GL2 backend. No GL3, core contexts, FBO, multipass or GDI
 * fallback. Compatibility logic is separate from passive presentation metrics.
 */
#include <windows.h>
#include <stdint.h>
#include "config.h"
#include "dd.h"
#include "ddsurface.h"
#include "render_ogl.h"
#include "fps_limiter.h"
#include "hook.h"
#include "gles2_pipeline.h"
#include "gles2_events.h"
#include "gles2_palette.h"
SRWLOCK pd2_gles2_palette_gate=SRWLOCK_INIT;
#define PD2_PRESENT_IMPLEMENTATION
#include "present_metrics.h"

static HGLRC pd2_context;
static HDC pd2_hdc;
static HWND pd2_hwnd;
static pd2_gl_api pd2_api;
static unsigned pd2_dimension(int n) { return n>0 && n<=16384 ? (unsigned)n:0; }
static void pd2_status(unsigned stage,unsigned code) {
 unsigned bpp=(g_ddraw.bpp==8 || g_ddraw.bpp==16 || g_ddraw.bpp==32) ? g_ddraw.bpp:0;
 pd2_gl_event(stage,code,bpp,pd2_dimension(g_ddraw.width),pd2_dimension(g_ddraw.height),pd2_dimension(g_ddraw.render.width),pd2_dimension(g_ddraw.render.height));
}
/* ExitProcess terminates ONLY this DLL's host, never other Wine sessions or
 * arbitrary PIDs. Normal teardown never calls this path. */
__declspec(noreturn) void pd2_gles2_fatal(unsigned stage,unsigned code) {
 pd2_status(stage,code);
 ExitProcess(PD2_GL_EXIT_CODE);
}
static FARPROC pd2_proc(const char *name) {
 PROC p=xwglGetProcAddress(name);
 if (!p || p==(PROC)1 || p==(PROC)2 || p==(PROC)3 || p==(PROC)-1)
 p=real_GetProcAddress(g_oglu_hmodule,name);
 return p;
}
static void pd2_load_api(void) {
#define PD2_LOAD(t,n) pd2_api.n=(t)pd2_proc("gl" #n);
 PD2_GL_API(PD2_LOAD)
#undef PD2_LOAD
 if (!pd2_gl_api_complete(&pd2_api)) pd2_gles2_fatal(2,PD2_GL_API_MISSING);
 /* Parse only major/minor numeric prefix; never persist driver strings. */
 { const unsigned char *v=pd2_api.GetString(GL_VERSION);
 if (!v || v[0]<'2' || v[0]>'9' || v[1]!='.' || v[2]<'0' || v[2]>'9') pd2_gles2_fatal(2,PD2_GL_VERSION);
 pd2_gl_major=v[0]-'0';pd2_gl_minor=v[2]-'0'; }
 if (pd2_gl_error(&pd2_api,PD2_GL_STATE)) pd2_gles2_fatal(2,PD2_GL_STATE);
 /* Swap control is optional; when advertised, honor the selected vsync mode. */
 { PFNWGLGETEXTENSIONSSTRINGARBPROC ext=(PFNWGLGETEXTENSIONSSTRINGARBPROC)pd2_proc("wglGetExtensionsStringARB");
 if (ext) {
 const char *extensions=ext(pd2_hdc);
 if (extensions && strstr(extensions,"WGL_EXT_swap_control")) {
 PFNWGLSWAPINTERVALEXTPROC interval=(PFNWGLSWAPINTERVALEXTPROC)pd2_proc("wglSwapIntervalEXT");
 if (!interval || !interval(g_config.vsync ? 1:0)) pd2_gles2_fatal(2,PD2_GL_STATE);
 }
 } }
 pd2_status(2,0);
}
BOOL ogl_release(void) {
 if (g_ddraw.render.thread) return FALSE;
 if (pd2_context) {
 /* Render thread detached before the caller joined it. This thread never
  * owned that context; an extra wglMakeCurrent(NULL,NULL) is not required. */
 if (!xwglDeleteContext(pd2_context)) pd2_gles2_fatal(7,PD2_GL_RELEASE);
 pd2_context=NULL;pd2_hdc=NULL;pd2_hwnd=NULL;
 }
 return TRUE;
}
BOOL ogl_create(void) {
 if (pd2_context && pd2_hdc==g_ddraw.render.hdc && pd2_hwnd==g_ddraw.hwnd) return TRUE;
 if (!ogl_release()) pd2_gles2_fatal(1,PD2_GL_CONTEXT);
 if (!IsWindow(g_ddraw.hwnd) || !xwglCreateContext || !xwglMakeCurrent || !xwglDeleteContext || !xwglGetProcAddress) pd2_gles2_fatal(1,PD2_GL_CONTEXT);
 pd2_context=xwglCreateContext(g_ddraw.render.hdc);
 if (!pd2_context) pd2_gles2_fatal(1,PD2_GL_CONTEXT);
 pd2_hdc=g_ddraw.render.hdc;pd2_hwnd=g_ddraw.hwnd;
 pd2_status(1,0);
 return TRUE;
}
static unsigned pd2_stage(int code) {
 if (code==PD2_GL_VERTEX || code==PD2_GL_FRAGMENT || code==PD2_GL_LINK) return 3;
 if (code==PD2_GL_TEXTURE || code==PD2_GL_FORMAT) return 4;
 return 5;
}
DWORD WINAPI ogl_render_main(void) {
 pd2_gl_pipeline pipeline; unsigned palette_snapshot[256]; int code,ready=0,first_frame=1; DWORD wait_result;
 if (!pd2_context || !xwglMakeCurrent(pd2_hdc,pd2_context)) pd2_gles2_fatal(1,PD2_GL_CONTEXT);
 pd2_load_api();
 /* Startup-only synthetic shader validation of the active 8/16/32-bit mode.
  * Native harness also exercises every mode. Never reads game surfaces. */
 code=pd2_gl_validate(&pd2_api,g_ddraw.bpp,g_config.rgb555);
 if (code) pd2_gles2_fatal(pd2_stage(code),code);
 pd2_status(5,0);
 code=pd2_gl_init(&pd2_api,&pipeline,g_ddraw.width,g_ddraw.height,g_ddraw.bpp,g_config.rgb555);
 if (code) pd2_gles2_fatal(pd2_stage(code),code);
 pd2_status(3,0);pd2_status(4,0);
 pd2_api.ClearColor(0,0,0,1);pd2_api.Clear(GL_COLOR_BUFFER_BIT);
 if (pd2_gl_error(&pd2_api,PD2_GL_STATE)) pd2_gles2_fatal(6,PD2_GL_STATE);
 pd2_present_start(2,g_ddraw.render.width,g_ddraw.render.height);
 fpsl_init();
 while (g_ddraw.render.run) {
 int changed=0,palette_dirty=0,surface_dirty=0,clear=0;
 wait_result=WaitForSingleObject(g_ddraw.render.sem,100);
 if (wait_result==WAIT_FAILED || wait_result==WAIT_ABANDONED) pd2_gles2_fatal(6,PD2_GL_WAIT);
 if (!g_ddraw.render.run) break;
 /* Timeouts only permit teardown checks, never force redraw. */
 if (wait_result==WAIT_TIMEOUT && ready) continue;
 fpsl_frame_start();
 EnterCriticalSection(&g_ddraw.cs);
 if (g_ddraw.primary && g_ddraw.primary->bpp==g_ddraw.bpp && g_ddraw.primary->width==pipeline.width && g_ddraw.primary->height==pipeline.height && (pipeline.bpp!=8 || g_ddraw.primary->palette)) {
 if (g_config.lock_surfaces) EnterCriticalSection(&g_ddraw.primary->cs);
 palette_dirty=InterlockedExchange(&g_ddraw.render.palette_updated,FALSE) || !ready;
 surface_dirty=InterlockedExchange(&g_ddraw.render.surface_updated,FALSE) || !ready;
 if (pipeline.bpp==8 && (surface_dirty || palette_dirty)) {
 AcquireSRWLockShared(&pd2_gles2_palette_gate);
 memcpy(palette_snapshot,g_ddraw.primary->palette->data_bgr,sizeof(palette_snapshot));
 ReleaseSRWLockShared(&pd2_gles2_palette_gate);
 }
 if (surface_dirty) {
 int pitch=g_ddraw.primary->pitch ? g_ddraw.primary->pitch:pipeline.width*(pipeline.bpp/8);
 code=pd2_gl_upload(&pd2_api,&pipeline,g_ddraw.primary->surface,pitch,pipeline.bpp==8 ? palette_snapshot:NULL);
 if (code) pd2_gles2_fatal(6,code);
 } else if (palette_dirty && pipeline.bpp==8) {
 code=pd2_gl_upload_palette(&pd2_api,&pipeline,palette_snapshot);
 if (code) pd2_gles2_fatal(6,code);
 }
 changed=surface_dirty || (palette_dirty && pipeline.bpp==8);ready=1;
 if (g_config.lock_surfaces) LeaveCriticalSection(&g_ddraw.primary->cs);
 }
 clear=InterlockedExchange(&g_ddraw.render.clear_screen,FALSE);
 LeaveCriticalSection(&g_ddraw.cs);
 if (!ready || (!changed && !clear && wait_result==WAIT_TIMEOUT)) continue;
 pd2_api.Clear(GL_COLOR_BUFFER_BIT);
 code=pd2_gl_draw(&pd2_api,&pipeline,g_ddraw.render.viewport.x,g_ddraw.render.viewport.y+g_ddraw.render.opengl_y_align,g_ddraw.render.viewport.width,g_ddraw.render.viewport.height);
 if (code) pd2_gles2_fatal(6,code);
 if (g_ddraw.bnet_active) pd2_api.Clear(GL_COLOR_BUFFER_BIT);
 if (pd2_gl_error(&pd2_api,PD2_GL_DRAW)) pd2_gles2_fatal(6,PD2_GL_DRAW);
 if (!SwapBuffers(pd2_hdc)) pd2_gles2_fatal(6,PD2_GL_SWAP);
 pd2_present_frame(2,1,g_ddraw.render.width,g_ddraw.render.height);
 if (first_frame) { pd2_status(6,0);first_frame=0; }
 fpsl_frame_end();
 }
 code=pd2_gl_destroy(&pd2_api,&pipeline);
 if (code) pd2_gles2_fatal(7,code);
 if (!xwglMakeCurrent(NULL,NULL)) pd2_gles2_fatal(7,PD2_GL_RELEASE);
 pd2_status(7,0);
 return 0;
}
