/* Read-only ABI evidence for the pinned upstream stat64_time64 warning.
 * Compile with the same ARMhf headers as Box86, then run under QEMU.
 * Does not call the unsafe conversion and does not touch the filesystem.
 */
#define _TIME_BITS 64
#define _FILE_OFFSET_BITS 64
#include <stddef.h>
#include <stdio.h>
#include <sys/stat.h>
#include <time.h>
int main(void) {
    printf("time_t=%zu stat=%zu atim=%zu mtim=%zu ctim=%zu timespec=%zu\n",
           sizeof(time_t), sizeof(struct stat), offsetof(struct stat, st_atim),
           offsetof(struct stat, st_mtim), offsetof(struct stat, st_ctim),
           sizeof(struct timespec));
    return 0;
}
