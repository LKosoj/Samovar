# Шаг 2.1. Build verification

## Обязательная сборка

- Дата: `2026-03-15`
- Команда: `pio run -e Samovar`
- Результат: `SUCCESS`
- Длительность: `00:00:21.697`
- RAM: `18.3% (59904 / 327680 bytes)`
- Flash: `70.1% (1148721 / 1638400 bytes)`

## Контекст

- Сборка выполнена после генерации baseline-артефактов `state_codes_inventory.md` и `state_inventory_grep_log.md`.
- В рамках подзадачи 2.1 production-логика не изменялась; зафиксирован только baseline state-слоя и добавлен regression-тест на его неизменность.
