/* SPDX-License-Identifier: MIT
 * GL2 pipeline only. No game structs, logging, process termination or readback
 * of game pixels. All functions return a bounded failure code to the adapter.
 */
#ifndef PD2_GLES2_PIPELINE_H
#define PD2_GLES2_PIPELINE_H
#include <string.h>
#include "opengl_utils.h"
#define PD2_GL_API(X) \
 X(PFNGLGETERRORPROC, GetError) X(PFNGLGETSTRINGPROC, GetString) \
 X(PFNGLCREATESHADERPROC, CreateShader) X(PFNGLSHADERSOURCEPROC, ShaderSource) \
 X(PFNGLCOMPILESHADERPROC, CompileShader) X(PFNGLGETSHADERIVPROC, GetShaderiv) \
 X(PFNGLDELETESHADERPROC, DeleteShader) X(PFNGLCREATEPROGRAMPROC, CreateProgram) \
 X(PFNGLATTACHSHADERPROC, AttachShader) X(PFNGLLINKPROGRAMPROC, LinkProgram) \
 X(PFNGLGETPROGRAMIVPROC, GetProgramiv) X(PFNGLDELETEPROGRAMPROC, DeleteProgram) \
 X(PFNGLBINDATTRIBLOCATIONPROC, BindAttribLocation) X(PFNGLUSEPROGRAMPROC, UseProgram) \
 X(PFNGLGETUNIFORMLOCATIONPROC, GetUniformLocation) X(PFNGLUNIFORM1IPROC, Uniform1i) \
 X(PFNGLGENTEXTURESPROC, GenTextures) X(PFNGLBINDTEXTUREPROC, BindTexture) \
 X(PFNGLTEXPARAMETERIPROC, TexParameteri) X(PFNGLTEXIMAGE2DPROC, TexImage2D) \
 X(PFNGLTEXSUBIMAGE2DPROC, TexSubImage2D) X(PFNGLDELETETEXTURESPROC, DeleteTextures) \
 X(PFNGLACTIVETEXTUREPROC, ActiveTexture) X(PFNGLPIXELSTOREIPROC, PixelStorei) \
 X(PFNGLGENBUFFERSPROC, GenBuffers) X(PFNGLBINDBUFFERPROC, BindBuffer) \
 X(PFNGLBUFFERDATAPROC, BufferData) X(PFNGLDELETEBUFFERSPROC, DeleteBuffers) \
 X(PFNGLVERTEXATTRIBPOINTERPROC, VertexAttribPointer) \
 X(PFNGLENABLEVERTEXATTRIBARRAYPROC, EnableVertexAttribArray) \
 X(PFNGLDRAWELEMENTSPROC, DrawElements) X(PFNGLVIEWPORTPROC, Viewport) \
 X(PFNGLCLEARCOLORPROC, ClearColor) X(PFNGLCLEARPROC, Clear) \
 X(PFNGLDISABLEPROC, Disable) X(PFNGLREADPIXELSPROC, ReadPixels) \
 X(PFNGLGETINTEGERVPROC, GetIntegerv)
#define PD2_GL_FIELD(t,n) t n;
typedef struct { PD2_GL_API(PD2_GL_FIELD) } pd2_gl_api;
#undef PD2_GL_FIELD

enum { PD2_GL_OK=0, PD2_GL_CONTEXT=1, PD2_GL_API_MISSING=2,
 PD2_GL_VERSION=3, PD2_GL_VERTEX=4, PD2_GL_FRAGMENT=5, PD2_GL_LINK=6,
 PD2_GL_TEXTURE=7, PD2_GL_VALIDATION=8, PD2_GL_UPLOAD=9, PD2_GL_DRAW=10,
 PD2_GL_SWAP=11, PD2_GL_FORMAT=12, PD2_GL_WAIT=13, PD2_GL_RELEASE=14,
 PD2_GL_POLICY=15, PD2_GL_STATE=16 };

typedef struct {
 GLuint program, texture, palette, vbo;
 GLenum format, type;
 int width, height, bpp, rgb555;
} pd2_gl_pipeline;

static int pd2_gl_api_complete(const pd2_gl_api *a) {
#define PD2_GL_CHECK(t,n) if (!a->n) return 0;
 PD2_GL_API(PD2_GL_CHECK)
#undef PD2_GL_CHECK
 return 1;
}
static int pd2_gl_error(pd2_gl_api *a, int failure) {
 /* Single bounded query: no draining and no errors ignored. */
 return a->GetError() == GL_NO_ERROR ? 0 : failure;
}
static int pd2_gl_format(int bpp,int rgb555,GLenum *format,GLenum *type) {
 if (bpp==8) { *format=GL_LUMINANCE; *type=GL_UNSIGNED_BYTE; }
 else if (bpp==16 && rgb555) { *format=GL_BGRA; *type=GL_UNSIGNED_SHORT_1_5_5_5_REV; }
 else if (bpp==16) { *format=GL_RGB; *type=GL_UNSIGNED_SHORT_5_6_5; }
 else if (bpp==32) { *format=GL_BGRA; *type=GL_UNSIGNED_BYTE; }
 else return PD2_GL_FORMAT;
 return 0;
}
static GLuint pd2_gl_shader(pd2_gl_api *a,GLenum type,const char *text) {
 GLint ok=0; GLuint shader=a->CreateShader(type);
 if (!shader) return 0;
 a->ShaderSource(shader,1,&text,NULL); a->CompileShader(shader);
 a->GetShaderiv(shader,GL_COMPILE_STATUS,&ok);
 if (!ok) { a->DeleteShader(shader); return 0; }
 return shader;
}
static int pd2_gl_destroy(pd2_gl_api *a,pd2_gl_pipeline *p) {
 if (p->program) a->DeleteProgram(p->program);
 if (p->texture) a->DeleteTextures(1,&p->texture);
 if (p->palette) a->DeleteTextures(1,&p->palette);
 if (p->vbo) a->DeleteBuffers(1,&p->vbo);
 memset(p,0,sizeof(*p));
 return pd2_gl_error(a,PD2_GL_RELEASE);
}
static int pd2_gl_init(pd2_gl_api *a,pd2_gl_pipeline *p,int width,int height,int bpp,int rgb555) {
 static const char *vs="#version 110\nattribute vec2 Position; attribute vec2 TexCoord; varying vec2 UV; void main(){UV=TexCoord;gl_Position=vec4(Position,0.0,1.0);}";
 static const char *fs_rgb="#version 110\nuniform sampler2D Surface; varying vec2 UV; void main(){gl_FragColor=vec4(texture2D(Surface,UV).rgb,1.0);}";
 static const char *fs_pal="#version 110\nuniform sampler2D Surface; uniform sampler2D Palette; varying vec2 UV; void main(){float i=floor(texture2D(Surface,UV).r*255.0+0.5);gl_FragColor=vec4(texture2D(Palette,vec2((i+0.5)/256.0,0.5)).rgb,1.0);}";
 GLuint v=0,f=0; GLint ok=0,location,maximum=0; int code;
 /* Top-left surface origin, bottom-left GL viewport. Interleaved attributes. */
 static const GLfloat vertices[]={-1,-1,0,1, 1,-1,1,1, 1,1,1,0, -1,1,0,0};
 memset(p,0,sizeof(*p));
 if (!pd2_gl_api_complete(a)) return PD2_GL_API_MISSING;
 if ((code=pd2_gl_format(bpp,rgb555,&p->format,&p->type))) return code;
 a->GetIntegerv(GL_MAX_TEXTURE_SIZE,&maximum);
 if (width<1 || height<1 || width>maximum || height>maximum || width>16384 || height>16384) return PD2_GL_FORMAT;
 p->width=width; p->height=height; p->bpp=bpp; p->rgb555=rgb555;
 if ((code=pd2_gl_error(a,PD2_GL_STATE))) return code;
 v=pd2_gl_shader(a,GL_VERTEX_SHADER,vs); if (!v) return PD2_GL_VERTEX;
 f=pd2_gl_shader(a,GL_FRAGMENT_SHADER,bpp==8 ? fs_pal:fs_rgb);
 if (!f) { a->DeleteShader(v); return PD2_GL_FRAGMENT; }
 p->program=a->CreateProgram();
 if (p->program) {
 a->AttachShader(p->program,v); a->AttachShader(p->program,f);
 a->BindAttribLocation(p->program,0,"Position"); a->BindAttribLocation(p->program,1,"TexCoord");
 a->LinkProgram(p->program); a->GetProgramiv(p->program,GL_LINK_STATUS,&ok);
 }
 a->DeleteShader(v); a->DeleteShader(f);
 if (!ok || pd2_gl_error(a,PD2_GL_LINK)) return PD2_GL_LINK;
 a->UseProgram(p->program);
 location=a->GetUniformLocation(p->program,"Surface"); if (location<0) return PD2_GL_LINK;
 a->Uniform1i(location,0);
 if (bpp==8) {
 location=a->GetUniformLocation(p->program,"Palette"); if (location<0) return PD2_GL_LINK;
 a->Uniform1i(location,1);
 }
 a->GenTextures(1,&p->texture);
 a->ActiveTexture(GL_TEXTURE0); a->BindTexture(GL_TEXTURE_2D,p->texture);
 a->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
 a->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
 a->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
 a->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
 a->PixelStorei(GL_UNPACK_ALIGNMENT,1);
 a->TexImage2D(GL_TEXTURE_2D,0,bpp==8 ? GL_LUMINANCE : bpp==16 && !rgb555 ? GL_RGB:GL_RGBA,width,height,0,p->format,p->type,NULL);
 if (bpp==8) {
 a->GenTextures(1,&p->palette); a->ActiveTexture(GL_TEXTURE1); a->BindTexture(GL_TEXTURE_2D,p->palette);
 a->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
 a->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
 a->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
 a->TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
 a->TexImage2D(GL_TEXTURE_2D,0,GL_RGBA,256,1,0,GL_RGBA,GL_UNSIGNED_BYTE,NULL);
 }
 if (!p->texture || (bpp==8 && !p->palette) || pd2_gl_error(a,PD2_GL_TEXTURE)) return PD2_GL_TEXTURE;
 a->GenBuffers(1,&p->vbo); a->BindBuffer(GL_ARRAY_BUFFER,p->vbo);
 a->BufferData(GL_ARRAY_BUFFER,sizeof(vertices),vertices,GL_STATIC_DRAW);
 a->VertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,4*sizeof(GLfloat),(const void *)0);
 a->VertexAttribPointer(1,2,GL_FLOAT,GL_FALSE,4*sizeof(GLfloat),(const void *)(2*sizeof(GLfloat)));
 a->EnableVertexAttribArray(0); a->EnableVertexAttribArray(1);
 a->Disable(GL_DEPTH_TEST); a->Disable(GL_BLEND); a->Disable(GL_CULL_FACE); a->Disable(GL_SCISSOR_TEST); a->Disable(GL_DITHER);
 return !p->vbo ? PD2_GL_STATE:pd2_gl_error(a,PD2_GL_STATE);
}
static int pd2_gl_upload_palette(pd2_gl_api *a,pd2_gl_pipeline *p,const void *palette) {
 if (p->bpp!=8 || !palette) return PD2_GL_UPLOAD;
 a->ActiveTexture(GL_TEXTURE1); a->BindTexture(GL_TEXTURE_2D,p->palette);
 a->TexSubImage2D(GL_TEXTURE_2D,0,0,0,256,1,GL_RGBA,GL_UNSIGNED_BYTE,palette);
 return pd2_gl_error(a,PD2_GL_UPLOAD);
}
static int pd2_gl_upload(pd2_gl_api *a,pd2_gl_pipeline *p,const void *pixels,int pitch,const void *palette) {
 int bytes=p->bpp/8,row;
 if (!pixels || pitch<p->width*bytes || pitch>268435456) return PD2_GL_UPLOAD;
 a->ActiveTexture(GL_TEXTURE0); a->BindTexture(GL_TEXTURE_2D,p->texture);
 /* No GL_UNPACK_ROW_LENGTH (not GLES2). Tight rows upload once; unusual pitch
  * uploads row slices directly, never converts/copies a full surface on CPU. */
 if (pitch==p->width*bytes) a->TexSubImage2D(GL_TEXTURE_2D,0,0,0,p->width,p->height,p->format,p->type,pixels);
 else for (row=0;row<p->height;++row) a->TexSubImage2D(GL_TEXTURE_2D,0,0,row,p->width,1,p->format,p->type,(const unsigned char *)pixels+(size_t)row*pitch);
 if (pd2_gl_error(a,PD2_GL_UPLOAD)) return PD2_GL_UPLOAD;
 if (p->bpp==8 && palette) return pd2_gl_upload_palette(a,p,palette);
 return 0;
}
static int pd2_gl_draw(pd2_gl_api *a,pd2_gl_pipeline *p,int x,int y,int width,int height) {
 static const GLushort indices[]={0,1,2,0,2,3};
 a->Viewport(x,y,width,height); a->UseProgram(p->program);
 a->ActiveTexture(GL_TEXTURE0); a->BindTexture(GL_TEXTURE_2D,p->texture);
 if (p->bpp==8) { a->ActiveTexture(GL_TEXTURE1); a->BindTexture(GL_TEXTURE_2D,p->palette); }
 a->DrawElements(GL_TRIANGLES,6,GL_UNSIGNED_SHORT,indices);
 return pd2_gl_error(a,PD2_GL_DRAW);
}
/* Startup-only real pixel validation of every supported input path. Synthetic
 * red/green top row, blue/white bottom row. ReadPixels is NEVER used on game data. */
static int pd2_gl_validate(pd2_gl_api *a,int selected_bpp,int selected_rgb555) {
 static const unsigned char indexed[]={1,2,3,4};
 static const unsigned short rgb565[]={0xf800,0x07e0,0x001f,0xffff};
 static const unsigned short rgb555[]={0x7c00,0x03e0,0x001f,0x7fff};
 static const unsigned char bgra[]={0,0,255,0, 0,255,0,0, 255,0,0,0, 255,255,255,0};
 static const unsigned char expected[]={0,0,255,255, 255,255,255,255, 255,0,0,255, 0,255,0,255};
 unsigned char palette[1024]={0},result[16];
 const void *pixels[]={indexed,rgb565,rgb555,bgra};
 const int bpps[]={8,16,16,32}; int i,j,code,destroy_code; pd2_gl_pipeline p;
 if (selected_bpp && selected_bpp!=8 && selected_bpp!=16 && selected_bpp!=32) return PD2_GL_FORMAT;
 palette[4]=255; palette[9]=255; palette[14]=255; palette[16]=palette[17]=palette[18]=255;
 for (i=0;i<4;++i) {
 /* Native harness requests all formats (0); runtime validates only the active
  * mode, so an unused driver format cannot reject otherwise valid gameplay. */
 if (selected_bpp && (bpps[i]!=selected_bpp || (selected_bpp==16 && (i==2)!=!!selected_rgb555))) continue;
 code=pd2_gl_init(a,&p,2,2,bpps[i],i==2);
 if (!code) code=pd2_gl_upload(a,&p,pixels[i],2*(bpps[i]/8),palette);
 if (!code) code=pd2_gl_draw(a,&p,0,0,2,2);
 if (!code) {
 memset(result,0,sizeof(result)); a->PixelStorei(GL_PACK_ALIGNMENT,1);
 a->ReadPixels(0,0,2,2,GL_RGBA,GL_UNSIGNED_BYTE,result);
 code=pd2_gl_error(a,PD2_GL_VALIDATION);
 if (!code) for (j=0;j<16;++j) if ((int)result[j]-(int)expected[j]>8 || (int)expected[j]-(int)result[j]>8) { code=PD2_GL_VALIDATION; break; }
 }
 /* Palette-only update must recolor without a surface reupload. */
 if (!code && i==0) {
 palette[12]=255;palette[13]=0;palette[14]=0;
 code=pd2_gl_upload_palette(a,&p,palette);
 if (!code) code=pd2_gl_draw(a,&p,0,0,2,2);
 if (!code) {
 a->ReadPixels(0,0,1,1,GL_RGBA,GL_UNSIGNED_BYTE,result);
 code=pd2_gl_error(a,PD2_GL_VALIDATION);
 if (!code && (result[0]<247 || result[1]>8 || result[2]>8 || result[3]<247)) code=PD2_GL_VALIDATION;
 }
 }
 destroy_code=pd2_gl_destroy(a,&p);
 if (code) return code; if (destroy_code) return destroy_code;
 }
 return 0;
}
#endif
