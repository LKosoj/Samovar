# Step 2.6b Build Matrix Results

## Scope

- Date: `2026-03-16`
- Task: `Step 2.6b: Build matrix verification`
- Constraint: `no code changes, only build verification and result фиксация`
- Environments checked: `Samovar`, `lua_expander`, `Samovar_s3`

## Summary

| Environment | Result | Duration | Flash | RAM | Log |
| --- | --- | --- | --- | --- | --- |
| `Samovar` | `SUCCESS` | `00:00:27.700` | `70.1% (1148545 bytes / 1638400 bytes)` | `18.3% (59904 bytes / 327680 bytes)` | `/tmp/build_matrix_samovar.log` |
| `lua_expander` | `SUCCESS` | `00:00:21.506` | `70.1% (1148545 bytes / 1638400 bytes)` | `18.3% (59904 bytes / 327680 bytes)` | `/tmp/build_matrix_lua_expander.log` |
| `Samovar_s3` | `SUCCESS` | `00:00:25.655` | `67.2% (1100905 bytes / 1638400 bytes)` | `18.2% (59752 bytes / 327680 bytes)` | `/tmp/build_matrix_samovar_s3.log` |

## 1. Samovar

- Command: `pio run -e Samovar`
- Result: `SUCCESS`
- Duration: `00:00:27.700`
- Flash: `70.1% (1148545 bytes / 1638400 bytes)`
- RAM: `18.3% (59904 bytes / 327680 bytes)`

### Raw excerpt

```text
Retrieving maximum program size .pio/build/Samovar/firmware.elf
Checking size .pio/build/Samovar/firmware.elf
Advanced Memory Usage is available via "PlatformIO Home > Project Inspect"
RAM:   [==        ]  18.3% (used 59904 bytes from 327680 bytes)
Flash: [=======   ]  70.1% (used 1148545 bytes from 1638400 bytes)
Building .pio/build/Samovar/firmware.bin
esptool.py v4.9.0
Creating esp32 image...
Merged 27 ELF sections
Successfully created esp32 image.
========================= [SUCCESS] Took 27.70 seconds =========================

Environment    Status    Duration
-------------  --------  ------------
Samovar        SUCCESS   00:00:27.700
========================= 1 succeeded in 00:00:27.700 =========================
```

## 2. lua_expander

- Command: `pio run -e lua_expander`
- Result: `SUCCESS`
- Duration: `00:00:21.506`
- Flash: `70.1% (1148545 bytes / 1638400 bytes)`
- RAM: `18.3% (59904 bytes / 327680 bytes)`

### Raw excerpt

```text
Retrieving maximum program size .pio/build/lua_expander/firmware.elf
Checking size .pio/build/lua_expander/firmware.elf
Advanced Memory Usage is available via "PlatformIO Home > Project Inspect"
RAM:   [==        ]  18.3% (used 59904 bytes from 327680 bytes)
Flash: [=======   ]  70.1% (used 1148545 bytes from 1638400 bytes)
Building .pio/build/lua_expander/firmware.bin
esptool.py v4.9.0
Creating esp32 image...
Merged 27 ELF sections
Successfully created esp32 image.
========================= [SUCCESS] Took 21.51 seconds =========================

Environment    Status    Duration
-------------  --------  ------------
lua_expander   SUCCESS   00:00:21.506
========================= 1 succeeded in 00:00:21.506 =========================
```

## 3. Samovar_s3

- Command: `pio run -e Samovar_s3`
- Result: `SUCCESS`
- Duration: `00:00:25.655`
- Flash: `67.2% (1100905 bytes / 1638400 bytes)`
- RAM: `18.2% (59752 bytes / 327680 bytes)`

### Raw excerpt

```text
Retrieving maximum program size .pio/build/Samovar_s3/firmware.elf
Checking size .pio/build/Samovar_s3/firmware.elf
Advanced Memory Usage is available via "PlatformIO Home > Project Inspect"
RAM:   [==        ]  18.2% (used 59752 bytes from 327680 bytes)
Flash: [=======   ]  67.2% (used 1100905 bytes from 1638400 bytes)
Building .pio/build/Samovar_s3/firmware.bin
esptool.py v4.9.0
Creating esp32s3 image...
Merged 2 ELF sections
Successfully created esp32s3 image.
========================= [SUCCESS] Took 25.65 seconds =========================

Environment    Status    Duration
-------------  --------  ------------
Samovar_s3     SUCCESS   00:00:25.655
========================= 1 succeeded in 00:00:25.655 =========================
```

## Acceptance Criteria Verification

| Criterion | Status | Evidence |
| --- | --- | --- |
| `pio run -e Samovar: SUCCESS` | `Done` | Build log `/tmp/build_matrix_samovar.log`, duration `00:00:27.700`, Flash `70.1% (1148545 bytes / 1638400 bytes)`, RAM `18.3% (59904 bytes / 327680 bytes)` |
| `pio run -e lua_expander: SUCCESS` | `Done` | Build log `/tmp/build_matrix_lua_expander.log`, duration `00:00:21.506`, Flash `70.1% (1148545 bytes / 1638400 bytes)`, RAM `18.3% (59904 bytes / 327680 bytes)` |
| `pio run -e Samovar_s3: SUCCESS` | `Done` | Build log `/tmp/build_matrix_samovar_s3.log`, duration `00:00:25.655`, Flash `67.2% (1100905 bytes / 1638400 bytes)`, RAM `18.2% (59752 bytes / 327680 bytes)` |
| Results documented in `docs/result/delivery/build_matrix_results.md` | `Done` | This document contains the current-session build summary and raw excerpts for all three environments |

