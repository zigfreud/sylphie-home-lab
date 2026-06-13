# Sylphie Home Lab

Native Windows CLI backend for controlling ASUS Aura/ENE RGB header on ASUS PRIME B450M-GAMING/BR.

## Status

Experimental home-lab software. The hardware protocol is validated on the tested motherboard, but the controller ownership, recovery, and capture tooling are still evolving.

## Safety

This project uses low-level SMBus and I/O port access. Use at your own risk. Do not run hardware write commands while ASUS Armoury Crate, Aura, LightingService, or another RGB controller is using the same SMBus device.

OpenRGB/OpenAuraSDK were used as research references only. No GPL source code is vendored or copied into this repository.

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
sylphie_rgb.exe takeover --dry-run
sylphie_rgb.exe takeover --execute --i-accept-stopping-lighting-services
sylphie_rgb.exe restore-services
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
src\native\sylphie_agent\build.bat
src\native\sylphie_piix4_broad_capture\build.bat
tools\probes\build_armoury_ui_capture.bat
```

The executables are written to `bin\`:

- `sylphie_rgb.exe`
- `sylphie_agent.exe`
- `sylphie_piix4_broad_capture.exe`
- `sylphie_piix4_armoury_ui_capture.exe`

If `sylphie_agent.exe` is already running, stop it before rebuilding:

```powershell
.\scripts\stop_agent.ps1
```

## Runtime Dependency

`inpout32.dll` is required next to the executable but is not committed to the repository.

## Local API / Dashboard

The local dashboard runs through a small Python standard-library HTTP server. It binds to `127.0.0.1` by default and prefers `sylphie_agent.exe` for hardware operations.

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

## Sylphie Control Center

Start the local operations panel:

```bat
.\start_sylphie.bat
```

Open:

```text
http://127.0.0.1:8765/
```

The Control Center shows the current owner at the top:

- `Armoury`: Armoury/LightingService owns RGB. Sylphie shows status, diagnostics, logs, and read-only capture controls, but RGB writes are blocked.
- `Sylphie`: `sylphie_agent.exe` owns RGB. Armoury/LightingService should be stopped, and RGB writes are allowed.
- `Research`: a read-only capture probe is running. SMBus writes are blocked.
- `Conflict` / `Unknown`: ownership is ambiguous. SMBus writes are blocked until the user resolves ownership.

The Control Center has these tabs:

- `Lights`: scenes, color picker, off, last RGB, and last command result.
- `Agent`: ping/status plus Scheduled Task status, install, enable/disable autostart, uninstall, start-now, and stop actions.
- `Armoury Takeover`: service/process status, takeover dry-run, explicit takeover execute, and restore services.
- `Diagnostics`: Armoury Health and Audio/Reactive Health for LightingService, Armoury addons/processes, Windows Audio, Logitech LampArray, and related process storms.
- `Recovery`: bus-status, recover, recover-set white/red/last color, and placeholders for experimental recovery flows.
- `Capture Lab`: start broad capture, start Armoury UI capture, launch full Armoury cold-start capture, stop capture, sidecar markers, and capture log tail.
- `Logs`: safe tail views for `logs/server.log`, `logs/agent.log`, `logs/commands.jsonl`, and the current capture log.

The HTTP server is not elevated. Privileged hardware and ownership operations go through `sylphie_agent.exe` or fixed whitelisted scripts. The server exposes only fixed endpoints and whitelisted scripts. It does not accept arbitrary commands, paths, or shell input. For debug-only CLI fallback, start the server with `SYLPHIE_USE_AGENT=0`.

The Scheduled Task for `sylphie_agent.exe` is opt-in for autostart. Installing the task creates it disabled by default unless the user explicitly enables autostart from the Control Center or passes the explicit flag in PowerShell. To start the agent manually without enabling autostart:

```powershell
.\scripts\start_agent_now.ps1
```

Capture Lab starts only whitelisted local probe executables from `bin\`. Markers are written through the dashboard into a sidecar marker log under `research/captures/`, so capture workflows do not require typing probe commands by hand.

Full Armoury cold-start capture is different: it intentionally stops the Sylphie server/agent, stops `LightingService` first, kills only whitelisted leftover Armoury/Aura/OpenRGB processes, launches Armoury or starts `LightingService`, and writes a sanitized summary under `docs/research/`. Because it must stop services, it runs in a separate elevated PowerShell window and the dashboard may disconnect during the workflow.

Capture Lab also supports a `Stack already stopped, start capture now` mode. Use it when you manually stopped `LightingService` and Armoury/Aura processes before starting capture. The marker log records `STACK_ALREADY_STOPPED_AT_CAPTURE_START` plus a service/process snapshot, so absence of `SERVICE_STOPPED` is not treated as a bad capture in that mode.

For short Armoury rearm bursts, keep `High-rate ring buffer` enabled. The Armoury UI probe then runs with `--high-rate --priority-high --focus-addr 40 --focus-registers 8000,8020,80A0,80F1,8022,8023` and dumps the preceding ring buffer around block writes and focus-register events. It still reads `SMBBLKDAT/+0x07` only on eligible block writes when payload capture is enabled.

Analyze captures from the panel with `Analyze latest capture`, or from PowerShell:

```powershell
python tools\analyze_capture.py research\captures\armoury_ui_YYYYMMDD_HHMMSS_master.log
```

## Controller Ownership and Recovery

Do not run Sylphie hardware writes while Armoury Crate, Aura, OpenRGB, or `LightingService` owns the controller. The local API checks `/api/ownership/status` before `set`, `scene`, `off`, and recovery writes. If the current owner is not `Sylphie`, the API returns HTTP 409 and does not write SMBus.

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

## Taking Ownership From Armoury/Aura

Takeover is an explicit, reversible operation for cases where ASUS/Aura/OpenRGB processes keep reclaiming the RGB controller.

From the Control Center, prefer `Takeover for Sylphie`. The flow stops `LightingService` first, waits for service release, terminates only whitelisted Armoury/Aura leftovers, leaves `AsusCertService` alone by default, does not change service `StartupType`, starts the Sylphie agent manually, and then runs read-only health checks. RGB controls unlock only after ownership resolves to `Sylphie`.

Read-only check:

```bat
sylphie_rgb.exe takeover-check
```

Preview what Sylphie would stop:

```bat
sylphie_rgb.exe takeover --dry-run
```

Execute the safe Tier 1 takeover:

```bat
sylphie_rgb.exe takeover --execute --i-accept-stopping-lighting-services
```

Include Armoury core helper components, except `AsusCertService`:

```bat
sylphie_rgb.exe takeover --execute --i-accept-stopping-lighting-services --include-armoury-core
```

Restore services stopped by Sylphie:

```bat
sylphie_rgb.exe restore-services
```

Takeover only stops whitelisted services/processes. It does not uninstall software, delete services, change `StartupType`, or disable services permanently. Sylphie saves `.sylphie/takeover_state.json` and `restore-services` only attempts to restart services recorded there. It does not recreate standalone processes.

Armoury/Aura may stop controlling RGB until `restore-services` runs or the machine reboots. The dashboard exposes takeover as explicit buttons; it never runs takeover automatically.

Use `Return to Armoury` when repairing Armoury, restoring addons, or using Music mode. The flow stops the Sylphie agent, optionally disables Sylphie autostart, restores services recorded in `.sylphie/takeover_state.json`, starts `LightingService`, and launches Armoury if a known path exists. It does not write SMBus.

## Hardware Agent

`sylphie_agent.exe` is the persistent elevated hardware owner prototype. It listens on the local named pipe `\\.\pipe\sylphie-hw`, serializes hardware writes, performs privileged ownership/recovery operations, and calls the native SMBus/Aura layer directly. The HTTP server should remain non-elevated.

Build:

```bat
src\native\sylphie_agent\build.bat
```

Manual agent test:

```bat
bin\sylphie_agent.exe --pipe \\.\pipe\sylphie-hw
bin\sylphie_agent.exe --client ping
bin\sylphie_agent.exe --client status
```

Scheduled Task setup:

```powershell
.\scripts\install_agent_task.ps1
.\scripts\start_agent_now.ps1
.\scripts\status_agent.ps1
.\scripts\stop_agent.ps1
```

The task is named `SylphieAgent` and runs with highest privileges. It is created disabled by default. Autostart at user logon is enabled only by explicit user action:

```powershell
.\scripts\install_agent_task.ps1 -EnableAutostart
```

The agent writes logs to:

```text
logs/agent.log
```

Do not run Armoury, Aura, OpenRGB, or `LightingService` at the same time as the agent. The agent refuses write commands when known controller conflicts are detected unless it was started with the debug-only `--allow-conflicts` flag.

Takeover from the agent follows the safe order:

1. Stop `LightingService` and other allowed services first.
2. Wait briefly.
3. Terminate only whitelisted leftover processes.
4. Save `.sylphie/takeover_state.json`.
5. Run bus status and conservative recovery.

`AsusCertService` is warning-only and is not stopped by default.

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
