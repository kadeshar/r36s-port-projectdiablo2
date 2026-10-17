@echo off
setlocal
rem Rebuild only our own diagnostic, never any imported PD2 files.
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64_x86 10.0.22621.0 -vcvars_ver=14.44
if errorlevel 1 exit /b %errorlevel%
pushd "%~dp0.."
if not exist ".state\xinput-build" mkdir ".state\xinput-build"
if not exist "sdcard\ports\projectdiablo2\compat\xinput-probe" mkdir "sdcard\ports\projectdiablo2\compat\xinput-probe"
cl /nologo /std:c11 /O1 /MT /W4 /D_WIN32_WINNT=0x0601 /DWINVER=0x0601 /Fo".state\xinput-build\xinput_probe.obj" /Fe"sdcard\ports\projectdiablo2\compat\xinput-probe\xinput-probe.exe" "tools\xinput_probe.c" /link /MACHINE:X86 /SUBSYSTEM:WINDOWS,6.01 /Brepro user32.lib gdi32.lib
set result=%errorlevel%
popd
exit /b %result%
