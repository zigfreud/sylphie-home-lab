# Sylphie Troubleshooting

## CLI Works But Dashboard Doesn't

Check whether the server is pointing at the expected executable:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
Invoke-RestMethod http://127.0.0.1:8765/api/debug/config
```

Confirm that the `exe` path is absolute and points to `bin\sylphie_rgb.exe`. If it does not, restart the server with:

```powershell
.\scripts\start_sylphie.ps1 -Restart
```

The Control Center prefers the elevated agent by default. If agent endpoints fail, check:

```powershell
.\scripts\status_agent.ps1
.\scripts\start_agent.ps1
```

Use `SYLPHIE_USE_AGENT=0` only for debug CLI fallback.

## Build Fails Because sylphie_agent.exe Is In Use

If `src\native\sylphie_agent\build.bat` cannot overwrite `bin\sylphie_agent.exe`, stop the running agent first:

```powershell
.\scripts\stop_agent.ps1
src\native\sylphie_agent\build.bat
```

This does not touch the SMBus hardware path; it only stops the Sylphie agent process/Scheduled Task.

## Doctor Fails Loading inpout32.dll

If `doctor` finds `bin\inpout32.dll` but then fails with `%1 is not a valid Win32 application`, the DLL exists but its architecture does not match the Sylphie executable. Sylphie currently targets x86 to match the x86 `inpout32.dll`, so rebuild with the native `build.bat` scripts and verify both files are x86.

## Dashboard Works Randomly

The dashboard calls the native CLI synchronously and serializes hardware commands. Random behavior usually means another controller is also touching the Aura/ENE device.

Run:

```powershell
bin\sylphie_rgb.exe takeover-check
Invoke-RestMethod http://127.0.0.1:8765/api/health
```

Close Armoury Crate, Aura, OpenRGB, and `LightingService` before writing colors from Sylphie.

## Armoury Works But Sylphie Doesn't

This suggests controller ownership or stale SMBus/controller state, not a change in the confirmed RGB protocol.

Recommended recovery flow:

```powershell
.\scripts\stop_sylphie.ps1
bin\sylphie_rgb.exe takeover-check
bin\sylphie_rgb.exe takeover --dry-run
bin\sylphie_rgb.exe bus-status
bin\sylphie_rgb.exe recover --verbose
bin\sylphie_rgb.exe recover-set FF0000
```

Do not use Armoury/OpenRGB at the same time as Sylphie.

If `takeover-check` keeps showing whitelisted lighting processes, run:

```powershell
bin\sylphie_rgb.exe takeover --execute --i-accept-stopping-lighting-services
```

Use `--include-armoury-core` only when the Tier 1 takeover is not enough.

## Armoury Music Mode Does Not React

If static, breathing, color cycle, or other Armoury lighting modes still work but Music does not, treat this as an audio/reactive pipeline failure. The RGB engine and header path can still be healthy while Armoury's audio capture path is broken.

Use `Diagnostics` -> `Audio/Reactive Health` in the Control Center to inspect:

- `Audiosrv`
- `AudioEndpointBuilder`
- `LightingService`
- `logi_lamparray_service`, when present
- Armoury, ASUS framework, Realtek, Nahimic, Sonic, Audio, Logitech, and LGHUB related processes

Do not investigate this first as an RGB header or SMBus failure. Music mode depends on Armoury/audio capture pipeline, not only SMBus RGB control.

The diagnostic view does not stop anything automatically. Its restart/restore actions require explicit confirmation:

- `Restart LightingService`
- `Restart Windows Audio services`
- `Restore Logitech LampArray service`

If Music mode only works again after reinstalling or restoring Armoury addons, keep the machine in Armoury Mode while repairing Armoury. Do not run Sylphie agent autostart during Armoury repair, because an elevated agent can reclaim ownership before Armoury's addon/audio pipeline has stabilized.

Music mode works only when Armoury addons and the audio capture pipeline are healthy. Do not treat a working static/breathing/color-cycle mode plus broken Music mode as an RGB header failure.

## Ownership Modes

The Control Center reports these ownership modes:

- `Armoury`: Armoury/LightingService owns RGB. Sylphie can show diagnostics, status, logs, and read-only captures, but RGB writes are blocked.
- `Soft Takeover / Unverified`: tier1 lighting blockers are stopped, but Armoury core services/helpers are still running. RGB writes are blocked.
- `Ready Clean`: tier1 blockers and Armoury core are stopped, but Sylphie ownership has not been claimed. RGB writes are blocked.
- `Sylphie Candidate`: clean ownership was claimed after takeover or already-clean detection. Normal RGB writes remain blocked; direct sanity test is allowed.
- `Sylphie Verified`: the red/green/blue/off direct sanity test was visually confirmed by the user, enabling normal RGB writes.
- `Research`: a read-only capture probe is running. SMBus writes are blocked.
- `Conflict` / `Unknown`: more than one owner is possible, or no owner is clear. RGB writes are blocked until resolved.

Armoury updates may leave multiple Armoury service generations present. Treat `ArmouryCrateService`, legacy `ArmouryCrate.Service`, and `asComSvc` as tier2 Armoury core. They are warnings during soft takeover and are stopped only by full takeover with the explicit `Close Armoury UI/helpers during takeover` checkbox. `AsusCertService` is never stopped by default; `asus`, `asusm`, and `AsusROGLSLService` are ignored update/download services by default.

### Sylphie Candidate But LEDs Do Not Change

If ownership is `Sylphie Candidate` and the direct sanity test reports `bus_write_ok=true`, but the LED strip does not physically change, do not mark the machine `Sylphie Verified`. Treat it as a real visual-control failure: `Hardware path regression or controller state issue`.

The sanity path must be `direct_v2_8101` only:

1. select `0x8020`, byte write `0x01`;
2. select `0x80A0`, byte write `0x01`;
3. select `0x8101`, block write length `3`, payload order `R G B`;
4. select `0x80A0`, byte write `0x01`.

Use the `Direct V2 raw test` buttons for off/blue/green/red/white and inspect `path_used`, `register_rgb`, `payload_hex`, `bus_status_before`, `bus_status_after`, `write_steps`, and `bus_write_ok`. If bus writes succeed but visual verification fails, keep normal RGB writes and scenes blocked. The experimental `Re-prime direct mode` button repeats only the same direct-on/apply/direct-v2/final-apply sequence; it does not introduce new registers.

If takeover execute makes no changes while tier1 and tier2 owners are already stopped, treat the environment as already clean, not as a failed no-op. Use `Claim clean ownership`, then run the direct sanity test. Do not show `Armoury core still running` unless a tier2 service is actually `Running`/has a PID or a tier2 helper process exists.

Logitech Download Assistant process storms are external diagnostic noise. They do not affect Armoury/Sylphie ownership. Use `Stop Logitech LampArray temporarily` to stop `logi_lamparray_service` and kill `logi_download_assistant*` without changing `StartupType`; use `Set Logitech LampArray to Manual` only as an explicit advanced action.

## Return To Armoury Flow

Use `Return to Armoury` after repairing Armoury, reinstalling addons, restoring Music mode, or deciding to give control back to ASUS software.

The flow:

- stops the Sylphie agent;
- optionally disables Sylphie autostart;
- restores services recorded in `.sylphie/takeover_state.json`;
- starts `LightingService`;
- launches Armoury if a known path exists;
- does not write SMBus.

The HTTP server remains non-elevated. Privileged work is launched through whitelisted scripts.

## Takeover For Sylphie Flow

Use `Takeover for Sylphie` only when you explicitly want Sylphie Mode.

The flow:

- stops `LightingService` first;
- stops `Aura Wallpaper Service` when present;
- waits for service release;
- terminates only whitelisted tier1 leftovers by default;
- does not stop `AsusCertService` by default;
- does not change service `StartupType`;
- starts the Sylphie agent manually, not through autostart;
- runs read-only doctor/bus-status checks;
- unlocks RGB controls only after full takeover resolves to `Sylphie Candidate`, and marks `Sylphie Verified` only after direct visual sanity confirmation.

## Armoury-Lite Recover

`recover-armoury-lite` is experimental. Use it only when the controller appears stuck/off, the confirmed direct RGB path is still unchanged, and normal `recover` did not rearm output.

Variant A has been observed to turn the LEDs off on this hardware, so do not assume `0x8023=0x11` is correct. `STUCKED.log` showed Armoury touching `0x80A0`, `0x8027`, `0x8020`, `0x8023`, `0x80F1`, and `0x8022`, but it did not capture a safe candidate payload. Prefer granular raw-register dry-runs and one-register manual tests before trying bundled Armoury-lite variants again.

Start with dry-runs:

```powershell
bin\sylphie_rgb.exe recover-armoury-lite --variant a --dry-run --verbose
bin\sylphie_rgb.exe recover-armoury-lite-set FFFFFF --variant a --dry-run --verbose
```

Granular experimental helpers:

```powershell
bin\sylphie_rgb.exe reg-byte 8020 01 --dry-run --verbose
bin\sylphie_rgb.exe reg-byte-apply 8020 01 --dry-run --verbose
bin\sylphie_rgb.exe reg-block3 8101 FFFFFF --dry-run --verbose
bin\sylphie_rgb.exe direct-rearm-minimal FFFFFF --dry-run --verbose
```

Actual raw register writes require:

```powershell
--i-accept-raw-register-write
```

`direct-rearm-minimal` only writes `0x8020=0x01`, applies, then uses the confirmed direct RGB path. It does not touch `0x8023`, `0x8027`, `0x80F1`, or `0x8022`.

Manual test order:

```powershell
bin\sylphie_rgb.exe recover-armoury-lite-set FFFFFF --variant a --verbose
bin\sylphie_rgb.exe recover-armoury-lite-set FFFFFF --variant b --verbose
bin\sylphie_rgb.exe recover-armoury-lite-set FFFFFF --variant c --verbose
```

The variants are based on observed Armoury recovery writes around `0x8027`, `0x8023`, `0x8020`, `0x80A0`, and optionally `0x80F1`. They do not use `0x8100`, `0x8160`, or streaming, and they do not change normal `set`, `off`, or `scene` behavior.

## LightingService Keeps Coming Back

Some ASUS components can restart helpers after they are stopped. Run:

```powershell
bin\sylphie_rgb.exe takeover --dry-run
```

If the dry-run shows only Tier 1 lighting components, execute takeover. If Armoury core helpers are involved, close Armoury Crate first. Then consider:

```powershell
bin\sylphie_rgb.exe takeover --execute --i-accept-stopping-lighting-services --include-armoury-core
```

Sylphie does not delete services, uninstall Armoury, or change service startup type.

## Correct Takeover Order

Do not kill Armoury helper processes before stopping `LightingService`. `LightingService` can recreate the helpers and reclaim the controller.

Correct order:

1. Stop `LightingService` first.
2. Wait for the service to stop.
3. Terminate only whitelisted leftover Armoury/Aura/OpenRGB processes.
4. Start or use the elevated Sylphie agent.
5. Run recover/rearm.
6. Set RGB.

The Control Center `Armoury Takeover` tab and agent takeover commands follow this order.

## Why The Server Is Not Elevated

The HTTP server binds to `127.0.0.1` and serves the dashboard/API. It should not run elevated because browser-facing HTTP code does not need direct SMBus or service-control privileges.

Privileged work belongs to `sylphie_agent.exe`, which runs elevated as a Scheduled Task and listens on a local named pipe. The server asks the agent for hardware writes, recovery, service status, and takeover operations.

## Capture Lab Notes

The Control Center `Capture Lab` can start broad or Armoury UI capture probes and records marker clicks in a sidecar marker log. The probes remain read-only: they use `Inp32`, never call `Out32`, and only read `SMBBLKDAT/+0x07` on block-write events when payload capture is enabled.

If you start capture after manually stopping the Armoury/Aura stack, select `Stack already stopped, start capture now` before pressing start. This records `STACK_ALREADY_STOPPED_AT_CAPTURE_START` and a service/process snapshot at capture start. In that mode, missing `SERVICE_STOPPED` is expected and does not mean the capture was performed incorrectly.

For fast Armoury rearm bursts, enable `High-rate ring buffer` in the panel. The probe minimizes sleeps, can raise priority, focuses on `ADDR=0x40` and registers `0x8000,0x8020,0x80A0,0x80F1,0x8022,0x8023`, and dumps recent snapshots around block writes. It still does not poll `SMBBLKDAT/+0x07`; payload reads remain limited to `CMD=0x03` block writes when payload capture is enabled.

If a capture does not start from the panel, confirm the probe exists:

```powershell
tools\probes\build_armoury_ui_capture.bat
src\native\sylphie_piix4_broad_capture\build.bat
```

## Full Armoury Cold-Start Capture

Use this when a simple `LightingService` restart does not recreate a clean Armoury/Aura initialization.

From an elevated PowerShell:

```powershell
.\scripts\capture_armoury_cold_start.ps1 -Mode gui-cold-launch
```

The script:

- starts the read-only Armoury UI probe with `--capture-block-payload`;
- stops Sylphie server/agent;
- stops `LightingService` first;
- waits for `LightingService` to stop;
- kills only whitelisted Armoury/Aura/OpenRGB leftover processes;
- never stops `AsusCertService` by default;
- does not change service startup type;
- does not delete services;
- writes raw logs to `research/captures/`;
- writes a sanitized summary to `docs/research/`.

The Control Center can launch this flow from Capture Lab, but it opens a separate elevated PowerShell window and the dashboard may disconnect because the script stops the Sylphie server.

To compare captures, use:

```powershell
python tools\analyze_capture.py research\captures\armoury_ui_YYYYMMDD_HHMMSS_master.log
```

The analyzer reports whether `0x8000 len=3` was observed, whether that block payload was captured, and the marker timeline around `CAPTURE_START`, `STACK_ALREADY_STOPPED_AT_CAPTURE_START`, `SERVICE_STARTED`, `ARMOURY_LAUNCHED`, `FIRST_LIGHT`, and `OK_CLICKED`.

For the stuck-red case, use `Capture Lab` -> `Capture stuck color transition`. Mark `RED_STUCK_STATE`, select green in Armoury, mark `COLOR_PICKER_CHANGED_GREEN`, mark `COLOR_VISUALLY_CHANGED` when the LED actually changes, click OK in Armoury, then mark `POPUP_OK_CLICKED`. Do not force an Apply marker. The analyzer reports block writes and watched byte writes between color picker change and visual change.

## When To Use Takeover

Use takeover when:

- `takeover-check` reports Armoury/Aura/OpenRGB conflicts.
- `/api/set` or the dashboard returns `controller conflict detected`.
- CLI writes work only after manually closing ASUS lighting tools.

Always start with:

```powershell
bin\sylphie_rgb.exe takeover --dry-run
```

## When To Use Restore Services

Use restore after a Sylphie takeover when you want ASUS/Aura services to control RGB again:

```powershell
bin\sylphie_rgb.exe restore-services
```

Restore only restarts services that Sylphie recorded in `.sylphie/takeover_state.json`. It does not recreate standalone processes such as a manually launched OpenRGB instance.

## Port 8765 Stuck

Inspect the saved PID and the real port owner:

```powershell
.\scripts\status_sylphie.ps1
```

Stop the Sylphie server:

```powershell
.\scripts\stop_sylphie.ps1
```

If the PID file is stale but the port owner is clearly the Sylphie server:

```powershell
.\scripts\stop_sylphie.ps1 -ForcePortOwner
```

If the port owner is not Sylphie, do not force-stop it from Sylphie scripts. Inspect the printed process name and command line first.

## When To Power Drain

Power drain is the last resort. Try it only after:

- Armoury/Aura/OpenRGB/LightingService are closed or stopped.
- `takeover-check` reports no known conflicts.
- `takeover --dry-run` shows no remaining whitelisted running candidates.
- `bus-status` can read the SMBus host.
- `recover --verbose` completed.
- `recover-set FF0000` completed but the strip still does not respond.

The confirmed direct RGB protocol remains `0x8101` with payload `R G B`. Do not switch back to `0x8100` or use the `0x8160` static/effect path as a recovery attempt.
