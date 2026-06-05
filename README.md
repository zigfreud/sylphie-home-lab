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

## Protocol Notes

The confirmed protocol for the current MVP is documented in `docs/protocol/asus-prime-b450m-aura-smbus.md`.
