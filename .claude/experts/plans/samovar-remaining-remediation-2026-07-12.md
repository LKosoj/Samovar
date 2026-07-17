# Исполняемый план оставшейся доработки Samovar

## 1. Цель и граница

Цель — закрыть все оставшиеся активные пункты `ARCHITECTURE_CODE_UI_AUDIT_2026-07-11.md` проверенными исправлениями без добавления продуктового функционала.

Зафиксированные решения пользователя:

- существующие HTTP-методы и имена маршрутов сохраняются: `/command`, `/program`, `/save` остаются POST; `/calibrate`, `/i2cpump`, `/i2cstepper`, `/lua` остаются GET;
- Ace остаётся на CDN; локальный Ace, UI pack runtime, A/B UI slots и изменение partition table не возвращаются;
- editor shell `data/edit.htm` и `data/edit.htm.gz` заморожен byte-for-byte
  на SHA-256
  `26b7e41df2a0a0197a14b9cf129f808fd001e760df4ed7c16df7a35a10b03ce6` и
  `bef3ce7e5c68a3cef89643ae1a22b5130c49b9983a9b69b71ffdd272dbe153f5`;
  он не входит в U-06/U-03/U-04/U-05 и не меняется даже ради `lang`;
- A-15 и иной security-hardening исключены для домашнего устройства;
- уже реализованный `clear=1` сохраняется;
- допустимы только минимальные корреляционные поля `operationId/state/error` в существующих ответах и `/ajax`, а также sequence/cursor для существующих сообщений;
- не добавляются новые routes, экраны, режимы, управляющие действия, tasks, transport-ы, recovery UI/CLI, alarm acknowledge, retry/priority policy или frontend framework.

Проект остаётся Arduino-совместимым: проектные `.cpp` в подкаталогах и `src/` запрещены; новые firmware-owner модули могут быть только корневыми inline `.h`; реализации в `Samovar.h` запрещены.

## 2. Проверенный baseline

На момент составления плана:

- R2.0 OperationStore завершён: focused smoke, полный smoke 51/51, blocking cppcheck, ESP32/ESP32-S3 builds, codebase map и независимый review `PASS: no errors, no warnings`;
- A-12 P1 и P2 завершены и приняты reviewer с `PASS: no errors, no warnings`: single-blob persistence, fail-closed migration/boot, canonical field-wise payload, единый compound `ProfileOperationSlot`, atomic phase/reset, loop-owned terminal publication и UI terminal wait проверены;
- A-02 завершён и принят reviewer с `PASS: no errors, no warnings`: единый loop-side lifecycle, подтверждённые I2C/calibration results и UI terminal wait проверены;
- A-06 завершён и принят reviewer с `PASS: no errors, no warnings`: методы GET сохранены, строгая форма `/lua` и no-store закрыты без нового lifecycle/security/UI;
- A-01 завершён и принят reviewer с `PASS: no errors, no warnings`: один fail-closed `SPIFFS.begin(false)`, отдельный owner FS-handlers и ранний terminal boot gate проверены;
- A-04 локально завершён и принят reviewer с `PASS: no errors, no warnings`:
  transaction/capacity/build/browser gates зелёные; внешний remote CDN parity
  остаётся отдельным publication/final blocker, поэтому release-complete не
  объявлен;
- A-05 завершён и принят reviewer с `PASS: no errors, no warnings`: normal
  `/ajax` сериализуется из immutable request-local snapshot с сохранённым wire
  contract;
- A-07 завершён и принят reviewer с `PASS: no errors, no warnings`: checked Lua
  numeric narrowing, mode owner и доступные I2C failures проверены;
- завершены A-03, A-09, A-10, software-часть A-11 и U-01;
- U-02 и A-15 имеют пользовательский `WAIVED`, а не технический `PASS`;
- A-11 hardware latency на ESP32/ESP32-S3 остаётся непроверенной из-за отсутствия HIL-стенда;
- активный LittleFS-раздел — `0xC0000` (786432 байта);
- в дереве есть большой незакоммиченный diff предыдущих волн; он считается существующей работой и не может быть сброшен, переформатирован или перезаписан целиком;
- CI обнаруживает все first-party `tools/smoke_*.py`, собирает семь environments и использует blocking/extended cppcheck;
- editor использует CDN Ace; P1.1 `ui_pack_format.h`/`ui_pack_store.h` остаются неиспользуемыми тестовыми артефактами и не входят в новые runtime-пути.

## 3. Оставшийся ledger

| Пункт | Состояние | Зависит от | Итоговая проверка |
|---|---|---|---|
| R2.0 | PASS | — | 51/51 smoke, cppcheck exit 0, ESP32/ESP32-S3 SUCCESS, reviewer PASS |
| A-02 | PASS | OperationStore, A-12 complete | focused 10/10; smoke 54/54; Playwright A-02 15 + numeric 36/9; cppcheck; 7/7 env; stack/UI asset/map/diff PASS; HIL high-water not run |
| A-06 | PASS | A-02 | contract mitigation PASS; state-changing GET replay risk accepted by user; targeted 9/9 + UI pack; Playwright 15; smoke 55/55; cppcheck; 3/3 env; map/diff PASS |
| A-12 | PASS: P1 single blob + P2 compound operation | OperationStore | `PASS: no errors, no warnings`; focused 9/9; smoke 53/53; cppcheck; 7/7 env; Playwright; UI asset/format; diff-check |
| A-13 | PASS: no errors, no warnings | общий `/ajax` contract | smoke 56/56; stable isolated Playwright 6/6; cppcheck; 7/7 env; RAM/stack/map/diff PASS; HIL high-water not run |
| A-14 | PASS: no errors, no warnings | event/log path | production-derived + actual vendor queue harness; smoke 57/57; cppcheck blocking/extended clean; 7/7 env + Telegram/Blynk compile; stable isolated Playwright 6/6; map/vendor/config/diff PASS |
| A-01 | PASS: no errors, no warnings | W2 stable | focused mutation gate; smoke 58/58; cppcheck 0 error/warning; 7/7 env; stable isolated Playwright 6/6; targeted map/diff PASS; HIL not run |
| A-04 | local PASS: no errors, no warnings; release blocked externally | A-01 | focused transaction/capacity; smoke 59/59; cppcheck; buildfs 2/2; 7/7 env; stable isolated Playwright 6/6; map/diff PASS; remote CDN parity OPEN |
| A-05 | PASS: no errors, no warnings | W2/W3 | focused immutable snapshot/golden; smoke 60/60; cppcheck; 7/7 env; stable isolated Playwright 6/6; map/diff PASS |
| A-07 | PASS: no errors, no warnings | A-05, numeric parsers | focused Lua/numeric matrix; smoke 61/61; cppcheck; 7/7 env + expander feature build; map/diff PASS |
| U-06 | PASS: no errors, no warnings | A-04 local, A-05, A-07 | focused/derived PASS; smoke 62/62; isolated stable Playwright 7/7; buildfs 2/2 and 430349/786432 payload; blocking cppcheck zero warning/error; extended informational-only; 7/7 env; fixed-epoch clean builds byte-identical; map/diff PASS; external A-04 remote parity remains publication/final blocker |
| U-03 | PASS: no errors, no warnings | U-06 | focused 8/8; smoke 63/63; isolated Playwright 8/8 with contrast 60+6+160; buildfs 2/2 and 433187/786432 payload; cppcheck blocking clean/extended informational-only; 7/7 env; fixed-epoch clean builds byte-identical; raw-update 23/413709; map/diff PASS |
| U-04 | PASS: no errors, no warnings | U-06/U-03 | Playwright 168/168 and browser 9/9; smoke 64/64; buildfs 2/2; cppcheck clean; 7/7 env; fixed-epoch artifacts identical; LittleFS 434245/786432; raw-update 23/414767; map/diff PASS |
| U-05 | PASS: no errors, no warnings | U-06/U-03/U-04 | focused 8/8; accessibility 88/88 + actions 207/207 + uploads 12/12; visual 20/20; browser 10/10; smoke 65/65; buildfs 2/2; cppcheck clean; fixed-epoch artifacts 5/5 identical; 7/7 env; LittleFS 450742/786432; raw-update 23/431264; map/diff PASS |
| A-08 | PASS: no errors, no warnings | U-05 PASS, W4 frozen | A/B firmware/ELF/inventory byte-identical for ESP32/ESP32-S3; 7/7 env; buildfs 2/2; smoke 66/66; blocking/extended cppcheck clean; metadata/map/diff PASS |

## 4. Выбранные минимальные решения

### 4.1 Результат async-команд

Рассмотрены: новый `/operation` route; выдача всех операций в каждом `/ajax`; optional lookup через текущий `/ajax`. Выбран третий вариант: accepted response возвращает `202` и `operationId/state/error`, а клиент добавляет `operationId` к уже существующему `/ajax`. Это не создаёт route, не раздувает каждый telemetry-response и не требует server-side client sessions.

### 4.2 Persistence

Рассмотрены: оставить независимые NVS keys; A/B generations; один versioned blob. Выбран один blob `header + canonical SetupEEPROM fields + reserved zero bytes + CRC32`, записываемый одной `Preferences::putBytes()` и немедленно перечитываемый. Поля кодируются явно, поэтому CRC не зависит от padding C++-структуры; общий payload v1 остаётся 516 байт. A/B, active pointer, commit marker и dual write запрещены. Старые keys используются только когда blob точно отсутствует, для однократной migration; NVS read/type error не считается absence. Невалидный существующий blob не маскируется чтением legacy keys.

### 4.3 Сообщения

Рассмотрены: SSE; массив всех событий; одно следующее событие через текущие поля. Выбран минимальный третий вариант: единый fixed ring для web-message и console-log; клиент передаёт `messageCursor`, `/ajax` возвращает не более одного следующего события через существующий `Msg` либо `LogMsg` плюс `messageSequence`. Клиент продвигает собственный cursor. Разрыв sequence явно показывает overflow; server-side sessions и acknowledge отсутствуют.

### 4.4 Web updater

Binary pack и A/B UI slots исключены. Typed projection сначала проверяет весь
candidate set: ровно 23 реально выдаваемых raw/gzip UI-файла общей длиной
412357 байт, включая пропущенные legacy-updater файлы `app.js`, `chart.js`,
`style.css`/`style.css.gz` и `edit.htm`/`edit.htm.gz`. Совпадающие local files
остаются на месте, а только изменившийся subset потоково скачивается во
временные файлы и проверяется по exact size/SHA-256. Затем subset публикуется до
регистрации handlers/routes и запуска web-server. Минимальный transaction journal
нужен только для восстановления прерванной rename-фазы; он не является runtime
UI slot или новым интерфейсом. Backup — rename старого файла, а не третья копия
payload. При невозможности разместить changed staging, journal и доказанный
LittleFS reserve update прекращается до первой FS-мутации.

## 5. Обязательный цикл каждой задачи

1. Read-only planning-сабагент проверяет живые symbols, зависимости, write scope и failure matrix и создаёт/обновляет отдельный task-plan.
2. Основной агент сверяет task-plan с этой границей и фиксирует baseline targeted tests.
3. Developer-сабагент меняет только разрешённые файлы задачи, не сбрасывает dirty tree и не форматирует соседний код.
4. Tester-проход добавляет behavioral backend/frontend tests; shape-only smoke допускается только как дополнительный static gate.
5. Основной агент запускает targeted tests и соответствующие build/browser gates.
6. Reviewer-сабагент читает весь task diff и возвращает ERROR/WARNING либо точный `PASS: no errors, no warnings`.
7. Любые ERROR/WARNING возвращаются тому же developer scope; проверки и review повторяются до чистого PASS.
8. Только после PASS обновляются ledger и `Last reviewed` затронутых codebase-map nodes.

Запрошенная модель `gpt-5.6-terra` недоступна: встроенный интерфейс сабагентов не имеет параметра модели, а проверенный локальный headless-agent CLI перечисляет только `grok-build` и `grok-composer-2.5-fast`. Используются доступные сабагенты; ни один из них не объявляется как `gpt-5.6-terra` без подтверждения инструмента.

## 6. Волна W2 — честные результаты существующих команд

Фактический порядок W2: R2.0 OperationStore → R2.3/A-12 → R2.1/A-02 → R2.2/A-06 → R2.4/A-13 → R2.5/A-14. A-12 ставится до A-02, потому что `calfinish` нельзя честно завершить без проверяемого NVS результата.

### R2.0 — минимальный OperationStore

**Статус:** завершён; независимый review `PASS: no errors, no warnings`.

**Зачем:** A-02 и A-12 сейчас отвечают до loop-side результата.

**Write scope:** новый `operation_store.h`; `Samovar.ino`; `samovar_api.h`; `WebServer.ino`; `tools/static_analysis_sources.json`; новый behavioral smoke/host test; соответствующие map nodes.

**Реализация:**

1. В `operation_store.h` определить только POD-типы `OperationId`, `OperationKind`, `OperationState`, `OperationError`, `OperationRecord` и фиксированный store без `String`, heap, callback или timestamp.
2. Хранилище определить в `Samovar.ino`; использовать существующий `pending_command_lock`, не создавать новый mutex/task.
3. ID — ненулевой `uint32_t`; wrap пропускает 0. Новый record занимает пустой либо самый старый terminal slot. `queued/running` никогда не перезаписываются; если все slots активны, route получает явный `503 operation_store_full`.
4. Единственный loop-side код меняет `queued → running → succeeded/failed`; повторный terminal transition отклоняется.
5. Terminal record хранится до переиспользования. Optional bounded `operationId` в `/ajax` возвращает только `operationId/state/error`; `/ajax` получает `Cache-Control: no-store`. Новый endpoint и `kind/detail/timestamps` в wire-contract не добавляются.
6. Ошибки — стабильные короткие codes, а не произвольный heap-текст.

**Tests/gate:** ID wrap/0, full active ring, reuse oldest terminal, invalid transition, two readers, missing/expired ID; C++11 host compile; static inventory; blocking cppcheck; `Samovar` и `Samovar_s3` build.

### R2.1 — A-02: I2C и calibration result

**Статус:** завершён; независимый review — `PASS: no errors, no warnings`. Gates: focused 10/10, smoke 54/54, Playwright A-02 15 + numeric 36/9, blocking cppcheck, 7/7 PlatformIO environments, stack/UI asset/map/diff PASS; hardware HIL high-water не запускался.

**Write scope:** `Samovar.ino`, `WebServer.ino`, `operation_store.h`, `logic.h`, `samovar_api.h`, `data/i2cstepper.htm`, `data/calibrate.htm`, focused smoke/host/browser tests и map nodes. `I2CStepper.h` и A-12 `data/app.js` остаются read-only.

**Реализация:**

1. Добавить `operationId` в существующие `PendingI2CStepperCmd`, `PendingI2CPumpCmd`, `PendingI2CCalCmd`, `PendingLocalCalCmd`.
2. `status` остаётся синхронным `200` с существующим device JSON; любая принятая мутация получает отдельный строгий `202 {operationId,state,error}` с `Cache-Control: no-store`, чтобы числовой device `error` не конфликтовал со строковым operation error.
3. Loop переводит запись в `running`, работает только с candidate, проверяет фактический `bool` каждого I2C call, `dev.error` и forced refresh; config busy-bit удерживается до confirmed commit/end.
4. Confirmed config/target/running state копируется только после ACK+refresh. На lock busy, command false, timeout/error или refresh failure record завершается `failed`, pending снимается, прежний confirmed state сохраняется.
5. Один bounded terminal-result slot повторяет только `operation_store_finish_locked()` до публикации; новые hardware side effects до этого не исполняются.
6. I2C `calfinish`, принятый `/calibrate` в `PendingI2CCalCmd`, считается успешным только после device ACK, refresh, вычисления candidate calibration и успешного persistence/read-back из R2.3. Generic `/i2cstepper?cmd=calstart/calfinish` сохраняет прежнюю command+refresh семантику без NVS и `I2CPumpCalibrating`. Local `pump_calibrate()` возвращает узкий result для invalid state/result и persistence failure вместо ложного success.
7. Существующие `SamovarApp.readOperationAcceptance()`/`waitForOperation()` используются read-only; I2C/calibration UI оставляет текущие controls/error box и показывает success только после terminal `succeeded`.

**Tests/gate:** config lock busy, command false, device error, refresh false, NVS failure, concurrent refresh, start/stop/calfinish; browser present=0/1, queued→success/failure, timeout, console clean; source/gzip/manifest parity для затронутого UI.

### R2.2 — A-06: сохранение текущих GET

**Статус:** завершён; независимый review — `PASS: no errors, no warnings`. Итог: `contract mitigation PASS; state-changing GET replay risk accepted by user`.

**Фактический production scope:** только inline `/lua` в `WebServer.ino`; numeric GET handlers, A-02 lifecycle и `data/**` остались read-only.

**Реализовано:**

1. Не менять ни один method или route name.
2. Подтверждено, что `/calibrate`, `/i2cpump`, `/i2cstepper` уже проверяют cardinality/allowlist/source/numeric bounds до pending reserve и используют A-02/no-store contract.
3. `/lua` принимает только ноль параметров либо один query `script` (включая пустой), остальные формы отклоняет до queue; все `200/400/503` имеют no-store, OperationStore lifecycle не добавлен.
4. Повторный GET остаётся принятым пользовательским риском; auth/token/idempotency/prefetch-защита и новый функционал не добавлены.

**Tests/gate:** exact seven-route inventory; source-extracted C++11 `/lua` matrix; Playwright exact-GET trace 15/15; targeted 9/9 + UI pack; smoke 55/55; blocking cppcheck; `Samovar`, `Samovar_s3`, `Samovar_lua_mqtt`; map/inventory/diff-check PASS.

### R2.3 — A-12: program/save и один NVS blob

**Статус:** завершён (P1+P2); reviewer — `PASS: no errors, no warnings`. Итоговые gates: focused 9/9, полный smoke 53/53, blocking cppcheck, 7/7 PlatformIO environments, Playwright profile/program-clear/numeric, UI asset/format contracts и `git diff --check` — PASS.

**Write scope:** новый `profile_store.h`; `NVS_Manager.ino`; `Samovar.ino`; `WebServer.ino`; `FS.ino`; `Menu.ino`; `samovar_api.h`; `operation_store.h` только для A-12 error codes; `selftest.h` только для существующего mode barrier; `data/app.js`; `data/setup.htm`; `data/program.htm` и mode pages только для ожидания существующей program-команды; focused host/smoke/browser tests; map nodes. `lua.h`, runtime helpers и mode registry остаются read-only.

**Реализация persistence:**

1. `profile_store.h` содержит C++11/Arduino-free layout header, version, payload size, CRC32 и pure encode/validate helpers. Никаких filesystem, Preferences или global state.
2. `PersistResult save_profile_nvs(const SetupEEPROM& candidate)` открывает namespace, пишет один key, перечитывает exact size, проверяет header/version/CRC и byte equality, затем возвращает результат. Нет retry, custom compaction, A/B или silent success.
3. `load_profile_nvs(SetupEEPROM& candidate)` читает валидный blob в local candidate. Если blob отсутствует, legacy key-reader формирует candidate и один раз сохраняет blob. Если blob существует, но invalid, boot fail-closed; legacy fallback запрещён.
4. После успешной migration старые keys больше не пишутся. Obsolete per-key writers/custom compaction/heap backup удаляются; load-only migration code остаётся ровно в одном месте.
5. Удалить бессодержательный `FS.ino::save_profile()` wrapper; все callers получают и обязаны проверить `PersistResult`.

**Реализация operation contract:**

1. `/program` после полной parse/validation создаёт operation и возвращает `202`, сохраняя текущие `ok/err/program` и добавляя только `operationId/state/error`; loop commit завершает её `succeeded/failed`.
2. `/save` после полной staged validation создаёт одну compound operation и возвращает JSON `202` с `operationId/state/error`, а не ранний redirect. Существующая setup page ждёт terminal result и только после success переходит на текущий `/`.
3. Для `/save` без mode change порядок: persist candidate → read-back success → commit `SamSetup`/sensor resets/optional program draft. Standalone `/program` не пишет NVS и завершает operation после loop-side program/metadata commit.
4. С mode change staged settings/program хранятся до финальной commit-фазы существующего mode-switch FSM; explicit/default program полностью готовится route-ом до `202`. После actuator/Lua-stop/queue/log cleanup выполняется persist candidate; только затем один loop-owned участок меняет `SamSetup`, mode, program и sensor state. Текущие void `apply_config_runtime()`/`load_lua_script()` выполняются после owner commit с прежней logging-семантикой и не расширяются в новый transactional API; Lua-result отдельно закрывает A-07. До подтверждённого read-back owner RAM остаётся прежним. Persistence atomicity ограничена штатной single-key семантикой ESP32 NVS; дополнительный software rollback/A-B слой не добавляется. Любой обнаруживаемый A-12 failure завершает compound operation как `failed`, а invalid persisted blob на следующем boot даёт fail-closed, не legacy fallback.
5. Параллельный save/program или active program session получает explicit busy и не занимает/не перезаписывает чужую operation.
6. Boot/default/migration/menu/mode-switch callers не игнорируют persistence failure; normal control startup не объявляет сохранение успешным.

**Tests/gate:** blob header/version/size/CRC; open/write/short-write/read-back/mismatch faults; absent blob migration once; corrupt blob no fallback; default-save failure; two concurrent saves; save+program+mode race; active-session race; UI queued→failed/succeeded and no early redirect/success; seven compile environments eventually green.

### R2.4 — A-13: недеструктивный event ring

**Статус:** завершён; независимый review — `PASS: no errors, no warnings`. Gates: focused A-13, smoke `56/56`, stable isolated Playwright `6/6`, blocking cppcheck, `7/7` PlatformIO environments, RAM/stack/map/diff PASS; HIL free-heap/high-water не запускался без ESP32.

**Write scope:** новый `runtime_event_log.h`; `runtime_helpers.h`; `Samovar.ino`; `Samovar.h` только shared type/state declarations/removal; `lua.h` для сохранения существующего `Msg` API; `data/app.js`; five mode pages и `chart.htm` только для cursor integration/removal duplicate consumers; focused host/smoke/browser tests; map nodes.

**Реализация:**

1. Fixed ring хранит sequence, kind (`message`/`console`), level и bounded text; storage находится у runtime owner в `Samovar.ino`, не в `Samovar.h`.
2. Используется существующий runtime lock; `append_web_message()` и `append_console_log()` больше не агрегируют/очищают globals. Oversize input не обрезается молча: допустимый размер подтверждается inventory, а превышение даёт явную Serial/console diagnostic или разбивается на последовательные records по заранее протестированному правилу.
3. `consume_ajax_runtime_snapshot()` становится недеструктивным telemetry copy и не меняет ring.
4. Клиент передаёт один bounded `messageCursor`; `/ajax` с `Cache-Control: no-store` возвращает самое старое следующее событие через существующее `Msg/msglvl` либо `LogMsg` и добавляет `messageSequence`.
5. Cursor больше latest (reboot) начинает чтение с oldest retained; gap определяется как sequence не равный `cursor + 1`. Никакого server-side client state/acknowledge.
6. Lua `Msg` setter добавляет обычное сообщение через owner API; getter читает latest retained message и не разрушает ring.

**Tests/gate:** independent fast/slow clients; reconnect; no duplicates per client; identical order; wrap; overflow gap; reboot cursor; mixed message/log order; Lua Msg compatibility; browser matrix five modes + chart.

### R2.5 — A-14: notification queue

**Статус:** завершён; независимый reviewer после проверки production-derived mutation resistance — `PASS: no errors, no warnings`.

**Фактический write scope:** только notification blocks в `Samovar.ino`, новый `tools/smoke_notification_queue.py`, TESTING/map metadata и status/evidence. `runtime_helpers.h`, vendor `libraries/simple_queue/**`, HTTP и UI/data не менялись.

**Реализация:**

1. `SendMsg()` проверяет lock acquisition и `msg_q.push()`; failure пишет прямую local diagnostic без рекурсивного `SendMsg()`.
2. `triggerGetClock()` под `xMsgSemaphore` выполняет только `pop()` в stack buffer и сразу освобождает mutex. Telegram/Blynk I/O выполняются после release.
3. Проверяются `pop()` и доступный Telegram result (`<ERR>`); Blynk failure определяется только по доступным API/connection signals, без выдуманного ACK.
4. Ошибка доставки видна через event/log owner; сообщение не requeue-ится. FIFO, capacity и существующее однократное delivery поведение сохраняются; retry/priority/reserve не добавляются.

**Tests/gate:** actual vendor queue и дословно извлечённые production-блоки проверяют fake 8-second I/O, producer progress, FIFO/capacity, безусловный release на empty/push-false/pop-false, точное сопоставление шести diagnostics, независимые Telegram/Blynk attempts, no requeue и отсутствие recursive notification path. Итог: focused PASS; smoke `57/57`; blocking/extended cppcheck без error/warning; `7/7` environments и отдельная Telegram+Blynk compile SUCCESS; stable isolated Playwright `6/6`; map `72/550`; `git diff --check` PASS.

### Gate W2

- targeted task gates и отдельный reviewer PASS для R2.0/A-02/A-06/A-12/A-13/A-14;
- full `tools/run_smoke_tests.py`;
- browser operation/message scenarios через обязательный `playwright-cli`;
- blocking cppcheck;
- builds `Samovar`, `Samovar_s3`, `Samovar_lua_mqtt`;
- `git diff --check`, static inventory и affected map nodes.

## 7. Волна W3 — LittleFS и updater

### R3.1 — A-01: fail-closed mount

**Статус:** завершён; независимый reviewer — `PASS: no errors, no warnings`.
Gates: focused source-extracted + injected pre-mount mutations, smoke `58/58`,
blocking/extended cppcheck без error/warning, `7/7` PlatformIO, stable isolated
Playwright `6/6`, targeted map/diff PASS; общий mapper state сохраняет unrelated
`needs_review`; destructive HIL не запускался без ESP32.

**Write scope:** `FS.ino`; `WebServer.ino`; `Samovar.ino`; `samovar_api.h`; focused mount/startup test; map nodes.

**Реализация:**

1. `FS_init()` возвращает `FsInitResult`; выполняет ровно `SPIFFS.begin(false)` и не вызывает `format()`.
2. На failure пишет явную Serial diagnostic и не регистрирует `/events`, editor, not-found/upload/body handlers.
3. `WebServerInit()` прекращается до route registration, `server.begin()` и updater. `setup()` фиксирует failure и не объявляет web/control UI запущенным.
4. Не добавлять format command, recovery server, serial CLI или альтернативную FS.

**Tests/gate:** injected begin(false)=false → format call count 0, handler/server start count 0, FS bytes unchanged; success path регистрируется один раз; both board builds; reviewer PASS.

### R3.2 — A-04: transaction текущих raw UI-файлов

**Статус:** локальные code/review/gates завершены с
`PASS: no errors, no warnings`; внешний remote CDN parity остаётся открытым
publication/final blocker. A-04 release-complete не объявлен.

**Write scope:** новый `web_update.h` либо, если task-plan докажет меньший объём, focused functions в `WebServer.ino`; `WebServer.ino`; `web_src/ui-manifest-v1.json` только текущие assets/SHA/limits; focused host/fault tests; map nodes. P1.1 files, partition layout и CDN Ace не меняются.

**Реализация:**

1. Зафиксированный source baseline: текущие 19 override-файлов занимают 329158 байт, но не включают обязательные `app.js`, `chart.js`, `style.css` и `edit.htm`; исправленный transaction set из 23 физических файлов занимает 412357 байт. Весь `data/` — 431835 байт, а `data +` полная staging-копия исправленного set — 844192 байта до LittleFS metadata/runtime logs; full-set staging не помещается в раздел 786432 байта. До первой записи вычислить required changed-subset staging и доказанный reserve. Если budget не проходит, update обязан завершаться до мутации; partition и runtime logs не очищаются.
2. Единственный authoring source — schema-validated `web_src/ui-manifest-v1.json`; firmware использует checked-in typed projection `raw_update` с exact version/path/stored size/SHA-256. Host contract требует exact parity JSON/data/header. Firmware не скачивает JSON и не вводит pack runtime. Projection bounded по count/path/size; unknown/duplicate/traversal/overflow отклоняются до recovery и любых записей. SHA используется только как consistency-check.
3. Проверить local SHA каждого manifest entry. Скачать только changed entries в уникальные temporary paths потоково, проверить byte count и streaming SHA-256. Не держать весь пакет или большой файл в `String`.
4. После проверки неизменённых finals и всего changed staging записать минимальный transaction journal, переименовать old→backup и staged→final до запуска web server, затем повторно проверить полный candidate set.
5. Version marker обновить только после полного commit. На инъецированной ошибке rollback восстанавливает весь old set. Boot recovery по journal либо завершает подтверждённый commit cleanup, либо полностью откатывает; mixed set не выдаётся routes.
6. Lua/default program files с `SAVE_FILE_IF_NOT_EXIST` не включать в UI transaction и не связывать с version marker.
7. Удалить старый sequential `updateFile()` success contract после переключения всех callers; не оставлять два updater-пути.

**Tests/gate:** manifest malformed/duplicate/size/SHA/network short read/no space; failure на каждой stage/rename/verify/version/journal операции и simulated reboot; результат all-old или all-new; server start только после recovery/update; active FS limit; no local Ace/pack/slot symbols; reviewer PASS.

### Gate W3

- targeted host/static fault suites;
- full smoke;
- `pio run -e Samovar -t buildfs` и `Samovar_s3 -t buildfs`;
- firmware builds обеих плат;
- blocking cppcheck и `git diff --check`;
- map nodes `FS.ino`, `WebServer.ino`, `Samovar.ino`, `data`, `tools`.

## 8. Волна W4 — владельцы state, Lua и существующий UI

Фиксированный UI-порядок: `U-06 → U-03 → U-04 → U-05`. Общий controller
стабилизируется первым; затем меняются только цвета, после них layout, и только
на устойчивой геометрии — semantics/focus/44×44. Реализация этих четырёх задач
не параллелится из-за общих `data/**` hunks.

Общая граница всех четырёх UI-задач: существующие GET/POST methods, routes,
request bodies и product actions неизменны; security-hardening, local Ace,
editor shell, новые controls/screens/routes/frameworks и P1.2 runtime запрещены.
После каждой задачи frozen post-task source собирается дважды детерминированно.
Равенство firmware SHA с pre-task baseline не требуется, потому что changed UI
bytes обновляют `WEB_UPDATE_ENTRIES` в `web_update.h`; любой pre/post
binary/map/section delta обязан механически объясняться только этой manifest
table без новых symbols/code paths или необъяснимого flash/RAM drift.

### R4.1 — A-05: узкие owners и TelemetrySnapshot

**Статус:** завершён; независимый reviewer —
`PASS: no errors, no warnings`.

**Write scope:** только локальный request snapshot/serializer в `Samovar.ino`,
новый focused `tools/smoke_a05_state_owners.py`, минимальная синхронизация stale
static boundaries в operation/A-13/API/ProgramType smoke без изменения их
behavioral harnesses, и после PASS targeted metadata.
`runtime_helpers.h`, owners, `WebServer.ino`, `Samovar.h`, `Blynk.ino`, `lua.h` и
UI остаются read-only.

**Реализация:**

1. Не переоткрывать уже закрытые OperationStore, RuntimeEventRing и ProfileStore:
единственный оставшийся дефект — normal `/ajax` перечитывает mutable globals во
время serialization/network I/O.
2. В `Samovar.ino` собрать только уже существующие wire scalars/derived values в
request-local `AjaxTelemetrySnapshot`; неизменённый
`copy_ajax_runtime_snapshot()` вызывается один раз, serialization выполняется
только из `const` snapshot после освобождения locks.
3. Сохранить GET `/ajax`, exact query classification, key order, JSON types,
precision, status/headers и A-13 event suffix byte-for-byte. Межполевая транзакция
для источников без общего lock и общая generation для разных readers не
обещаются.
4. Не добавлять header/owner framework/mutex/task/queue/route/UI и не менять
operation/query/error paths.

**Tests/gate:** production-derived mutation A→source change→serialization A
byte-identical, capture B отражает изменение; golden JSON feature matrix;
operation/A-13 regressions; `sizeof(snapshot) <= 512`; отсутствие post-capture
mutable reads, нового mutex/task/heap/global state; reviewer PASS.

### R4.2 — A-07: Lua failures и narrowing

**Статус:** завершён; независимый reviewer —
`PASS: no errors, no warnings`.

**Write scope:** `lua.h`; `numeric_parse.h` только общий exact finite-integral helper; existing command/pending helper declaration/implementation при необходимости; focused host/Lua smoke; map nodes.

**Реализация:**

1. Descriptor явно различает integral и fractional domain: integer arguments
читаются через `luaL_checkinteger()` и wide-integral checked narrowing, float
fields — через `luaL_checknumber()` с finite-check. Значения `16777217` и
`INT32_MAX` не проходят через 32-bit float.
2. `SamSetup_Mode`, `Samovar_Mode`, `Samovar_CR_Mode` сохраняют три разные
семантики через один узкий owner под существующим `pending_command_lock`; busy,
active mode switch и любая non-empty profile phase дают Lua error без mutation.
3. Expander `pinMode/digitalWrite/analogWrite` возвращают `luaL_error` при I2C
lock timeout; только `digitalWrite()` имеет реальный vendor bool failure. Для
void API выдуманный ACK не добавляется, а `pinMode` сохраняет
`INPUT/OUTPUT/INPUT_PULLUP`.
4. I2C pump/stepper wrappers проверяют range и positive product в
`[1, UINT32_MAX]`, сохраняют существующий `i2c_get_speed_from_rate()` и его
I2C/local calibration semantics, а также возвращают фактический bool result.
Ни один новый error path не держит живой Arduino `String` через `luaL_error()`.
5. Не добавлять Lua functions, routes, operation IDs или отдельный Lua job lifecycle.

**Tests/gate:** min/max, ±1, fractional-to-integer, NaN/Inf, invalid mode, I2C timeout/failure, queue busy; invalid не меняет state; Lua example compatibility; `Samovar_lua_mqtt` build; reviewer PASS.

### R4.3 — U-06: единый существующий UI runtime

**Статус:** реализация, focused/full gates и независимый review завершены:
`PASS: no errors, no warnings`. External A-04 remote parity остаётся
publication/final blocker и не маскируется локальным U-06 PASS.

**Write scope:** `data/app.js`; `index.htm`, `beer.htm`, `distiller.htm`, `bk.htm`, `nbk.htm`, `chart.htm`; browser/static tests; manifests/hashes; data/tools map nodes. Остальные standalone pages остаются regression-only.

**Реализация:**

1. Добавить в существующий `SamovarApp` один узкий
`startTelemetryPage(renderFn, options)`, который переиспользует уже существующие
`init/pollAjax/startPollLoop` и владеет только polling, message cursor,
theme/history, connection/request-error lifecycle.
2. На пяти mode pages оставить локальными все field mapping/rendering,
`setPowerUnit`, program/PWM/heat actions и page-specific startup. Удалить только
локальную polling-обёртку `loadDoc`; generic field descriptors/DSL не добавлять.
3. `chart.htm` использует тот же lifecycle с его существующими отличиями через
закрытые options; chart drawing/CSV/series/legend/status/throttle остаются local.
Удалить только дубли chart connection/message/audio/theme, polling wrapper и
неиспользуемый chart-local `setPowerUnit`. Setup/program/calibration/I2C не
меняются в U-06.
4. Не добавлять framework, module loader, template generator или build runtime.

**Tests/gate:** static one-definition/one-start allowlist; browser telemetry
matrix five modes + chart с exact thresholds/options, one in-flight request,
message/theme/connection parity и неизменными action requests; no missing
DOM/console error; raw-update manifest/projection parity; existing chart/runtime/
I2C tests переходят только с прямого `loadDoc` на real shared lifecycle без
удаления или ослабления assertions; frozen editor SHA; reviewer PASS.

### R4.4 — U-03: существующая light/dark theme

**Write scope:** `data/style.css`; перечисленные pages только для удаления hard-coded operational colors; deterministic `style.css.gz`; manifests/tests/map. Editor shell исключён.

**Реализация:** заменить hard-coded foreground/background operational states на существующие CSS tokens; program-row colors получают парные text tokens; новый theme selector/mode не добавляется.

**Gate:** automated contrast на `index`, `beer`, `distiller`, `bk`, `nbk`, `program`, `setup`, `chart`, `i2cstepper`, `calibrate` в light/dark: normal text ≥4.5:1, large ≥3:1; state различим не только цветом; existing foundation/style tests меняют только stale color-token expectations, U-06 controller tests остаются read-only; Playwright screenshots/console; reviewer PASS.

### R4.5 — U-04: responsive layout

**Статус:** реализация и полный gate завершены; независимый reviewer —
`PASS: no errors, no warnings`. Изменения ограничены containment существующих
setup/chart элементов; desktop geometry, действия, CDN Ace и backend неизменны.

**Write scope:** `data/style.css`, `setup.htm`, `chart.htm`; gzip/manifests/tests/map. Остальные pages и editor shell read-only.

**Реализация:** в `setup.htm` убрать `setupform min-width:1024`, fixed 668px action shell и выходящие long inputs; в `chart.htm` перевести mobile message wrapper в normal flow и ограничить canvas containing block. Существующие controls/sections сохраняются; новые panels/collapsible regions не создаются. Остальные pages — regression-only.

**Gate:** 320/390/768/desktop: `scrollWidth <= innerWidth`, critical actions видимы, нет overlap/obscured focus, chart/setup usable; foundation/style tests меняют только bounded layout literals/selectors, `smoke_chart_ui.py` — только stale wrapper selector; profile/numeric/shared-controller/runtime browser tests остаются behaviorally unchanged; Playwright screenshots/console; reviewer PASS.

**Фактическая проверка:** focused responsive/static/manifest/transaction PASS;
Playwright U-04 `168/168`, полный browser block `9/9`, smoke `64/64`;
LittleFS source `45/434245`, raw-update `23/414767`, buildfs `2/2`;
blocking cppcheck и extended cppcheck без errors/warnings; семь environments
PASS; две fixed-epoch clean-сборки побайтово совпали по firmware/ELF/map/
bootloader/partitions; targeted map/diff PASS.

### R4.6 — U-05: accessibility и touch

**Статус:** реализация и полный gate завершены; независимый reviewer —
`PASS: no errors, no warnings`. Изменения ограничены semantics, keyboard/focus
и touch containment существующих controls; backend, request contracts,
editor/CDN и product functionality не менялись.

**Write scope:** только `index`, `beer`, `distiller`, `bk`, `nbk`,
`program`, `setup`, `chart`, `calibrate`, `i2cstepper`, `brewxml`,
`style.css(.gz)` и `app.js` для semantic state существующих controls;
gzip/manifests/browser tests/map. Editor shell и `wifi.htm` read-only.

**Реализация:** `lang=ru` только на 11 pages из write scope; unique IDs;
explicit `label[for]`/control associations; exact 51 setup controls плюс named
`<output id="PackDensDisplay" name="PackDensDisplay" for="PackDens">`;
generated row inputs/selects именуются visible row+column headers. Click-only
history/clear и generated plus/minus images на
`index/beer/distiller/program` превращаются в native named buttons. Exact
`aria-label` разрешён только row actions и existing icon-only theme toggles.
Tab state получает только control, который реально открывает existing
`.tabcontent`; I2CStepper navigation не объявляется tabs. Visible focus;
Enter/Space; no focus trap. Critical mode/alarm/heater/main-action targets и row
actions ≥44×44 CSS px и не перекрываются. State получает существующий
text/icon/semantic indicator, а не новую product state.

**Gate:** 88/88 scenarios (11 pages × 4 viewports × light/dark); duplicate IDs
0; all applicable controls named; keyboard full path; Chromium CDP
`Accessibility.getFullAXTree` + deterministic DOM checks дают zero hard
failures; bounding boxes/overlap on 320/390; editor exact frozen SHA без AX/lang
checks. U-06/U-03/U-04 smoke+browser pairs входят в U-05 test allowlist только
для адаптации stale DOM/selector/baseline expectations; их scenarios и
controller/contrast/layout invariants не удаляются и не ослабляются. Manual
viewport checklist; reviewer PASS.

**Фактическая проверка:** focused static/contracts `8/8`; accessibility
Playwright `88/88`, actions `207/207`, uploads `12/12`; отдельный 320/390
light/dark Lua/top-controls visual matrix `20/20`; полный browser block `10/10`,
включая U-03 `60+6+160` и U-04 `168/168`; smoke `65/65`; buildfs `2/2`;
blocking cppcheck exit `0` без errors/warnings; две fixed-epoch clean-сборки
дали `5/5` byte-identical artifacts; семь environments PASS. LittleFS source
`45/450742` из `786432`, raw-update `23/431264`; targeted map/allowlist/
`git diff --check` PASS.

## 9. Волна W5 — A-08 reproducibility

**Write scope:** `platformio.ini`; существующие
`.github/workflows/firmware-ci.yml`/`build_release.yml`; один
read-only `tools/build_metadata.py` и один focused
`tools/smoke_reproducible_builds.py`; после PASS targeted build docs/map.
`SPIFFSEditor.h`, Blynk/vendor, firmware/UI/data/partitions остаются read-only.

**Compatibility-only write scope:** ровно `tools/ui_pack_assets_contract.py` и
`tools/smoke_ui_pack_assets.py`. Разрешена только поддержка двух exact A-08 base
flags; product/UI/data, raw manifest/schema, Lua suffix semantics и asset
inventory не меняются и не расширяются.

**Реализация:**

1. Pin текущий `platform-espressif32` на exact commit; override добавить только
пяти реально range-resolved packages. Existing exact toolchains и
`tool-esp32partitiontool` URL/version не дублировать и не обновлять.
2. Унифицировать Python `3.12`/PlatformIO `6.1.19`; exact
`tool-scons 4.40801.0` установить штатным PlatformIO package manager. Python
wheel-lock/bootstrap и собственный installer не создавать.
3. Один stdlib read-only `build_metadata.py` после успешного build фиксирует
Git SHA/dirty, explicit commit-derived `SOURCE_DATE_EPOCH`, Python/Core,
platform/package и vendored-library tree hashes, raw firmware/map size+SHA.
Helper ничего не устанавливает, не скачивает и не меняет обычный `pio run`.
4. `firmware-ci.yml` генерирует/проверяет metadata внутри прежней seven-env
matrix без нового artifact flow. `build_release.yml` добавляет map/metadata
только в existing Archive; triggers/jobs/default env и release `.bin` glob
сохраняются.
5. R3 подтвердил equal inventories и payload; различались только embedded
`app_elf_sha256` и производный footer: ELF содержал 2077 package debug roots и
два project DWARF `comp_dir`. В base env заменить macro-only flag exact ordered
pair `-ffile-prefix-map=${platformio.packages_dir}=.platformio/packages`, затем
`-fdebug-prefix-map=${platformio.src_dir}=.`. Standalone macro map, Core/build
maps, random/build-id flags и post-processing запрещены. File map сохраняет
package macro mapping и меняет package debug paths; source map касается только
двух project `comp_dir`.
6. Только из `tool-esptoolpy` package tree hash исключить pip-generated
`_contrib/bin/**` и `_contrib/*.dist-info/RECORD`. Те же paths в других
packages, ordinary `_contrib` code, manifest/binary и absolute-path bytes вне
этих exclusions остаются hashed.

**Gate:** две isolated cold work directories с разными absolute paths, отдельными
HOME/venv/core/cache/tmp и одинаковым frozen source/epoch дают identical runtime,
package и vendored-library hashes; raw `firmware.bin` для `Samovar` и
`Samovar_s3` совпадает A↔B byte-for-byte. Raw map сохраняется без normalization,
firmware после build не переписывается. Unexplained drift блокирует PASS.
Package inventory игнорирует только два exact generated path classes. Buildfs
остаётся обычным regression 2/2, не A/B contract.
Отдельный pre-pin binary baseline не создаётся; сохраняются existing hard
size/partition ceilings и семь build environments.

## 10. Допустимый параллелизм

| Этап | Параллельно можно | Нельзя параллельно |
|---|---|---|
| После master plan | read-only task-plans W2, W3, W4/W5 | одновременные edits общих firmware files |
| W2 | планирование/tests A-13 и A-14 | development A-02/A-12/A-13/A-14: все касаются `Samovar.ino`/runtime state |
| W3 | test design A-04 во время A-01 | A-01 и A-04 edits: общие FS/WebServer startup |
| После A-05 | A-07 (`lua.h`), U-06/U-03/U-04/U-05 последовательно; A-08 только read-only planning/review | A-08 production и любые сборки до U-05 PASS/freeze W4 |
| UI | screenshot/test preparation | U-03/U-04/U-05 implementation: общие CSS/pages, выполнять последовательно |
| W5/W6 build gates | только read-only анализ уже завершённого log/evidence | любые PlatformIO environments параллельно; PlatformIO и cppcheck одновременно |

Все сабагенты работают в общем checkout. Параллельный write разрешается только для непересекающихся allowlists; перед каждым patch повторно проверяется `git status` и текущий diff конкретных файлов.

## 11. Волна W6 — финальная стабилизация и reviewer-loop

1. Заморозить source snapshot; удалить только transient артефакты, созданные этой работой (`tools/__pycache__`, временные browser outputs), не пользовательские файлы.
2. Запустить все targeted behavioral suites и полный deterministic smoke runner.
3. Через `playwright-cli` выполнить operation/message, five-mode + chart shared-runtime telemetry, light/dark contrast, responsive и accessibility matrices.
4. Проверить deterministic gzip parity, UI manifests, active LittleFS hard limit и absence local Ace/P1.2 runtime.
5. Последовательно запустить blocking cppcheck, затем extended cppcheck; необъяснённых ERROR/WARNING нет.
6. Собрать семь environments: `Samovar`, `Samovar_s3`, `Samovar_no_power`, `Samovar_rmvk`, `Samovar_sem`, `Samovar_lua_mqtt`, `Samovar_alarm_button`; отдельно buildfs для `Samovar`/`Samovar_s3`; проверить existing hard size/partition ceilings. A-08 сравнивает raw `firmware.bin` и dependency inventory A↔B; raw map сохраняется как evidence, а отсутствующий pre-pin RAM/flash baseline не заявляется.
7. Выполнить A-08 two-clean-build comparison.
8. Обновить все affected codebase-map nodes и проверить graph state/targeted repair.
9. Применить `anti-ai-slop` только к изменениям этой remediation: убрать дубли, speculative abstractions, stale comments/tests и orphan symbols без изменения поведения.
10. Финальный reviewer-сабагент читает весь diff. При любом ERROR/WARNING исправить в том же scope, повторить затронутые gates и вызвать reviewer снова.
11. Завершение допускается только при точной строке `PASS: no errors, no warnings`, зелёных software gates и честной пометке `A-11 HIL not run`.

## 12. Rollback и критерий остановки

- Никаких `git reset --hard`, checkout чужих файлов или удаления существующего dirty worktree.
- Незавершённая задача откатывается только точечным обратным patch собственных строк.
- Если реальный symbol/data flow расходится с этим планом, developer останавливается до изменения архитектуры и возвращает evidence; нельзя добавлять fallback или второй путь.
- Одна и та же ошибка дважды запускает обязательное web-исследование 3–5 решений по правилу репозитория.
- Hardware HIL не заменяется симуляцией и не объявляется PASS.
