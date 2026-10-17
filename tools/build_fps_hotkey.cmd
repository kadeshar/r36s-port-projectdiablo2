@echo off
setlocal
rem Build only this standalone sidecar; never alter imported PD2 binaries.
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64_x86 10.0.22621.0 -vcvars_ver=14.44
if errorlevel 1 exit /b %errorlevel%
pushd "%~dp0.."
if not exist ".state\fps-build" mkdir ".state\fps-build"
if not exist "sdcard\ports\projectdiablo2\compat\fps-hotkey" mkdir "sdcard\ports\projectdiablo2\compat\fps-hotkey"
cl /nologo /std:c11 /O1 /MT /W4 /D_WIN32_WINNT=0x0601 /DWINVER=0x0601 /Fo".state\fps-build\fps_hotkey.obj" /Fe"sdcard\ports\projectdiablo2\compat\fps-hotkey\fps-hotkey.exe" "tools\fps_hotkey.c" /link /MACHINE:X86 /SUBSYSTEM:WINDOWS,6.01 /Brepro user32.lib
set result=%errorlevel%
popd
exit /b %result%
