/* SPDX-License-Identifier: MIT
 * Synthetic RGB diagnostic; no game assets, development headers or link-time GL.
 * Parent owns the 15 second deadline (including driver calls).
 */
#define _POSIX_C_SOURCE 200809L
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static const char *mode = "sdl", *backend = "unknown", *renderer = "unknown";
static void event(const char *stage, int code, unsigned frame) {
    printf("PD2_EVENT {\"event\":\"graphics_layer\",\"schema\":1,\"probe\":\"%s\",\"stage\":\"%s\",\"status\":\"%s\",\"backend\":\"%s\",\"renderer\":\"%s\",\"frame\":%u,\"code\":%d}\n",
           mode, stage, code ? "failed" : "ok", backend, renderer, frame, code);
    fflush(stdout);
}
static void pause_frame(void) {
    struct timespec remaining = {2, 0};
    while (nanosleep(&remaining, &remaining) != 0) {}
}
/* Known software signatures dominate. Hardware classification only for known
 * driver families; it describes GL_RENDERER, never proves hardware execution. */
static const char *classify(const unsigned char *s) {
    char lower[256]; size_t i;
    if (!s) return "unknown";
    for (i = 0; i < sizeof(lower)-1 && s[i]; ++i)
        lower[i] = s[i] >= 'A' && s[i] <= 'Z' ? (char)(s[i]+32) : (char)s[i];
    lower[i] = 0;
    if (strstr(lower,"llvmpipe") || strstr(lower,"softpipe") ||
        strstr(lower,"software") || strstr(lower,"swrast") || strstr(lower,"swiftshader")) return "software";
    if (strstr(lower,"mali") || strstr(lower,"panfrost") || strstr(lower,"lima") ||
        strstr(lower,"adreno") || strstr(lower,"nvidia") || strstr(lower,"radeon") || strstr(lower,"intel")) return "gpu";
    return "unknown";
}
#define LOAD(handle, name) do { *(void **)(&name) = dlsym(handle, #name); if (!name) { code = 2; goto out; } } while (0)
static int sdl_probe(void) {
    int code = 0, initialized = 0; void *lib = NULL, *window = NULL, *context = NULL;
    int (*SDL_Init)(unsigned); void (*SDL_Quit)(void);
    int (*SDL_GL_SetAttribute)(int,int); void *(*SDL_CreateWindow)(const char *,int,int,int,int,unsigned);
    void (*SDL_DestroyWindow)(void *); void *(*SDL_GL_CreateContext)(void *);
    void (*SDL_GL_DeleteContext)(void *); void *(*SDL_GL_GetProcAddress)(const char *);
    void (*SDL_GL_SwapWindow)(void *); void (*SDL_PumpEvents)(void);
    const char *(*SDL_GetCurrentVideoDriver)(void);
    void (*glClearColor)(float,float,float,float); void (*glClear)(unsigned);
    const unsigned char *(*glGetString)(unsigned); unsigned i;
    const char *path = getenv("CRUSTY_LIBSDL"), *driver;
    if (!path || !*path) { code = 1; goto out; }
    lib = dlopen(path, RTLD_NOW | RTLD_LOCAL); if (!lib) { code = 1; goto out; }
    LOAD(lib, SDL_Init); LOAD(lib, SDL_Quit); LOAD(lib, SDL_GL_SetAttribute);
    LOAD(lib, SDL_CreateWindow); LOAD(lib, SDL_DestroyWindow); LOAD(lib, SDL_GL_CreateContext);
    LOAD(lib, SDL_GL_DeleteContext); LOAD(lib, SDL_GL_GetProcAddress); LOAD(lib, SDL_GL_SwapWindow);
    LOAD(lib, SDL_GetCurrentVideoDriver); LOAD(lib, SDL_PumpEvents);
    event("library",0,0);
    if (SDL_Init(0x20u) != 0) { code = 3; goto out; } initialized = 1;
    driver = SDL_GetCurrentVideoDriver();
    if (driver) {
        const char *known[] = {"x11","wayland","kmsdrm","directfb","dummy","windows"};
        backend = "other";
        for (i=0;i<sizeof(known)/sizeof(known[0]);++i) if (!strcmp(driver,known[i])) backend=known[i];
        if (!strcmp(driver,"KMSDRM")) backend="kmsdrm";
    }
    /* SDL_GL_CONTEXT_PROFILE_MASK=21, ES=4; major=17, minor=18. */
    if (SDL_GL_SetAttribute(21,4) || SDL_GL_SetAttribute(17,2) ||
        SDL_GL_SetAttribute(18,0) || SDL_GL_SetAttribute(5,1)) { code=4; goto out; }
    window = SDL_CreateWindow("PD2 synthetic RGB",0x2fff0000,0x2fff0000,640,480,0x6u);
    if (!window) { code=5; goto out; }
    context = SDL_GL_CreateContext(window); if (!context) { code=6; goto out; }
    *(void **)(&glClearColor)=SDL_GL_GetProcAddress("glClearColor");
    *(void **)(&glClear)=SDL_GL_GetProcAddress("glClear");
    *(void **)(&glGetString)=SDL_GL_GetProcAddress("glGetString");
    if (!glClearColor || !glClear || !glGetString) { code=2; goto out; }
    renderer=classify(glGetString(0x1f01)); event("context",0,0);
    for (i=0;i<3;++i) {
        SDL_PumpEvents(); glClearColor(i==0,i==1,i==2,1); glClear(0x4000);
        SDL_GL_SwapWindow(window); event("frame",0,i+1); pause_frame();
    }
out:
    if (context) SDL_GL_DeleteContext(context);
    if (window) SDL_DestroyWindow(window);
    if (initialized) SDL_Quit();
    if (lib) dlclose(lib);
    event(code ? "error" : "done",code,0); return code;
}
/* Xlib ABI: XID and pointer-sized fields follow native unsigned long. These
 * public XVisualInfo/XSetWindowAttributes layouts apply to ARM ILP32 and LP64. */
typedef unsigned long XID;
typedef struct { void *visual; XID visualid; int screen,depth,class_; unsigned long red_mask,green_mask,blue_mask; int colormap_size,bits_per_rgb; } VisualInfo;
typedef struct { XID background_pixmap; unsigned long background_pixel; XID border_pixmap; unsigned long border_pixel; int bit_gravity,win_gravity,backing_store; unsigned long backing_planes,backing_pixel; int save_under; long event_mask,do_not_propagate_mask; int override_redirect; XID colormap,cursor; } WindowAttributes;
static int glx_probe(void) {
    int code=0; unsigned i; void *x=NULL,*g=NULL,*display=NULL,*context=NULL; VisualInfo *visual=NULL;
    XID window=0,colormap=0; WindowAttributes attrs;
    void *(*XOpenDisplay)(const char *); int (*XDefaultScreen)(void *); XID (*XRootWindow)(void *,int);
    XID (*XCreateColormap)(void *,XID,void *,int);
    XID (*XCreateWindow)(void *,XID,int,int,unsigned,unsigned,unsigned,int,unsigned,void *,unsigned long,WindowAttributes *);
    int (*XMapWindow)(void *,XID); int (*XSync)(void *,int); int (*XDestroyWindow)(void *,XID);
    int (*XFreeColormap)(void *,XID); int (*XFree)(void *); int (*XCloseDisplay)(void *);
    VisualInfo *(*glXChooseVisual)(void *,int,int *); void *(*glXCreateContext)(void *,VisualInfo *,void *,int);
    int (*glXMakeCurrent)(void *,XID,void *); void (*glXSwapBuffers)(void *,XID); void (*glXDestroyContext)(void *,void *);
    void (*glClearColor)(float,float,float,float); void (*glClear)(unsigned); const unsigned char *(*glGetString)(unsigned);
    int visual_attrs[]={4,5,8,8,9,8,10,8,0}; /* RGBA, DOUBLEBUFFER, RGB sizes */
    x=dlopen("libX11.so.6",RTLD_NOW|RTLD_LOCAL); g=dlopen("libGL.so.1",RTLD_NOW|RTLD_LOCAL);
    if (!x || !g) { code=1; goto out; }
    LOAD(x,XOpenDisplay); LOAD(x,XDefaultScreen); LOAD(x,XRootWindow); LOAD(x,XCreateColormap);
    LOAD(x,XCreateWindow); LOAD(x,XMapWindow); LOAD(x,XSync); LOAD(x,XDestroyWindow);
    LOAD(x,XFreeColormap); LOAD(x,XFree); LOAD(x,XCloseDisplay);
    LOAD(g,glXChooseVisual); LOAD(g,glXCreateContext); LOAD(g,glXMakeCurrent);
    LOAD(g,glXSwapBuffers); LOAD(g,glXDestroyContext); LOAD(g,glClearColor); LOAD(g,glClear); LOAD(g,glGetString);
    event("library",0,0); display=XOpenDisplay(NULL); if (!display) { code=7; goto out; } backend="x11";
    visual=glXChooseVisual(display,XDefaultScreen(display),visual_attrs); if (!visual) { code=8; goto out; }
    colormap=XCreateColormap(display,XRootWindow(display,visual->screen),visual->visual,0);
    memset(&attrs,0,sizeof(attrs)); attrs.colormap=colormap;
    window=XCreateWindow(display,XRootWindow(display,visual->screen),0,0,640,480,0,visual->depth,1,visual->visual,1ul<<13,&attrs);
    if (!window) { code=5; goto out; } XMapWindow(display,window); XSync(display,0);
    context=glXCreateContext(display,visual,NULL,1); if (!context || !glXMakeCurrent(display,window,context)) { code=6; goto out; }
    renderer=classify(glGetString(0x1f01)); event("context",0,0);
    for (i=0;i<3;++i) { glClearColor(i==0,i==1,i==2,1); glClear(0x4000); glXSwapBuffers(display,window); event("frame",0,i+1); pause_frame(); }
out:
    if (context) { glXMakeCurrent(display,0,NULL); glXDestroyContext(display,context); }
    if (window) XDestroyWindow(display,window);
    if (colormap) XFreeColormap(display,colormap);
    if (visual) XFree(visual);
    if (display) XCloseDisplay(display);
    if (g) dlclose(g);
    if (x) dlclose(x);
    event(code ? "error" : "done",code,0); return code;
}
int main(int argc,char **argv) {
    if (argc!=3 || strcmp(argv[1],"--mode") || (strcmp(argv[2],"sdl") && strcmp(argv[2],"glx"))) { event("error",20,0); return 20; }
    mode=argv[2]; event("start",0,0);
    return !strcmp(mode,"sdl") ? sdl_probe() : glx_probe();
}
