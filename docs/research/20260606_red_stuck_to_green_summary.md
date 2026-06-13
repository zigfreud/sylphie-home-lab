# RED_STUCK_TO_GREEN Capture Summary

Raw captures remain local under `research/captures/` and are not committed.

## Timeline

- RED_STUCK_STATE: 2026-06-06 13:44:30.000, 2026-06-06 13:45:04.000
- COLOR_PICKER_CHANGED_GREEN: 2026-06-06 13:51:41.000
- MOUSE_COLOR_SELECTED_GREEN: not observed
- COLOR_VISUALLY_CHANGED: not observed
- POPUP_OK_CLICKED: not observed

## Analysis Windows

### 10s_before_color_picker_changed_green

- start: `2026-06-06 13:51:31.000`
- end: `2026-06-06 13:51:41.000`

Block writes:
- none

Watched byte writes:
- none

Reads CMD=0x81/0x90:
- none

## All Block Writes CMD=0x03

- none

## All Watched Byte Writes

- none

## Reads CMD=0x81 / CMD=0x90

- none

## Selected Register History

- none

## Immediately Before COLOR_VISUALLY_CHANGED

Block writes:
- none

Watched byte writes:
- none

## Comparison

Known good direct path:
- `0x8020=0x01`
- `0x80A0=0x01`
- `block 0x8101 RGB payload R G B`
- `0x80A0=0x01`

Known Armoury UI RGB path:
- `0x80F1 block payload RGB was observed in prior UI capture`

## Conclusion

Candidate transition block writes:
- none

Candidate mode/commit byte writes:
- none

- recommended next microtest: Repeat RED_STUCK_TO_GREEN_CAPTURE; markers or transition writes are insufficient.
- do not implement recover-full yet: true
