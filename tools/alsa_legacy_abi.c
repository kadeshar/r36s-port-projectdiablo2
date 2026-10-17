/* Compile against the source headers with exactly the library's toolchain. */
#include <sys/ioctl.h>
#include <time.h>
#include <sound/asound.h>
_Static_assert(sizeof(void *) == 4, "requires ARM32");
_Static_assert(sizeof(time_t) == 4, "requires legacy time32 ABI");
_Static_assert(sizeof(struct snd_pcm_sync_ptr) == 132, "unexpected sync_ptr layout");
_Static_assert(SNDRV_PCM_IOCTL_SYNC_PTR == 0xc0844123U, "unexpected sync_ptr ioctl");
