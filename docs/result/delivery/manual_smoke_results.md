# Step 2.6d Manual Smoke Results

## Status

- Date: `2026-03-17`
- Task: `Step 2.6d: Ручной smoke-тест на железе`
- Result: `PASSED`
- Evidence source: `операторская верификация на реальном Samovar/ESP32, подтверждённая пользователем в текущей сессии`
- Scope: `финальный hardware smoke для закрытия REQ-8`

## Execution Record

Manual smoke был выполнен на реальном устройстве вне текущего CLI-сеанса.
Этот документ фиксирует принятый результат ручной проверки по операторскому отчёту.

Проверенный сценарий:

1. Последовательное переключение режимов `RECT -> DIST -> BEER -> BK -> NBK -> SUVID -> LUA`.
2. Запуск и остановка как минимум одного runtime после каждой смены режима.
3. Проверка, что web/menu показывают корректный runtime в соответствии с текущим mode ownership.
4. Проверка, что после stop/switch не остаются зависшие флаги `pause`, `power`, `program state`.

## Manual Smoke Matrix

| Mode | Switch | Start/Stop | Web/Menu Runtime | Stuck Flags | Notes |
| --- | --- | --- | --- | --- | --- |
| `RECT` | `ok` | `ok` | `ok` | `clear` | Rect runtime и page surface корректны |
| `DIST` | `ok` | `ok` | `ok` | `clear` | Dist runtime и program transitions корректны |
| `BEER` | `ok` | `ok` | `ok` | `clear` | Beer runtime и program start/finish корректны |
| `BK` | `ok` | `ok` | `ok` | `clear` | BK runtime и power path корректны |
| `NBK` | `ok` | `ok` | `ok` | `clear` | NBK runtime и work/pause pipeline корректны |
| `SUVID` | `ok` | `ok` | `ok` | `clear` | Runtime surface согласуется с текущим ownership mapping |
| `LUA` | `ok` | `ok` | `ok` | `clear` | Lua mode-selection и runtime surface согласуются с текущим ownership mapping |

## Acceptance Summary

| Check | Status | Evidence |
| --- | --- | --- |
| Sequential switch through `RECT -> DIST -> BEER -> BK -> NBK -> SUVID -> LUA` on real hardware | `done` | Operator-reported hardware smoke completed on `2026-03-17` |
| Start and stop at least one mode after each switch | `done` | Operator confirmed successful start/stop after each mode change |
| Web and menu show correct runtime for each mode | `done` | Operator confirmed runtime display consistency with current ownership mapping |
| No stuck `pause/power/program state` flags after switching | `done` | Operator confirmed clean stop/reset state across the full switching chain |

## Conclusion

`REQ-8` is confirmed.

Step 2 manual smoke gate is closed on the basis of the completed real-hardware smoke reported by the project operator on `2026-03-17`.
