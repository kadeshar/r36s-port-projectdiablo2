@echo off
setlocal
rem Test build stays under .state and cannot overwrite the production helper.
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64_x86 10.0.22621.0 -vcvars_ver=14.44
if errorlevel 1 exit /b %errorlevel%
pushd "%~dp0.."
if not exist ".state\fps-native-tests" mkdir ".state\fps-native-tests"
cl /nologo /std:c11 /Od /MT /W4 /DFPS_NATIVE_TEST /Fo".state\fps-native-tests\fps_test.obj" /Fe".state\fps-native-tests\fps_test.exe" "tools\fps_hotkey.c" /link /MACHINE:X86 /Brepro
if errorlevel 1 goto done
".state\fps-native-tests\fps_test.exe"
:done
set result=%errorlevel%
popd
exit /b %result%
