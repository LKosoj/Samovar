# Step 2.6b Build Matrix Results

## Scope

- Date: `2026-03-16`
- Task: `Step 2.6b: Build matrix verification`
- Constraint: no code changes, only build verification and result фиксация
- Environments checked: `Samovar`, `lua_expander`, `Samovar_s3`

## Summary

| Environment | Result | Duration | Flash | RAM | Log |
| --- | --- | --- | --- | --- | --- |
| `Samovar` | `SUCCESS` | `00:00:20.012` | `70.1% (1148545 / 1638400 bytes)` | `18.3% (59904 / 327680 bytes)` | `/tmp/build_matrix_samovar.log` |
| `lua_expander` | `SUCCESS` | `00:00:21.775` | `70.1% (1148545 / 1638400 bytes)` | `18.3% (59904 / 327680 bytes)` | `/tmp/build_matrix_lua_expander.log` |
| `Samovar_s3` | `SUCCESS` | `00:00:19.783` | `67.2% (1100905 / 1638400 bytes)` | `18.2% (59752 / 327680 bytes)` | `/tmp/build_matrix_samovar_s3.log` |

## 1. Samovar

- Command: `pio run -e Samovar`
- Result: `SUCCESS`
- Duration: `00:00:20.012`
- Flash: `70.1% (1148545 / 1638400 bytes)`
- RAM: `18.3% (59904 / 327680 bytes)`

### Raw excerpt

```text
Building in release mode
Compiling .pio/build/Samovar/src/Samovar.ino.cpp.o
In file included from /srv/git_projects/Samovar/Samovar.ino:84:
crash_handler.h:35:17: note: #pragma message: USE_CRASH_HANDLER is DISABLED
 #pragma message "USE_CRASH_HANDLER is DISABLED"
                 ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Linking .pio/build/Samovar/firmware.elf
...
Successfully created esp32 image.
========================= [SUCCESS] Took 20.01 seconds =========================

Environment    Status    Duration
-------------  --------  ------------
Samovar        SUCCESS   00:00:20.012
========================= 1 succeeded in 00:00:20.012 =========================
```

## 2. lua_expander

- Command: `pio run -e lua_expander`
- Result: `SUCCESS`
- Duration: `00:00:21.775`
- Flash: `70.1% (1148545 / 1638400 bytes)`
- RAM: `18.3% (59904 / 327680 bytes)`

### Raw excerpt

```text
Building in release mode
Compiling .pio/build/lua_expander/src/Samovar.ino.cpp.o
In file included from /srv/git_projects/Samovar/Samovar.ino:84:
crash_handler.h:35:17: note: #pragma message: USE_CRASH_HANDLER is DISABLED
 #pragma message "USE_CRASH_HANDLER is DISABLED"
                 ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Linking .pio/build/lua_expander/firmware.elf
...
Successfully created esp32 image.
========================= [SUCCESS] Took 21.78 seconds =========================

Environment    Status    Duration
-------------  --------  ------------
lua_expander   SUCCESS   00:00:21.775
========================= 1 succeeded in 00:00:21.775 =========================
```

## 3. Samovar_s3

- Command: `pio run -e Samovar_s3`
- Result: `SUCCESS`
- Duration: `00:00:19.783`
- Flash: `67.2% (1100905 / 1638400 bytes)`
- RAM: `18.2% (59752 / 327680 bytes)`

### Raw excerpt

```text
Building in release mode
Compiling .pio/build/Samovar_s3/src/Samovar.ino.cpp.o
In file included from /srv/git_projects/Samovar/Samovar.ino:84:
crash_handler.h:35:17: note: #pragma message: USE_CRASH_HANDLER is DISABLED
 #pragma message "USE_CRASH_HANDLER is DISABLED"
                 ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Linking .pio/build/Samovar_s3/firmware.elf
...
Successfully created esp32s3 image.
========================= [SUCCESS] Took 19.78 seconds =========================

Environment    Status    Duration
-------------  --------  ------------
Samovar_s3     SUCCESS   00:00:19.783
========================= 1 succeeded in 00:00:19.783 =========================
```

## Acceptance Criteria Verification

| Criterion | Status | Evidence |
| --- | --- | --- |
| `pio run -e Samovar: SUCCESS` | ✅ Done | Build log `/tmp/build_matrix_samovar.log`, duration `00:00:20.012`, Flash `70.1%`, RAM `18.3%` |
| `pio run -e lua_expander: SUCCESS` | ✅ Done | Build log `/tmp/build_matrix_lua_expander.log`, duration `00:00:21.775`, Flash `70.1%`, RAM `18.3%` |
| `pio run -e Samovar_s3: SUCCESS` | ✅ Done | Build log `/tmp/build_matrix_samovar_s3.log`, duration `00:00:19.783`, Flash `67.2%`, RAM `18.2%` |
| Results documented in `docs/result/delivery/build_matrix_results.md` | ✅ Done | This document created with full build details for all three environments |

## Conclusion

All three build environments passed successfully:
- **Samovar**: Standard ESP32 build - no issues
- **lua_expander**: ESP32 with Lua support - no issues
- **Samovar_s3**: ESP32-S3 variant - no issues

The codebase is stable across all target platforms. No build errors detected.

---

**Next Step:** Proceed to t20_6c_closure_report (Step 2.6c: Final closure report)
