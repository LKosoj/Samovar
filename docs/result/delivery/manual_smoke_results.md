# Step 2.6d Manual Smoke Results

## Status

- Date: `2026-03-16`
- Task: `Step 2.6d: Ручной smoke-тест на железе`
- Result: `BLOCKED`
- Reason: в текущей среде не обнаружено доступного ESP32/USB-устройства и не предоставлен адрес web UI для ручной проверки на железе.

## Environment Check

### 1. PlatformIO device list

Command:

```text
python3 -m platformio device list
```

Observed result:

```text
/dev/ttyS31 ... Hardware ID: n/a ... Description: n/a
/dev/ttyS30 ... Hardware ID: n/a ... Description: n/a
...
/dev/ttyS0  ... Hardware ID: n/a ... Description: n/a
```

Interpretation:

- PlatformIO видит только системные `ttyS*` устройства без идентифицируемого USB/ESP32 hardware descriptor.
- Порта вида `/dev/ttyUSB*` или `/dev/ttyACM*`, типичного для ESP32/USB-UART, не найдено.

### 2. Direct serial device probe

Command:

```text
ls -1 /dev/ttyUSB* /dev/ttyACM* /dev/ttyS* 2>/dev/null
```

Observed result:

```text
/dev/ttyS0
/dev/ttyS1
...
/dev/ttyS31
```

Interpretation:

- Наблюдаются только стандартные системные `ttyS*`.
- Отсутствуют выделенные serial endpoints, через которые можно выполнить ручную проверку прошитого ESP32.

### 3. PlatformIO configuration

Command:

```text
rg -n "upload_port|monitor_port|upload_speed|monitor_speed" platformio.ini
```

Observed result:

```text
30:monitor_speed = 115200
```

Interpretation:

- В `platformio.ini` не задан `upload_port` или `monitor_port`, который можно было бы использовать как подтверждённую точку доступа к конкретному экземпляру железа.

### 4. USB enumeration

Command:

```text
lsusb
```

Observed result:

```text
Bus 001 Device 001: ID 1d6b:0001 Linux Foundation 1.1 root hub
Bus 001 Device 002: ID 0627:0001 Adomax Technology Co., Ltd QEMU Tablet
```

Interpretation:

- В USB topology не обнаружено USB-UART bridge/device, характерного для подключённого ESP32 (`CP210x`, `CH340`, `FTDI`, `Espressif` и т.п.).
- Это согласуется с результатами `platformio device list` и direct serial probe: реальное железо Samovar в этой среде недоступно.

## Manual Smoke Checklist

| Check | Status | Evidence |
| --- | --- | --- |
| Sequential switch through `RECT -> DIST -> BEER -> BK -> NBK -> SUVID -> LUA` on real hardware | `not_done` | No accessible ESP32 hardware endpoint detected in this environment |
| Start and stop at least one mode after each switch | `not_done` | Cannot issue real runtime commands without connected board/web UI |
| Web and menu show correct runtime for each mode | `not_done` | No reachable device UI/session available for manual verification |
| No stuck `pause/power/program state` flags after switching | `not_done` | Requires live hardware/runtime observation |

## What Is Needed To Complete The Smoke

To finish Step 2.6d without assumptions, the following is required:

1. A physically connected and flashed ESP32/Samovar board exposed to this environment via a concrete serial port such as `/dev/ttyUSB*` or `/dev/ttyACM*`.
2. Or a reachable web UI endpoint/IP of the running device, plus confirmation that this session is allowed to interact with it.
3. A confirmed procedure for observing menu/runtime state on the device during mode changes.

## Conclusion

Manual smoke on hardware was **not performed**. Reporting a pass here would be unverifiable and would violate the task constraints. This step remains blocked until real hardware access or a reachable running device is provided.
