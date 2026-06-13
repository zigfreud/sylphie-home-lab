# Armoury Cold-Start Capture Summary - 20260606

Raw captures remain local under `research/captures/` and are not committed.

## Run

- timestamp: `20260606_063623`
- mode: `gui-cold-launch`
- uac_observed: unknown
- master_log: `C:\Users\kizin\Development\sylphie-home-lab\research\captures\armoury_cold_start_20260606_063623_master.log`
- marker_log: `C:\Users\kizin\Development\sylphie-home-lab\research\captures\armoury_cold_start_20260606_063623_markers.log`

## Stack Stop

- stopped_services: none
- terminated_processes: ArmouryCrate.UserSessionHelper.exe pid=17624
- AsusCertService: warning-only, not stopped by this script

## Markers

- `2026-06-06 06:36:44.335 MARKER CAPTURE_STARTED note=pid=9680`
- `2026-06-06 06:36:48.895 MARKER STACK_STOP_BEGIN`
- `2026-06-06 06:36:49.887 MARKER SERVICE_STOPPED note=FULL_STACK_STOPPED_LIGHTINGSERVICE`
- `2026-06-06 06:36:57.972 MARKER STACK_STOPPED note=FULL_STACK_STOPPED`
- `2026-06-06 06:37:23.778 MARKER UAC_ACCEPTED_BY_USER note=manual_confirmation`
- `2026-06-06 06:37:23.782 MARKER ARMOURY_LAUNCHED`
- `2026-06-06 06:37:27.187 MARKER FIRST_LIGHT`
- `2026-06-06 06:37:44.151 MARKER WHITE_SELECTED`
- `2026-06-06 06:37:50.838 MARKER MOUSE_COLOR_SELECTED note=white_if_applicable`
- `2026-06-06 06:37:55.598 MARKER OK_CLICKED note=white_if_applicable`
- `2026-06-06 06:37:58.193 MARKER APPLY_CLICKED note=white_if_applicable`
- `2026-06-06 06:38:06.623 MARKER RED_SELECTED`
- `2026-06-06 06:38:11.126 MARKER MOUSE_COLOR_SELECTED note=red_if_applicable`
- `2026-06-06 06:38:13.380 MARKER OK_CLICKED note=red_if_applicable`
- `2026-06-06 06:38:14.719 MARKER APPLY_CLICKED note=red_if_applicable`
- `2026-06-06 06:38:44.339 MARKER CAPTURE_STOPPED note=exit_code=0`

## Relevant SMBus Events

- `  AURA read CMD=0x81 STS=0x00 CNT=0x08 D0=0x80 D1=0xC1`
- `  AURA read CMD=0x81 STS=0x01 CNT=0x08 D0=0x80 D1=0xC1`
- `  AURA read CMD=0x81 STS=0x00 CNT=0x08 D0=0x01 D1=0xC1`
- `  AURA read CMD=0x81 STS=0x01 CNT=0x08 D0=0x80 D1=0xAA`
- `  AURA read CMD=0x81 STS=0x00 CNT=0x08 D0=0xFF D1=0xAA`
- `  AURA read CMD=0x81 STS=0x01 CNT=0x08 D0=0x80 D1=0xC1`
- `  AURA read CMD=0x81 STS=0x81 CNT=0x08 D0=0x01 D1=0xC1`
- `  AURA read CMD=0x81 STS=0x00 CNT=0x08 D0=0x01 D1=0xC1`
- `  AURA read CMD=0x81 STS=0x00 CNT=0xA0 D0=0x80 D1=0xC8`
- `  AURA read CMD=0x81 STS=0x01 CNT=0x08 D0=0x80 D1=0xC8`
- `  AURA read CMD=0x90 STS=0x00 CNT=0x14 D0=0x10 D1=0x00`
- `  AURA byte_write value=0x01 last_selected_register=0x80A0 d1_hint_register=0x80A0 confidence=selected`
- `  AURA byte_write value=0xAA last_selected_register=0x80A0 d1_hint_register=0x80A0 confidence=selected`
- `  AURA block_write last_selected_register=0x80B0 len=3 recent_selects=[0x80AA,0x80AA,0x80C1,0x80D0,0x8020,0x80A0,0x8025,0x80B0] payload_reads=00 00 00 [extra=41] confidence=selected`
- `  AURA block_write last_selected_register=0x80B0 len=3 recent_selects=[0x80AA,0x80AA,0x80C1,0x80D0,0x8020,0x80A0,0x8025,0x80B0] payload_reads=25 3D 50 [extra=41] confidence=selected`
- `  AURA byte_write value=0x30 last_selected_register=0x8022 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x01 last_selected_register=0x8020 d1_hint_register=0x80F1 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8022 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8022 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8023 d1_hint_register=0x8023 confidence=selected`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA block_write last_selected_register=0x8020 len=3 recent_selects=[0x8022,0x8020,0x8022,0x8020,0x8020,0x8023,0x8020,0x8020] payload_reads=FF FF FF [extra=41] confidence=selected`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA read CMD=0x81 STS=0x00 CNT=0x08 D0=0x80 D1=0xC1`
- `  AURA read CMD=0x81 STS=0x01 CNT=0x08 D0=0x80 D1=0xC1`
- `  AURA read CMD=0x81 STS=0x00 CNT=0x08 D0=0x01 D1=0xC1`
- `  AURA read CMD=0x81 STS=0x01 CNT=0x08 D0=0x80 D1=0xAA`
- `  AURA read CMD=0x81 STS=0x00 CNT=0x08 D0=0xFF D1=0xAA`
- `  AURA read CMD=0x81 STS=0x00 CNT=0x08 D0=0x80 D1=0xC1`
- `  AURA read CMD=0x81 STS=0x00 CNT=0x08 D0=0x01 D1=0xC1`
- `  AURA read CMD=0x81 STS=0x01 CNT=0x08 D0=0x80 D1=0xC8`
- `  AURA read CMD=0x81 STS=0x01 CNT=0x08 D0=0x80 D1=0xE0`
- `  AURA read CMD=0x90 STS=0x00 CNT=0x14 D0=0x10 D1=0x00`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  AURA byte_write value=0x30 last_selected_register=0x8020 d1_hint_register=0x8023 confidence=ambiguous`
- `  0x80B0 payload_reads=00 00 00 [extra=41]`
- `  0x80B0 payload_reads=25 3D 50 [extra=41]`
- `  0x8020 payload_reads=FF FF FF [extra=41]`

## Payloads

- `  AURA block_write last_selected_register=0x80B0 len=3 recent_selects=[0x80AA,0x80AA,0x80C1,0x80D0,0x8020,0x80A0,0x8025,0x80B0] payload_reads=00 00 00 [extra=41] confidence=selected`
- `  AURA block_write last_selected_register=0x80B0 len=3 recent_selects=[0x80AA,0x80AA,0x80C1,0x80D0,0x8020,0x80A0,0x8025,0x80B0] payload_reads=25 3D 50 [extra=41] confidence=selected`
- `  AURA block_write last_selected_register=0x8020 len=3 recent_selects=[0x8022,0x8020,0x8022,0x8020,0x8020,0x8023,0x8020,0x8020] payload_reads=FF FF FF [extra=41] confidence=selected`
- `  0x80B0 payload_reads=00 00 00 [extra=41]`
- `  0x80B0 payload_reads=25 3D 50 [extra=41]`
- `  0x8020 payload_reads=FF FF FF [extra=41]`

## 0x8000 Result

- `block_write last_selected_register=0x8000 len=3` was not captured in this run.

## Recover-Full Hypothesis

- Do not alter normal RGB writes: `0x8101`, payload `R G B`.
- Avoid `0x8100` and `0x8160`.
- Use captured service rearm events only after the `0x8000 len=3` payload is confirmed.
- Candidate rearm registers remain `0x8000`, `0x80A0`, `0x80F1`, `0x8023`, and `0x8022`.
