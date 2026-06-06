# Sylphie Architecture

## Native CLI

`sylphie_rgb.exe` is the low-level debug and maintenance CLI. It talks directly to the ASUS/ENE controller through `inpout32.dll`, PIIX4 SMBus, and the confirmed direct RGB protocol:

- SMBus base `0x0B20`
- addr7 `0x40`
- direct mode register `0x8020`
- apply register `0x80A0`
- RGB direct register `0x8101`
- payload order `R G B`

The CLI remains useful for `doctor`, `bus-status`, `takeover-check`, dry-runs, and recovery diagnostics.

## Hardware Agent

`sylphie_agent.exe` is the planned persistent hardware owner. It runs elevated, listens on the local named pipe `\\.\pipe\sylphie-hw`, and serializes all hardware writes through one process.

The agent accepts JSON-lines IPC. It does not expose TCP, does not run shell commands, and does not accept arbitrary commands. It calls the native `Piix4Smbus` and `AuraEne` layers directly.

The first prototype is installed with a Windows Scheduled Task named `SylphieAgent` using highest privileges. This avoids elevating the HTTP server and avoids creating a real Windows Service before the runtime shape is stable.

TODO: tighten named pipe ACLs to the current user and Administrators explicitly.

## HTTP Server

`src/server/sylphie_server.py` is the localhost API/dashboard server. It must not run elevated. By default it routes compatible hardware and ownership operations through `sylphie_agent.exe` over `\\.\pipe\sylphie-hw`.

Set this environment variable only for debug CLI fallback:

```powershell
$env:SYLPHIE_USE_AGENT = "0"
```

The server continues to bind to `127.0.0.1` by default.

The server never accepts arbitrary commands or paths from HTTP. Lifecycle actions use a whitelist of project scripts, log tail endpoints use a whitelist of log names, and capture actions use whitelisted probe executables.

## Dashboard

The static dashboard calls the HTTP API only. It does not talk to SMBus, `inpout32.dll`, or the named pipe directly.

Current tabs:

- Lights
- Agent
- Armoury Takeover
- Recovery
- Capture Lab
- Logs

Capture Lab starts read-only probes and records UI marker clicks into sidecar marker logs. It does not elevate the HTTP server.

## Ownership Flow

The safe takeover order is:

1. Stop `LightingService` first.
2. Wait for service stop/release.
3. Terminate only whitelisted Armoury/Aura/OpenRGB leftover processes.
4. Save `.sylphie/takeover_state.json`.
5. Run bus-status and conservative recovery.
6. Apply RGB through the confirmed direct path.

`AsusCertService` is warning-only and is not stopped by default.

## Future Integrations

Home Assistant, Alexa, mobile/LAN access, and media modes should integrate through the HTTP/API layer or a future authenticated local control layer. They should not talk directly to SMBus.
