# Инвентаризация run/set/get program owners для Шага 3

Дата: `2026-03-17`

Назначение:
- зафиксировать фактических владельцев program codec API перед стартом Шага 3;
- показать, какие поверхности уже используют mode-specific owners, а где выбор owner family ещё дублируется;
- дать опорный baseline для нормализации `run_*program`, `set_*program`, `get_*program` без изменения внешних контрактов.

## 1. Каноническое family mapping

Source of truth для program ownership уже зафиксирован в
[`src/core/state/mode_ownership.h`](/srv/git_projects/Samovar/src/core/state/mode_ownership.h).

| Runtime mode | Program owner family | Codec owner | Runtime owner | Notes |
| --- | --- | --- | --- | --- |
| `RECT` | `RECT` | `modes/rect/rect_program_codec.h` | `modes/rect/rect_runtime.h` | Базовая rect family |
| `BK` | `RECT` | `modes/rect/rect_program_codec.h` | `modes/rect/rect_runtime.h` + BK runtime helpers | BK использует rect program family |
| `LUA` | `RECT` | `modes/rect/rect_program_codec.h` | rect runtime family | Lua mode использует rect program family |
| `DIST` | `DIST` | `modes/dist/dist_program_codec.h` | `modes/dist/dist_runtime.h` | Изолированная dist family |
| `BEER` | `BEER` | `modes/beer/beer_program_codec.h` | `modes/beer/beer_runtime.h` | Изолированная beer family |
| `SUVID` | `BEER` | `modes/beer/beer_program_codec.h` | rect runtime family по mode ownership | Program owner отличается от runtime owner |
| `NBK` | `NBK` | `modes/nbk/nbk_program_codec.h` | `modes/nbk/nbk_runtime.h` | Изолированная NBK family |

## 2. Primary code owners

| Family | File | Owned symbols | Responsibility |
| --- | --- | --- | --- |
| `RECT` | [`modes/rect/rect_program_codec.h`](/srv/git_projects/Samovar/modes/rect/rect_program_codec.h) | `set_program`, `get_program` | rect/BK/LUA text codec, parse + stringify, shared `program[]` population |
| `RECT` | [`modes/rect/rect_runtime.h`](/srv/git_projects/Samovar/modes/rect/rect_runtime.h) | `run_program` | rect family runtime step transition and finish path |
| `DIST` | [`modes/dist/dist_program_codec.h`](/srv/git_projects/Samovar/modes/dist/dist_program_codec.h) | `set_dist_program`, `get_dist_program` | dist text codec |
| `DIST` | [`modes/dist/dist_runtime.h`](/srv/git_projects/Samovar/modes/dist/dist_runtime.h) | `run_dist_program` | dist runtime step transition |
| `BEER` | [`modes/beer/beer_program_codec.h`](/srv/git_projects/Samovar/modes/beer/beer_program_codec.h) | `set_beer_program`, `get_beer_program` | beer/SUVID text codec |
| `BEER` | [`modes/beer/beer_runtime.h`](/srv/git_projects/Samovar/modes/beer/beer_runtime.h) | `run_beer_program` | beer runtime step transition |
| `NBK` | [`modes/nbk/nbk_program_codec.h`](/srv/git_projects/Samovar/modes/nbk/nbk_program_codec.h) | `set_nbk_program`, `get_nbk_program` | NBK text codec |
| `NBK` | [`modes/nbk/nbk_runtime.h`](/srv/git_projects/Samovar/modes/nbk/nbk_runtime.h) | `run_nbk_program` | NBK runtime step transition |
| `DEFAULTS` | [`app/default_programs.h`](/srv/git_projects/Samovar/app/default_programs.h) | `load_default_program_for_mode` | canonical default program selection through `mode_program_owner(Samovar_Mode)` |

## 3. Surface owners and consumers

| Surface | File | Symbols / calls | Notes |
| --- | --- | --- | --- |
| Web write API | [`ui/web/routes_program.h`](/srv/git_projects/Samovar/ui/web/routes_program.h) | `set_beer_program`, `set_dist_program`, `set_nbk_program`, `set_program` | `/program` route writes program text and returns normalized text back |
| Web setup/save | [`ui/web/routes_setup.h`](/srv/git_projects/Samovar/ui/web/routes_setup.h) | `load_default_program_for_mode`, `set_beer_program`, `set_program` | setup path changes mode and applies family defaults; legacy split still visible in `WProgram` save branch |
| Web template read | [`ui/web/template_keys.h`](/srv/git_projects/Samovar/ui/web/template_keys.h) | `get_beer_program`, `get_dist_program`, `get_nbk_program`, `get_program` | Mode-based selection duplicated in template processor |
| Frontend POST owner | [`data/common.js`](/srv/git_projects/Samovar/data/common.js) | `set_program()` JS helper | posts `WProgram` to `/program`; HTTP contract must remain unchanged |
| Menu runtime start | [`ui/menu/actions.h`](/srv/git_projects/Samovar/ui/menu/actions.h) | `run_program` | menu start/next/finish is rect-family specific today |
| Runtime loop dispatch | [`app/loop_dispatch.h`](/srv/git_projects/Samovar/app/loop_dispatch.h) | `run_beer_program`, `run_dist_program`, `run_nbk_program` | runtime family dispatch path outside codec files |
| Runtime orchestration | [`app/orchestration.h`](/srv/git_projects/Samovar/app/orchestration.h) | `run_beer_program` and mode-switch side effects | orchestration still touches program transitions indirectly |
| Session logging | [`storage/session_logs.h`](/srv/git_projects/Samovar/storage/session_logs.h) | `get_program`, `get_beer_program`, `get_dist_program`, `get_nbk_program` | saves active program text into `/prg.csv` per current mode |
| Blynk | [`Blynk.ino`](/srv/git_projects/Samovar/Blynk.ino) | `get_beer_program`, `get_dist_program`, `get_nbk_program`, `get_program` | V24 mirrors current program text with family switch |

## 4. Current duplication and ownership gaps

Наблюдаемые дублирования, которые Шаг 3 должен закрыть:

1. Выбор program family по `Samovar_Mode` размазан по нескольким поверхностям:
   - `ui/web/routes_program.h`
   - `ui/web/template_keys.h`
   - `storage/session_logs.h`
   - `Blynk.ino`
2. `load_default_program_for_mode()` уже использует `mode_program_owner()`, но web/template/logging/Blynk selection не везде переведены на такой же явный owner-based выбор.
3. Валидация форматов и reset shared массива `program[]` повторяются в каждом codec owner (`rect/dist/beer/nbk`) с похожими шаблонами очистки, проверки длины и parse error handling.
4. Rect-family `run_program()` уже отделён от codec, но menu/web surfaces знают о rect family напрямую, а не через явную owner policy.
5. `SUVID` и `LUA` опираются на чужие program families (`BEER` и `RECT`), и это надо держать явно задокументированным, чтобы не потерять контракт при дедупликации.

## 5. Вывод для Шага 3

Шаг 3 должен работать не от абстрактной идеи "свести всё в общий codec", а от этого baseline:

- изолированные codec owners уже существуют;
- главная следующая работа — убрать дублирование выбора owner family и нормализовать общие validate helpers;
- внешний контракт `WProgram`, program text formats и web/menu/Blynk surfaces менять нельзя;
- новый shim или промежуточный codec-layer вводить нельзя.
