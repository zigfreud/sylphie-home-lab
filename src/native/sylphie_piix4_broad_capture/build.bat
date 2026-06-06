@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%..\..\.." >nul
set "ROOT_DIR=%CD%"
popd >nul
set "OUT_DIR=%ROOT_DIR%\bin"

if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

cl /nologo /std:c++17 /EHsc /W4 /DWIN32_LEAN_AND_MEAN /DNOMINMAX ^
  /Fo"%OUT_DIR%\\" /Fd"%OUT_DIR%\\" ^
  /Fe"%OUT_DIR%\sylphie_piix4_broad_capture.exe" ^
  "%SCRIPT_DIR%main.cpp"

if errorlevel 1 exit /b 1

echo Built "%OUT_DIR%\sylphie_piix4_broad_capture.exe"
echo Place inpout32.dll next to the executable before running capture.
