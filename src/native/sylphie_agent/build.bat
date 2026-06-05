@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "ROOT_DIR=%SCRIPT_DIR%..\..\.."
set "RGB_DIR=%SCRIPT_DIR%..\sylphie_rgb"
set "OUT_DIR=%ROOT_DIR%\bin"

if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

cl /nologo /std:c++17 /EHsc /W4 /DWIN32_LEAN_AND_MEAN /DNOMINMAX ^
  /I"%RGB_DIR%" ^
  /Fe"%OUT_DIR%\sylphie_agent.exe" ^
  "%SCRIPT_DIR%main.cpp" ^
  "%SCRIPT_DIR%named_pipe_server.cpp" ^
  "%SCRIPT_DIR%agent_state.cpp" ^
  "%SCRIPT_DIR%hardware_controller.cpp" ^
  "%RGB_DIR%\piix4_smbus.cpp" ^
  "%RGB_DIR%\aura_ene.cpp" ^
  "%RGB_DIR%\process_check.cpp" ^
  Advapi32.lib

if errorlevel 1 exit /b 1

echo Built "%OUT_DIR%\sylphie_agent.exe"
echo Place inpout32.dll next to sylphie_agent.exe before running hardware commands.
