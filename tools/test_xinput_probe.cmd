@echo off
setlocal
rem Host-only synthetic Win32 ABI tests; not Wine/handheld/controller validation.
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64_x86 10.0.22621.0 -vcvars_ver=14.44
if errorlevel 1 exit /b %errorlevel%
python -B "%~dp0..\tests\run_xinput_probe_native.py"
exit /b %errorlevel%
