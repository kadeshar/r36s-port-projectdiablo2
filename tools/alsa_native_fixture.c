/* Synthetic ALSA ABI for QEMU tests only; never packaged in the port. */
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static int opened, closed;
int snd_pcm_open(void **pcm, const char *name, int stream, int mode)
{
    const char *test = getenv("PD2_FIXTURE_MODE");
    if (stream != 0 || mode != 1) return -99;
    if (!test || strcmp(test, "success")) return !strcmp(name, "default") ? -25 : -16;
    *pcm = (void *)1;
    ++opened;
    return 0;
}
#ifndef NO_CLOSE
int snd_pcm_close(void *pcm)
{
    if (pcm != (void *)1) _exit(8);
    ++closed;
    return 0;
}
#endif
__attribute__((destructor)) static void check_closed(void)
{
    if (opened != closed) _exit(7);
}
