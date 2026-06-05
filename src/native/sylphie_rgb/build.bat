@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "ROOT_DIR=%SCRIPT_DIR%..\..\.."
set "OUT_DIR=%ROOT_DIR%\bin"

if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

cl /nologo /std:c++17 /EHsc /W4 /DWIN32_LEAN_AND_MEAN /DNOMINMAX ^
  /Fe"%OUT_DIR%\sylphie_rgb.exe" ^
  "%SCRIPT_DIR%main.cpp" ^
  "%SCRIPT_DIR%piix4_smbus.cpp" ^
  "%SCRIPT_DIR%aura_ene.cpp" ^
  "%SCRIPT_DIR%process_check.cpp"

if errorlevel 1 exit /b 1

echo Built "%OUT_DIR%\sylphie_rgb.exe"
echo Place inpout32.dll next to sylphie_rgb.exe before running hardware commands or doctor.
