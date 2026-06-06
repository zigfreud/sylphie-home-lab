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
