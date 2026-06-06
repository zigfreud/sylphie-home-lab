# Armoury Rearm Capture - 2026-06-06

This is a sanitized summary of a local `sylphie_piix4_armoury_ui_capture` run. Raw capture logs remain local under `research/captures/` and are not committed.

## Capture Setup

- Probe: `sylphie_piix4_armoury_ui_capture`
- SMBus base: `0x0B20`
- Payload capture: enabled
- Segment logs: enabled
- Safe continuous offsets only; `SMBBLKDAT/+0x07` was read only on `ADDR=0x40 W CMD=0x03` block events.

## Markers

- `SERVICE_STOPPED`
- `SERVICE_STARTED`
- `FIRST_LIGHT`
- `WHITE_SELECTED`
- `FIXED_MODE_SELECTED`
- `QUIT`

`SERVICE_STOPPED` and `SERVICE_STARTED` were very close together in this run, so service rearm timing should be recaptured with more separation.

## Observed Sequence

Around `FIRST_LIGHT`:

- `AURA select_register 0x80E0`
- `AURA read CMD=0x90`
- byte write with `last_selected_register=0x80E0`, `d1_hint_register=0x80A0`, `confidence=ambiguous`
- `AURA select_register 0x80A0`
- byte write with `last_selected_register=0x80A0`, `d1_hint_register=0x8020`, `confidence=ambiguous`
- `AURA select_register 0x80F1`
- repeated byte writes where `D1` hints at `0x8023` and `0x8022`

Around `WHITE_SELECTED`:

- byte writes with `last_selected_register=0x80F1`, hints `0x8022` and `0x8023`
- byte write `value=0x01`, `last_selected_register=0x80F1`, `d1_hint_register=0x80F1`, `confidence=selected`
- `AURA block_write last_selected_register=0x80F1 len=3 payload_reads=FF 00 00 [extra=41] confidence=selected`

## Payloads

Captured block payload:

- selected register: `0x80F1`
- length: `0x03`
- payload bytes: `FF 00 00`
- extra FIFO read: `0x41`

No `AURA block_write selected_register=0x8000 len=0x03` event was captured in this run.

## Interpretation

The captured `FF 00 00` confirms that Armoury can emit the same RGB byte order as Sylphie's confirmed direct RGB path. However, this run does not prove the rearm payload for `0x8000`.

The `0x80F1` attribution may still need care because earlier byte writes show ambiguous `D1` hints for `0x8022` and `0x8023`. The block event itself occurred after a selected-register state of `0x80F1`.

## Recover-Full Hypothesis

Do not implement `recover-full` from this capture alone. Current safe hypothesis:

- Keep normal RGB writes unchanged: register `0x8101`, payload order `R G B`.
- Continue using conservative `recover` as the default software recovery.
- Recapture service rearm with clearer timing to find the missing `0x8000 len=3` block payload.
- Candidate rearm state remains around `0x80E0`, `0x80A0`, `0x8020`, `0x80F1`, `0x8022`, and `0x8023`.
- Avoid `0x8100` and `0x8160`.

## Next Capture

Recommended next run:

1. Start capture before stopping services.
2. Mark `SERVICE_STOPPED` only after `LightingService` is confirmed stopped.
3. Start `LightingService`.
4. Mark `SERVICE_STARTED` immediately after start command returns.
5. Mark `FIRST_LIGHT` when LEDs visibly return.
6. Avoid applying colors until after `FIRST_LIGHT` is marked.
7. Then apply `WHITE`, `RED`, `GREEN`, and `BLUE` with markers.
