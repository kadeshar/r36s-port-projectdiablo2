#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>

struct wl_list {
    struct wl_list *prev;
    struct wl_list *next;
};

struct wl_listener {
    struct wl_list link;
    void (*notify)(struct wl_listener *listener, void *data);
};

static void (*orig_desktop_surface_set_size)(void *surface, int32_t width, int32_t height) = NULL;
static void (*orig_center_on_output)(void *view, void *output) = NULL;
static void (*orig_set_position)(void *view, double x, double y) = NULL;

static FILE *g_log = NULL;
static void log_msg(const char *msg) {
    if (!g_log) g_log = fopen("/roms2/ports/projectdiablo2/logs/scaler.log", "a");
    if (g_log) { fputs(msg, g_log); fflush(g_log); }
}

static inline void wl_list_insert(struct wl_list *list, struct wl_list *elm) {
    elm->prev = list;
    elm->next = list->next;
    list->next->prev = elm;
    list->next = elm;
}

static void surface_commit_handler(struct wl_listener *listener, void *data) {
    void *surface = data;
    if (!surface) return;

    int buf_w = *(int *)((char *)surface + 272);
    int buf_h = *(int *)((char *)surface + 276);

    if (buf_w > 640 || buf_h > 480) {
        /* Set viewport destination to 640x480 */
        *(int32_t *)((char *)surface + 0x108) = 640;
        *(int32_t *)((char *)surface + 0x10c) = 480;

        /* Set surface geometry width & height to 640x480 */
        int orig_sw = *(int32_t *)((char *)surface + 0x88);
        int orig_sh = *(int32_t *)((char *)surface + 0x8c);
        *(int32_t *)((char *)surface + 0x88)  = 640;
        *(int32_t *)((char *)surface + 0x8c)  = 480;

        char buf[256];
        snprintf(buf, sizeof(buf), "[weston_scaler] commit_handler: scaled %dx%d (surf %dx%d) -> 640x480\n",
                 buf_w, buf_h, orig_sw, orig_sh);
        log_msg(buf);
    }
}

static struct wl_listener g_commit_listener = {
    .notify = surface_commit_handler
};
static void *g_attached_surface = NULL;

__attribute__((constructor))
static void init_scaler(void) {
    orig_desktop_surface_set_size = dlsym(RTLD_NEXT, "weston_desktop_surface_set_size");
    orig_center_on_output = dlsym(RTLD_NEXT, "weston_shell_utils_center_on_output");
    orig_set_position = dlsym(RTLD_NEXT, "weston_view_set_position");

    char buf[256];
    snprintf(buf, sizeof(buf), "[weston_scaler] Scaler v3 initialized: set_size=%p center=%p set_pos=%p\n",
             (void *)orig_desktop_surface_set_size, (void *)orig_center_on_output, (void *)orig_set_position);
    log_msg(buf);
}

void weston_desktop_surface_set_size(void *desktop_surface, int32_t width, int32_t height) {
    if (desktop_surface) {
        /* desktop_surface->surface is at offset 56 */
        void *surface = *(void **)((char *)desktop_surface + 56);
        if (surface && surface != g_attached_surface) {
            /* Attach commit listener to surface->commit_signal (offset 0x20 = 32) */
            struct wl_list *signal_list = (struct wl_list *)((char *)surface + 32);
            wl_list_insert(signal_list, &g_commit_listener.link);
            g_attached_surface = surface;
            log_msg("[weston_scaler] Attached commit listener to game surface\n");
        }
    }

    if (orig_desktop_surface_set_size) {
        orig_desktop_surface_set_size(desktop_surface, width, height);
    }
}

void weston_shell_utils_center_on_output(void *view, void *output) {
    if (!view || !output) return;

    void *surface = *(void **)view; /* view->surface at offset 0 */
    if (surface) {
        int buf_w = *(int *)((char *)surface + 272);
        int buf_h = *(int *)((char *)surface + 276);
        if (buf_w > 640 || buf_h > 480) {
            log_msg("[weston_scaler] center_on_output: positioning scaled view at (0,0)\n");
            if (orig_set_position) {
                orig_set_position(view, 0.0, 0.0);
            }
            return;
        }
    }

    if (orig_center_on_output) {
        orig_center_on_output(view, output);
    }
}
