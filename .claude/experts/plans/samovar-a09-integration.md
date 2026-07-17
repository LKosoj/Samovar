# A-09: завершение атомарного обновления программ

## Completion record

- Статус: **complete**.
- Review: **PASS: no errors, no warnings**.
- Результат: невалидный ввод и runtime-race не меняют
  `program[]`/`ProgramLen`; валидная программа передаётся в `loop()` уже
  разобранным фиксированным `PendingProgramUpdate`, а очистка выполняется только
  отдельным явным действием.

Реализовано:

- `program_types.h` содержит `ProgramParseError` и `ProgramParseResult` с номером строки;
- `program_io.h` содержит `ProgramDraft`, недеструктивный
  `program_parse_lines(..., draft)`, `program_commit()`, `program_clear()` и
  trivially-copyable `PendingProgramUpdate`;
- setters всех четырёх форматов, включая NBK, возвращают и обрабатывают
  `ProgramParseResult`;
- default loaders и call sites проверяют результат;
- web handlers полностью проверяют mode-specific draft до queue и не хранят
  `pending_program_str`;
- `loop()` применяет уже валидированный POD без повторного разбора;
- пустой ввод не очищает программу; clear остаётся отдельной явной командой.

Проверка на момент закрытия A-09:

- полный smoke: `41/41` PASS;
- Playwright: 12 viewports / 48 scenarios PASS;
- PlatformIO: `7/7` environments PASS;
- buildfs, blocking/extended cppcheck и `git diff --check`: PASS.

`OperationStore` не входит в A-09 и остаётся отдельной функциональной задачей W2.

## Архитектурное решение

Рассмотрены три пути:

1. Оставить сырой `String` и повторный parser в `loop()` — отклонено: heap, двойная validation и расхождение двух parse-path.
2. Commit из async HTTP-handler — отклонено: нарушает loop-owned runtime и текущую защиту от конкурентного чтения программы.
3. Передавать в pending slot только уже проверенный POD draft либо explicit clear — выбранный путь.

Целевой поток:

```text
request/default literal
  -> точный mode-to-format lookup
  -> parse в локальный ProgramDraft
  -> failure: явный Result, globals и pending неизменны
  -> success: PendingProgramUpdate {targetMode, action, draft}
  -> loop recheck active session + target mode
  -> program_commit(draft) либо program_clear()
```

`ProgramDraft` остаётся в `program_io.h`: перенос в `program_types.h` невозможен без ухудшения include-графа, потому что `Samovar.h` подключает `program_types.h` до определения `WProgram`.

## 1. Доменный Result и mode mapping

### `program_types.h`

- При необходимости добавить `PROGRAM_PARSE_UNSUPPORTED_MODE`; неизвестный `SAMOVAR_MODE` не должен молча превращаться в rectification.
- Сохранить стабильные поля `ProgramParseResult {error, lineNumber, errorMessage}` для последующего отображения в W2 operation detail.
- Не добавлять operation ID/state в A-09.

### `program_io.h`

Добавить:

```cpp
enum ProgramUpdateAction : uint8_t {
  PROGRAM_UPDATE_NONE = 0,
  PROGRAM_UPDATE_REPLACE,
  PROGRAM_UPDATE_CLEAR,
};

struct PendingProgramUpdate {
  ProgramDraft draft;
  SAMOVAR_MODE targetMode;
  ProgramUpdateAction action;
};
```

Обязательные ограничения:

```cpp
static_assert(std::is_trivially_copyable<PendingProgramUpdate>::value, ...);
static_assert(sizeof(PendingProgramUpdate) <= 576, ...);
```

Добавить единственные helpers:

- `format_program_parse_error(const ProgramParseResult&)` — добавляет номер строки только при `lineNumber > 0`;
- mode-to-spec lookup без default fallback;
- parse helper, принимающий явный mode, input и `ProgramDraft&`.

Зафиксировать mode/format characterization:

- rectification и BK — rect format;
- distillation — dist format;
- beer — beer format;
- NBK — NBK format;
- SUVID должен следовать beer, поскольку так уже работают default loader и Blynk;
- Lua сохраняет текущий rect contract, пока его program editor существует;
- неизвестный enum — явная ошибка.

При синхронизации SUVID проверить `WebServer.ino` template/getter: сейчас web mapper и default/Blynk расходятся. Оставлять два неявных источника истины запрещено.

### `logic.h`, `beer.h`, `distiller.h`, `nbk.h`

- Оставить существующие rect/beer/dist thin wrappers.
- Изменить NBK на:

  ```cpp
  ProgramParseResult set_nbk_program(const String& programText);
  ```

- Не создавать `void` overload или compatibility shim.

### `samovar_api.h`

- Синхронизировать точные Result-returning signatures четырёх setter-ов.
- Если default prepare helper принимает draft по ссылке, добавить только forward declaration `struct ProgramDraft;`; реализаций и storage в API header не добавлять.

## 2. Проверяемый default loader

### `sensorinit.h`

Разделить подготовку и commit:

```cpp
ProgramParseResult prepare_default_program_for_mode(
    SAMOVAR_MODE mode,
    ProgramDraft& draft);

ProgramParseResult load_default_program_for_mode(SAMOVAR_MODE mode);
```

Контракт:

- mode всегда передаётся явно;
- `prepare_*` только разбирает literal в draft;
- `load_*` commit-ит только после полного success;
- failure оставляет весь старый `program[]` и `ProgramLen` без изменений;
- неизвестный mode не получает rect fallback;
- default literals четырёх форматов покрываются host tests.

### Все call sites

1. `Samovar.ino::setup()`:
   - после загрузки NVS вызвать `load_default_program_for_mode(Samovar_Mode)`;
   - проверить result;
   - при failure вывести точную причину и задействовать существующий A-11 emergency latch, не разрешая нагрев;
   - не подставлять другой default и не делать скрытый retry.
2. `sensorinit.h::sensor_init()`:
   - удалить второй дублирующий вызов default loader: между ним и setup-вызовом mode не меняется, повтор маскирует failure.
3. `WebServer.ino::switch_samovar_mode()`:
   - после готовности A-11 cleanup, но до `samovar_reset()`, публикации mode и `save_profile()` подготовить target default draft;
   - при failure завершить switch как terminal failure, оставить старые mode/program/profile и снять transition/barrier;
   - при success опубликовать mode и commit-ить valid draft до снятия barrier.

Текущий `bool switch_samovar_mode()` не различает «ещё выполняется» и terminal failure. После стабилизации A-11 заменить его результат на явный enum, например:

```cpp
enum ModeSwitchResult : uint8_t {
  MODE_SWITCH_PENDING,
  MODE_SWITCH_SUCCEEDED,
  MODE_SWITCH_FAILED,
};
```

При `MODE_SWITCH_FAILED` loop также удаляет pending draft, предназначенный для несостоявшегося target mode; применять его к старому режиму запрещено.

## 3. POD pending pipeline

### `Samovar.ino`

Удалить:

- `String pending_program_str`;
- использование `pending_program_mode` как единственного payload/flag;
- локальный `String pstr`;
- loop-side вызовы `set_program(pstr)`, `set_beer_program(pstr)`, `set_dist_program(pstr)`, `set_nbk_program(pstr)`.

Добавить один slot:

```cpp
PendingProgramUpdate pending_program_update{};
```

Он не должен быть `volatile`: чтение и запись выполняются только под `pending_command_lock`; `action != PROGRAM_UPDATE_NONE` означает занятость.

Loop-side порядок:

1. Под lock скопировать весь POD в локальный payload и снять slot.
2. Не consume-ить его, пока выполняется связанный `pending_switch_mode_flag`.
3. После unlock повторно проверить `program_update_session_active()`.
4. Проверить `update.targetMode == Samovar_Mode`.
5. Active-session race или mode mismatch: явное предупреждение, старый program неизменен, retry запрещён.
6. `PROGRAM_UPDATE_REPLACE`: один `program_commit(update.draft)`.
7. `PROGRAM_UPDATE_CLEAR`: только explicit `program_clear()`.
8. Неизвестный action: fail-closed, без commit.

### `WebServer.ino`

Обновить:

```cpp
static bool queue_pending_program(const PendingProgramUpdate& update);
static bool pending_program_slot_busy();

static bool queue_pending_setup_save(
    const PendingSetupSave& setupSave,
    const PendingProgramUpdate* programUpdate,
    bool hasSwitchMode,
    SAMOVAR_MODE switchMode,
    const char*& busyText);
```

Правила:

- request parsing выполняется до lock;
- под mutex копируется только проверенный POD;
- queue не принимает `PROGRAM_UPDATE_NONE`;
- `/save` и `/program` разделяют один busy slot;
- raw request string после parser нигде не сохраняется.

## 4. `/program`: prevalidation и explicit clear

`WebServer.ino::web_program()` должен определять и полностью проверять действие до queue и до изменения program state.

Разрешено:

- ровно один `WProgram`;
- либо отдельный exact `clear=1`;
- либо отсутствие program action для существующих `Descr`/`vless`.

Строгие правила:

- `clear=`, `clear=0`, `clear=true`, duplicate `clear` — `400`;
- `clear` вместе с `WProgram` — `400`;
- clear рекомендуется не совмещать с `Descr`/`vless`, чтобы это было отдельное действие;
- empty/blank-only `WProgram` — parse error, а не clear;
- invalid input возвращает `400 application/json` с точной причиной/строкой;
- pending busy — `503`;
- уже активная сессия — `409`;
- при valid replace в slot попадает draft;
- при valid clear в slot попадает только clear action;
- accepted async action возвращает `202`, не `200`: это «валидировано и поставлено в очередь», а не terminal success.

До W2 сохранить малый JSON-контракт `{ok, err, program}` и не создавать временный result endpoint. UI не должен называть `202` фактической установкой.

## 5. `/save`: compound prevalidation

`WebServer.ino::handleSave()`:

1. Сохранить раннюю проверку pending/active-session, если присутствует `WProgram`.
2. Разобрать mode через единый strict A-10 parser.
3. Разобрать setup-поля только в локальный `PendingSetupSave`.
4. При `WProgram` выбрать формат по `requestedMode`, если mode меняется, иначе по текущему mode.
5. Разобрать программу в локальный draft до `queue_pending_setup_save()`.
6. Parse failure возвращает `400`; ни setup, ни mode, ни program flag не устанавливаются.
7. В queue передаётся `PendingProgramUpdate`, не текст.
8. Empty `WProgram` отвергается.
9. `clear` в `/save` не поддерживать молча: отдельная очистка выполняется через `/program clear=1`.

NVS/RAM transaction, persistence rollback и terminal result не входят в A-09; это A-12/W2.

## 6. UI explicit clear

### `data/app.js`

Добавить общий helper, который:

- показывает подтверждение;
- создаёт новый `FormData` только с `clear=1`;
- не сериализует форму с `WProgram`;
- использует тот же строгий JSON parser;
- отображает `400/409/503`;
- на `202` сообщает только «очистка принята в обработку».

### Основные редакторы

Добавить отдельную кнопку очистки рядом с установкой программы:

- `data/index.htm`;
- `data/beer.htm`;
- `data/distiller.htm`;
- `data/bk.htm`;
- `data/nbk.htm`;
- `data/program.htm`.

`brewxml.htm` и `setup.htm` не являются основными UI очистки. Любое web-изменение проверяется через `playwright-cli`.

## Failure matrix

| Сценарий | Результат | `program[]`/`ProgramLen` | Pending |
|---|---|---|---|
| Валидный rect/dist/beer/NBK | `202`, затем loop commit | меняются только в loop | снимается после consume |
| Empty/blank WProgram | `400` | byte-for-byte прежние | не создаётся |
| Input > 1024 | `400` | прежние | не создаётся |
| Bad type/field count/number | `400`, точная строка | прежние | не создаётся |
| NaN/Inf/overflow | `400` через A-10 | прежние | не создаётся |
| NBK не H/S/O/W или не 4 строки | `400` | прежние | не создаётся |
| `clear=1` | `202`, затем `program_clear()` | `ProgramLen=0`, tail `WType=NONE` | снимается |
| Invalid/duplicate clear | `400` | прежние | не создаётся |
| WProgram + clear | `400` | прежние | не создаётся |
| Slot занят | `503` | прежние | прежний slot сохранён |
| Сессия активна до queue | `409` | прежние | не создаётся |
| Сессия стартовала после `202` | loop warning/failure | прежние | consume без retry |
| Mode изменился до apply | loop warning/failure | прежние | consume без retry |
| Built-in default invalid при boot | exact error + A-11 latch | прежние/пустые | нет |
| Target default invalid при switch | terminal switch failure | старые mode/program | target pending удаляется |

## Тесты

### Host behavioral

Расширить `tools/smoke_program_atomic.py`:

- round-trip четырёх форматов и всех built-in defaults;
- mode-to-format table и unsupported mode;
- NBK Result signature;
- полный `memcmp` массива и `ProgramLen` на каждой ошибке;
- CRLF, blank rows, max rows, extra row, bad type, NaN/Inf/overflow;
- explicit clear;
- `sizeof(ProgramDraft) == 564`;
- `sizeof(PendingProgramUpdate) <= 576` и trivially-copyable contract.

### Static/pipeline contracts

- `tools/smoke_program_io_contract.py`: все четыре Result wrappers, проверяемый default loader, отсутствие parser duplication.
- `tools/smoke_api_routes.py`: preparse до queue, exact clear, `202`, active/mode checks до commit, отсутствие loop setter/parser.
- `tools/smoke_handle_save_staging.py`: draft до compound queue, POD payload вместо String.
- `tools/smoke_shared_state_strings.py`: удалить старые положительные ожидания и запрещать `pending_program_str` в production.
- `tools/smoke_safety_timing.py`: новый terminal mode-switch result, target default parse до публикации mode, barrier снимается после valid commit.
- Рекомендуемый новый `tools/smoke_program_update_pipeline.py`: behavioral queue/active/mode/clear failure matrix, а не только shape tokens.

### Browser

Playwright desktop/mobile matrix:

- cancel confirmation не отправляет request;
- accept отправляет ровно `clear=1`, без `WProgram`;
- `202/400/409/503` отображаются честно;
- ни одна страница не считает `202` terminal success;
- console clean.

### Общие gates

1. Targeted A-09 tests.
2. Полный `tools/run_smoke_tests.py`.
3. `pio run -e Samovar`.
4. `pio run -e Samovar_s3`.
5. Blocking cppcheck.
6. `git diff --check`.
7. `rg pending_program_str` не находит production use.
8. Codebase-map metadata обновлены.
9. Отдельный reviewer-loop до `PASS: no errors, no warnings`.

## Память и stack budget

Из текущего ESP32 ELF:

- `sizeof(WProgram) == 28`;
- `sizeof(ProgramDraft) == 564`;
- `sizeof(SetupEEPROM) == 516`;
- `sizeof(PendingSetupSave) == 524`;
- frame `program_parse_lines(..., draft)` — 1088 байт из-за `char input[1025]`;
- текущий frame `handleSave()` — 656 байт;
- текущий frame `web_program()` — 112 байт;
- текущий frame `loop()` — 752 байта;
- AsyncTCP stack — 4096 байт;
- Arduino loop stack — 8192 байта.

После добавления локального draft ориентировочный call chain `handleSave -> parser` — около 2,3 КБ без library frames. Acceptance:

- повторно измерить compiler `entry` frames после сборки;
- проверить runtime high-water mark на максимальном `/save` и `/program`;
- сохранить минимум 1024 байта AsyncTCP stack headroom;
- payload cap 576 байт;
- не держать два локальных `ProgramDraft` в одной функции.

## Граница с A-10, A-11 и W2

### Выполняется сейчас в A-09

- NBK Result wrapper/API;
- checked default loader и все call sites;
- route-side mode-specific prevalidation;
- POD draft/clear pending;
- explicit `clear=1` и UI;
- loop active-session/mode race recheck;
- byte-stable failures;
- fail-closed default/mode-switch result;
- честный `202 queued`;
- host/static/browser coverage.

### A-10

- A-09 использует только `numeric_parse.h` finite/bounded helpers;
- `toInt()/toFloat()` в затронутом program path не возвращаются;
- `vless` остаётся частью A-10, но его validation должна выполняться до любых side effects совместного `/program` request.

### A-11

- Использовать единственный существующий emergency latch и mode-switch barrier;
- не создавать второй safety path;
- изменения mode-switch выполнять только после reviewer PASS A-11 и затем повторно прогнать его tests/review.

### Граница с W2/A-12 и A-06

Не создавать в A-09:

- `OperationStore` и operation ID;
- terminal polling/result endpoint;
- временный второй lifecycle API;
- NVS transaction/journal/rollback;
- единый tagged config union с `SetupEEPROM`;
- UI-ожидание `succeeded/failed`.

W2 может связать operation ID и terminal result с уже существующим типизированным
`PendingProgramUpdate`, но не возвращает raw String/reparse и не меняет
`ProgramParseError + lineNumber`. По решению пользователя state-changing GET
сохраняются; W2 не добавляет security-контур.

## Точный write scope реализации

Production:

- `program_types.h`;
- `program_io.h`;
- `logic.h` только если требуется синхронизация уже изменённой signature;
- `distiller.h` только если требуется синхронизация уже изменённой signature;
- `beer.h` только если требуется синхронизация уже изменённой signature;
- `nbk.h`;
- `sensorinit.h`;
- `samovar_api.h`;
- `Samovar.ino`;
- `WebServer.ino`;
- `mode_registry.h` только для согласования program-owner/mode-switch result;
- `data/app.js` и перечисленные шесть program pages.

Tests:

- `tools/smoke_program_atomic.py`;
- `tools/smoke_program_io_contract.py`;
- `tools/smoke_api_routes.py`;
- `tools/smoke_handle_save_staging.py`;
- `tools/smoke_shared_state_strings.py`;
- `tools/smoke_safety_timing.py`;
- новый focused pipeline/browser test при необходимости.

Не входят в A-09: `FS.ino`, `NVS_Manager.ino`, `operation_store.h`, profile persistence format, unrelated UI/theme refactor.

## Codebase map

После реализации обновить `Last reviewed` в затронутых nodes:

- `program-types-h.md`;
- `program-io-h.md`;
- `samovar-api-h.md`;
- `nbk-h.md`;
- `sensorinit-h.md`;
- `samovar-ino.md`;
- `webserver-ino.md`;
- `mode-registry-h.md` при изменении;
- `logic-h.md`, `distiller-h.md`, `beer-h.md` при изменении;
- `tools.md`;
- `data.md` при UI clear.

## Reviewer acceptance

Reviewer должен вернуть `PASS: no errors, no warnings` только если:

- NBK wrapper и API возвращают и не теряют `ProgramParseResult`;
- все default-load call sites проверяют result;
- неизвестный mode не получает неявный rect fallback;
- `/program` и `/save` разбирают draft до queue;
- raw `pending_program_str` полностью удалён;
- `loop()` не вызывает parser/setter и commit-ит только validated POD;
- active-session и target-mode race не меняют program;
- invalid/oversize/NaN/NBK-count failure сохраняют весь старый массив и len byte-for-byte;
- clear возможен только через exact `clear=1`;
- HTTP до W2 сообщает только `queued`, не terminal success;
- default/mode-switch failure не публикует частичный mode/program state;
- A-10 parser и A-11 barrier не обходятся;
- stack/BSS acceptance выполнен;
- targeted/full smoke, обе PIO-сборки, cppcheck, Playwright и `git diff --check` зелёные.

## Использованные skills

- `dev-experts`, persona `architect`: file/symbol architecture, alternatives, failure boundaries и reviewer acceptance.
- `97-dev`: минимальный POD-контракт, отсутствие второго источника истины, fail-fast/fail-closed и behavioral test discipline.
