/* Real host-kernel syscall format test, against a container-only /dev/null alias. */
#include <errno.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <unistd.h>
int main(void)
{
    int value = 0, rc, error;
    int fd = open("/dev/snd/pcmC2D3p", O_RDWR | O_NONBLOCK);
    if (fd < 0) return 2;
    rc = ioctl(fd, 0x80044100UL, &value);
    error = errno;
    close(fd);
    return rc == -1 && error == ENOTTY ? 0 : 3;
}
