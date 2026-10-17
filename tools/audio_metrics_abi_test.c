/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Real exported dlsym entrypoints of instrumented ALSA, synthetic null PCM only.
 * Run native host build and QEMU ARMhf build. Not a hardware/audio-quality test.
 */
#define _POSIX_C_SOURCE 200809L
#include <alsa/asoundlib.h>
#include <dlfcn.h>
#include <assert.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <sys/ioctl.h>
#ifdef PD2_ARM_ABI
/* Kernel UAPI assertions live in the separately compiled alsa_legacy_abi.c;
 * mixing its UAPI typedefs with public asoundlib.h is not a valid ALSA TU. */
_Static_assert(sizeof(void *)==4,"ARM32 ABI required");
_Static_assert(sizeof(time_t)==4,"time32 ABI required");
#endif
#define LOAD(name) do { *(void **)(&p_##name)=dlsym(lib,#name); assert(p_##name); } while(0)
int main(int argc,char **argv) {
 int pipes[2], flags, i; void *lib; snd_pcm_t *pcm;
 char fdtext[16], records[32768]; size_t total=0;
 short silence[256*2]={0};
 int (*p_snd_pcm_open)(snd_pcm_t **,const char *,snd_pcm_stream_t,int);
 int (*p_snd_pcm_set_params)(snd_pcm_t *,snd_pcm_format_t,snd_pcm_access_t,unsigned,unsigned,int,unsigned);
 snd_pcm_sframes_t (*p_snd_pcm_writei)(snd_pcm_t *,const void *,snd_pcm_uframes_t);
 int (*p_snd_pcm_mmap_begin)(snd_pcm_t *,const snd_pcm_channel_area_t **,snd_pcm_uframes_t *,snd_pcm_uframes_t *);
 snd_pcm_sframes_t (*p_snd_pcm_mmap_commit)(snd_pcm_t *,snd_pcm_uframes_t,snd_pcm_uframes_t);
 snd_pcm_sframes_t (*p_snd_pcm_avail_update)(snd_pcm_t *);
 int (*p_snd_pcm_recover)(snd_pcm_t *,int,int);
 int (*p_snd_pcm_start)(snd_pcm_t *), (*p_snd_pcm_prepare)(snd_pcm_t *), (*p_snd_pcm_drop)(snd_pcm_t *), (*p_snd_pcm_close)(snd_pcm_t *);
 assert(argc==2 && pipe(pipes)==0);
 flags=fcntl(pipes[1],F_GETFL); assert(flags>=0 && fcntl(pipes[1],F_SETFL,flags|O_NONBLOCK)==0);
 assert(fcntl(pipes[0],F_SETFL,O_NONBLOCK)==0);
 snprintf(fdtext,sizeof(fdtext),"%d",pipes[1]); assert(setenv("PD2_AUDIO_METRICS_FD",fdtext,1)==0);
 lib=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL); assert(lib);
 LOAD(snd_pcm_open); LOAD(snd_pcm_set_params); LOAD(snd_pcm_writei);
 LOAD(snd_pcm_mmap_begin); LOAD(snd_pcm_mmap_commit); LOAD(snd_pcm_avail_update);
 LOAD(snd_pcm_recover); LOAD(snd_pcm_start); LOAD(snd_pcm_prepare); LOAD(snd_pcm_drop); LOAD(snd_pcm_close);
 assert(p_snd_pcm_open(&pcm,"null",SND_PCM_STREAM_PLAYBACK,0)==0);
 assert(p_snd_pcm_set_params(pcm,SND_PCM_FORMAT_S16_LE,SND_PCM_ACCESS_RW_INTERLEAVED,2,48000,1,40000)==0);
 for(i=0;i<2000;++i) assert(p_snd_pcm_writei(pcm,silence,256)==256);
 assert(p_snd_pcm_recover(pcm,-EPIPE,1)==0);
 assert(p_snd_pcm_drop(pcm)==0); assert(p_snd_pcm_close(pcm)==0);
 assert(p_snd_pcm_open(&pcm,"null",SND_PCM_STREAM_PLAYBACK,0)==0);
 assert(p_snd_pcm_set_params(pcm,SND_PCM_FORMAT_S16_LE,SND_PCM_ACCESS_MMAP_INTERLEAVED,2,48000,1,40000)==0);
 assert(p_snd_pcm_prepare(pcm)==0); assert(p_snd_pcm_start(pcm)==0);
 for(i=0;i<2000;++i) {
  const snd_pcm_channel_area_t *areas; snd_pcm_uframes_t offset,frames=1;
  assert(p_snd_pcm_avail_update(pcm)>=0);
  assert(p_snd_pcm_mmap_begin(pcm,&areas,&offset,&frames)==0);
  assert(frames==1 && areas);
  /* Null backend: acknowledge a synthetic frame; no input samples inspected. */
  assert(p_snd_pcm_mmap_commit(pcm,offset,frames)==1);
 }
 assert(p_snd_pcm_drop(pcm)==0); assert(p_snd_pcm_close(pcm)==0);
 /* Writer alone formats/writes snapshots, not any PCM API above. */
 { struct timespec delay={1,300000000}; nanosleep(&delay,NULL); }
 for(;;) { ssize_t n=read(pipes[0],records+total,sizeof(records)-1-total); if(n<=0) break; total+=(size_t)n; assert(total<sizeof(records)-1); }
 records[total]=0;
 assert(strstr(records,"\"write_calls\":2000") && strstr(records,"\"write_frames\":512000"));
 assert(strstr(records,"\"mmap_commit_calls\":2000") && strstr(records,"\"mmap_frames\":2000"));
 assert(strstr(records,"\"recover_epipe_calls\":1") && strstr(records,"\"params_valid\":1"));
 assert(strstr(records,"\"rate_hz\":48000") && strstr(records,"\"channels\":2"));
 assert(!strstr(records,"null") && !strstr(records,"0x"));
 assert(dlclose(lib)==0); close(pipes[0]); close(pipes[1]);
 puts("PD2_AUDIO_ABI_OK"); return 0;
}
