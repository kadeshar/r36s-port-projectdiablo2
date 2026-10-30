#!/usr/bin/env python3
"""Numeric local metrics plus fixed scope enums. No process identity dumps."""
import argparse,itertools,json,os,pathlib,re,shutil,stat,sys,time


_COUNTER_MAX=10**18


def _uint(value):
 if not re.fullmatch(r'[0-9]{1,19}',value):return None
 number=int(value)
 return number if number<=_COUNTER_MAX else None


def _process(proc_root,pid):
 """Parse only numeric stat fields; never export comm, cmdline or environ."""
 text=_text(proc_root/str(pid)/'stat',8192)
 end=text.rfind(')')
 if end<0 or text[:text.find('(')].strip()!=str(pid):return None
 parts=text[end+1:].split()
 if len(parts)<22:return None
 # Offsets start at stat field 3 (state); cutime/cstime intentionally excluded.
 values=[_uint(parts[index]) for index in (1,9,11,12,19)]
 if any(value is None for value in values):return None
 return dict(zip(('ppid','faults','user','system','start'),values))


class MetricsSampler:
 """Per-loop baselines, pinned to one session anchor identity.

 Only the anchor and its verified descendants are game processes. A root-owned
 compositor elsewhere in the process tree is deliberately NOT authorized by
 its name, a role pid file, or an arbitrary caller-supplied PID. Reparented
 processes are dropped in legacy anchor mode. Optional private-prefix mode
 independently authenticates UID/prefix/starttime and retains reparented Wine
 processes. Its scope is always a verified subset, never a completeness claim.
 No process scan occurs without an explicit anchor.
 """
 def __init__(self,pid=None,*,clock_ticks=None,wine_prefix=None,uid=None,wine_exe=None):
  if len({value is None for value in (wine_prefix,uid,wine_exe)})!=1:raise ValueError('complete session scope required')
  self.wine_exe_identity=None
  if wine_prefix is not None:
   if type(pid) is not int or not 1<pid<=2**31-1 or type(uid) is not int or not 0<=uid<=2**32-1:raise ValueError('invalid session scope')
   if not isinstance(wine_prefix,str) or not wine_prefix.startswith('/') or '\x00' in wine_prefix:raise ValueError('invalid private prefix')
   if not isinstance(wine_exe,str) or not wine_exe.startswith('/'):raise ValueError('invalid Wine runner')
   try:
    executable=os.stat(wine_exe)
    if not stat.S_ISREG(executable.st_mode):raise ValueError('invalid Wine runner')
    self.wine_exe_identity=(executable.st_dev,executable.st_ino)
   except OSError:raise ValueError('unavailable Wine runner') from None
  self.wine_prefix=wine_prefix
  self.uid=uid
  self.session_bound=None
  self.session_failed=False
  self.pid=pid
  self.anchor_start=None
  self.anchor_ended=False
  self.previous_cpu=None
  self.previous_processes={}
  self.previous_time=None
  if clock_ticks is None:
   try:clock_ticks=os.sysconf('SC_CLK_TCK')
   except (AttributeError,OSError,ValueError):clock_ticks=None
  self.clock_ticks=clock_ticks if type(clock_ticks) is int and clock_ticks>0 else None

 def collect(self,proc_root,now_ms):
  fields={}
  self._system_cpu(proc_root,fields)
  if self.wine_prefix is not None:self._session(proc_root,now_ms,fields)
  elif self.pid is not None:self._game(proc_root,now_ms,fields)
  return fields

 def _system_cpu(self,root,fields):
  # The aggregate first line is enough; do not read an unbounded CPU table.
  try:
   with (root/'stat').open(encoding='ascii') as stream:line=stream.readline(1025)
  except (OSError,UnicodeError,ValueError):line=''
  parts=line.split()
  if len(line)>1024 or len(parts)<5 or parts[0]!='cpu':
   self.previous_cpu=None;return
  numbers=[_uint(value) for value in parts[1:9]]
  if any(value is None for value in numbers):
   self.previous_cpu=None;return
  # Guest times are already included in user/nice; never double-count them.
  total=sum(numbers)
  idle=numbers[3]+(numbers[4] if len(numbers)>4 else 0)
  previous=self.previous_cpu
  self.previous_cpu=(total,idle)
  if previous is not None:
   elapsed=total-previous[0];idle_delta=idle-previous[1]
   if elapsed>0 and 0<=idle_delta<=elapsed:
    fields['system_cpu_pct_x100']=(elapsed-idle_delta)*10000//elapsed

 def _session_identity(self,root,pid,process,*,require_runner=True):
  """Local authorization only; neither status nor environment is exported.

  A private prefix is an exclusive session capability supplied by the launcher.
  Never infer ownership from a process name or an inherited parent relationship.
  """
  status=_bounded_bytes(root/str(pid)/'status',16384)
  if status is None:return None
  uids=re.findall(rb'^Uid:[ \t]+([0-9]{1,10})[ \t]+([0-9]{1,10})[ \t]+([0-9]{1,10})[ \t]+([0-9]{1,10})[ \t]*$',status,re.M)
  if len(uids)!=1:return None
  if any(int(value)!=self.uid for value in uids[0]):return False
  if require_runner:
   try:executable=os.stat(root/str(pid)/'exe')
   except OSError:return None
   if (executable.st_dev,executable.st_ino)!=self.wine_exe_identity:return False
  environment=_bounded_bytes(root/str(pid)/'environ',16384)
  if environment is None:return None
  if not environment.endswith(b'\x00'):return None
  prefixes=[part[len(b'WINEPREFIX='):] for part in environment.split(b'\x00') if part.startswith(b'WINEPREFIX=')]
  if prefixes!=[os.fsencode(self.wine_prefix)]:return False
  current=_process(root,pid)
  if current is None or current['start']!=process['start']:return None
  return status

 def _session(self,root,now_ms,fields):
  # A start bound is established once from the authenticated launch anchor.
  # It remains pinned after explorer exits. No subsequent PID reuse can reset it.
  fields['game_scope']='unavailable'
  if self.session_failed:return
  if self.session_bound is None:
   anchor=_process(root,self.pid)
   if (anchor is None or (self.anchor_start is not None and anchor['start']!=self.anchor_start)
       or not self._session_identity(root,self.pid,anchor,require_runner=False)):
    self.session_failed=True;return
   self.anchor_start=self.session_bound=anchor['start']
  try:entries=list(itertools.islice(root.iterdir(),4097))
  except OSError:entries=[]
  if not entries or len(entries)>4096:
   self.previous_processes={};self.previous_time=None;return
  selected={};statuses={};partial=False;reads=0
  for entry in entries:
   if not re.fullmatch(r'[0-9]{1,10}',entry.name):continue
   pid=int(entry.name)
   process=_process(root,pid)
   if process is None:
    partial=True;continue
   if process['start']<self.session_bound:continue
   # Two passes cap status+environment reads at 64 MiB per snapshot, even
   # with maximally sized files. A cap is not represented as a zero aggregate.
   if reads>=1024:partial=True;break
   reads+=1
   status=self._session_identity(root,pid,process)
   if status is None:partial=True;continue
   if status is False:continue
   # Tick-resolution equality does not prove a different process began after
   # this session. Omit ambiguous same-tick candidates rather than admit stale
   # users of a persistent prefix. The authenticated original anchor is known.
   if process['start']==self.session_bound and pid!=self.pid:
    partial=True;continue
   # Recheck ownership as well as numeric identity after all capture reads.
   again=self._session_identity(root,pid,process)
   if again is None or again is False:partial=True;continue
   values={}
   for key in ('VmRSS','VmSwap'):
    matches=re.findall(rb'^'+key.encode()+rb':\s+([0-9]{1,19})\s+kB\s*$',again,re.M)
    if len(matches)==1:
     value=_uint(matches[0].decode('ascii'))
     if value is not None:values[key]=value
   selected[pid]=process;statuses[pid]=values
  if not selected:
   self.previous_processes={};self.previous_time=None;return
  fields['game_scope']='partial' if partial else 'verified_subset'
  self._aggregate(selected,statuses,now_ms,fields)
  # Interval CPU is not trustworthy when access/caps/races hid processes.
  if partial:
   fields.pop('game_cpu_pct_x100',None)
   self.previous_processes={};self.previous_time=None

 def _game(self,root,now_ms,fields):
  if self.anchor_ended:return
  anchor=_process(root,self.pid) if type(self.pid) is int and self.pid>1 else None
  if anchor is None:
   self.anchor_ended=True;return
  if self.anchor_start is None:self.anchor_start=anchor['start']
  if anchor['start']!=self.anchor_start:
   self.anchor_ended=True;return
  processes={self.pid:anchor}
  try:
   # A capped scan bounds work even on hosts with unexpectedly many processes.
   # Do not publish a partial tree if the directory cap is exceeded.
   entries=list(itertools.islice(root.iterdir(),4097))
  except OSError:return
  if len(entries)>4096:return
  for entry in entries:
   if not re.fullmatch(r'[0-9]{1,10}',entry.name):continue
   pid=int(entry.name)
   if pid==self.pid:continue
   process=_process(root,pid)
   if process is not None:processes[pid]=process
  owned={self.pid}
  # Every link must be in this numeric snapshot; reject cycles and broken chains.
  def descendant(pid):
   chain=set()
   while pid not in owned:
    if pid in chain or pid not in processes:return False
    chain.add(pid)
    child=processes[pid];parent=processes.get(child['ppid'])
    if parent is None or child['start']<parent['start']:return False
    pid=child['ppid']
   owned.update(chain)
   return True
  selected={pid:process for pid,process in processes.items() if descendant(pid)}
  # Read status only for authorized processes and recheck identity after reading.
  statuses={}
  for pid,process in selected.items():
   status={}
   for line in _text(root/str(pid)/'status',16384).splitlines():
    match=re.fullmatch(r'(VmRSS|VmSwap):\s+([0-9]{1,19})\s+kB',line)
    if match:
     value=_uint(match.group(2))
     if value is not None:status[match.group(1)]=value
   current=_process(root,pid)
   if current is None or current['start']!=process['start'] or current['ppid']!=process['ppid']:
    # A racing tree is not a trustworthy aggregate; omit rather than claim zero.
    self.previous_processes={};self.previous_time=None;return
   statuses[pid]=status
  current_anchor=_process(root,self.pid)
  if current_anchor is None or current_anchor['start']!=self.anchor_start:
   self.anchor_ended=True;return
  self._aggregate(selected,statuses,now_ms,fields)

 def _aggregate(self,selected,statuses,now_ms,fields):
  fields['game_processes']=len(selected)
  fields['game_major_faults']=sum(process['faults'] for process in selected.values())
  if self.clock_ticks:
   for key,source in (('game_cpu_user_ms','user'),('game_cpu_system_ms','system')):
    fields[key]=sum(process[source] for process in selected.values())*1000//self.clock_ticks
   elapsed=now_ms-self.previous_time if self.previous_time is not None else 0
   # Only an unchanged, fully observed tree has a trustworthy interval delta.
   # New/reused/exited PIDs have missing CPU history: omit, never claim zero
   # or attribute a new process's pre-observation CPU to this interval.
   deltas=[]
   for pid,process in selected.items():
    previous=self.previous_processes.get(pid)
    if previous and previous['start']==process['start']:
     delta=process['user']+process['system']-previous['user']-previous['system']
     if delta>=0:deltas.append(delta)
   if elapsed>0 and len(deltas)==len(selected)==len(self.previous_processes):
    fields['game_cpu_pct_x100']=sum(deltas)*10000000//(self.clock_ticks*elapsed)
  for key,source in (('game_rss_kb','VmRSS'),('game_swap_kb','VmSwap')):
   if all(source in status for status in statuses.values()):
    fields[key]=sum(status[source] for status in statuses.values())
  self.previous_processes=selected
  self.previous_time=now_ms


def _system_memory(root,fields):
 for line in _text(root/'meminfo',65536).splitlines():
  match=re.fullmatch(r'(MemAvailable|SwapTotal|SwapFree):\s+([0-9]{1,16})\s+kB',line)
  if match:
   value=int(match.group(2))
   if value<=10**12*1024:
    key={'MemAvailable':'available_ram_mb','SwapTotal':'swap_total_mb','SwapFree':'swap_free_mb'}[match.group(1)]
    fields[key]=value//1024
 for line in _text(root/'vmstat',65536).splitlines():
  match=re.fullmatch(r'(pswpin|pswpout|pgmajfault)\s+([0-9]{1,19})',line)
  if match:
   value=_uint(match.group(2))
   if value is not None:
    fields[{'pswpin':'swap_in_pages','pswpout':'swap_out_pages','pgmajfault':'system_major_faults'}[match.group(1)]]=value
 for resource in ('cpu','memory','io'):
  for line in _text(root/'pressure'/resource,4096).splitlines():
   parts=line.split()
   if not parts or parts[0] not in ('some','full'):continue
   prefix='pressure_'+resource+'_'+parts[0]
   for part in parts[1:]:
    if part.startswith('avg10='):
     match=re.fullmatch(r'avg10=([0-9]{1,3})\.([0-9]{2})',part)
     if match:
      value=int(match.group(1))*100+int(match.group(2))
      if value<=10000:fields[prefix+'_avg10_x100']=value
    elif part.startswith('total='):
     value=_uint(part[6:])
     if value is not None:fields[prefix+'_total_us']=value


def _bounded_bytes(path,limit):
 """Read the whole bounded proc record, never accept truncation or symlinks."""
 try:
  flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_CLOEXEC',0)
  fd=os.open(path,flags)
  with os.fdopen(fd,'rb') as stream:value=stream.read(limit+1)
  return value if len(value)<=limit else None
 except (OSError,ValueError):return None


def _text(path, limit=128):
 """Read bounded ASCII sys/proc data; errors never enter telemetry."""
 try:
  with path.open(encoding='ascii') as stream:
   value=stream.read(limit+1)
  return value.strip() if len(value)<=limit else ''
 except (OSError,UnicodeError,ValueError):return ''


def _number(path, low, high):
 text=_text(path)
 if not re.fullmatch(r'-?[0-9]+',text):return None
 value=int(text)
 return value if low<=value<=high else None


def _first_number(paths, low, high):
 for path in paths:
  value=_number(path,low,high)
  if value is not None:return value
 return None


def collect_snapshot(port, *, sys_root='/sys', proc_root='/proc', disk_usage=None,
                     sampler=None, pid=None):
 """Return a numeric snapshot without printing, writes, sleeps or global state.

 Roots and disk_usage are injectable for isolated tests. Frequency units are
 native sysfs units: CPU kHz (1..10**7), GPU Hz (1..10**10). Missing or invalid
 readings are omitted. Pass a persistent MetricsSampler for interval deltas;
 pid alone creates a one-shot anchor-scoped sample. CPU percentages use 10000
 for 100% (game can exceed that on multicore); PSI totals are cumulative us,
 vmstat swap counters cumulative pages, process times cumulative milliseconds.
 The caller retains responsibility for metrics opt-in.
 """
 sys_root,proc_root=pathlib.Path(sys_root),pathlib.Path(proc_root)
 now_ms=time.monotonic_ns()//1000000
 fields={'event':'metrics','sample_monotonic_ms':now_ms}
 _system_memory(proc_root,fields)
 fields.update((sampler or MetricsSampler(pid)).collect(proc_root,now_ms))
 try:
  free=(disk_usage or shutil.disk_usage)(port).free
  if type(free) is int and 0<=free<=10**12*1048576:
   fields['disk_mb']=free//1048576
 except (OSError,ValueError):pass
 value=_number(sys_root/'class/thermal/thermal_zone0/temp',-50000,200000)
 if value is not None:fields['temperature_mc']=value
 cpu_roots=[sys_root/'devices/system/cpu/cpufreq/policy0',
            sys_root/'devices/system/cpu/cpu0/cpufreq']
 for field,names in (('cpu_freq_khz',('scaling_cur_freq','cpuinfo_cur_freq')),
                     ('cpu_max_freq_khz',('scaling_max_freq','cpuinfo_max_freq'))):
  value=_first_number((root/name for root in cpu_roots for name in names),1,10**7)
  if value is not None:fields[field]=value
 try:
  devices=sorted(itertools.islice((sys_root/'class/devfreq').iterdir(),257))
  if len(devices)>256:devices=[]
 except OSError:devices=[]
 for device in devices:
  # Match a GPU identity, not the first devfreq entry (often DDR/DMC).
  identities=(device.name,_text(device/'name'),_text(device/'device/name'))
  if not any(re.search(r'(^|[^a-z0-9])(gpu|mali|panfrost)[0-9]*($|[^a-z0-9])',
                       name.lower()) for name in identities):continue
  readings={}
  for field,name in (('gpu_freq_hz','cur_freq'),('gpu_max_freq_hz','max_freq')):
   value=_number(device/name,1,10**10)
   if value is not None:readings[field]=value
  if readings:
   fields.update(readings)
   break  # Never combine current/max readings from different GPUs.
 return fields


def snapshot(port, role='game', file=None, **kwargs):
 fields=collect_snapshot(port,**kwargs)
 if role in ('compositor','mapper'):
  fields={role+k[4:] if k.startswith('game_') else k:v for k,v in fields.items()}
 print('PD2_EVENT '+json.dumps(fields),flush=True,file=file or sys.stdout)

def main():
 p=argparse.ArgumentParser();p.add_argument('--port',required=True);p.add_argument('--pid',type=int);p.add_argument('--enabled',action='store_true');p.add_argument('--role',choices=('game','compositor','mapper'),default='game')
 p.add_argument('--wine-prefix');p.add_argument('--uid',type=int);p.add_argument('--wine-exe')
 p.add_argument('--preflight',action='store_true');a=p.parse_args()
 if len({value is None for value in (a.wine_prefix,a.uid,a.wine_exe)})!=1:return 1
 if a.wine_prefix is not None and (a.role!='game' or a.pid is None):return 1
 if a.enabled or a.preflight:
  try:
   f=pathlib.Path(a.port)/'config/settings.json'
   enabled=False
   if not f.is_symlink() and f.stat().st_size<=65536:
    with f.open(encoding='utf-8') as stream:text=stream.read(65537)
    enabled=len(text)<=65536 and json.loads(text).get('metrics') is True
  except (OSError,ValueError,TypeError,AttributeError):enabled=False
  if a.preflight:
   # One spawn: sample goes to the log stream (stderr), token to stdout.
   # The sample is best-effort; the token must always be printed.
   try:snapshot(a.port,file=sys.stderr)
   except Exception:pass
  print('1' if enabled else '0');return 0
 if a.pid is not None and a.pid<=1:return 1
 try:sampler=MetricsSampler(a.pid,wine_prefix=a.wine_prefix,uid=a.uid,wine_exe=a.wine_exe)
 except ValueError:return 1
 try:
  while True:
   if a.pid is not None:
    if sampler.wine_prefix is None:
     current=_process(pathlib.Path('/proc'),a.pid)
     if current is None or (sampler.anchor_start is not None and current['start']!=sampler.anchor_start):return 0
     # Legacy roles end with their pinned tree; Wine session mode instead lives
     # until the parent stops the sampler, even if its launch anchor has exited.
     if sampler.anchor_start is None:sampler.anchor_start=current['start']
    snapshot(a.port,sampler=sampler,**({'role':a.role} if a.role!='game' else {}))
    if sampler.anchor_ended:return 0
   else:snapshot(a.port)
   if a.pid is None:return 0
   time.sleep(5)
 except (OSError,ValueError,KeyboardInterrupt):return 1
if __name__=='__main__':raise SystemExit(main())
