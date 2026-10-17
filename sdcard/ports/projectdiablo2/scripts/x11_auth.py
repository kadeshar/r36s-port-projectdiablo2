#!/usr/bin/env python3
"""Create one private Xauthority cookie for the session's Xwayland.
The cookie is temporary, never printed, logged, hashed or exported.
"""
import argparse,os,pathlib,secrets,stat,struct,sys,tempfile
sys.dont_write_bytecode=True
NAME=b'MIT-MAGIC-COOKIE-1';DISPLAY=b'0';COOKIE_BYTES=16;MAX_FILE=4096
FAMILY_LOCAL=256;FAMILY_WILD=65535

def field(value):
 if len(value)>65535:raise ValueError('field')
 return struct.pack('>H',len(value))+value

def record(family,cookie):
 return struct.pack('>H',family)+field(b'')+field(DISPLAY)+field(NAME)+field(cookie)

def safe_parent(path):
 path=path.absolute()
 if path.name!='xauthority' or path.is_symlink():raise ValueError('path')
 parent=path.parent
 if parent.is_symlink() or not parent.is_dir():raise ValueError('parent')
 return path

def create(path):
 path=safe_parent(path)
 if path.exists():raise ValueError('exists')
 cookie=secrets.token_bytes(COOKIE_BYTES)
 data=record(FAMILY_WILD,cookie)+record(FAMILY_LOCAL,cookie)
 temporary=None
 try:
  if os.name=='nt':
   temporary=path.parent/('.xauth-'+secrets.token_hex(8))
   fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_BINARY,0o666)
  else:
   fd,name=tempfile.mkstemp(prefix='.xauth-',dir=str(path.parent));temporary=pathlib.Path(name)
   os.fchmod(fd,0o600)
  with os.fdopen(fd,'wb',closefd=True) as stream:
   stream.write(data);stream.flush();os.fsync(stream.fileno())
  if temporary.stat().st_size>MAX_FILE:raise ValueError('size')
  # Hard-link publication is exclusive on POSIX/NTFS; never overwrite a raced target.
  os.link(temporary,path);temporary.unlink();temporary=None
  info=os.lstat(path)
  if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('result')
 except BaseException:
  if temporary is not None:
   try:temporary.unlink()
   except OSError:pass
  raise

def main(argv=None):
 parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--path',required=True)
 try:
  args=parser.parse_args(argv);create(pathlib.Path(args.path));return 0
 except BaseException:return 1
if __name__=='__main__':raise SystemExit(main())
