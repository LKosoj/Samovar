# A-04 — транзакция текущих raw UI-файлов

## 1. Цель, зависимости и граница

A-04 выполняется только после полного PASS A-01. До начала разработки повторно проверить, что mount уже fail-closed, `WebServerInit()` имеет ранний FS guard, а существующий dirty tree не сброшен и не переформатирован.

Критерий готовности: после любой ошибки или перезагрузки до `server.begin()` существует ровно один пригодный к выдаче набор — byte-identical старый либо полностью проверенный новый. Смешанный набор routes не видит. Успешный путь использует один updater и один `server.begin()`.

В scope нет binary pack, A/B UI slots, второго раздела, изменения `partitions/samovar.csv`/`platformio.ini`, локального Ace, HTTPS/signature/trust anchor, security-hardening, нового route/UI/recovery CLI, task, retry, альтернативного transport или fallback. SHA-256 проверяет согласованность release-файлов, но не является контуром доверия.

Проверенный baseline:

- legacy-набор из 19 активных `SAVE_FILE_OVERRIDE` файлов занимает 329158 байт и не включает обязательные `app.js`, `chart.js`, `style.css` и `edit.htm`;
- исправленный transaction set состоит из 23 физических файлов и занимает 412357 байт;
- весь `data/` занимает 431835 байт;
- `data/` плюс полная staging-копия этих 23 файлов занимает 844192 байта ещё до LittleFS metadata, journal и runtime logs;
- активный LittleFS — `0xC0000`, то есть 786432 байта;
- сейчас `server.begin()` вызывается до `get_web_interface()`, а `write_web_file_atomic()` атомарен только для одного файла.

Следствие: staging всего набора запрещён. Полный candidate проверяется всегда, но скачиваются только отсутствующие/не совпавшие по exact size/SHA файлы.

## 2. Единственный manifest source

Authoring source — checked-in `web_src/ui-manifest-v1.json`. В нём добавить один строго schema-validated раздел `raw_update` с normalized UI version и отсортированными entries `{path, size, sha256}`. Его набор — ровно 23 взаимозависимых физических UI-файла: активные override-файлы, обязательные `app.js`/`chart.js` и обе половины реально выдаваемых raw/gzip пар `style.css(.gz)` и `edit.htm(.gz)`:

```text
Green.png Red_light.gif alarm.mp3 app.js beer.htm bk.htm brewxml.htm
calibrate.htm chart.htm chart.js distiller.htm edit.htm edit.htm.gz
favicon.ico i2cstepper.htm index.htm minus.png nbk.htm plus.png
program.htm setup.htm style.css style.css.gz
```

`size` — точный размер реально сохраняемых bytes, не maximum и не expanded size; `sha256` — digest этих же bytes. Version обязан совпадать с нормализованным `data/version.txt`. Existing P1.1 fields остаются неиспользуемым offline-контрактом и не становятся runtime pack.

Firmware не скачивает JSON manifest. `web_update.h` содержит checked-in typed projection только `raw_update`; host contract детерминированно строит ожидаемую projection из JSON/data и требует exact parity с header. Это устраняет новый deploy-артефакт и build-time frontend pipeline: обычная PlatformIO/Arduino сборка только компилирует header, а существующий HTTP host продолжает отдавать те же raw files по текущим URL. Несовпадение remote bytes с firmware projection даёт явный SHA/size failure до commit.

Runtime не нужен общий JSON parser: fixed table имеет compile-time bound, а перед использованием `validate_web_update_manifest()` повторно проверяет schema/version, count, root-only canonical paths, uniqueness с учётом case, exact nonzero sizes, SHA length и overflow сумм. Host negative tests покрывают malformed JSON, unknown field/path, duplicate, traversal, count/size overflow и stale projection. Ни JSON, ни pack index не хранятся в LittleFS.

Lua/default assets текущих `SAVE_FILE_IF_NOT_EXIST` остаются вне UI transaction и вне version marker:

```text
beer.lua bk.lua nbk.lua dist.lua init.lua rectificat.lua script.lua
btn_{rect,beer,dist,bk,nbk}_button{1,2}.lua
program_fruit.txt program_grain.txt program_shugar.txt
```

Они используют тот же единственный streaming download primitive, но отдельную seed-фазу без journal/rollback UI. Эта фаза запускается только в прежний update-triggered момент и сохраняет `SAVE_FILE_IF_NOT_EXIST`: удалённый пользователем Lua/default-файл не восстанавливается на каждом boot. Ошибка seed-файла диагностируется явно, не меняет уже подтверждённый UI marker и не создаёт второй updater implementation.

## 3. Реализация по символам

### `web_update.h`

Создать один корневой header с `inline` реализацией; `.cpp`, `src/`, код в `Samovar.h`, virtual backend, production test seam и heap-копия manifest запрещены.

Минимальные типы: bounded `WebUpdateEntry`, fixed `WebUpdateManifest`, `WebUpdateResult`, малые `WebUpdateJournalHeader`/`WebUpdateJournalRecord`. Manifest paths и SHA хранятся во flash; рабочие buffers фиксированы. Полного journal object в RAM нет.

Один startup orchestrator выполняет строго этот порядок:

1. До любых FS mutations целиком проверить typed manifest и его projection: version, количество, уникальность/path allowlist, bounded sizes и SHA. Invalid projection возвращает terminal result без recovery, cleanup или иных записей.
2. Только с уже проверенной projection вызвать `recover_web_update_transaction()`; recovery завершается до сети, регистрации handlers/routes и `server.begin()`.
3. Прочитать local marker, потоково посчитать size/SHA всех 23 finals и сформировать bounded changed-index array. Совпавшие finals остаются на месте; path из сети никогда не определяет имя файла.
4. До первого `remove/open/rename` вычислить conservative LittleFS bound: сумма allocation-rounded changed payloads + maximum journal/version bytes + доказанный metadata/GC reserve для active LittleFS geometry. Сравнить с `totalBytes-usedBytes` checked arithmetic. Сам reserve фиксируется только после capacity-теста exact operation sequence; непроверенная magic margin запрещена. Недостаток места возвращает `NO_SPACE` с `free/required` и нулём FS mutations; logs/runtime files не удаляются.
5. Для каждого changed entry открыть обычный HTTP 200 response по существующему base URL, потребовать присутствующий и строго распарсенный exact `Content-Length`, отклонить chunked/unknown length, затем polling-ом `asyncHTTPrequest::available()`/`responseRead()` читать bounded chunks прямо в уникальный reserved staging path и одновременно обновлять byte counter и SHA-256. `responseText()`, payload `String`, чтение из `onData` callback и buffered whole-file path запрещены: `onData` исполняется под внутренним lock библиотеки, и повторный `responseRead()` там может заблокироваться. Short/extra read, timeout, write/close/reopen/size/SHA failure удаляет только staging и сохраняет finals/marker.
6. Повторно проверить полный candidate: каждый unchanged final и каждый changed staged file обязан совпасть с manifest. Только затем создать и read-back проверить journal.
7. Выполнить rename commit, повторно size/SHA проверить все 23 finals, затем атомарно записать version marker последним.
8. После подтверждённого marker удалить backups/staging и journal; только после successful recovery/cleanup разрешить `server.begin()`.
9. Только если существующий update-trigger действительно сработал, после подтверждённой UI-транзакции выполнить прежние `SAVE_FILE_IF_NOT_EXIST` seed-вызовы; отсутствие update-trigger оставляет seed-файлы нетронутыми.

Reserved имена используют уже зафиксированный manifest namespace `/.ui-*` и не пересекаются с user/editor tmp: `/.ui-wu-journal`, `/.ui-wu-journal.tmp`, `/.ui-wu-new-N`, `/.ui-wu-old-N`, `/.ui-wu-version.tmp`, `/.ui-wu-version.old`. Очистка работает только с этим allowlist; новый namespace и generic `*.tmp`/`*.bak` scan запрещены.

### Journal и recovery

Journal появляется только после полного staging/candidate verify и непосредственно перед первым final rename. Он содержит magic/schema, candidate version, changed count, old/new metadata самого version marker, для каждого changed index — `hadFinal`, old size/SHA и new size/SHA — плюс CRC всего journal. Формат сериализуется явно с фиксированным byte order: небольшой header и по одной bounded record; raw C++ struct с padding, чтение/запись всего journal одним stack object и heap-копия запрещены. Progress-журнал и active-slot pointer не нужны: по fixed names, presence и hashes recovery однозначно распознаёт состояние каждой пары. После реализации измерить stack/BSS delta; main-task stack не расходуется на массив всех records.

До любого recovery-rename journal сверяется с уже проверенной projection: candidate version обязан совпадать, каждый changed index обязан быть bounded и уникальным, а записанные new size/SHA — точно совпадать с соответствующей manifest entry. Stale/cross-projection journal, duplicate/out-of-range index или metadata mismatch дают terminal result без rename/remove/cleanup и без иных FS mutations.

Commit для entry: `final -> old`, затем `new -> final`; rename не копирует payload. Новый commit считается подтверждённым только если marker равен target version **и** все 23 finals совпадают с target size/SHA. Один marker недостаточен, потому что old/new наборы уже могут иметь одинаковую строку `6.27.5`. При любом другом journal-state recovery откатывает все changed entries и version marker к записанным old hash/absence. После подтверждённого full-candidate recovery только завершает cleanup; назад к old уже не переключается. Journal удаляется последним, после backups.

Reboot до создания journal обрабатывается отдельно: при отсутствующем journal можно удалить только известные `/.ui-wu-new-*` и `/.ui-wu-*.tmp`; любой `/.ui-wu-old-*` или `/.ui-wu-version.old` без валидного journal — terminal fatal. Невозможность удалить известный staging/tmp также блокирует `server.begin()`. Никакие finals/marker без journal recovery не переименовываются.

Invalid/нечитаемый journal, невозможный state, rollback/cleanup/hash failure — terminal fatal diagnostic без `server.begin()`. Восстановление только внешнее существующее `uploadfs`/перепрошивка; format, retry, recovery route или выдача сомнительных files не добавляются.

### `WebServer.ino`

- Сразу после A-01 FS guard вызвать единственный orchestrator **до** `FS_register_web_handlers()` и до любой регистрации route/handler; route names/methods/bodies не менять. Только после не-terminal результата регистрировать handlers/routes и вызывать `server.begin()`. Расширить отдельный `WebServerInitResult` значением `WEB_SERVER_INIT_UI_UPDATE_FAILED`; не отображать updater failure как FS failure или молчаливый OK.
- Удалить updater-only `get_web_interface()`, sequential `updateFile` list, `get_web_file()`, `write_web_file_atomic()` и empty-body helper после перевода UI и seed callers. Общий HTTP helper, если у него есть не-updater callers, не трогать.
- No-space либо HTTP/staging/journal-creation failure до первого final rename разрешает запуск только после allowlisted cleanup и повторной проверки byte-identical pre-update set: непустой корректно нормализованный старый marker, все 23 существующих finals и отсутствие journal/reserved artifacts. Missing/corrupt marker, отсутствующий обязательный final, cleanup failure либо незавершённый recovery блокирует server; это не fallback на непроверенный UI.
- Не оставлять legacy и transaction callers одновременно; static gate требует один manifest, один downloader, один updater call и один `server.begin()`.

Точное отображение результата:

| `WebUpdateResult` outcome | `WebServerInitResult` / server |
|---|---|
| target marker + все 23 target hashes уже совпадают | `WEB_SERVER_INIT_OK`; updater unchanged; обычный startup |
| transaction commit и cleanup завершены | `WEB_SERVER_INIT_OK`; updated; обычный startup |
| no-space либо HTTP/staging/journal-creation failure произошёл до первого final rename; allowlisted cleanup успешен, а полный существующий 23-file set, marker и отсутствие artifacts повторно подтверждены byte-identical | явная `old set preserved` diagnostic, затем `WEB_SERVER_INIT_OK`; это сохранение существующего failure-поведения, не silent fallback |
| UI подтверждён, но update-triggered `SAVE_FILE_IF_NOT_EXIST` seed завершился ошибкой | явная seed diagnostic, без rollback UI/marker; `WEB_SERVER_INIT_OK` и server запускается |
| manifest/projection invalid, incomplete local set, recovery/journal/rollback/commit/final-verify/marker/cleanup terminal failure | `WEB_SERVER_INIT_UI_UPDATE_FAILED`; handlers/routes/server не запускаются |

`Samovar.ino` различает `WEB_SERVER_INIT_FS_UNAVAILABLE` и `WEB_SERVER_INIT_UI_UPDATE_FAILED`; для второго печатает точную `FATAL: normal startup halted: web interface unavailable` и остаётся в том же terminal boot loop. Ни один outcome не игнорируется.

## 4. Fault/reboot matrix

| Fault/reboot point | Обязательный итог до server start |
|---|---|
| manifest/projection invalid, duplicate, traversal, overflow | 0 writes; recovery/cleanup не запускаются; old set/marker byte-identical |
| stale/cross-projection journal, duplicate/out-of-range changed index, new metadata mismatch | terminal без rename/remove/cleanup; FS byte-identical |
| no space | 0 `remove/open-write/rename`; old set/marker byte-identical |
| HTTP status/length/open/read timeout/short/extra | только allowlisted staging cleanup; после подтверждения old set/marker и отсутствия artifacts — `old set preserved` |
| staging write/reopen/size/SHA fault | только allowlisted staging cleanup; после подтверждения old set/marker и отсутствия artifacts — `old set preserved` |
| journal tmp/write/read-back/CRC/rename fault до первого final rename | allowlisted journal/staging cleanup; после подтверждения old set/marker и отсутствия artifacts — `old set preserved` |
| fault/reboot до, между или после `final->old`/`new->final` | применить единое правило recovery: marker target + все 23 target hashes → all-new cleanup; иначе полный rollback к old |
| full-final verify failure до marker | rollback целиком к old |
| version tmp/old/final rename fault | marker target + все 23 target hashes → all-new cleanup; иначе rollback к old |
| reboot после нового marker, до backup/journal cleanup | только marker + все 23 target hashes подтверждают all-new; finish cleanup, оставить new marker |
| cleanup failure после нового marker | all-new сохраняется, но server не стартует; следующий boot повторяет cleanup |
| reboot без journal и только known staging/tmp | удалить known staging/tmp; cleanup failure блокирует server |
| reboot без journal при наличии old/version-old | fatal; server 0; finals не угадывать |
| corrupt journal, ambiguous files, rollback failure | fatal; server 0; никакого fallback/format |
| first-write Lua/default failure | UI transaction/marker не откатываются; явная diagnostic, без substitute file |

Каждый injected operation fault запускается также как simulated reboot: RAM state сбрасывается, fake flash сохраняется, затем вызывается только boot recovery. Acceptance invariant — `all-old XOR all-new`; mixed/unknown и `server.begin()` до invariant запрещены.

## 5. Точный write allowlist реализации

- новый `web_update.h`;
- `WebServer.ino` — только updater functions/call order перед `server.begin()`;
- `Samovar.ino` — только раздельная обработка `WEB_SERVER_INIT_UI_UPDATE_FAILED` в существующем startup gate;
- `samovar_api.h` — только добавление `WEB_SERVER_INIT_UI_UPDATE_FAILED` и удаление obsolete updater prototypes;
- `Samovar.h` — только удаление orphan `get_web_type` после удаления legacy updater;
- `web_src/ui-manifest-v1.json` и `web_src/schemas/ui-manifest-v1.schema.json` — только `raw_update` contract;
- `tools/ui_pack_assets_contract.py`, `tools/smoke_ui_pack_assets.py` — только strict raw-update/projection/data parity и active FS cap; механически обновить соответствующие строки `EXPECTED_CONTRACT_INPUT_SHA256`, а из-за изменения `WebServer.ino` — только `A10_FREEZE_AGGREGATE_SHA256`;
- `tools/smoke_web_file_writes.py` — заменить obsolete single-file contract на single-updater/order/absence gate;
- новый `tools/smoke_web_update_transaction.py` — behavioral host/fault/reboot/capacity harness;
- `tools/static_analysis_sources.json` — только inventory нового root header;
- metadata only: nodes для `WebServer.ino`, `Samovar.ino`, `Samovar.h`, `samovar_api.h`, `data`, `tools`, новый node `web_update.h`, новый/актуальный area-node `web_src`, `.cli-proxy/.codebase_map/TESTING.md` и `.cli-proxy/.codebase_map/INDEX.md`; graph/state обновлять только targeted mapper repair;
- после полного PASS: status/evidence A-04 в этом плане и обоих master-ledger — `.claude/experts/plans/samovar-audit-remediation.md` и `.claude/experts/plans/samovar-remaining-remediation-2026-07-12.md`.

Запрещены изменения `FS.ino`, `SPIFFSEditor.h`, `data/**`, libraries, routes/UI, `platformio.ini`, любых partition tables, P1.1 pack headers/fixtures/generators и Ace contour. Разрешённые hunks `Samovar.ino`, `Samovar.h` и `samovar_api.h` ограничены перечисленной cleanup/result wiring; иные runtime symbols не трогать. Если A-01 ещё требует пересекающийся hunk `WebServerInit()`, A-04 development не начинается до его PASS.

## 6. Gates, map, review и rollback

Минимальный порядок проверки:

```bash
python3 tools/smoke_web_update_transaction.py
python3 tools/smoke_web_file_writes.py
python3 tools/smoke_ui_pack_assets.py
python3 tools/smoke_api_routes.py
python3 tools/run_smoke_tests.py --timeout 60
pio run -e Samovar -t buildfs
pio run -e Samovar_s3 -t buildfs
python3 tools/run_cppcheck.py --timeout 180 --report /tmp/samovar-a04-cppcheck.txt
python3 tools/run_cppcheck.py --force --timeout 600 --report /tmp/samovar-a04-cppcheck-extended.txt
pio run -e Samovar
pio run -e Samovar_s3
pio run -e Samovar_lua_mqtt
pio run -e Samovar_no_power
pio run -e Samovar_rmvk
pio run -e Samovar_sem
pio run -e Samovar_alarm_button
git diff --check
```

Ожидаемый inventory после нового transaction smoke — `168 durable tools / 59 smoke / 6 browser`; новый `web_update.h` и фактически затронутая `web_src` область получают отдельные map nodes. Cppcheck и PlatformIO выполнять последовательно.

`buildfs` gate проверяет hard limit `0xC0000`, exact manifest files/hashes и отсутствие transaction artifacts в image. Firmware builds сохраняют linker maps; сравнить flash/IRAM/DRAM/BSS с pre-A-04 baseline, отдельно подтвердить, что descriptor остаётся const/flash, staging payload не попал в RAM и нет второго SHA/HTTP implementation.

`tools/smoke_web_update_transaction.py` обязан напрямую включать и компилировать production `web_update.h` в C++11 harness с test-only fake FS/HTTP/SHA environment и выполнять на нём всю fault/reboot matrix. Static/source gate отдельно доказывает порядок `validate projection -> recover journal -> network -> handlers/routes -> server.begin()`; behavioral gate покрывает stale/cross-projection journal, duplicate/out-of-range indices и metadata mismatch как terminal без FS mutations. Отдельно переписанный Python/C++ transaction coordinator может быть только вспомогательной oracle-моделью и не считается доказательством production-кода.

Перед production-ready PASS выполнить remote parity gate по существующему `http://web.samovar-tool.ru/6.27/`: все 23 URL обязаны вернуть `200`, exact `Content-Length` и SHA из projection. Проверенный planning snapshot пока блокирующий: remote marker — `6.27.5`, но `app.js`/`chart.js` возвращали `404`, а большинство изменённых HTML/CSS не совпадали по SHA. Fixture доказывает код, но не заменяет remote parity; без исправленного внешнего набора A-04 не объявляется завершённым.

Через обязательный стабильный изолированный `playwright-cli` на восстановленном valid device/fixture открыть существующие `/index.htm`, mode pages и `/chart.htm` после old-preserved и successful-new сценариев: нет 404/console errors, marker и все загруженные assets относятся к одному набору. Затем прогнать все существующие browser contracts. Новые страницы/controls отсутствуют.

После code/tests/build/browser/remote-parity PASS обновить только affected `Last reviewed`; для нового header создать/repair ровно его node, при сбое использовать targeted `update-node`/`repair`, затем проверить graph state. Reviewer читает весь task diff и требует: scope allowlist; no pack/slot/partition/security/fallback; точные 23 files; manifest source/projection parity; preflight до write; polling streaming size/SHA; journal только rename-phase и без whole-journal stack object; marker + all hashes; seed files вне transaction; recovery до server; legacy updater/orphan API отсутствуют. Завершение — только `PASS: no errors, no warnings`.

Rollback — обратный patch только A-04 hunks: новый header/tests и raw-update metadata удаляются, `WebServer.ino` возвращается к точному pre-A-04 updater состоянию без отката A-01 или чужого dirty work. Запрещены `git reset --hard`, checkout чужих файлов и массовая очистка. Если capacity bound, streaming API или journal recovery нельзя доказать на active LittleFS, остановиться с evidence; не добавлять full staging, partition resize, buffered fallback или второй updater.
