#!/usr/bin/env python3
"""Authenticate fixed synthetic probes; never execute paths from manifests."""
import argparse
import hashlib
import os
from pathlib import Path
import stat
from fps_renderer import _directory, _identity, _linked, _absolute

PINS = {
    'armhf': ('graphics-layers.armhf', 9692, 'da8b918db612575a05b6f8da136ca72ec93c52d2f13ec04f1232fe783e48dfde'),
    'win32': ('graphics-layers.exe', 114176, '86fb129281f7b8edaea13a7c6a814416b9ee293e409bd80a569967a273541925'),
}


def authenticate(port,arch):
    name,size,digest=PINS[arch]
    path=_absolute(port)/'compat/graphics-probe'/name
    _directory(path.parent)
    info=path.lstat()
    if _linked(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 0<size<=1048576 or info.st_size!=size:
        raise ValueError('invalid probe')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
    with os.fdopen(fd,'rb') as stream:
        if _identity(os.fstat(stream.fileno()))!=_identity(info): raise ValueError('invalid probe')
        data=stream.read(size+1)
    if len(data)!=size or hashlib.sha256(data).hexdigest()!=digest or _identity(path.lstat())!=_identity(info):
        raise ValueError('invalid probe')
    return path,data


def prepare(port,work,arch):
    path,data=authenticate(port,arch)
    if arch=='armhf': return path
    directory=_absolute(work)/'ProjectD2'
    _directory(directory)
    target=directory/'pd2-graphics.exe'
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0),0o600)
    with os.fdopen(fd,'wb') as stream: stream.write(data)
    return target


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',required=True);parser.add_argument('--work',required=True)
    parser.add_argument('--arch',choices=tuple(PINS),required=True)
    args=parser.parse_args()
    try: prepare(args.port,args.work,args.arch);return 0
    except (OSError,ValueError,TypeError): return 1

if __name__=='__main__': raise SystemExit(main())
