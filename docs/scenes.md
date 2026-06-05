# Sylphie RGB Scenes

Scenes are local CLI presets. They all use the confirmed direct RGB path:

- SMBus base: `0x0B20`
- Aura/ENE addr7: `0x40`
- Direct mode register: `0x8020`
- Apply register: `0x80A0`
- RGB direct register: `0x8101`
- Payload order: `R G B`

## Scene Table

| Scene | RGB | Intended visual effect |
| --- | --- | --- |
| `focus` | `FFFFFF` | Strong neutral white |
| `movie` | `202060` | Visible dark blue-purple bias light |
| `night` | `300000` | Low red above visibility threshold |
| `reading` | `FFC080` | Warm reading light |
| `cyberpunk` | `FF0080` | Magenta accent |
| `deepblue` | `0000FF` | Full blue |
| `red` | `FF0000` | Full red |
| `green` | `00FF00` | Full green |
| `blue` | `0000FF` | Full blue |
| `white` | `FFFFFF` | Full white |
| `off` | `000000` | Direct RGB off |

## Calibration

Use:

```bat
sylphie_rgb.exe calibrate --dry-run
```

The command prints a manual calibration sequence and does not write hardware in dry-run mode. Low values can be imperceptible on some 12V analog strips, so `movie` and `night` are intentionally above the first visible threshold observed during early testing.
