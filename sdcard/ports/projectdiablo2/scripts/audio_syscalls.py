"""Project bounded strace open/ioctl/close records into numeric-only events.

No filenames, process IDs, memory addresses or free-form errno text survive.
The node category describes the requested /dev/snd path, not proof of its type.
"""
import re

LIMIT = 262144
MAX_EVENTS = 64
# Linux errno values, independent of the host running the parser/tests.
ERRNO = dict(EPERM=1, ENOENT=2, EINTR=4, EIO=5, ENXIO=6, EBADF=9, EAGAIN=11,
             ENOMEM=12, EACCES=13, EFAULT=14, EBUSY=16, EEXIST=17, ENODEV=19,
             ENOTDIR=20, EINVAL=22, ENFILE=23, EMFILE=24, ENOTTY=25, ENOSPC=28,
             ESPIPE=29, EROFS=30, EPIPE=32, ENAMETOOLONG=36, ENOSYS=38,
             ELOOP=40, EOVERFLOW=75, EOPNOTSUPP=95, ENOTSUP=95, ETIMEDOUT=110,
             EREMOTEIO=121)


def trace_event(arch, status):
    return dict(event='session_probe', phase='launch', check='audio_syscall_trace', arch=arch, status=status)


def result_code(text):
    match = re.match(r'(-?(?:0x[0-9a-f]+|[0-9]+))(?: (E[A-Z0-9]+))?', text)
    if not match:
        return None
    value = int(match[1], 16 if 'x' in match[1] else 10)
    if value == -1:
        return -ERRNO[match[2]] if match[2] in ERRNO else None
    return value if 0 <= value <= 2147483647 else None


def project_trace(content, arch, limited=False):
    if arch not in ('armhf', 'aarch64'):
        raise ValueError('invalid architecture')
    limited |= len(content) > LIMIT
    content = content[:LIMIT]
    fds, results, seen, libraries = {}, [], set(), set()
    for raw in content.decode('utf-8', 'replace').splitlines(keepends=True):
        if not raw.endswith('\n'):
            continue  # Never interpret a truncated syscall record.
        line = raw.rstrip('\r\n')
        # No -f is used: exactly one helper process, no interleaved PID tables.
        opened = re.fullmatch(r'(?:openat\([^,]+, |open\()"([^"\\]{1,256})"[^\n]*\)\s+= (.*)', line)
        value = None
        if opened:
            rc = result_code(opened[2])
            if rc is None:
                continue
            if rc >= 0:
                fds.pop(rc, None)  # FD reuse must not inherit a previous node.
            path = opened[1]
            if rc >= 0 and re.fullmatch(r'libasound\.so\.2(?:\.[0-9.]+)?', path.rsplit('/', 1)[-1]):
                libraries.add('legacy_armhf' if path.endswith('/.alsa-legacy-armhf/libasound.so.2') else 'system')
            if re.fullmatch(r'/dev/snd/pcmC[0-9]{1,4}D[0-9]{1,4}[pc]', path):
                node = 'pcm'
            elif re.fullmatch(r'/dev/snd/controlC[0-9]{1,4}', path):
                node = 'control'
            else:
                continue
            metadata = dict(node=node, device_kind='unknown')
            device = re.search(r'<(char|block) ([0-9]{1,7}):([0-9]{1,7})>', opened[2])
            if rc >= 0 and device and all(int(n) <= 1048575 for n in device.groups()[1:]):
                metadata.update(device_kind=device[1], device_major=int(device[2]), device_minor=int(device[3]))
            value = dict(event='session_probe', phase='launch', check='audio_syscall_open',
                         arch=arch, status='ready' if rc >= 0 else 'failed', syscall_rc=rc, **metadata)
            if rc >= 0:
                if rc > 1048575:
                    continue
                value['fd'] = rc
                fds[rc] = metadata
        else:
            closed = re.fullmatch(r'close\(([0-9]+)(?:<.*>)?\)\s+= 0', line)
            if closed:
                fds.pop(int(closed[1]), None)
                continue
            call = re.fullmatch(r'ioctl\((0x[0-9a-f]{1,8}|[0-9]{1,7}), (0x[0-9a-f]{1,8}|[0-9]{1,10}), [^\n]*\)\s+= (.*)', line)
            if not call:
                continue
            fd, request = (int(v, 16 if v.startswith('0x') else 10) for v in call.groups()[:2])
            rc = result_code(call[3])
            if rc is None or fd > 1048575 or request > 4294967295:
                continue
            if fd not in fds and ((request >> 8) & 255) not in (ord('A'), ord('U')):
                continue
            metadata = fds.get(fd, dict(node='unknown', device_kind='unknown'))
            value = dict(event='session_probe', phase='launch', check='audio_syscall_ioctl',
                         arch=arch, status='ready' if rc >= 0 else 'failed', syscall_rc=rc,
                         fd=fd, request=request, **metadata)
        signature = tuple(sorted(value.items()))
        if signature not in seen:
            seen.add(signature)
            if len(results) < MAX_EVENTS:
                results.append(value)
            else:
                limited = True
    for library in sorted(libraries):
        if len(results) < MAX_EVENTS:
            results.append(dict(event='session_probe', phase='launch', check='audio_syscall_library', arch=arch, status=library))
        else:
            limited = True
    status = 'limited' if limited else 'complete' if results else 'not_observed'
    return [trace_event(arch, status), *results]
