@echo off
setlocal
rem Run from an x64 Native Tools Command Prompt (Visual Studio + Windows SDK).
where cl >nul 2>nul
if errorlevel 1 (echo Open an x64 Native Tools Command Prompt first. & exit /b 1)
if not defined OPENNI_INCLUDE (echo Set OPENNI_INCLUDE to the official SDK Include directory. & exit /b 1)
if not defined OPENNI_RUNTIME (echo Set OPENNI_RUNTIME to the Win64 runtime containing OpenNI2.dll. & exit /b 1)
cd /d "%~dp0"
if not exist "build" mkdir "build"
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; if (-not (Test-Path -LiteralPath ($env:OPENNI_RUNTIME + '\OpenNI2.dll'))) { throw 'Missing OpenNI2.dll' }; New-Item -ItemType Directory -Force 'build\openni_runtime' >$null; Get-ChildItem -LiteralPath $env:OPENNI_RUNTIME | Copy-Item -Destination 'build\openni_runtime' -Recurse -Force"
if errorlevel 1 exit /b 1
cd build
cl /nologo /std:c++20 /EHsc /W4 /utf-8 /MT /I"%OPENNI_INCLUDE%" "..\D2Capture.cpp" "..\test_capture.cpp" /Fe:test_capture.exe /link bcrypt.lib
if errorlevel 1 exit /b 1
cl /nologo /std:c++20 /EHsc /W4 /utf-8 /MT /LD /I"%OPENNI_INCLUDE%" "..\D2Capture.cpp" "..\D2MediaSource.cpp" "..\dllmain.cpp" /Fe:D2MediaSource.dll /link /DEF:"..\module.def" bcrypt.lib mfplat.lib mf.lib mfuuid.lib ole32.lib mfsensorgroup.lib
if errorlevel 1 exit /b 1
for %%T in (test_consumer test_activate test_source_reader virtual_camera_probe) do (
  cl /nologo /std:c++20 /EHsc /W4 /utf-8 /MT "..\%%T.cpp" /Fe:%%T.exe /link mfplat.lib mf.lib mfuuid.lib ole32.lib mfreadwrite.lib mfsensorgroup.lib
  if errorlevel 1 exit /b 1
)
cl /nologo /std:c++20 /EHsc /W4 /utf-8 /MT /I"%OPENNI_INCLUDE%" "..\D2Capture.cpp" "..\test_background.cpp" /Fe:test_background.exe /link bcrypt.lib
exit /b %errorlevel%
