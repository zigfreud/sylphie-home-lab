# Sylphie Home Lab Roadmap

## Current Phase

Local API/dashboard stability:

- Native `sylphie_rgb.exe` remains the hardware backend.
- Python standard-library HTTP server wraps the backend for local browser control.
- Write commands are serialized to avoid concurrent SMBus access.
- Dashboard is local-first and binds to `127.0.0.1` by default.
- Controller ownership checks run before API writes.
- Armoury/Sylphie coexistence distinguishes soft takeover, Sylphie Candidate, and Sylphie Verified via direct visual sanity test.
- Direct V2 sanity emits mandatory technical trace and does not unlock normal writes without visual confirmation.
- Already-clean ownership is claimable without stop actions; Logitech process storms are grouped as external diagnostics noise.
- Conservative software recovery is available through the CLI and dashboard.

## Next Phases

1. Windows autostart/tray
2. LAN/mobile access with token-based access control
3. Home Assistant integration
4. Alexa integration
5. Native Sylphie audio reactive mode using WASAPI loopback
6. Fire TV / media mode

## Future Issues

- Implement native Sylphie audio reactive mode using WASAPI loopback, independent of Armoury's audio capture pipeline.
- Track Armoury service alias changes after Armoury Crate updates (`ArmouryCrateService`, legacy `ArmouryCrate.Service`, `asComSvc`).

## Deferred

- No OpenRGB runtime.
- No Armoury/LightingService control automation.
- No static/effect register path for the MVP.
- No streaming mode until the direct RGB path is fully stable.
