@echo off
setlocal
rem Build only our diagnostic; never run a real audio test on the build host.
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64_x86 10.0.22621.0 -vcvars_ver=14.44
if errorlevel 1 exit /b %errorlevel%
pushd "%~dp0.."
if not exist ".state\audio-build" mkdir ".state\audio-build"
if not exist "sdcard\ports\projectdiablo2\compat\audio-probe" mkdir "sdcard\ports\projectdiablo2\compat\audio-probe"
cl /nologo /std:c11 /O1 /MT /W4 /D_WIN32_WINNT=0x0601 /DWINVER=0x0601 /Fo".state\audio-build\audio_probe.obj" /Fe"sdcard\ports\projectdiablo2\compat\audio-probe\audio-probe.exe" "tools\audio_probe.c" /link /MACHINE:X86 /SUBSYSTEM:WINDOWS,6.01 /Brepro user32.lib gdi32.lib winmm.lib dsound.lib
set result=%errorlevel%
popd
exit /b %result%
