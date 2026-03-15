# Шаг 2. Build verification

## Подзадача 2.1

- Дата: `2026-03-15`
- Команда: `pio run -e Samovar`
- Результат: `SUCCESS`
- Длительность: `00:00:21.697`
- RAM: `18.3% (59904 / 327680 bytes)`
- Flash: `70.1% (1148721 / 1638400 bytes)`
- Контекст: baseline-инвентаризация state-кодов (`state_codes_inventory.md`, `state_inventory_grep_log.md`)

## Подзадача 2.4

- Дата: `2026-03-15`
- Команда: `pio run -e Samovar`
- Результат: `SUCCESS`
- Длительность: `00:00:23.020`
- RAM: `18.3% (59904 / 327680 bytes)`
- Flash: `70.1% (1148721 / 1638400 bytes)`
- Контекст: формализация reset pipeline (`reset_pipeline_spec.md`, `step2_regression_log.md`, `tools/tests/test_reset_pipeline_invariant.py`)

### Raw build excerpt

```text
========================= [SUCCESS] Took 23.02 seconds =========================

Environment    Status    Duration
-------------  --------  ------------
Samovar        SUCCESS   00:00:23.020

========================= 1 succeeded in 00:00:23.020 =========================
```

## Подзадача 2.2a

- Дата: `2026-03-15`
- Команда: `pio run -e Samovar`
- Результат: `SUCCESS`
- Длительность: `00:00:23.129`
- RAM: `18.3% (59904 / 327680 bytes)`
- Flash: `70.1% (1148721 / 1638400 bytes)`
- Контекст: введение именованных status/command constants (`src/core/state/status_codes.h`, `status_codes_grep_log.md`)

### Raw build excerpt

```text
========================= [SUCCESS] Took 23.13 seconds =========================

Environment    Status    Duration
-------------  --------  ------------
Samovar        SUCCESS   00:00:23.129

========================= 1 succeeded in 00:00:23.129 =========================
```

## Подзадача 2.2b

- Дата: `2026-03-15`
- Команда: `pio run -e Samovar`
- Результат: `SUCCESS`
- Длительность: `00:00:59.340`
- RAM: `18.3% (59904 / 327680 bytes)`
- Flash: `70.1% (1148721 / 1638400 bytes)`
- Контекст: введение именованных mode/startval constants (`src/core/state/mode_codes.h`, `mode_codes_grep_log.md`)

### Raw build excerpt

```text
========================= [SUCCESS] Took 59.34 seconds =========================

Environment    Status    Duration
-------------  --------  ------------
Samovar        SUCCESS   00:00:59.340

========================= 1 succeeded in 00:00:59.340 =========================
```

## Подзадача 2.3

- Дата: `2026-03-16`
- Команда: `pio run -e Samovar`
- Результат: `SUCCESS`
- Длительность: `00:00:49.720`
- RAM: `18.3% (59904 / 327680 bytes)`
- Flash: `70.1% (1148561 / 1638400 bytes)`
- Контекст: явное описание mode ownership и runtime routing (`mode_ownership_mapping.md`, `src/core/state/mode_ownership.h`)

### Raw build excerpt

```text
========================= [SUCCESS] Took 49.72 seconds =========================

Environment    Status    Duration
-------------  --------  ------------
Samovar        SUCCESS   00:00:49.720

========================= 1 succeeded in 00:00:49.720 =========================
```

## Подзадача 2.5

- Дата: `2026-03-16`
- Команда: `pio run -e Samovar`
- Результат: `SUCCESS`
- Длительность: `00:00:24.112`
- RAM: `18.3% (59904 / 327680 bytes)`
- Flash: `70.1% (1148545 / 1638400 bytes)`
- Контекст: финальная зачистка magic numbers в state-логике (`magic_cleanup_log.md`, обновлённый `state_codes_inventory.md`)

### Raw build excerpt

```text
========================= [SUCCESS] Took 24.11 seconds =========================

Environment    Status    Duration
-------------  --------  ------------
Samovar        SUCCESS   00:00:24.112

========================= 1 succeeded in 00:00:24.112 =========================
```
