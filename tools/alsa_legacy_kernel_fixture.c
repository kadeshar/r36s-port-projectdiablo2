/* Test-only simulated ALSA kernel for the REAL local libasound under QEMU.
 * Rejects the unsupported 136-byte request; accepts the 132-byte ARM32 ABI.
 * Never packaged or loaded on the handheld.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <sound/asound.h>

static int devices[4096], old_calls, pcm_opens;

static int open_node(const char *name, int flags, mode_t mode)
{
    int kind = !strncmp(name, "/dev/snd/controlC", 17) ? 1 : !strncmp(name, "/dev/snd/pcmC", 13) ? 2 : 0;
    int fd = syscall(SYS_openat, AT_FDCWD, kind ? "/dev/null" : name, flags, mode);
    if (fd >= 0 && fd < 4096) devices[fd] = kind;
    if (fd >= 0 && kind == 2) ++pcm_opens;
    return fd;
}

int open(const char *name, int flags, ...)
{
    mode_t mode = 0;
    if (flags & O_CREAT) { va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap); }
    return open_node(name, flags, mode);
}

int open64(const char *name, int flags, ...)
{
    mode_t mode = 0;
    if (flags & O_CREAT) { va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap); }
    return open_node(name, flags, mode);
}

int close(int fd)
{
    if (fd >= 0 && fd < 4096) devices[fd] = 0;
    return syscall(SYS_close, fd);
}

void *mmap(void *address, size_t length, int prot, int flags, int fd, off_t offset)
{
    void *(*real_mmap)(void *, size_t, int, int, int, off_t) = dlsym(RTLD_NEXT, "mmap");
    if (fd >= 0 && fd < 4096 && devices[fd]) { errno = ENXIO; return MAP_FAILED; }
    return real_mmap(address, length, prot, flags, fd, offset);
}

void *mmap64(void *address, size_t length, int prot, int flags, int fd, off64_t offset)
{
    void *(*real_mmap)(void *, size_t, int, int, int, off64_t) = dlsym(RTLD_NEXT, "mmap64");
    if (fd >= 0 && fd < 4096 && devices[fd]) { errno = ENXIO; return MAP_FAILED; }
    return real_mmap(address, length, prot, flags, fd, offset);
}

int ioctl(int fd, unsigned long request, ...)
{
    void *arg = NULL;
    int (*real_ioctl)(int, unsigned long, ...) = dlsym(RTLD_NEXT, "ioctl");
    if (_IOC_DIR(request) || _IOC_SIZE(request)) { va_list ap; va_start(ap, request); arg = va_arg(ap, void *); va_end(ap); }
    if (fd < 0 || fd >= 4096 || !devices[fd]) return real_ioctl(fd, request, arg);
    if (request == 0xc0884123UL) _exit(73);
    if (devices[fd] == 1) {
        if (request == SNDRV_CTL_IOCTL_PVERSION) { *(int *)arg = SNDRV_CTL_VERSION; return 0; }
        if (request == SNDRV_CTL_IOCTL_CARD_INFO) {
            struct snd_ctl_card_info *info = arg;
            memset(info, 0, sizeof(*info)); strcpy((char *)info->id, "fixture"); return 0;
        }
        if (request == SNDRV_CTL_IOCTL_PCM_PREFER_SUBDEVICE) return 0;
    } else {
        if (request == SNDRV_PCM_IOCTL_PVERSION) { *(int *)arg = SNDRV_PROTOCOL_VERSION(2,0,9); return 0; }
        if (request == SNDRV_PCM_IOCTL_INFO) {
            struct snd_pcm_info *info = arg;
            memset(info, 0, sizeof(*info)); info->subdevices_count = 1; return 0;
        }
        if (request == SNDRV_PCM_IOCTL_TTSTAMP || request == SNDRV_PCM_IOCTL_TSTAMP) return 0;
        if (request == 0xc0844123UL) {
            struct snd_pcm_sync_ptr *sync = arg;
            ++old_calls;
            if (getenv("PD2_FIXTURE_DENY_LEGACY")) { errno = ENOTTY; return -1; }
            sync->s.status.state = SNDRV_PCM_STATE_OPEN;
            sync->s.status.hw_ptr = 0;
            return 0;
        }
    }
    errno = ENOTTY;
    return -1;
}

__attribute__((destructor)) static void verify(void)
{
    if (!pcm_opens || !old_calls) _exit(74);
}
