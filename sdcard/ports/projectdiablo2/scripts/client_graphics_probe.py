#!/usr/bin/env python3
"""Non-root access check only; does not take DRM master or modify devices."""
import json
import os
import stat


def drm_access(path='/dev/dri/card0'):
    fd = None
    try:
        if not stat.S_ISCHR(os.stat(path).st_mode):
            return 'invalid'
        fd = os.open(path, os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK)
        return 'ready'
    except FileNotFoundError:
        return 'missing'
    except PermissionError:
        return 'denied'
    except OSError:
        return 'unavailable'
    finally:
        if fd is not None:
            os.close(fd)


if __name__ == '__main__':
    print('PD2_EVENT ' + json.dumps(dict(event='session_probe', phase='launch',
          check='client_drm_access', status=drm_access()), separators=(',', ':')))
