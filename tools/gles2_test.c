/* SPDX-License-Identifier: MIT */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include "gles2_pipeline.h"
#include "gles2_events.h"
#include "gles2_palette.h"
SRWLOCK pd2_gles2_palette_gate=SRWLOCK_INIT;
static unsigned concurrent_palette[256];
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); exit(1); } } while(0)
static GLenum pending_error;
static int fail_vertex,fail_fragment,fail_link,fail_texture,fail_buffer,fail_uniform,corrupt,format_bpp,format555,uploads,draws,reads;
static GLuint nextid=1,bound_texture,active_unit;
static unsigned char texels[16],colors[1024];
static GLenum APIENTRY mGetError(void){GLenum e=pending_error;pending_error=0;return e;}
static const GLubyte * APIENTRY mGetString(GLenum n){(void)n;return (const GLubyte *)"2.1 mock";}
static GLuint APIENTRY mCreateShader(GLenum t){return t==GL_VERTEX_SHADER ? 1:2;}
static void APIENTRY mShaderSource(GLuint s,GLsizei n,const GLchar *const *p,const GLint *l){(void)s;(void)n;(void)p;(void)l;}
static void APIENTRY mCompileShader(GLuint s){(void)s;}
static void APIENTRY mGetShaderiv(GLuint s,GLenum n,GLint *v){(void)n;*v=!((s==1 && fail_vertex)||(s==2 && fail_fragment));}
static void APIENTRY mDeleteShader(GLuint s){(void)s;}
static GLuint APIENTRY mCreateProgram(void){return nextid++;}
static void APIENTRY mAttachShader(GLuint p,GLuint s){(void)p;(void)s;}
static void APIENTRY mLinkProgram(GLuint p){(void)p;}
static void APIENTRY mGetProgramiv(GLuint p,GLenum n,GLint *v){(void)p;(void)n;*v=!fail_link;}
static void APIENTRY mDeleteProgram(GLuint p){(void)p;}
static void APIENTRY mBindAttribLocation(GLuint p,GLuint i,const GLchar *n){(void)p;(void)i;(void)n;}
static void APIENTRY mUseProgram(GLuint p){(void)p;}
static GLint APIENTRY mGetUniformLocation(GLuint p,const GLchar *n){(void)p;(void)n;return fail_uniform ? -1:0;}
static void APIENTRY mUniform1i(GLint l,GLint v){(void)l;(void)v;}
static void APIENTRY mGenTextures(GLsizei n,GLuint *p){int i;for(i=0;i<n;++i)p[i]=fail_texture ? 0:nextid++;}
static void APIENTRY mBindTexture(GLenum t,GLuint p){(void)t;bound_texture=p;}
static void APIENTRY mTexParameteri(GLenum t,GLenum p,GLint v){(void)t;(void)p;(void)v;}
static void APIENTRY mTexImage2D(GLenum t,GLint l,GLint in,GLsizei w,GLsizei h,GLint b,GLenum f,GLenum ty,const void *p){(void)t;(void)l;(void)in;(void)h;(void)b;(void)p;(void)bound_texture;if(w!=256){format_bpp=f==GL_LUMINANCE ? 8:ty==GL_UNSIGNED_BYTE ? 32:16;format555=ty==GL_UNSIGNED_SHORT_1_5_5_5_REV;}}
static void APIENTRY mTexSubImage2D(GLenum t,GLint l,GLint x,GLint y,GLsizei w,GLsizei h,GLenum f,GLenum ty,const void *p){(void)t;(void)l;(void)x;(void)y;(void)f;(void)ty;++uploads;if(active_unit==GL_TEXTURE1)memcpy(colors,p,1024);else if(w==2 && h==2)memcpy(texels,p,(size_t)(4*format_bpp/8));}
static void APIENTRY mDeleteTextures(GLsizei n,const GLuint *p){(void)n;(void)p;}
static void APIENTRY mActiveTexture(GLenum t){active_unit=t;}
static void APIENTRY mPixelStorei(GLenum p,GLint v){(void)p;(void)v;}
static void APIENTRY mGenBuffers(GLsizei n,GLuint *p){int i;for(i=0;i<n;++i)p[i]=fail_buffer ? 0:nextid++;}
static void APIENTRY mBindBuffer(GLenum t,GLuint b){(void)t;(void)b;}
static void APIENTRY mBufferData(GLenum t,GLsizeiptr s,const void *p,GLenum u){(void)t;(void)s;(void)p;(void)u;}
static void APIENTRY mDeleteBuffers(GLsizei n,const GLuint *p){(void)n;(void)p;}
static void APIENTRY mVertexAttribPointer(GLuint i,GLint s,GLenum t,GLboolean n,GLsizei stride,const void *p){(void)i;(void)s;(void)t;(void)n;CHECK(stride==4*sizeof(GLfloat));(void)p;}
static void APIENTRY mEnableVertexAttribArray(GLuint i){CHECK(i<2);}
static void APIENTRY mDrawElements(GLenum m,GLsizei n,GLenum t,const void *p){CHECK(m==GL_TRIANGLES && n==6 && t==GL_UNSIGNED_SHORT && p);++draws;}
static void APIENTRY mViewport(GLint x,GLint y,GLsizei w,GLsizei h){(void)x;(void)y;CHECK(w>0 && h>0);}
static void APIENTRY mClearColor(GLfloat r,GLfloat g,GLfloat b,GLfloat a){(void)r;(void)g;(void)b;(void)a;}
static void APIENTRY mClear(GLbitfield b){(void)b;}
static void APIENTRY mDisable(GLenum e){(void)e;}
static void APIENTRY mReadPixels(GLint x,GLint y,GLsizei w,GLsizei h,GLenum f,GLenum t,void *out){
 int i;unsigned char *o=out;(void)x;(void)y;CHECK(((w==2 && h==2)||(w==1 && h==1)) && f==GL_RGBA && t==GL_UNSIGNED_BYTE);++reads;
 for(i=0;i<w*h;++i){int src=(i+2)%4;unsigned r,g,b;
 if(format_bpp==8){r=colors[texels[src]*4];g=colors[texels[src]*4+1];b=colors[texels[src]*4+2];}
 else if(format_bpp==32){b=texels[src*4];g=texels[src*4+1];r=texels[src*4+2];}
 else{unsigned v=((unsigned short *)texels)[src];r=((v>>(format555?10:11))&31)*255/31;g=((v>>5)&(format555?31:63))*255/(format555?31:63);b=(v&31)*255/31;}
 o[i*4]=(unsigned char)r;o[i*4+1]=(unsigned char)g;o[i*4+2]=(unsigned char)b;o[i*4+3]=255;
 } if(corrupt)o[0]^=255;
}
static void APIENTRY mGetIntegerv(GLenum e,GLint *v){CHECK(e==GL_MAX_TEXTURE_SIZE);*v=4096;}
static pd2_gl_api mock_api(void){pd2_gl_api a;
#define SET(t,n) a.n=m##n;
 PD2_GL_API(SET)
#undef SET
 return a;}
static void native_mock_tests(void){pd2_gl_api a=mock_api();pd2_gl_pipeline p;GLenum f,t;unsigned char pixels[24]={0};int code;
 CHECK(pd2_gl_api_complete(&a));a.GetError=NULL;CHECK(!pd2_gl_api_complete(&a));CHECK(pd2_gl_init(&a,&p,2,2,8,0)==PD2_GL_API_MISSING);a=mock_api();
 CHECK(pd2_gl_format(24,0,&f,&t)==PD2_GL_FORMAT);CHECK(pd2_gl_init(&a,&p,0,2,8,0)==PD2_GL_FORMAT);CHECK(pd2_gl_init(&a,&p,4097,2,8,0)==PD2_GL_FORMAT);
 pending_error=GL_INVALID_OPERATION;CHECK(pd2_gl_init(&a,&p,2,2,8,0)==PD2_GL_STATE);
 fail_vertex=1;CHECK(pd2_gl_init(&a,&p,2,2,8,0)==PD2_GL_VERTEX);fail_vertex=0;
 fail_fragment=1;CHECK(pd2_gl_init(&a,&p,2,2,8,0)==PD2_GL_FRAGMENT);fail_fragment=0;
 fail_link=1;CHECK(pd2_gl_init(&a,&p,2,2,8,0)==PD2_GL_LINK);fail_link=0;CHECK(!pd2_gl_destroy(&a,&p));
 fail_uniform=1;CHECK(pd2_gl_init(&a,&p,2,2,8,0)==PD2_GL_LINK);fail_uniform=0;CHECK(!pd2_gl_destroy(&a,&p));
 fail_texture=1;CHECK(pd2_gl_init(&a,&p,2,2,8,0)==PD2_GL_TEXTURE);fail_texture=0;CHECK(!pd2_gl_destroy(&a,&p));
 fail_buffer=1;CHECK(pd2_gl_init(&a,&p,2,2,8,0)==PD2_GL_STATE);fail_buffer=0;CHECK(!pd2_gl_destroy(&a,&p));
 CHECK(!pd2_gl_validate(&a,0,0));CHECK(reads==5 && draws==5);corrupt=1;CHECK(pd2_gl_validate(&a,0,0)==PD2_GL_VALIDATION);corrupt=0;
 CHECK(!pd2_gl_init(&a,&p,2,2,32,0));CHECK(pd2_gl_upload(&a,&p,NULL,8,NULL)==PD2_GL_UPLOAD);CHECK(pd2_gl_upload(&a,&p,pixels,7,NULL)==PD2_GL_UPLOAD);
 uploads=0;CHECK(!pd2_gl_upload(&a,&p,pixels,12,NULL));CHECK(uploads==2);
 pending_error=GL_INVALID_OPERATION;CHECK(pd2_gl_upload(&a,&p,pixels,8,NULL)==PD2_GL_UPLOAD);
 pending_error=GL_INVALID_OPERATION;CHECK(pd2_gl_draw(&a,&p,0,0,2,2)==PD2_GL_DRAW);
 pending_error=GL_INVALID_OPERATION;CHECK(pd2_gl_destroy(&a,&p)==PD2_GL_RELEASE);
 code=pd2_gl_validate(&a,0,0);CHECK(!code);puts("native mock pipeline: PASS (formats, palette, padded pitch, all pipeline failure codes)");
}
static FARPROC real_proc(HMODULE lib,const char *name){PROC p=wglGetProcAddress(name);if(!p || p==(PROC)1 || p==(PROC)2 || p==(PROC)3 || p==(PROC)-1)p=GetProcAddress(lib,name);return p;}
static void real_gl_test(void){
 WNDCLASSA wc={0};HWND window;HDC dc;HGLRC ctx;HMODULE lib;PIXELFORMATDESCRIPTOR pfd={0};int format,code;pd2_gl_api a;
 wc.style=CS_OWNDC;wc.lpfnWndProc=DefWindowProcA;wc.hInstance=GetModuleHandleW(NULL);wc.lpszClassName="PD2GL2NativeTest";
 CHECK(RegisterClassA(&wc));window=CreateWindowA(wc.lpszClassName,"synthetic",WS_POPUP|WS_VISIBLE,0,0,32,32,NULL,NULL,wc.hInstance,NULL);CHECK(window);UpdateWindow(window);
 dc=GetDC(window);CHECK(dc);pfd.nSize=sizeof(pfd);pfd.nVersion=1;pfd.dwFlags=PFD_DRAW_TO_WINDOW|PFD_SUPPORT_OPENGL|PFD_DOUBLEBUFFER;pfd.iPixelType=PFD_TYPE_RGBA;pfd.cColorBits=24;pfd.cAlphaBits=8;
 format=ChoosePixelFormat(dc,&pfd);CHECK(format);CHECK(SetPixelFormat(dc,format,&pfd));ctx=wglCreateContext(dc);CHECK(ctx);CHECK(wglMakeCurrent(dc,ctx));lib=LoadLibraryW(L"opengl32.dll");CHECK(lib);
#define SET_REAL(t,n) a.n=(t)real_proc(lib,"gl" #n);
 PD2_GL_API(SET_REAL)
#undef SET_REAL
 if(!pd2_gl_api_complete(&a)){puts("native real GL2: SKIP (host exports only legacy GL)");}
 else {
 pd2_gl_pipeline p;unsigned char sample[4];static const unsigned short source[]={0xf800,0x07e0,0x001f,0x001f,0xffff,0xf800};
 code=pd2_gl_validate(&a,0,0);printf("native real GL2 synthetic readPixels: %s code=%d\n",code ? "FAIL":"PASS",code);CHECK(!code);
 CHECK(!pd2_gl_init(&a,&p,3,2,16,0));CHECK(!pd2_gl_upload(&a,&p,source,6,NULL));CHECK(!pd2_gl_draw(&a,&p,0,0,6,4));
 a.ReadPixels(0,0,1,1,GL_RGBA,GL_UNSIGNED_BYTE,sample);CHECK(!pd2_gl_error(&a,8));CHECK(sample[0]<8 && sample[1]<8 && sample[2]>247);
 a.ReadPixels(5,3,1,1,GL_RGBA,GL_UNSIGNED_BYTE,sample);CHECK(!pd2_gl_error(&a,8));CHECK(sample[0]<8 && sample[1]<8 && sample[2]>247);
 CHECK(!pd2_gl_destroy(&a,&p));CHECK(!pd2_gl_validate(&a,0,0));
 puts("native real GL2 resize/NPOT/source-rebuild/palette-only update: PASS");
 }
 CHECK(wglMakeCurrent(NULL,NULL));CHECK(wglDeleteContext(ctx));ReleaseDC(window,dc);DestroyWindow(window);FreeLibrary(lib);
}
static void writer_tests(void) {
 unsigned i;DWORD size;HANDLE input;
 pd2_gl_event(0,0,8,2,2,2,2);CHECK(pd2_gl_event_file==INVALID_HANDLE_VALUE);
 for(i=0;i<200;++i)pd2_gl_event(1,0,8,2,2,2,2);
 CHECK(pd2_gl_event_count==127);pd2_gl_event(6,11,8,2,2,2,2);CHECK(pd2_gl_event_count==128);
 size=GetFileSize(pd2_gl_event_file,NULL);CHECK(size>0 && size<PD2_GL_EVENT_LIMIT);
 CloseHandle(pd2_gl_event_file);pd2_gl_event_file=INVALID_HANDLE_VALUE;pd2_gl_event_count=0;pd2_gl_event_bytes=0;
 pd2_gl_event(1,0,8,2,2,2,2);CHECK(pd2_gl_event_disabled);CHECK(pd2_gl_event_file==INVALID_HANDLE_VALUE);
 input=CreateFileW(L"pd2-gles2.jsonl",GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);CHECK(input!=INVALID_HANDLE_VALUE);CHECK(GetFileSize(input,NULL)==size);CloseHandle(input);
 puts("native event writer: PASS (numeric schema, reserved fatal record, cap, CREATE_NEW refusal)");
}
static DWORD WINAPI palette_writer(void *unused) {
 unsigned generation,i;(void)unused;
 for(generation=1;generation<=10000;++generation) {
 AcquireSRWLockExclusive(&pd2_gles2_palette_gate);
 for(i=0;i<256;++i)concurrent_palette[i]=generation;
 ReleaseSRWLockExclusive(&pd2_gles2_palette_gate);
 }return 0;
}
static void palette_concurrency_test(void) {
 HANDLE writer=CreateThread(NULL,0,palette_writer,NULL,0,NULL);unsigned snapshot[256],iteration,i;CHECK(writer);
 for(iteration=0;iteration<10000;++iteration) {
 AcquireSRWLockShared(&pd2_gles2_palette_gate);memcpy(snapshot,concurrent_palette,sizeof(snapshot));ReleaseSRWLockShared(&pd2_gles2_palette_gate);
 for(i=1;i<256;++i)CHECK(snapshot[i]==snapshot[0]);
 }
 CHECK(WaitForSingleObject(writer,5000)==WAIT_OBJECT_0);CloseHandle(writer);
 puts("native palette concurrent writer/snapshot: PASS (10000 coherent snapshots)");
}
int main(void){native_mock_tests();real_gl_test();writer_tests();palette_concurrency_test();return 0;}
