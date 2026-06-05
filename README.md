# Sylphie Home Lab

Native Windows CLI backend for controlling ASUS Aura/ENE RGB header on ASUS PRIME B450M-GAMING/BR.

## Safety

This project uses low-level SMBus and I/O port access. Use at your own risk. Do not run hardware write commands while ASUS Armoury Crate, Aura, LightingService, or another RGB controller is using the same SMBus device.

## Tested Hardware

- ASUS PRIME B450M-GAMING/BR
- ENE/Aura AUMA0-E8K4-0101
- RGB header 12V analog

## Commands

```bat
sylphie_rgb.exe doctor
sylphie_rgb.exe set FF0000
sylphie_rgb.exe set 00FF00
sylphie_rgb.exe set 0000FF
sylphie_rgb.exe off
sylphie_rgb.exe scenes
sylphie_rgb.exe scene focus
sylphie_rgb.exe scene movie
sylphie_rgb.exe scene off
sylphie_rgb.exe calibrate --dry-run
sylphie_rgb.exe bus-status
sylphie_rgb.exe takeover-check
sylphie_rgb.exe recover
sylphie_rgb.exe recover-set FF0000
```

Use `--dry-run` with `set`, `off`, or `scene` to print the SMBus sequence without writing to hardware. Use `--verbose` with hardware write commands to print SMBus status and selected registers.

## Calibration and Scenes

Available scenes:

- `focus` - `FFFFFF` - strong neutral white
- `movie` - `202060` - visible dark blue-purple bias light
- `night` - `300000` - low red above visibility threshold
- `reading` - `FFC080` - warm reading light
- `cyberpunk` - `FF0080` - magenta accent
- `deepblue` - `0000FF` - full blue
- `red` - `FF0000` - full red
- `green` - `00FF00` - full green
- `blue` - `0000FF` - full blue
- `white` - `FFFFFF` - full white
- `off` - `000000` - direct RGB off

Run:

```bat
sylphie_rgb.exe calibrate --dry-run
```

This prints the manual calibration sequence without writing to hardware. The calibration command does not auto-cycle colors by default; run each printed command manually and verify the visible result before continuing.

Scene details are documented in `docs/scenes.md`.

## Build

Build from the x86 Native Tools Command Prompt for Visual Studio 2019:

```bat
src\native\sylphie_rgb\build.bat
```

The executable is written to `bin\sylphie_rgb.exe`.

## Runtime Dependency

`inpout32.dll` is required next to the executable but is not committed to the repository.

## Local API / Dashboard

The local dashboard wraps `sylphie_rgb.exe` through a small Python standard-library HTTP server. It binds to `127.0.0.1` by default.

```bat
python src/server/sylphie_server.py --host 127.0.0.1 --port 8765 --exe bin/sylphie_rgb.exe
```

Open:

```text
http://127.0.0.1:8765/
```

PowerShell examples:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/scene -Body '{"name":"movie"}' -ContentType 'application/json'
Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/set -Body '{"rgb":"FF0000"}' -ContentType 'application/json'
Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/off
```

The server never accepts arbitrary shell commands and calls the backend with `shell=False`.

## Controller Ownership and Recovery

Do not run Sylphie hardware writes while Armoury Crate, Aura, OpenRGB, or `LightingService` owns the controller. The local API runs `takeover-check` before `set`, `scene`, and `off`; if a known controller process is detected, the API returns HTTP 409 and does not write.

Useful checks:

```bat
sylphie_rgb.exe bus-status
sylphie_rgb.exe takeover-check
```

If the color stops responding after switching between Sylphie and ASUS tools:

1. Stop Sylphie: `.\scripts\stop_sylphie.ps1`
2. Close the dashboard/browser tab.
3. Close or stop Armoury/Aura/OpenRGB/LightingService.
4. Run `sylphie_rgb.exe takeover-check`.
5. Run `sylphie_rgb.exe recover --verbose`.
6. Run `sylphie_rgb.exe recover-set FF0000`.
7. Use a full power drain only if software recovery and ownership cleanup do not restore control.

The recovery command only toggles the confirmed direct-mode path and writes direct RGB `000000`; it does not touch `0x8160`, streaming, or experimental registers.

## Starting Sylphie

From the project root:

```bat
.\start_sylphie.bat
```

The dashboard runs at:

```text
http://127.0.0.1:8765/
```

Status and stop commands:

```powershell
.\scripts\status_sylphie.ps1
.\scripts\stop_sylphie.ps1
.\scripts\stop_sylphie.ps1 -ForcePortOwner
.\scripts\start_sylphie.ps1 -Restart
```

Startup validates `bin\sylphie_rgb.exe`, `bin\inpout32.dll`, the Python server, and `python` availability. It runs `sylphie_rgb.exe doctor` before starting the dashboard.

Runtime state is written to `.sylphie/`, and server logs are written to:

```text
logs/server.log
```

ASUS Armoury Crate, Aura, and LightingService should be closed or stopped before issuing hardware write commands. Sylphie only warns about those processes; it does not kill or stop them automatically.

The API is intended for localhost use. Binding to `0.0.0.0` is not recommended until authentication is implemented.

If port `8765` is occupied, inspect it with:

```powershell
.\scripts\status_sylphie.ps1
```

`stop_sylphie.ps1` stops only the saved Sylphie PID or the process that owns the configured port and matches the Sylphie server signature. If the port owner has an empty or unusual command line but you know it is the Sylphie server, use:

```powershell
.\scripts\stop_sylphie.ps1 -ForcePortOwner
```

## API Reliability Test

PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health

Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/scene `
  -Body '{"name":"red"}' `
  -ContentType 'application/json'

Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/scene `
  -Body '{"name":"green"}' `
  -ContentType 'application/json'

Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/scene `
  -Body '{"name":"blue"}' `
  -ContentType 'application/json'

Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/off
```

Write endpoints are deterministic: the API returns `ok: true` only after `sylphie_rgb.exe` exits with code `0`.

## Protocol Notes

The confirmed protocol for the current MVP is documented in `docs/protocol/asus-prime-b450m-aura-smbus.md`.
