# Sylphie Home Lab

Native Windows CLI backend for controlling ASUS Aura/ENE RGB header on ASUS PRIME B450M-GAMING/BR.

## Safety

This project uses low-level SMBus and I/O port access. Use at your own risk. Do not run hardware write commands while ASUS Armoury Crate, Aura, LightingService, or another RGB controller is using the same SMBus device.

## Tested Hardware

- ASUS PRIME B450M-GAMING/BR
- ENE/Aura AUMA0-E8K4-0101
- RGB header 12V analog

## Commands

```bat
sylphie_rgb.exe doctor
sylphie_rgb.exe set FF0000
sylphie_rgb.exe set 00FF00
sylphie_rgb.exe set 0000FF
sylphie_rgb.exe off
```

Planned higher-level scene command:

```bat
sylphie_rgb.exe scene focus
```

Use `--dry-run` with `set` or `off` to print the SMBus sequence without writing to hardware.

## Build

Build from the x86 Native Tools Command Prompt for Visual Studio 2019:

```bat
src\native\sylphie_rgb\build.bat
```

The executable is written to `bin\sylphie_rgb.exe`.

## Runtime Dependency

`inpout32.dll` is required next to the executable but is not committed to the repository.

## Protocol Notes

The confirmed protocol for the current MVP is documented in `docs/protocol/asus-prime-b450m-aura-smbus.md`.
