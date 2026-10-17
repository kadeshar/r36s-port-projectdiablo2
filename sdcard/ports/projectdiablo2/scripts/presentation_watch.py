#!/usr/bin/env python3
"""Bounded numeric-only presentation telemetry; never retain raw output."""
import argparse
import json
import os
from pathlib import Path
import stat
import time

MAX_BYTES = 262144
MAX_LINE = 512
KEYS = {'event','backend','frames','duration_ms','width','height'}


def decode_record(raw):
    try:
        def unique(pairs):
            out = {}
            for key,value in pairs:
                if key in out: raise ValueError()
                out[key]=value
            return out
        value=json.loads(raw,object_pairs_hook=unique)
        if type(value) is not dict or set(value)!=KEYS:
            return None
        if not all(type(n) is int for n in value.values()):
            return None
        if value['event'] not in (1,2,3) or value['backend'] not in (1,2):
            return None
        if not all(1<=value[k]<=16384 for k in ('width','height')):
            return None
        backend='gdi' if value['backend']==1 else 'opengl'
        if value['event'] in (2,3):
            if value['frames']!=(0 if value['event']==2 else 1) or value['duration_ms']!=0: return None
            return dict(event='render_status',backend=backend,status='window_ready' if value['event']==2 else 'first_present',width=value['width'],height=value['height'])
        if not 0<=value['frames']<=1000000 or not 1<=value['duration_ms']<=3600000:
            return None
        return dict(event='render_sample',backend=backend,frames=value['frames'],duration_ms=value['duration_ms'],width=value['width'],height=value['height'])
    except (ValueError,TypeError,RecursionError,UnicodeError):
        return None


def emit(value):
    print('PD2_EVENT '+json.dumps(value,separators=(',',':')),flush=True)


def status(kind,backend='unknown',width=640,height=480):
    return dict(event='render_status',backend=backend,status=kind,width=width,height=height)


def watch(work,pid,deadline_seconds=30):
    path=Path(work)/'ProjectD2/pd2-present.jsonl'
    start=time.monotonic(); warned=False; seen=False; count=0; pending=b''; stream=None
    try:
        while True:
            try: os.kill(pid,0)
            except (ProcessLookupError,PermissionError): return 0
            if stream is None:
                try:
                    before=path.lstat()
                    if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1:
                        emit(status('invalid_capture'));return 1
                    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
                    actual=os.fstat(fd)
                    if (actual.st_dev,actual.st_ino)!=(before.st_dev,before.st_ino) or not stat.S_ISREG(actual.st_mode) or actual.st_nlink!=1:
                        os.close(fd);emit(status('invalid_capture'));return 1
                    stream=os.fdopen(fd,'rb',buffering=0)
                except FileNotFoundError: pass
                except OSError:
                    emit(status('unavailable'));return 1
            if stream is not None:
                chunk=stream.read(min(4096,MAX_BYTES-count))
                if chunk:
                    count+=len(chunk);pending+=chunk
                    while b'\n' in pending:
                        line,pending=pending.split(b'\n',1)
                        value=decode_record(line) if len(line)<=MAX_LINE else None
                        if value:
                            emit(value)
                            if (value['event']=='render_sample' and value['frames']>0) or value.get('status')=='first_present': seen=True
                    if len(pending)>MAX_LINE:
                        emit(status('invalid_capture'));return 1
                    if count>=MAX_BYTES:
                        emit(status('capture_limit'));return 0
            if not seen and not warned and time.monotonic()-start>=deadline_seconds:
                emit(status('no_presentation'));warned=True
            time.sleep(0.25)
    finally:
        if stream is not None: stream.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--work',required=True);parser.add_argument('--pid',type=int,required=True)
    args=parser.parse_args()
    if args.pid<=1:return 1
    try: return watch(args.work,args.pid)
    except (OSError,ValueError):
        emit(status('unavailable'));return 1

if __name__=='__main__':
    raise SystemExit(main())
