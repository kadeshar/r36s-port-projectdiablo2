/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Fixed-memory mocked PCM bookkeeping; no sound device or audio content.
 */
#define PD2_AM_TEST
#include "audio_metrics_core.h"
#include <assert.h>

int main(void) {
 int pcm1, pcm2, unknown; unsigned i;
 struct pd2_am_slot *s;
 pd2_am_enabled = 1;
 assert(pd2_am_enter()); assert(!pd2_am_enter()); pd2_am_leave(); pd2_am_leave();
 pd2_am_open(&pcm1); pd2_am_open(&pcm2);
 pd2_am_params(&pcm1,48000,2,3,480,1920);
 s = &pd2_am_slots[0];
 assert(s->params_valid && s->rate_hz==48000 && s->period_frames==480 && s->buffer_frames==1920);
 for(i=0;i<100000;++i) {
  pd2_am_result(&pcm1,PD2_AM_WRITE,480,480,0);
  pd2_am_result(&pcm1,PD2_AM_MMAP_BEGIN,0,0,0);
  pd2_am_result(&pcm1,PD2_AM_MMAP_COMMIT,480,0,0);
 }
 assert(s->write_calls==100000 && s->write_frames==48000000);
 assert(s->mmap_begin_calls==100000 && s->mmap_commit_calls==100000 && s->mmap_frames==48000000);
 pd2_am_result(&pcm1,PD2_AM_WRITE,240,480,0);
 assert(s->short_writes==1 && s->write_frames==48000240);
 pd2_am_result(&pcm1,PD2_AM_WRITE,-EPIPE,480,0);
 pd2_am_result(&pcm1,PD2_AM_MMAP_BEGIN,-ESTRPIPE,0,0);
 pd2_am_result(&pcm1,PD2_AM_MMAP_COMMIT,-EAGAIN,0,0);
 pd2_am_result(&pcm1,PD2_AM_START,-EINTR,0,0);
 pd2_am_result(&pcm1,PD2_AM_PREPARE,-ENOTTY,0,0);
 pd2_am_result(&pcm1,PD2_AM_RECOVER,0,0,-EPIPE);
 assert(s->recover_calls==1 && s->recover_epipe_calls==1 && s->recover_successes==1);
 assert(s->error_results==5 && s->epipe_results==1 && s->estrpipe_results==1 && s->eagain_results==1 && s->eintr_results==1 && s->other_error_results==1);
 /* Repeated recover EPIPE is NOT another uniquely identified underrun. */
 pd2_am_result(&pcm1,PD2_AM_RECOVER,-EPIPE,0,-EPIPE);
 assert(s->recover_epipe_calls==2 && s->epipe_results==2 && s->recover_successes==1);
 pd2_am_result(&unknown,PD2_AM_WRITE,100,100,0);
 assert(s->write_frames==48000240 && pd2_am_slots[1].write_calls==0);
 /* No telemetry wait on a contended callback. */
 pd2_am_guard=1; pd2_am_result(&pcm1,PD2_AM_WRITE,100,100,0); pd2_am_guard=0;
 assert(pd2_am_lost==1 && s->write_frames==48000240);
 pd2_am_result(&pcm1,PD2_AM_PARAMS,-EINVAL,0,0); assert(!s->params_valid);
 pd2_am_params(&pcm1,48000,2,3,480,1920); assert(s->params_valid);
 pd2_am_params(&pcm1,0,2,3,480,1920); assert(!s->params_valid);
 pd2_am_result(&pcm1,PD2_AM_CLOSE,0,0,0); assert(!s->active && s->handle==NULL);
 pd2_am_result(&pcm1,PD2_AM_WRITE,100,100,0); assert(s->write_frames==48000240);
 pd2_am_open(&pcm1); assert(pd2_am_slots[2].id==3 && pd2_am_slots[2].write_frames==0);
 pd2_am_result(&pcm1,PD2_AM_CLOSE,0,0,0);
 pd2_am_result(&pcm2,PD2_AM_CLOSE,0,0,0);

 /* Concurrent active capacity limit test: 8 active streams max */
 int concurrent[PD2_AM_CONCURRENT_LIMIT];
 for(i=0;i<PD2_AM_CONCURRENT_LIMIT;++i) pd2_am_open(&concurrent[i]);
 pd2_am_open(&unknown); assert(pd2_am_capacity==1);
 /* Closing one allows new active open */
 pd2_am_result(&concurrent[0],PD2_AM_CLOSE,0,0,0);
 pd2_am_open(&concurrent[0]); assert(pd2_am_capacity==1);
 for(i=0;i<PD2_AM_CONCURRENT_LIMIT;++i) pd2_am_result(&concurrent[i],PD2_AM_CLOSE,0,0,0);

 /* 100 consecutive open/close cycles followed by long-running stream */
 int probe_pcm;
 for(i=0;i<100;++i) {
  pd2_am_open(&probe_pcm);
  pd2_am_result(&probe_pcm,PD2_AM_WRITE,10,10,0);
  pd2_am_result(&probe_pcm,PD2_AM_CLOSE,0,0,0);
 }
 int long_pcm;
 pd2_am_open(&long_pcm);
 pd2_am_params(&long_pcm,48000,2,3,480,1920);
 for(i=0;i<1000;++i) {
  pd2_am_result(&long_pcm,PD2_AM_WRITE,480,480,0);
 }
 struct pd2_am_slot *ls = pd2_am_find(&long_pcm);
 assert(ls!=NULL && ls->active && ls->params_valid && ls->write_frames==480000);
 assert(ls->producer_monotonic_ms>0);

 /* Address reuse gets fresh monotonic stream ID */
 unsigned old_id = ls->id;
 pd2_am_result(&long_pcm,PD2_AM_CLOSE,0,0,0);
 pd2_am_open(&long_pcm);
 struct pd2_am_slot *ls2 = pd2_am_find(&long_pcm);
 assert(ls2!=NULL && ls2->id>old_id && ls2->write_frames==0);

 /* Flush test via nonblocking pipe */
 int pipefds[2];
 assert(pipe(pipefds)==0);
 fcntl(pipefds[1],F_SETFL,O_NONBLOCK);
 pd2_am_fd = pipefds[1];
 pd2_am_flush();
 char pipe_buf[4096];
 ssize_t pn = read(pipefds[0],pipe_buf,sizeof(pipe_buf)-1);
 assert(pn>0);
 pipe_buf[pn]=0;
 assert(strstr(pipe_buf,"\"producer_monotonic_ms\":"));
 close(pipefds[0]); close(pipefds[1]); pd2_am_fd = -1;

 assert(pd2_am_add(PD2_AM_CAP-1,480)==PD2_AM_CAP);
 puts("PD2_AUDIO_CORE_OK"); return 0;
}
