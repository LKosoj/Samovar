# A-06 — строгий контракт существующих GET

## Цель, решение и неподвижная граница

Закрыть дефекты формы запроса и кеширования у уже существующих state-changing GET без изменения transport, внешних имён и пользовательской функциональности. Итог A-06 формулируется только так: `contract mitigation PASS; state-changing GET replay risk accepted by user`. Исходную REST-проблему нельзя объявлять полностью исправленной, потому что пользователь осознанно сохраняет GET.

| Route | Единственный method |
|---|---|
| `/command` | `HTTP_POST` |
| `/program` | `HTTP_POST` |
| `/save` | `HTTP_POST` |
| `/calibrate` | `HTTP_GET` |
| `/i2cpump` | `HTTP_GET` |
| `/i2cstepper` | `HTTP_GET` |
| `/lua` | `HTTP_GET` под `USE_LUA` |

Не добавлять POST-миграцию, новый route/UI/action, auth/session/token, CSRF/Origin/Referer gate, idempotency key, prefetch-защиту, task, queue, retry, fallback, shim или compatibility layer. `/lua` не получает `OperationStore`, `operationId`, `/ajax` lookup либо отдельный lifecycle. A-02 lifecycle `/calibrate`, `/i2cpump` и команд `/i2cstepper` остаётся неизменным; status `/i2cstepper` остаётся синхронным `200`.

Из рассмотренных подходов:

1. миграция mutating GET на POST действительно устранила бы REST-дефект, но прямо запрещена подтверждённой границей;
2. общий middleware или `OperationStore` для `/lua` добавил бы архитектуру и функциональность без необходимости;
3. выбран минимальный вариант: одна inline-проверка точной формы `/lua`, единый существующий no-store writer и усиление регрессионных тестов. Numeric GET production-код не меняется.

## Обязательный prerequisite и проверенный live baseline

A-06 можно начинать только после одновременной проверки четырёх источников истины:

1. `.claude/experts/plans/samovar-a02-i2c-results.md` содержит итоговый независимый `PASS: no errors, no warnings`;
2. обе master-ledger строки A-02 имеют статус `PASS`, а не `in progress`/`planned`;
3. nodes `webserver-ino`, `samovar-ino`, `operation-store-h`, `data`, `tools` отражают принятый A-02 lifecycle;
4. в живом коде существуют четыре A-02 reserve owner (`queue_pending_i2cstepper`, `queue_pending_i2cpump`, `queue_pending_i2ccal`, `queue_pending_local_cal`), `OperationId` в pending DTO, `send_i2c_operation_accepted()`, `/ajax?operationId=...` и `SamovarApp.waitForOperation()` в обоих I2C/calibration UI.

На момент уточнения плана 2026-07-13 все четыре проверки пройдены. Перед первым production patch исполнитель повторяет их по живому дереву. При любом несовпадении он останавливается и обновляет план; создавать второй путь или shim запрещено.

Текущий live baseline также подтверждает, что `calibrate_command()`, `handle_i2c_pump_request()` и `handle_i2c_stepper_request()` уже выполняют allowlist/cardinality/source/numeric validation до A-02 reserve, а их responses уже идут через no-store helpers. Эти обработчики считаются соответствующими A-06 и остаются production read-only.

## Точный `/lua` contract

Меняется только тело существующего inline `server.on("/lua", HTTP_GET, ...)` в `WebServer.ino::WebServerInit()`:

| Форма запроса | Действие | Ответ |
|---|---|---|
| `request->params() == 0` | существующий `queue_pending_flag(pending_lua_start_flag)` | `200 text/html OK` или `503 text/plain BUSY` |
| ровно один query-параметр `script`, `!isPost()`, `!isFile()` | существующий `queue_pending_string(pending_lua_file_flag, pending_lua_file, value)` | `200 text/html OK` или `503 text/plain BUSY` |
| любая другая форма | ни одна queue-функция не вызывается | `400 text/plain BAD_REQUEST` |

К «любой другой форме» относятся unknown name, duplicate `script`, `script` вместе с другим полем, POST-body parameter, file parameter и null parameter при ненулевом `params()`. Проверка формы полностью завершается до queue. Пустой query `?script=` считается ровно одним допустимым `script` и передаёт пустое значение в прежнюю file queue: содержимое/семантика Lua не меняются.

Все `200/400/503` ветки `/lua` используют существующий `send_no_store_response()` и получают `Cache-Control: no-store`. Не читать SPIFFS, не запускать Lua и не менять pending/Lua state непосредственно в async handler. Не менять queue helpers, flags, loop consumer, `lua.h`, status codes, media types или тела успешного/busy ответа.

## Write allowlist реализации

- production: только inline-hunk `/lua` в `WebServer.ino`; остальные строки файла и все numeric GET handlers read-only;
- tests: `tools/smoke_api_routes.py`, `tools/smoke_numeric_misc_routes.py`, новый `tools/smoke_lua_get_contract.py`, `tools/test_i2c_operation_results_browser.py` только для method trace/assertions; fixture-contract exception: в `tools/ui_pack_assets_contract.py` разрешена только замена значения `A10_FREEZE_AGGREGATE_SHA256` на `4ad332e05534c1b52ec48feea67e0b7cdb9d897d9528256e8f1906b580c53901`;
- map после зелёных gates: `.cli-proxy/.codebase_map/nodes/webserver-ino.md`, `.cli-proxy/.codebase_map/nodes/tools.md` и `.cli-proxy/.codebase_map/TESTING.md`; в `.cli-proxy/.codebase_map/INDEX.md` проверить и точечно обновить только строку `tools`, потому что новый smoke меняет file count; targeted state/graph entry — только если этого требует `update-node`;
- ledgers только после независимого reviewer PASS: этот plan и только строки A-06 в `.claude/experts/plans/samovar-audit-remediation.md` и `.claude/experts/plans/samovar-remaining-remediation-2026-07-12.md`.

Production read-only: `calibrate_command()`, `handle_i2c_pump_request()`, `handle_i2c_stepper_request()`, `send_i2c_stepper_json()`, A-02 queue/DTO/lifecycle code. Полностью read-only: `data/**`, `Samovar.ino`, `operation_store.h`, `Samovar.h`, `samovar_api.h`, `lua.h`, `I2CStepper.h`, numeric headers, NVS/profile code, libraries и build config. В `tools/ui_pack_assets_contract.py` все значения кроме одной разрешённой `A10_FREEZE_AGGREGATE_SHA256` read-only: не менять `_A10_PATHS`, `EXPECTED_RAW_SOURCE_TREE_SHA256`, input hashes, totals, limits, paths или algorithms; `tools/fixtures/**`, `web_src/**`, manifests и raw tree также read-only. `/i2cpump` и `/lua` не получают UI caller; поэтому gzip/manifest/raw-tree hashes и totals не меняются.

Перед patch сохранить scoped diff allowlisted файлов. Чужую dirty worktree не форматировать, не очищать и не включать в rollback.

## Детальный test plan

### 1. Единственный route inventory

В `tools/smoke_api_routes.py` задать одну таблицу семи routes из верхней таблицы. Для каждого route выполнять точный `re.findall(...)` по исходному `WebServer.ino` и требовать `matches == [expected_method]`. Это одновременно ловит отсутствие, неверный method и duplicate registration. Set/dict-агрегацию, которая схлопывает одинаковые дубликаты, для этих routes удалить.

Из `tools/smoke_numeric_misc_routes.py` удалить устаревший `route_methods` block и `import re`, если после удаления он больше не используется. Остальные numeric wiring/hash проверки не ослаблять и не переносить: один факт имеет одного test owner.

### 2. Новый behavioral `/lua` gate

Создать `tools/smoke_lua_get_contract.py`. Test должен извлекать из production source фактическое тело inline `/lua` handler, включать его без копирования алгоритма в временный host C++11 harness с минимальными mock `AsyncWebServerRequest`/parameter/response и stub существующих queue/no-store helpers, затем компилировать и выполнять harness.

Матрица обязана проверить:

- zero params: одна start queue, ноль file queue, success `200 text/html OK`, no-store;
- один непустой и один пустой query `script`: одна file queue с byte-exact value, ноль start queue, success `200 text/html OK`, no-store;
- busy отдельно для start и file: ровно одна соответствующая queue attempt, `503 text/plain BUSY`, no-store;
- unknown, duplicate, mixed, POST, file и null parameter: `400 text/plain BAD_REQUEST`, no-store, обе queue counters равны нулю, оба pending values неизменны;
- handler не содержит `OperationId`, `operation_store`, `/ajax`, `run_lua_script`, `load_lua_script`, SPIFFS access, новый queue/task/retry/fallback.

Компиляция: C++11 с warnings-as-errors. Harness должен падать по конкретной форме запроса, status/content/body/header либо side-effect count; substring-only «тест наличия токенов» не считается behavioral gate.

### 3. Numeric/A-02 regression

Существующие static gates подтверждают без production edits:

- `/calibrate`: точный `pump/start|finish/stpstep`, взаимоисключающая cardinality, query-only source, finite/bounds и validation до `queue_pending_local_cal()`/`queue_pending_i2ccal()`;
- `/i2cpump`: только `stop` либо ровно `speed+volume`, query-only source, validation до `queue_pending_i2cpump()`;
- `/i2cstepper`: allowlist `device/cmd/relay/state` плюс config fields, duplicate/unknown/wrong-source reject до `queue_pending_i2cstepper()`;
- reject не резервирует operation и не меняет pending state; accepted/terminal контракт остаётся ровно A-02; все response exits имеют no-store.

Если этот gate обнаружит реальный numeric production defect, A-06 немедленно останавливается: расширять production scope молча нельзя, нужен отдельный evidence и перепланирование.

### 4. Обязательный browser method trace

В существующем `tools/test_i2c_operation_results_browser.py` расширить только fetch instrumentation. Effective method вычислять в порядке `options.method` → `Request.method` → default `GET`, нормализовать к upper-case и сохранять вместе с URL. Для каждого наблюдаемого запроса assert exact `GET`:

- `/calibrate?...` mutation;
- `/i2cstepper?...` action и status read;
- `/ajax` и `/ajax?operationId=...` read/terminal lookup.

Trace обязан падать при любом non-GET, неожиданном route или запросе к `/i2cpump`/`/lua`. Отдельный source inventory по `data/**/*.{htm,js}` подтверждает отсутствие UI callers `/i2cpump` и `/lua`; новые browser-сценарии для несуществующего UI не добавлять. Сохранить все 15 A-02 сценариев, terminal wait, failure/timeout без повторной mutation и ноль console/page errors. Запускать через обязательный `playwright-cli`.

### 5. Механическое обновление A10 freeze

`tools/ui_pack_assets_contract.py::_A10_PATHS` уже включает `WebServer.ino`, поэтому единственный production hunk `/lua` закономерно меняет eight-file aggregate при неизменных browser/UI assets. После production/test patch независимо пересчитать агрегат по существующему `_A10_PATHS` и подтвердить точное значение `4ad332e05534c1b52ec48feea67e0b7cdb9d897d9528256e8f1906b580c53901`. Затем заменить только `A10_FREEZE_AGGREGATE_SHA256`; список восьми путей, все остальные constants/totals/fixtures/data/manifests и алгоритм `_verify_a10()` не менять.

Сразу после этой единственной constant update выполнить `python3 tools/smoke_ui_pack_assets.py`. Gate обязан подтвердить новый A10 aggregate и одновременно прежние raw source tree SHA, manifest hashes, UI totals, path inventory и LittleFS budget. Любой иной drift означает ошибку scope и останавливает A-06; обновлять дополнительные freeze/constants под результат запрещено.

После gates обновить test inventory в `.cli-proxy/.codebase_map/TESTING.md` по живому дереву: ровно `55` runnable smoke contracts и `5` browser contracts. Browser suite перечислить полностью: `tools/test_i2c_operation_results_browser.py`, `tools/test_i2c_pump_ui_browser.py`, `tools/test_numeric_input_ui_browser.py`, `tools/test_profile_operation_ui_browser.py`, `tools/test_program_clear_ui_browser.py`. Удалить все устаревшие утверждения про `50` smoke, три browser-контракта или suite из трёх scripts. В `.cli-proxy/.codebase_map/INDEX.md` пересчитать `tools/**` тем же способом, который использует node inventory, исключая transient `tools/__pycache__/**`; ожидаемый A-06 delta — с текущих `162` durable files до `163` после добавления `smoke_lua_get_contract.py`. Если live count отличается, сначала сверить состав файлов и отразить фактическое число, не запускать full map regeneration.

### 6. Gates

Targeted, последовательно:

1. `python3 tools/smoke_lua_get_contract.py`;
2. `python3 tools/smoke_api_routes.py`;
3. `python3 tools/smoke_numeric_parse.py`;
4. `python3 tools/smoke_control_numeric_input.py`;
5. `python3 tools/smoke_numeric_i2c_contract.py`;
6. `python3 tools/smoke_numeric_misc_routes.py`;
7. `python3 tools/smoke_calibration_ux.py`;
8. `python3 tools/smoke_operation_store.py`;
9. `python3 tools/smoke_i2c_operation_results.py`;
10. `python3 tools/test_i2c_operation_results_browser.py` через `playwright-cli`;
11. после точечной A10 constant update — `python3 tools/smoke_ui_pack_assets.py`.

После успешного focused UI-pack gate обязательно заново запустить полный `python3 tools/run_smoke_tests.py`; ожидается `55/55`. Затем последовательно, не совмещая cppcheck и PlatformIO: blocking `python3 tools/run_cppcheck.py --timeout 180`, `pio run -e Samovar`, `pio run -e Samovar_s3`, `pio run -e Samovar_lua_mqtt`, `git diff --check`, write-allowlist audit и проверка отсутствия изменений `data/**`, manifests, `_A10_PATHS`, raw tree и totals. `Samovar_lua_mqtt` обязателен, потому что production hunk находится под `USE_LUA`.

## Порядок работы и review closure

1. Повторно проверить A-02 exact PASS, обе ledger строки, пять map nodes и live symbols из prerequisite; снять scoped baseline diff.
2. Запустить текущие targeted gates как baseline.
3. Изменить только inline `/lua` hunk.
4. Усилить exact route inventory, удалить duplicate test ownership, добавить source-extracted C++11 harness и browser method trace.
5. Выполнить targeted и browser gates; пересчитать A10 aggregate, заменить только разрешённую constant на точный SHA, выполнить focused `smoke_ui_pack_assets.py`, затем повторить full smoke до `55/55`, cppcheck, три build и diff/allowlist gates.
6. После зелёных gates обновить nodes `webserver-ino` и `tools` (в `tools` при необходимости описать новый Lua smoke и механический A10 SHA refresh из-за входящего в freeze `WebServer.ino`, явно указав неизменность paths/data/manifests/totals), общий `.cli-proxy/.codebase_map/TESTING.md` до фактических `55` smoke/`5` browser с полным списком пяти browser scripts и только строку `tools` в `.cli-proxy/.codebase_map/INDEX.md` до фактического file count; выполнить targeted `update-node`, а при ошибке — targeted `repair`, без full regeneration.
7. Независимый reviewer читает production, tests/fixture contract (включая exact one-line `A10_FREEZE_AGGREGATE_SHA256` diff в `tools/ui_pack_assets_contract.py`) и весь A-06 map diff (`nodes/webserver-ino.md`, `nodes/tools.md`, `TESTING.md`, targeted `INDEX.md` и только реально потребовавшиеся state/graph entries) вместе и проверяет отсутствие method/name drift, numeric production edits, новых routes/actions/tasks, security/idempotency/prefetch/fallback, Lua lifecycle, UI edits, дополнительных A10/raw/manifest changes и устаревших test counts.
8. Любой `ERROR`/`WARNING` исправляется в том же allowlist; затронутые gates и review повторяются до точного `PASS: no errors, no warnings`.
9. Только после этого обновить A-06 status/result/gates в двух master ledgers и итоговый блок этого plan. После ledger patch повторить `git diff --check` и scoped consistency check.

## Итог реализации — PASS

- Production diff ограничен телом существующего GET `/lua`: ноль параметров ставит прежний start flag, ровно один query `script` (включая пустой) ставит прежний file flag, все остальные формы получают `400 BAD_REQUEST` до queue; `200/400/503` используют `send_no_store_response()`.
- Numeric GET handlers, A-02 lifecycle, `data/**`, routes/methods, Lua consumer, security-контур и пользовательская функциональность не изменены. Единственное механическое fixture-изменение — новый A10 aggregate для входящего в него `WebServer.ino`; UI paths/data/manifests/totals/raw tree остались прежними.
- Gates: 9/9 targeted backend, focused UI-pack PASS, Playwright 15/15 с нулём console/page errors, полный smoke 55/55, blocking cppcheck exit 0 без error/warning diagnostics, PlatformIO `Samovar`/`Samovar_s3`/`Samovar_lua_mqtt` SUCCESS, py_compile/map/inventory/diff-check PASS.
- Карта синхронизирована с live inventory `163 durable tools / 55 smoke / 5 browser`; независимый reviewer вернул точный `PASS: no errors, no warnings`.
- Итог finding: `contract mitigation PASS; state-changing GET replay risk accepted by user`. Исходный REST-риск не объявляется полностью устранённым.

## Acceptance и rollback

A-06 принят только если одновременно выполнено:

- route methods и names byte-for-byte соответствуют таблице;
- numeric GET production остался неизменным и его A-02 validation/result/no-store gates зелёные;
- `/lua` принимает только `{}` или ровно один query `script`, включая прежнюю empty-string semantics;
- invalid `/lua` не вызывает queue, busy/success вызывают ровно одну правильную queue, все ответы no-store;
- browser доказывает exact GET для calibration/I2C/ajax и отсутствие `/i2cpump`/`/lua` callers;
- `TESTING.md` отражает ровно `55` runnable smoke и `5` browser contracts, перечисляет все пять текущих browser scripts и нигде не утверждает, что их три;
- targeted строка `tools` в `INDEX.md` совпадает с пересчитанным live inventory (ожидается `163` durable files после единственного нового smoke), а full map regeneration не выполнялся;
- `tools/ui_pack_assets_contract.py` отличается только новым `A10_FREEZE_AGGREGATE_SHA256=4ad332e05534c1b52ec48feea67e0b7cdb9d897d9528256e8f1906b580c53901`; focused `smoke_ui_pack_assets.py` и повторный full smoke `55/55` прошли, а `_A10_PATHS`, остальные constants/totals/fixtures/paths, `data/**`, manifests и raw tree неизменны;
- production diff равен одному inline `/lua` hunk, `data/**`/A-02 lifecycle не изменены;
- независимый reviewer вернул `PASS: no errors, no warnings`;
- ledger использует формулировку `contract mitigation PASS; state-changing GET replay risk accepted by user` и не заявляет полное исправление исходного REST finding.

Rollback — только обратный patch собственных A-06 строк в `/lua`, tests, map и ledgers. `git reset`, checkout и очистка чужих изменений запрещены. Не оставлять ослабленный inventory, validation после queue, direct response без no-store, частично обновлённые map/ledgers или новый fallback. Если strict contract требует менять method, UI, A-02 lifecycle либо иной production-файл, остановиться и вернуть evidence. Повтор одной ошибки дважды запускает обязательное web-исследование 3–5 решений до следующей попытки.
