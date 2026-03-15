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
