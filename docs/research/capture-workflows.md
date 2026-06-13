# Capture Workflows

Use the Control Center `Capture Lab` tab when possible. It starts probes with fixed whitelisted paths and writes logs under `research/captures/`.

## Armoury OK Popup Workflow

1. Stop the Sylphie agent/server if it owns the controller.
2. Open the Control Center and start `Armoury UI capture`.
3. Open Armoury.
4. Select a color in the Armoury color picker.
5. Click marker `MOUSE_COLOR_SELECTED`.
6. Click OK in Armoury.
7. Click marker `OK_CLICKED`.
8. Click Apply in Armoury if available.
9. Click marker `APPLY_CLICKED`.
10. Repeat with `WHITE`, `RED`, `GREEN`, and `BLUE`.
11. Stop capture.

## Service Rearm Workflow

1. Stop LightingService/Armoury.
2. Start `Armoury UI capture`.
3. Click marker `SERVICE_STOPPED`.
4. Start LightingService/Armoury.
5. Click marker `SERVICE_STARTED`.
6. When the LEDs return, click marker `FIRST_LIGHT`.
7. Apply red/white from Armoury and mark the color.
8. Stop capture.

If the Armoury/Aura stack was already stopped before the capture began, use the Control Center mode `Stack already stopped, start capture now`. This records `STACK_ALREADY_STOPPED_AT_CAPTURE_START` and writes a service/process snapshot at `CAPTURE_START`. In that mode, absence of `SERVICE_STOPPED` is expected and should not be treated as operator error.

Recommended panel sequence for this mode:

1. Stop the Armoury/Aura stack manually.
2. Open `Capture Lab`.
3. Select `Stack already stopped, start capture now`.
4. Keep `High-rate ring buffer` enabled.
5. Start `Armoury UI capture`.
6. Click `Start LightingService / Launch Armoury`.
7. Mark `FIRST_LIGHT` when the LEDs return.
8. Apply `WHITE` and `RED` in Armoury and mark each action.
9. Stop capture.
10. Run `Analyze latest capture`.

## Full Armoury Cold-Start Workflow

Use this workflow to capture the rearm sequence that may include `0x8000` block writes.

Preferred command:

```powershell
.\scripts\capture_armoury_cold_start.ps1 -Mode gui-cold-launch
```

Alternative service-only mode:

```powershell
.\scripts\capture_armoury_cold_start.ps1 -Mode service-only
```

The script starts capture before stopping the Armoury/Aura stack. It stops `LightingService` first, waits for it to stop, kills only whitelisted leftover processes, and then launches Armoury or starts `LightingService`. Raw captures stay in `research/captures/`; the script writes a sanitized summary to `docs/research/`.

Markers to produce during the flow:

- `STACK_STOP_BEGIN`
- `SERVICE_STOPPED`
- `STACK_STOPPED`
- `ARMOURY_LAUNCHED` or `SERVICE_STARTED`
- `UAC_ACCEPTED_BY_USER` when applicable
- `FIRST_LIGHT`
- `WHITE_SELECTED`
- `RED_SELECTED`

Inspect the summary for:

- reads `CMD=0x81` / `CMD=0x90`;
- `select_register 0x8000`;
- `block_write last_selected_register=0x8000 len=3`;
- payload reads from that block write;
- writes around `0x8000`, `0x80A0`, `0x80F1`, `0x8023`, and `0x8022`.

## High-Rate / Ring Buffer Capture

The Armoury UI probe supports:

```powershell
bin\sylphie_piix4_armoury_ui_capture.exe --base 0B20 --capture-block-payload --high-rate --priority-high --focus-addr 40 --focus-registers 8000,8020,80A0,80F1,8022,8023 --output research\captures\manual_master.log
```

`--high-rate` minimizes sleep time and keeps a ring buffer of recent snapshots. When the probe sees a block write or a focus register such as `0x8000`, it dumps the preceding snapshots into the log. This helps diagnose short Armoury bursts that may otherwise be missed.

The probe still does not read `SMBBLKDAT/+0x07` continuously. With `--capture-block-payload`, it reads `+0x07` only for eligible `ADDR=0x40 W CMD=0x03` block write events.

## Capture Analyzer

Use the Control Center `Analyze latest capture` button, or run:

```powershell
python tools\analyze_capture.py research\captures\armoury_ui_YYYYMMDD_HHMMSS_master.log
```

The analyzer reports selected registers, block writes, captured payloads, marker timeline, and whether `0x8000 len=3` was observed and had payload bytes captured.

## RED_STUCK_TO_GREEN_CAPTURE Workflow

Use this when the LEDs are visually stuck red and Armoury can change them to green. The goal is to capture only the transition that unsticks the controller.

Panel flow:

1. Open `Capture Lab`.
2. Keep `High-rate ring buffer` enabled.
3. Click `Capture stuck color transition`.
4. Click marker `RED_STUCK_STATE`.
5. In Armoury, select green in the color picker.
6. Click marker `COLOR_PICKER_CHANGED_GREEN`.
7. When the LEDs actually change, click marker `COLOR_VISUALLY_CHANGED`.
8. Click OK in the Armoury popup.
9. Click marker `POPUP_OK_CLICKED`.
10. Stop capture.
11. Click `Analyze latest capture`.

The analyzer reports:

- block writes between `RED_STUCK_STATE` and `COLOR_VISUALLY_CHANGED`;
- selected register and payload for each block write in that window;
- byte writes to `0x80F1`, `0x8020`, `0x8023`, and `0x80A0` in that same window.

This workflow is read-only from Sylphie's side. Armoury is the actor changing the LEDs.
Do not force an `APPLY_CLICKED` marker for this workflow. On this Armoury UI, selecting the color can change the LEDs before OK; OK may only close or commit the popup.

When comparing captures, treat these as different flows:

- `SERVICE_STOPPED` present: capture included a stop operation after the probe started.
- `STACK_ALREADY_STOPPED_AT_CAPTURE_START` present: stack was already stopped before capture, so missing `SERVICE_STOPPED` is normal.
- no stop markers: manual research mode, interpret only against user notes and action markers.

## Static Color Workflow

1. Start `Armoury UI capture`.
2. In Armoury, switch to the fixed/static color mode.
3. Click marker `OTHER` or `FIXED_MODE_SELECTED` if using the console probe.
4. Apply white, red, green, and blue.
5. Use markers for each color immediately after the UI action.
6. Stop capture and inspect payloads around the marker times.

## Marker Guidance

Press or click the marker immediately after the UI action. The capture log is continuous, and marker timing is the anchor for correlating Armoury SMBus traffic with UI behavior.

The confirmed Sylphie direct RGB protocol remains unchanged: register `0x8101`, payload order `R G B`.
