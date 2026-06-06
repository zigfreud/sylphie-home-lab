# Armoury UI Capture

This probe is read-only. It uses `Inp32` only, never calls `Out32`, and does not read `SMBBLKDAT/+0x07` continuously.

The script `scripts/capture_armoury_ui.ps1` runs the probe with `--capture-block-payload` by default so block payloads are captured only on `ADDR=0x40 W CMD=0x03` events.

## Build

From an x86 Visual Studio developer shell:

```bat
tools\probes\build_armoury_ui_capture.bat
```

## Run

```powershell
.\scripts\capture_armoury_ui.ps1
```

Logs are written under `research/captures/` with timestamped names.

## Flow A - OK Popup

1. Stop the Sylphie agent/server.
2. Start `.\scripts\capture_armoury_ui.ps1`.
3. Open Armoury.
4. Select a color in the color picker with the mouse.
5. Press `m` in the probe.
6. Click OK in the popup.
7. Press `o` immediately in the probe.
8. Click Apply if Armoury shows it.
9. Press `a` in the probe.
10. Repeat for white, red, and blue using `w`, `r`, and `b`.
11. Press `q` to quit.

## Flow B - Service Rearm

1. Stop LightingService/Armoury.
2. Start the probe.
3. Press `1`.
4. Start LightingService/Armoury.
5. Press `2`.
6. When lights return, press `3`.
7. Apply red/white from Armoury and mark with `r`/`w`.
8. Press `q` to quit.

## Decoder Notes

The decoder highlights Aura traffic at `ADDR7=0x40`.

- `CMD=0x00` is decoded as `AURA select_register 0xXXXX`.
- `CMD=0x01` is decoded as a byte write with both `last_selected_register` and a possible `d1_hint_register`.
- If the D1 hint does not match the last selected register, the event is marked `confidence=ambiguous`.
- `CMD=0x03` is decoded as block write and shows `payload_reads` when payload capture is enabled.

The normal Sylphie RGB protocol remains unchanged: RGB direct writes use register `0x8101` with payload order `R G B`.
