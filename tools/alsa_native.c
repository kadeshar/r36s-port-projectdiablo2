/* Native ARM32 ALSA open comparison. No writes, mixer calls or playback.
 * Built without ALSA headers: load the same libasound.so.2 as Box86 at runtime.
 */
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

typedef struct _snd_pcm snd_pcm_t;
typedef int (*open_fn)(snd_pcm_t **, const char *, int, int);
typedef int (*close_fn)(snd_pcm_t *);

static int valid_node(const char *name)
{
    const char *p;
    unsigned int value;
    int i;
    if (strncmp(name, "plughw:", 7)) return 0;
    p = name + 7;
    for (i = 0; i < 2; ++i) {
        if (*p < '0' || *p > '9') return 0;
        value = 0;
        while (*p >= '0' && *p <= '9') {
            value = value * 10 + (unsigned)(*p++ - '0');
            if (value > 1023) return 0;
        }
        if (i == 0 && *p++ != ',') return 0;
    }
    return !*p;
}

static int try_open(open_fn pcm_open, close_fn pcm_close, const char *name)
{
    snd_pcm_t *pcm = NULL;
    /* SND_PCM_STREAM_PLAYBACK = 0, SND_PCM_NONBLOCK = 1 (ALSA public ABI). */
    int rc = pcm_open(&pcm, name, 0, 1);
    if (rc >= 0 && pcm) pcm_close(pcm);
    return rc;
}

int main(int argc, char **argv)
{
    void *library;
    open_fn pcm_open;
    close_fn pcm_close;
    int default_rc, plughw_rc = 0;
    if (argc > 2 || (argc == 2 && !valid_node(argv[1]))) return 2;
    library = dlopen("libasound.so.2", RTLD_NOW | RTLD_LOCAL);
    if (!library) {
        puts("{\"schema_version\":1,\"status\":\"library_missing\"}");
        return 0;
    }
    pcm_open = (open_fn)dlsym(library, "snd_pcm_open");
    pcm_close = (close_fn)dlsym(library, "snd_pcm_close");
    if (!pcm_open || !pcm_close) {
        puts("{\"schema_version\":1,\"status\":\"symbol_missing\"}");
        dlclose(library);
        return 0;
    }
    default_rc = try_open(pcm_open, pcm_close, "default");
    if (argc == 2) plughw_rc = try_open(pcm_open, pcm_close, argv[1]);
    printf("{\"schema_version\":1,\"status\":\"ready\",\"default_rc\":%d,\"plughw_rc\":", default_rc);
    if (argc == 2) printf("%d", plughw_rc);
    else printf("null");
    puts("}");
    dlclose(library);
    return 0;
}
