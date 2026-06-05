# ASUS PRIME B450M-GAMING/BR Aura SMBus Protocol

## Hardware Target

- Motherboard: ASUS PRIME B450M-GAMING/BR
- RGB output: 12V RGB header
- Controller family: AUMA0-E8K4-0101
- SMBus host base: `0x0B20`
- Aura/ENE SMBus 7-bit address: `0x40`
- Build/runtime target: Windows x86 with `inpout32.dll` / InpOut32

OpenRGB/OpenAuraSDK were used only for reverse engineering. The Sylphie runtime must use its own native implementation.

## Discovered Constants

- Direct mode register: `0x8020`
- Apply register: `0x80A0`
- RGB direct register: `0x8101`
- RGB payload order: `R G B`

## Final Working Sequence

1. Select direct mode register `0x8020`
   - SMBus `WORD_DATA` to address `0x40`
   - `CMD=0x00`
   - `D0=0x80`
   - `D1=0x20`
2. Enable direct mode
   - SMBus `BYTE_DATA`
   - `CMD=0x01`
   - `D0=0x01`
3. Select apply register `0x80A0`
   - SMBus `WORD_DATA`
   - `CMD=0x00`
   - `D0=0x80`
   - `D1=0xA0`
4. Apply
   - SMBus `BYTE_DATA`
   - `CMD=0x01`
   - `D0=0x01`
5. Select RGB direct register `0x8101`
   - SMBus `WORD_DATA`
   - `CMD=0x00`
   - `D0=0x81`
   - `D1=0x01`
6. Write direct RGB payload
   - SMBus `BLOCK_DATA`
   - `CMD=0x03`
   - `length=0x03`
   - `payload=R G B`
7. Select apply register `0x80A0` again
8. Apply again
   - SMBus `BYTE_DATA`
   - `CMD=0x01`
   - `D0=0x01`

Verified visual results:

- `808080`: stable gray/white
- `FF0000`: red
- `00FF00`: green
- `0000FF`: blue

Low RGB values may be below the visible threshold for the connected 12V analog strip or room lighting. Scenes such as `movie` and `night` should use calibrated low-but-visible values rather than extremely small channel values.

## Known Bad Or Unstable Paths

- `0x8100` was one byte early and produced incorrect behavior. `0x8101` is the correct direct RGB register for the confirmed MVP path.
- `0x8160` static/effect path is not part of the MVP.
- Stream/probe tools are research only and must not become the public API.
- Experimental raw-block/probe code should not be used as runtime surface.

## Safety Notes

- Do not run Sylphie RGB hardware writes alongside ASUS Armoury Crate, Aura, or `LightingService`.
- The initial CLI only reports conflicting ASUS processes; it does not kill or stop services.
- `doctor` must perform reads only and must not touch `SMBBLKDAT` / offset `+0x07`.
- `off` writes direct RGB `000000`; it does not use mode-off registers.
- `bus-status` and `takeover-check` are read-only diagnostics.
- `recover` is a conservative software recovery path: it clears status, toggles direct mode through `0x8020`, applies with `0x80A0`, writes direct RGB `000000` through `0x8101`, and does not use `0x8160` or streaming.
