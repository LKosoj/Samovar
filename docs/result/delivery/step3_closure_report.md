# Step 3 Closure Report

## 1. Status

- Date: `2026-03-19`
- Scope: `Шаг 3. Нормализация программ режимов`
- Overall result: `DONE`
- Closure decision: all gate conditions confirmed

## 2. Gate Conditions (from 03_program_codec_normalization_plan_ru.md §11)

| Gate condition | Status | Evidence |
| --- | --- | --- |
| Каждый режим имеет явного program owner | `confirmed` | `mode_program_owner()` в `mode_ownership.h`, dispatch через `get_program_for_mode()` / `set_program_for_mode()` в `default_programs.h` |
| `run/set/get program` owners читаются из кода и документации | `confirmed` | `step3_program_owner_inventory.md`, `step3_program_format_spec.md` |
| Текстовые форматы `rect/dist/beer/nbk` не изменились | `confirmed` | 21 format freeze тест (field mapping + serialization order) |
| Web upload/read/save программ работает без изменения контрактов | `confirmed` | `routes_program.h` → `set_program_for_mode` / `get_program_for_mode`, endpoint `/program` и payload `WProgram` не изменены |
| В program layer нет shim, adapter и migration wrappers | `confirmed` | `grep -ril "shim\|adapter\|compat_layer\|migration_wrapper" modes/ support/program_parse_helpers.h` → 0 результатов |
| Build и regression checks подтверждают отсутствие регрессии | `confirmed` | `python3 -m pytest -q` → 392 passed, 0 failed |

## 3. Completed Tasks

### Task 3.1. Program owner inventory (baseline)

- Already completed before Step 3 start
- Artifact: [`step3_program_owner_inventory.md`](/srv/git_projects/Samovar/docs/result/delivery/step3_program_owner_inventory.md)

### Task 3.2. Program format freeze

Зафиксированы exact format contracts для всех 4 families:

| Family | Format | Fields | Tests |
| --- | --- | --- | --- |
| RECT | `WType;Volume;Speed;capacity_num;Temp;Power\n` | 6 | `test_modes_rect_program_codec_baseline.py` |
| DIST | `WType;Speed;capacity_num;Power\n` | 4 | `test_modes_dist_program_codec.py::DistFormatFreezeTest` |
| BEER | `WType;Temp;Time;devType^Speed^Volume^Power;TempSensor\n` | 5 (4-е составное) | `test_modes_beer_program_codec.py::BeerFormatFreezeTest` |
| NBK | `WType;Speed;Power\n` | 3 | `test_modes_nbk_program_codec.py::NbkFormatFreezeTest` |

Artifact: [`step3_program_format_spec.md`](/srv/git_projects/Samovar/docs/result/delivery/step3_program_format_spec.md)

### Task 3.3. Validate helpers extraction

Создан `support/program_parse_helpers.h` с 3 shared helpers:

| Helper | Что делает | Использовался в |
| --- | --- | --- |
| `program_clear()` | Сброс `program[]` и `ProgramLen` | 4 codecs × 2 вызова = 8 мест |
| `trim_line_end(char* line)` | Trim trailing CR/space/tab | 4 codecs |
| `program_fail(const char* msg)` | `program_clear()` + `SendMsg(msg, ALARM_MSG)` | 4 codecs + 1 доп. error path в beer |

Устранено ~85 строк дублирования. Family-specific parse logic осталась в owners.

### Task 3.4. Owner selection cleanup

Добавлены dispatch функции в `app/default_programs.h`:
- `get_program_for_mode(SAMOVAR_MODE mode)` — dispatch get по `mode_program_owner()`
- `set_program_for_mode(SAMOVAR_MODE mode, String WProgram)` — dispatch set по `mode_program_owner()`

5 surfaces упрощены:

| Surface | File | Было | Стало |
| --- | --- | --- | --- |
| Web write/read | `routes_program.h` | 4-branch if/else, 12 строк | 2 строки через dispatch |
| Web template (index) | `template_keys.h` indexKeyProcessor | 4-branch if/else | 1 строка |
| Web template (setup) | `template_keys.h` setupKeyProcessor | 2-branch if/else (неполный!) | 1 строка |
| Session logging | `session_logs.h` | 4-branch if/else с двойным вызовом | 1 вызов dispatch |
| Blynk | `Blynk.ino` | 4-branch if/else (ручной SUVID alias) | 1 строка dispatch |

Попутно исправлены latent баги:
- `setupKeyProcessor` не обрабатывал DIST/NBK mode programs
- `Blynk.ino` ручной SUVID alias вместо `mode_program_owner()`

Include cleanup: `Blynk.ino` и `session_logs.h` заменили 4 codec include на один `app/default_programs.h`.

### Task 3.5. Runtime/program coupling audit

Аудит 27 call sites для `run_program`, `run_dist_program`, `run_beer_program`, `run_nbk_program`:

- **0 cross-family violations** — каждый runtime family вызывает только свой `run_*program`
- Alias modes корректно маршрутизируются: SUVID→BEER, LUA→RECT, BK→RECT (program), BK→BK (runtime)
- Dispatch в `loop_dispatch.h` и `orchestration.h` использует правильные family-specific paths

## 4. Artifact Index

### Source files changed

- [`support/program_parse_helpers.h`](/srv/git_projects/Samovar/support/program_parse_helpers.h) — **new**, shared parse helpers
- [`app/default_programs.h`](/srv/git_projects/Samovar/app/default_programs.h) — added `get_program_for_mode`, `set_program_for_mode`
- [`modes/rect/rect_program_codec.h`](/srv/git_projects/Samovar/modes/rect/rect_program_codec.h) — uses shared helpers
- [`modes/dist/dist_program_codec.h`](/srv/git_projects/Samovar/modes/dist/dist_program_codec.h) — uses shared helpers
- [`modes/beer/beer_program_codec.h`](/srv/git_projects/Samovar/modes/beer/beer_program_codec.h) — uses shared helpers
- [`modes/nbk/nbk_program_codec.h`](/srv/git_projects/Samovar/modes/nbk/nbk_program_codec.h) — uses shared helpers
- [`ui/web/routes_program.h`](/srv/git_projects/Samovar/ui/web/routes_program.h) — uses dispatch
- [`ui/web/template_keys.h`](/srv/git_projects/Samovar/ui/web/template_keys.h) — uses dispatch
- [`storage/session_logs.h`](/srv/git_projects/Samovar/storage/session_logs.h) — uses dispatch
- [`Blynk.ino`](/srv/git_projects/Samovar/Blynk.ino) — uses dispatch

### Delivery documents

- [`step3_program_owner_inventory.md`](/srv/git_projects/Samovar/docs/result/delivery/step3_program_owner_inventory.md) — baseline owner inventory
- [`step3_program_format_spec.md`](/srv/git_projects/Samovar/docs/result/delivery/step3_program_format_spec.md) — format specification for all 4 families

### Reference planning documents

- [`00_full_refactoring_roadmap_ru.md`](/srv/git_projects/Samovar/docs/refactoring/00_full_refactoring_roadmap_ru.md)
- [`03_program_codec_normalization_plan_ru.md`](/srv/git_projects/Samovar/docs/refactoring/03_program_codec_normalization_plan_ru.md)

## 5. Remaining Hardware Validation

Step 3 gate requires manual smoke:
- загрузка и чтение программ через web для `rect/dist/beer/nbk`
- старт программы после загрузки
- проверка, что сохранённый текст программы не меняется
- проверка, что alias owners (`BK/LUA/SUVID`) используют правильную family

Manual validation confirmed by operator on 2026-03-19.

## 6. Final Gate Decision

Step 3 program codec normalization is **complete** for all software invariants.

Step 3 gate is **closed**. Hardware smoke confirmed by operator on 2026-03-19.

Next step per roadmap: **Шаг 4. Консолидация UI и transport-слоя**.
