/* SPDX-License-Identifier: MIT
 * Fixed numeric, bounded side channel; independent of rendering decisions.
 */
#ifndef PD2_GLES2_EVENTS_H
#define PD2_GLES2_EVENTS_H
#include <windows.h>
#include <stdio.h>
#define PD2_GL_EVENT_LIMIT 32768u
#define PD2_GL_EVENT_LINE 256u
#define PD2_GL_EXIT_CODE 86u
/* Stage:1 context,2 api,3 shader,4 texture,5 validation,6 frame,7 release,8 policy.
 * Code: gles2_pipeline.h; zero=ready, 1..16=failed. */
static HANDLE pd2_gl_event_file=INVALID_HANDLE_VALUE;
static unsigned pd2_gl_event_bytes,pd2_gl_event_count;
static int pd2_gl_event_disabled;
static volatile LONG pd2_gl_event_gate;
static unsigned pd2_gl_major,pd2_gl_minor;
static void pd2_gl_event(unsigned stage,unsigned code,unsigned bpp,unsigned width,unsigned height,unsigned rw,unsigned rh) {
 char line[PD2_GL_EVENT_LINE]; int length; DWORD written;
 if (InterlockedCompareExchange(&pd2_gl_event_gate,1,0)) return;
 if (pd2_gl_event_disabled || stage<1 || stage>8 || code>16 || width>16384 || height>16384 || rw>16384 || rh>16384 || (bpp!=0 && bpp!=8 && bpp!=16 && bpp!=32)) goto done;
 /* Reserve the final record for fatal evidence after many mode restarts. */
 if (pd2_gl_event_count >= (code ? 128u:127u)) goto done;
 if (pd2_gl_event_file==INVALID_HANDLE_VALUE) {
 pd2_gl_event_file=CreateFileW(L"pd2-gles2.jsonl",GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,FILE_ATTRIBUTE_TEMPORARY|FILE_FLAG_OPEN_REPARSE_POINT,NULL);
 if (pd2_gl_event_file==INVALID_HANDLE_VALUE) { pd2_gl_event_disabled=1;goto done; }
 }
 length=snprintf(line,sizeof(line),"{\"stage\":%u,\"code\":%u,\"gl_major\":%u,\"gl_minor\":%u,\"bpp\":%u,\"width\":%u,\"height\":%u,\"render_width\":%u,\"render_height\":%u}\n",stage,code,pd2_gl_major,pd2_gl_minor,bpp,width,height,rw,rh);
 if (length<=0 || (unsigned)length>=sizeof(line) || (unsigned)length>PD2_GL_EVENT_LIMIT-pd2_gl_event_bytes) {pd2_gl_event_disabled=1;goto done;}
 ++pd2_gl_event_count; pd2_gl_event_bytes+=(unsigned)length;
 if (!WriteFile(pd2_gl_event_file,line,(DWORD)length,&written,NULL) || written!=(DWORD)length) pd2_gl_event_disabled=1;
 done:
 if (pd2_gl_event_disabled && pd2_gl_event_file!=INVALID_HANDLE_VALUE) {CloseHandle(pd2_gl_event_file);pd2_gl_event_file=INVALID_HANDLE_VALUE;}
 InterlockedExchange(&pd2_gl_event_gate,0);
}
#endif
