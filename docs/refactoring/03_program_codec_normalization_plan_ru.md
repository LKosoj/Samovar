# Детальное ТЗ: Шаг 3. Нормализация программ режимов

Дата: `2026-03-17`

Статус документа:
- draft for implementation

Связь с master roadmap:
- этот документ является детальным ТЗ для шага 3 из [00_full_refactoring_roadmap_ru.md](/srv/git_projects/Samovar/docs/refactoring/00_full_refactoring_roadmap_ru.md)

Связь с завершённым шагом 2:
- Step 2 closure и подтверждённые state invariants зафиксированы в [step2_closure_report.md](/srv/git_projects/Samovar/docs/result/delivery/step2_closure_report.md)
- baseline owners для `run/set/get program` зафиксированы в [step3_program_owner_inventory.md](/srv/git_projects/Samovar/docs/result/delivery/step3_program_owner_inventory.md)

## 1. Назначение

После завершения Шага 2 внутренняя state-модель стала явной, но слой программ режимов всё ещё остаётся неоднородным:
- mode-specific codec owners уже разнесены по `modes/*/*_program_codec.h`, но одинаковые parse/reset шаблоны дублируются;
- выбор family owner для program text всё ещё размазан по web/template/logging/Blynk поверхностям;
- для части режимов (`BK`, `LUA`, `SUVID`) program owner отличается от runtime owner, и это легко сломать неявным упрощением;
- run/set/get program API читается, но не оформлен как единая карта владельцев и форматов.

Цель Шага 3:
- сделать слой программ режимов читаемым и обслуживаемым;
- сохранить текстовые форматы программ, HTTP payload и runtime behaviour 1:1;
- убрать дублирование и неявные owner-ветки без введения новых миграционных слоёв.

## 2. Обязательные инварианты шага

- Нельзя менять текстовый формат `WProgram` для `rect/dist/beer/nbk`.
- Нельзя менять HTTP payload, web endpoint и JSON/menu/Blynk/Lua contracts, связанные с программами.
- Нельзя менять последовательность runtime side effects при `run_*program`.
- Нельзя вводить новый shim, adapter, compat-layer или "единый универсальный codec framework" поверх существующих owners.
- Нельзя ломать mapping `mode -> program owner family`, уже зафиксированный в [`mode_ownership.h`](/srv/git_projects/Samovar/src/core/state/mode_ownership.h).
- Каждый подшаг должен заканчиваться собираемым состоянием и доказуемыми проверками.

## 3. Что входит в шаг 3

- финальная нормализация mode-specific codec modules;
- инвентаризация и явная фиксация владельцев `run_*program`, `set_*program`, `get_*program`;
- унификация validate helpers там, где это можно сделать без нового абстрактного слоя;
- устранение дублирования выбора owner family в web/menu/Blynk/storage surfaces;
- документация форматов `rect/dist/beer/nbk`;
- финальная проверка загрузки/чтения/запуска программ через существующие поверхности.

## 4. Что не входит в шаг 3

- смена текстового формата строк программ;
- смена HTTP payload `WProgram`;
- перепроектирование runtime state machine;
- redesign web/menu/Lua/Blynk surfaces;
- создание нового центрального "program manager" ради миграции.

## 5. Архитектурное решение шага

Рекомендуемый подход:
- считать существующие family owners каноническими и не ломать их границы:
  - rect family: `set_program`, `get_program`, `run_program`
  - dist family: `set_dist_program`, `get_dist_program`, `run_dist_program`
  - beer family: `set_beer_program`, `get_beer_program`, `run_beer_program`
  - nbk family: `set_nbk_program`, `get_nbk_program`, `run_nbk_program`
- дедуплицировать не сами owners, а повторяющиеся куски:
  - owner selection
  - validation utilities
  - read/write surfaces
- держать source of truth ближе к существующим owners и к `mode_program_owner()`, а не вводить новый промежуточный слой.

Результат шага должен дать прямой ответ на три вопроса:
- какой формат программы у каждой family;
- кто владеет `set/get/run` API для каждой family;
- как web/menu/Blynk/storage выбирают owner family без неявных веток.

## 6. Baseline ownership перед стартом

Базовая инвентаризация для Шага 3 уже зафиксирована в:
- [step3_program_owner_inventory.md](/srv/git_projects/Samovar/docs/result/delivery/step3_program_owner_inventory.md)

Эта инвентаризация является обязательным baseline.
Любая нормализация Шага 3 должна сохранять описанный там mapping `mode -> program owner family`.

## 7. Декомпозиция на подзадачи

### Подзадача 3.1. Инвентаризация и freeze program formats

Цель:
- зафиксировать фактические форматы `rect/dist/beer/nbk` и owner mapping как baseline contract.

Что сделать:
- документировать формат каждой строки программы по family;
- зафиксировать mode-family mapping для `BK/LUA/SUVID`;
- собрать таблицу surface owners: web/menu/Blynk/storage/runtime.

Артефакты:
- inventory doc по owners и formats;
- baseline tests или doc-tests на round-trip и format parity.

Критерии приёмки:
- нет неразобранных `run/set/get` entry points;
- формат каждой family задокументирован;
- все consumer surfaces имеют явного owner.

Проверки:
- doc/test parity на функции codec owners;
- сборка `pio run -e Samovar`.

### Подзадача 3.2. Нормализация validate helpers без нового слоя

Цель:
- убрать копипасту parse/reset/error handling, не создавая новый runtime framework.

Что сделать:
- вынести повторяющиеся parse/trim/check helpers в `support/` или рядом с owner-модулями;
- оставить family-specific смысл и текст ошибок внутри owners;
- не смешивать несовместимые форматы в один "универсальный parser".

Критерии приёмки:
- повторяющиеся шаблоны очистки, проверки длины и safe-parse сокращены;
- owner files остаются главными владельцами своих форматов.

Проверки:
- unit/doc tests на exact parse behaviour;
- baseline string round-trip tests.

### Подзадача 3.3. Явный owner selection во всех surfaces

Цель:
- убрать ручные mode-ветки там, где поверхность только выбирает program family.

Что сделать:
- нормализовать owner selection в:
  - web routes
  - template processors
  - session logging
  - Blynk program mirror
  - default program loading
- по возможности использовать уже существующий `mode_program_owner()`.

Критерии приёмки:
- surface code не дублирует разъезжающиеся mode switches без необходимости;
- owner choice читается из одной явной semantics, а не из набора ad-hoc `if`.

Проверки:
- web integration tests на `/program` и setup/save;
- tests на Blynk/logging selection;
- regression на `load_default_program_for_mode()`.

### Подзадача 3.4. Финальная зачистка run entry points

Цель:
- сделать `run_*program` owners читаемыми и явно связанными с их codec family.

Что сделать:
- проверить, что каждый runtime family использует только свой `run_*program`;
- убрать неявные переходы и out-of-family assumptions;
- документировать особые режимы (`BK`, `LUA`, `SUVID`) как alias family, а не как отдельные codec owners.

Критерии приёмки:
- каждый режим имеет явную связь с owner family;
- запуск программы из runtime/menu/web не опирается на неявные допущения.

Проверки:
- behavioral harness на run transitions;
- menu/web start-flow regression.

### Подзадача 3.5. Финальная интеграционная верификация Шага 3

Цель:
- закрыть step gate перед переходом к Шагу 4.

Что сделать:
- прогнать codec parity и round-trip набор;
- прогнать web upload/save/read smoke;
- прогнать build matrix;
- зафиксировать итоговый closure report по Шагу 3.

Критерии приёмки:
- owners и formats читаются прямо из кода и документации;
- web upload программ продолжает работать 1:1;
- runtime behaviour не меняется относительно baseline.

## 8. Требования к доказательствам

Для каждой подзадачи обязательно фиксировать evidence в трёх формах:
- код: какие owner files изменены и где находится source of truth;
- тест: какой regression/harness подтверждает инвариант;
- сборка: какой `pio run` подтверждает, что шаг не сломал проект.

Если хотя бы по одному инварианту нет достаточного evidence, подзадача считается `not_done`.

## 9. Рекомендуемые тестовые пакеты шага

Минимальный обязательный набор:
- baseline/round-trip tests для `set/get` каждой family;
- tests на owner selection в web/template/logging/Blynk surfaces;
- tests на `load_default_program_for_mode()`;
- behavioral tests на `run_program`, `run_dist_program`, `run_beer_program`, `run_nbk_program`;
- tests на web upload/save/read сценарии через `/program`.

Минимальный build-набор:
- `pio run -e Samovar`
- `pio run -e lua_expander`

Желательный расширенный build-набор:
- `pio run -e Samovar_s3`
- `pio run -e nbk_pressure`
- `pio run -e no_power`

Ручной smoke после интеграции:
- загрузка и чтение программ через web для `rect/dist/beer/nbk`;
- старт программы после загрузки;
- проверка, что сохранённый текст программы не меняется относительно baseline формата;
- проверка, что alias owners (`BK/LUA/SUVID`) используют правильную family.

## 10. Риски шага

Основные риски:
- под видом дедупликации сломать различия между format families;
- случайно изменить текст программы при round-trip;
- вынести слишком много логики в новый общий слой и создать новый legacy;
- потерять неочевидные alias owners (`BK/LUA -> RECT`, `SUVID -> BEER`);
- сломать web/menu/Blynk surfaces, которые не являются codec owners, но читают program text.

Способ снижения рисков:
- сначала фиксировать owners и format parity тестами, потом упрощать;
- не объединять разные форматы в одну parser abstraction;
- сводить дублирование через owner selection semantics и точечные helpers, а не через новый framework;
- после каждой подзадачи держать проект в собираемом состоянии.

## 11. Gate завершения шага 3

Шаг 3 считается завершённым только если одновременно выполнено всё ниже:
- каждый режим имеет явного program owner;
- `run/set/get program` owners читаются прямо из кода и документации;
- текстовые форматы `rect/dist/beer/nbk` не изменились относительно baseline;
- web upload/read/save программ продолжает работать без изменения контрактов;
- в program layer нет shim, adapter и migration wrappers;
- build и regression checks подтверждают отсутствие регрессии.

## 12. Формат постановки задач в рамках шага 3

Каждую реализацию внутри шага 3 ставить как отдельную задачу с единым шаблоном:
- цель подзадачи;
- конкретная область кода;
- acceptance criteria;
- список обязательных regression/build checks;
- явные ограничения "что нельзя менять";
- Definition of Done с требованием evidence.

Рекомендуемые task ids:
- `t30_1_program_owner_inventory`
- `t30_2_program_format_freeze`
- `t30_3_program_validate_helpers`
- `t30_4_program_owner_selection_cleanup`
- `t30_5_program_runtime_entrypoints`
- `t30_6_program_layer_final_verification`

## 13. Рекомендуемый следующий исполнимый task

Следующим открывать:
- `t30_2_program_format_freeze`

Почему:
- owner inventory уже собран и зафиксирован в [step3_program_owner_inventory.md](/srv/git_projects/Samovar/docs/result/delivery/step3_program_owner_inventory.md);
- следующий полезный шаг — заморозить format parity и собрать baseline tests, чтобы дальше дедуплицировать без риска изменения контрактов;
- это первый task, после которого можно безопасно трогать parse/validate helpers.

## 14. Детальный backlog для low-middle разработчика

Ниже — рабочая декомпозиция в том виде, в котором задачи можно брать в реализацию последовательно, без архитектурных догадок.

### Task 3.2a. Freeze rect format contract

Цель:
- зафиксировать exact format и round-trip контракт rect family.

Файлы:
- [`modes/rect/rect_program_codec.h`](/srv/git_projects/Samovar/modes/rect/rect_program_codec.h)
- [`tests/test_modes_rect_program_codec_baseline.py`](/srv/git_projects/Samovar/tests/test_modes_rect_program_codec_baseline.py)
- новый delivery-артефакт с rect format notes

Что сделать:
- описать grammar строки rect program;
- проверить, что `set_program()` и `get_program()` дают baseline-compatible round-trip;
- зафиксировать все ограничения по полям и parse errors.

Готовый результат:
- rect format задокументирован;
- есть тест, который подтверждает exact parity.

Нельзя:
- менять порядок полей;
- менять тексты ошибок;
- менять `WProgram` contract.

### Task 3.2b. Freeze dist format contract

Цель:
- зафиксировать format и round-trip контракт dist family.

Файлы:
- [`modes/dist/dist_program_codec.h`](/srv/git_projects/Samovar/modes/dist/dist_program_codec.h)
- [`tests/test_modes_dist_program_codec.py`](/srv/git_projects/Samovar/tests/test_modes_dist_program_codec.py)
- delivery-note по dist format

Что сделать:
- описать grammar dist line;
- проверить stringify/parse parity;
- зафиксировать допустимые и недопустимые значения.

Проверки:
- targeted unittest/doc-test;
- `pio run -e Samovar`.

### Task 3.2c. Freeze beer format contract

Цель:
- зафиксировать beer/SUVID format contract как отдельную family.

Файлы:
- [`modes/beer/beer_program_codec.h`](/srv/git_projects/Samovar/modes/beer/beer_program_codec.h)
- [`tests/test_modes_beer_program_codec.py`](/srv/git_projects/Samovar/tests/test_modes_beer_program_codec.py)
- delivery-note по beer format

Что сделать:
- описать структуру `device payload` через `^`;
- зафиксировать round-trip behaviour;
- отдельно отметить, что `SUVID` использует beer program owner family.

Проверки:
- targeted unittest/doc-test;
- web readback smoke harness.

### Task 3.2d. Freeze nbk format contract

Цель:
- зафиксировать NBK format contract.

Файлы:
- [`modes/nbk/nbk_program_codec.h`](/srv/git_projects/Samovar/modes/nbk/nbk_program_codec.h)
- [`tests/test_modes_nbk_program_codec.py`](/srv/git_projects/Samovar/tests/test_modes_nbk_program_codec.py)
- delivery-note по nbk format

Что сделать:
- описать NBK grammar;
- проверить parity `set_nbk_program()` / `get_nbk_program()`;
- зафиксировать границы parse errors.

### Task 3.3a. Extract safe shared input helpers

Цель:
- сократить копипасту trim/length/line-splitting logic в codec owners.

Файлы-кандидаты:
- [`modes/rect/rect_program_codec.h`](/srv/git_projects/Samovar/modes/rect/rect_program_codec.h)
- [`modes/dist/dist_program_codec.h`](/srv/git_projects/Samovar/modes/dist/dist_program_codec.h)
- [`modes/beer/beer_program_codec.h`](/srv/git_projects/Samovar/modes/beer/beer_program_codec.h)
- [`modes/nbk/nbk_program_codec.h`](/srv/git_projects/Samovar/modes/nbk/nbk_program_codec.h)
- `support/` helper file, только если helper реально общий и не становится новым framework

Что сделать:
- вынести общие низкоуровневые куски: input length guard, trim CR/tab/space, line iteration;
- family-specific parse rules оставить внутри family owners.

Нельзя:
- делать универсальный parser для всех форматов;
- смешивать family-specific семантику в одном helper.

### Task 3.3b. Normalize reset/fail patterns in codec owners

Цель:
- убрать повторяющийся reset массива `program[]` и `ProgramLen` при parse failure.

Что сделать:
- найти единообразный минимальный helper или локальный idiom;
- сохранить текущую семантику: при ошибке входа owner обнуляет program state и отправляет family-specific error message.

Проверки:
- baseline tests на error path;
- regression на exact messages, где они уже зафиксированы тестами.

### Task 3.4a. Cleanup web owner selection

Цель:
- убрать рассыпанные ручные owner switches в web layer.

Файлы:
- [`ui/web/routes_program.h`](/srv/git_projects/Samovar/ui/web/routes_program.h)
- [`ui/web/routes_setup.h`](/srv/git_projects/Samovar/ui/web/routes_setup.h)
- [`ui/web/template_keys.h`](/srv/git_projects/Samovar/ui/web/template_keys.h)
- [`app/default_programs.h`](/srv/git_projects/Samovar/app/default_programs.h)

Что сделать:
- перевести выбор family owner на явную semantics через `mode_program_owner()`, где это уместно;
- не менять endpoint `/program`, поле `WProgram`, порядок save/read flow.

Проверки:
- `tests/test_ui_web_routes_program.py`
- web integration harness
- targeted regression на template readback.

### Task 3.4b. Cleanup non-web owner selection

Цель:
- убрать дублирование owner selection в surfaces вне web.

Файлы:
- [`storage/session_logs.h`](/srv/git_projects/Samovar/storage/session_logs.h)
- [`Blynk.ino`](/srv/git_projects/Samovar/Blynk.ino)
- при необходимости [`app/process_common.h`](/srv/git_projects/Samovar/app/process_common.h) и соседние consumers

Что сделать:
- нормализовать выбор `get_*program()` для логов и Blynk;
- сохранить текущий output text 1:1.

Проверки:
- targeted tests на selection logic;
- smoke на session log output и Blynk mirror contract.

### Task 3.5a. Audit rect-family runtime/program coupling

Цель:
- проверить, что rect runtime, BK и Lua не тянут program semantics из неявных мест.

Файлы:
- [`modes/rect/rect_runtime.h`](/srv/git_projects/Samovar/modes/rect/rect_runtime.h)
- [`ui/menu/actions.h`](/srv/git_projects/Samovar/ui/menu/actions.h)
- [`app/loop_dispatch.h`](/srv/git_projects/Samovar/app/loop_dispatch.h)

Что сделать:
- зафиксировать, кто имеет право вызывать `run_program()`;
- убрать неявные assumptions по alias owners, если они найдутся;
- не менять rect/BK/Lua behaviour.

### Task 3.5b. Audit dist/beer/nbk runtime/program coupling

Цель:
- проверить прямые связи `run_dist_program`, `run_beer_program`, `run_nbk_program` с их codec owners и callers.

Файлы:
- [`modes/dist/dist_runtime.h`](/srv/git_projects/Samovar/modes/dist/dist_runtime.h)
- [`modes/beer/beer_runtime.h`](/srv/git_projects/Samovar/modes/beer/beer_runtime.h)
- [`modes/nbk/nbk_runtime.h`](/srv/git_projects/Samovar/modes/nbk/nbk_runtime.h)
- [`app/orchestration.h`](/srv/git_projects/Samovar/app/orchestration.h)
- [`app/loop_dispatch.h`](/srv/git_projects/Samovar/app/loop_dispatch.h)

Что сделать:
- подтвердить, что каждый runtime family использует только свой `run_*program`;
- убрать неявные переходы между families, если они есть;
- зафиксировать final owner map в tests/docs.

### Task 3.6. Final verification and closure

Цель:
- закрыть Шаг 3 единым deliverable пакетом.

Что должно быть готово к этому моменту:
- inventory owners;
- format docs для всех families;
- round-trip tests;
- owner-selection cleanup;
- runtime coupling cleanup.

Обязательные проверки:
- regression suite по codec/runtime/web selection;
- `pio run -e Samovar`
- `pio run -e lua_expander`
- желательно `pio run -e Samovar_s3`
- manual smoke загрузки/чтения/старта программ.

Финальный артефакт:
- closure report Шага 3 с explicit evidence по каждому инварианту.
