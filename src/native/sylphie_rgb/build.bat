@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%..\..\.." >nul
set "ROOT_DIR=%CD%"
popd >nul
set "OUT_DIR=%ROOT_DIR%\bin"

if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

call :ensure_msvc_x86
if errorlevel 1 exit /b 1

cl /nologo /std:c++17 /EHsc /W4 /DWIN32_LEAN_AND_MEAN /DNOMINMAX ^
  /Fo"%OUT_DIR%\\" /Fd"%OUT_DIR%\\" ^
  /Fe"%OUT_DIR%\sylphie_rgb.exe" ^
  "%SCRIPT_DIR%main.cpp" ^
  "%SCRIPT_DIR%piix4_smbus.cpp" ^
  "%SCRIPT_DIR%aura_ene.cpp" ^
  "%SCRIPT_DIR%process_check.cpp" ^
  Advapi32.lib ^
  /link /MACHINE:X86

if errorlevel 1 exit /b 1

echo Built "%OUT_DIR%\sylphie_rgb.exe"
echo Place inpout32.dll next to sylphie_rgb.exe before running hardware commands or doctor.
exit /b 0

:ensure_msvc_x86
if /I "%VSCMD_ARG_TGT_ARCH%"=="x86" (
  where cl >nul 2>nul
  if not errorlevel 1 exit /b 0
)

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
set "VSINSTALL="
if exist "%VSWHERE%" (
  for /f "usebackq tokens=*" %%I in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSINSTALL=%%I"
)

if defined VSINSTALL if exist "%VSINSTALL%\VC\Auxiliary\Build\vcvarsall.bat" (
  call "%VSINSTALL%\VC\Auxiliary\Build\vcvarsall.bat" x86 >nul
)

where cl >nul 2>nul
if errorlevel 1 (
  echo cl.exe not found. Install Visual Studio Build Tools C++ workload or run from an x86 Native Tools prompt.
  exit /b 1
)

if /I not "%VSCMD_ARG_TGT_ARCH%"=="x86" (
  echo Warning: MSVC target arch is "%VSCMD_ARG_TGT_ARCH%"; Sylphie expects x86 to match bin\inpout32.dll.
)
exit /b 0
