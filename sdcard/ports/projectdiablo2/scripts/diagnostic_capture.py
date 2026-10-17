#!/usr/bin/env python3
"""Drain child output; accept only bounded graphics-layer events, never raw text."""
import json
import sys
from safe_log import parse_line


def stream(source,sink):
    total=0; events=0; oversized=False
    while True:
        raw=source.readline(4097)
        if not raw: break
        total+=len(raw)
        if oversized or len(raw)>4096:
            oversized=not raw.endswith(b'\n');continue
        if total>16384 or events>=16: continue
        value=parse_line(raw.decode('utf-8','replace'))
        if value and value.get('event')=='graphics_layer':
            events+=1
            try:
                sink.write('PD2_EVENT '+json.dumps(value,separators=(',',':'))+'\n');sink.flush()
            except (OSError,ValueError): pass

if __name__=='__main__':
    stream(sys.stdin.buffer,sys.stdout)
