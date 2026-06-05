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
