#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

struct wl_list {
    struct wl_list *prev;
    struct wl_list *next;
};

struct wl_listener {
    struct wl_list link;
    void (*notify)(struct wl_listener *listener, void *data);
};

static void (*orig_desktop_surface_set_size)(void *surface, int32_t width, int32_t height) = NULL;
static void *(*orig_desktop_surface_get_surface)(void *desktop_surface) = NULL;
static void *(*orig_desktop_surface_create_view)(void *desktop_surface) = NULL;
static void (*orig_surface_build_buffer_matrix)(void *surface, void *matrix) = NULL;
static int (*orig_matrix_invert)(void *dst, const void *src) = NULL;
static void (*orig_view_geometry_dirty)(void *view) = NULL;
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
        /* Set viewport destination to 640x480 in active and pending surface state */
        *(int32_t *)((char *)surface + 0x108) = 640;  /* surface->buffer_viewport.destination_width */
        *(int32_t *)((char *)surface + 0x10c) = 480;  /* surface->buffer_viewport.destination_height */
        *(int32_t *)((char *)surface + 0x200) = 640;  /* pending.buffer_viewport.destination_width */
        *(int32_t *)((char *)surface + 0x204) = 480;  /* pending.buffer_viewport.destination_height */

        /* Recompute surface transform matrices */
        void *surface_to_buffer = (char *)surface + 0x28c;
        void *buffer_to_surface = (char *)surface + 0x248;
        if (orig_surface_build_buffer_matrix) {
            orig_surface_build_buffer_matrix(surface, surface_to_buffer);
        }
        if (orig_matrix_invert) {
            orig_matrix_invert(buffer_to_surface, surface_to_buffer);
        }

        /* Set surface geometry width & height to 640x480 */
        int orig_sw = *(int32_t *)((char *)surface + 0x88);
        int orig_sh = *(int32_t *)((char *)surface + 0x8c);
        *(int32_t *)((char *)surface + 0x88)  = 640;
        *(int32_t *)((char *)surface + 0x8c)  = 480;

        /* Dirty geometry on all surface views */
        struct wl_list *views = (struct wl_list *)((char *)surface + 0xa0);
        if (views->next && views->prev && orig_view_geometry_dirty) {
            for (struct wl_list *pos = views->next; pos && pos != views; pos = pos->next) {
                void *view = (char *)pos - 0x8;
                orig_view_geometry_dirty(view);
            }
        }

        static int s_commit_logged = 0;
        if (s_commit_logged < 15) {
            s_commit_logged++;
            char buf[256];
            snprintf(buf, sizeof(buf), "[weston_scaler] commit_handler: scaled %dx%d (surf %dx%d) -> 640x480\n",
                     buf_w, buf_h, orig_sw, orig_sh);
            log_msg(buf);
        }
    }
}

#define MAX_ATTACHED 8
static struct {
    void *surface;
    struct wl_listener listener;
} g_attached[MAX_ATTACHED];
static int g_num_attached = 0;

static void attach_scaler_listener(void *surface) {
    if (!surface) return;
    for (int i = 0; i < g_num_attached; i++) {
        if (g_attached[i].surface == surface) return;
    }
    if (g_num_attached >= MAX_ATTACHED) return;

    int idx = g_num_attached++;
    g_attached[idx].surface = surface;
    g_attached[idx].listener.notify = surface_commit_handler;

    struct wl_list *signal_list = (struct wl_list *)((char *)surface + 32);
    if (signal_list->prev) {
        wl_list_insert(signal_list->prev, &g_attached[idx].listener.link);
    } else {
        wl_list_insert(signal_list, &g_attached[idx].listener.link);
    }

    char buf[256];
    snprintf(buf, sizeof(buf), "[weston_scaler] Attached commit listener to surface %p (slot %d)\n", surface, idx);
    log_msg(buf);
}

__attribute__((constructor))
static void init_scaler(void) {
    orig_desktop_surface_set_size = dlsym(RTLD_NEXT, "weston_desktop_surface_set_size");
    orig_desktop_surface_get_surface = dlsym(RTLD_NEXT, "weston_desktop_surface_get_surface");
    orig_desktop_surface_create_view = dlsym(RTLD_NEXT, "weston_desktop_surface_create_view");
    orig_surface_build_buffer_matrix = dlsym(RTLD_NEXT, "weston_surface_build_buffer_matrix");
    orig_matrix_invert = dlsym(RTLD_NEXT, "weston_matrix_invert");
    orig_view_geometry_dirty = dlsym(RTLD_NEXT, "weston_view_geometry_dirty");
    orig_center_on_output = dlsym(RTLD_NEXT, "weston_shell_utils_center_on_output");
    orig_set_position = dlsym(RTLD_NEXT, "weston_view_set_position");

    char buf[384];
    snprintf(buf, sizeof(buf),
             "[weston_scaler] Scaler v4 initialized: set_size=%p get_surf=%p build_mat=%p inv=%p geo_dirty=%p center=%p set_pos=%p\n",
             (void *)orig_desktop_surface_set_size, (void *)orig_desktop_surface_get_surface,
             (void *)orig_surface_build_buffer_matrix, (void *)orig_matrix_invert,
             (void *)orig_view_geometry_dirty, (void *)orig_center_on_output, (void *)orig_set_position);
    log_msg(buf);
}

void weston_desktop_surface_set_size(void *desktop_surface, int32_t width, int32_t height) {
    if (desktop_surface && orig_desktop_surface_get_surface) {
        void *surface = orig_desktop_surface_get_surface(desktop_surface);
        attach_scaler_listener(surface);
    }

    if (orig_desktop_surface_set_size) {
        orig_desktop_surface_set_size(desktop_surface, width, height);
    }
}

void *weston_desktop_surface_create_view(void *desktop_surface) {
    if (desktop_surface && orig_desktop_surface_get_surface) {
        void *surface = orig_desktop_surface_get_surface(desktop_surface);
        attach_scaler_listener(surface);
    }

    if (orig_desktop_surface_create_view) {
        return orig_desktop_surface_create_view(desktop_surface);
    }
    return NULL;
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
