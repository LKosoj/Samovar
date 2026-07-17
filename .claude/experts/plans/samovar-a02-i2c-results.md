# A-02 — подтверждённые результаты I2C и калибровки

## Цель и обязательные зависимости

Закрыть A-02 без нового действия устройства: принятые `/i2cstepper`, `/i2cpump` и `/calibrate` получают корреляцию с loop-side результатом, а UI сообщает success только после terminal `succeeded`.

Начинать реализацию только после отдельных `PASS` R2.0 и A-12. В живом дереве к этому моменту обязаны существовать `OperationStore operationStore`, `OperationId`, `operation_store_reserve_locked()`, `operation_store_mark_running_locked()`, `operation_store_finish_locked()`, optional lookup `/ajax?operationId=...`, `PersistResult save_profile_nvs(const SetupEEPROM&)` с read-back и `SamovarApp.waitForOperation()`. Использовать точные A-12 helpers принятия/terminal transition и mapping HTTP errors; при расхождении symbols остановиться и обновить этот план, не создавать compatibility wrapper.

Готово, когда:

- каждый успешно поставленный `PendingI2CStepperCmd`, `PendingI2CPumpCmd`, `PendingI2CCalCmd` и `PendingLocalCalCmd` имеет ненулевой `operationId` и ровно один terminal result;
- `status` `/i2cstepper` остаётся синхронным `200`, а принятые команды возвращают `202` и `operationId/state/error` с `Cache-Control: no-store`;
- loop не публикует config, target, running/calibration state до подтверждённых command ACK, `dev.error == 0` и отдельного forced refresh;
- I2C `calfinish`, принятый через `/calibrate` в `PendingI2CCalCmd`, публикует новый `StepperStepMlI2C` только после успешного A-12 persistence/read-back; generic `/i2cstepper?cmd=calstart/calfinish` сохраняет прежнюю семантику без записи profile и без изменения `I2CPumpCalibrating`;
- failure всегда снимает собственный pending, завершает operation как `failed`, сохраняет прежний confirmed state и виден в существующем error area UI;
- targeted backend/browser gates, full smoke, builds, map update и reviewer-loop проходят без ошибок и предупреждений.

## Неподвижная граница

- Сохраняются `HTTP_GET` и имена `/i2cstepper`, `/i2cpump`, `/calibrate`; новый route/status endpoint не добавляется.
- Не добавлять task, mutex/semaphore, queue, retry, fallback, idempotency/session, detail/timestamp в `OperationRecord` или второй I2C executor.
- `I2CStepper.h` в production read-only: существующих `i2c_stepper_config_begin/end`, `i2c_stepper_{apply,save,start,stop}`, `i2c_stepper_write_config()`, `i2c_stepper_send_command()`, `i2c_stepper_refresh(dev, true)` и `I2CStepperDevice::error` достаточно. Не переписывать wire/register API.
- Не выполнять I2C или NVS под `pending_command_lock`; lock защищает только reserve/publication, DTO consume/transition и terminal publication.
- Не менять unrelated `/command`, Lua, mode, telemetry или persistence behavior. Local calibration не получает выдуманный hardware ACK: существующий `pump_calibrate()` остаётся единственным executor, но возвращает узкий `PumpCalibrationResult`, чтобы operation отличала invalid state/result и A-12 persistence failure от success.
- Generic `/i2cstepper?cmd=calstart/calfinish` не становится вторым profile-calibration path: он, как и до A-02, только выполняет команду устройства и confirmed refresh. Только `PendingI2CCalCmd`, созданный `/calibrate`, владеет `I2CPumpCalibrating` и persistence `SamSetup.StepperStepMlI2C`.
- Последующий обычный SysTicker refresh вправе показать реально наблюдаемое устройство после failed operation; это не меняет terminal `failed` и не считается success команды. Сам A-02 failure не копирует candidate в confirmed globals.

## Точные symbols и ошибки

1. Добавить `OperationId operationId` в `PendingI2CStepperCmd`, `PendingI2CPumpCmd`, `PendingI2CCalCmd`, `PendingLocalCalCmd`; сохранить POD/fixed-size contracts и зафиксировать измеряемые caps соответственно `<=64`, `<=24`, `<=12`, `<=8` байт.
2. Использовать kinds `I2C_STEPPER`, `I2C_PUMP`, `CALIBRATION`; оба calibration DTO используют один существующий kind.
3. В `OperationError` добавить только отсутствующие A-02 codes и static wire literals:
   - `OPERATION_ERROR_I2C_CONFIG_BUSY` → `i2c_config_busy`;
   - `OPERATION_ERROR_I2C_COMMAND_FAILED` → `i2c_command_failed` (включая ACK timeout без device error);
   - `OPERATION_ERROR_I2C_DEVICE_ERROR` → `i2c_device_error`;
   - `OPERATION_ERROR_I2C_REFRESH_FAILED` → `i2c_refresh_failed`;
   - `OPERATION_ERROR_CALIBRATION_INVALID_RESULT` → `calibration_invalid_result`.
4. Переиспользовать уже принятые A-12 codes: `OPERATION_ERROR_CANCELLED`, `OPERATION_ERROR_PROFILE_PERSIST_FAILED`, `OPERATION_ERROR_RUNTIME_BUSY` и `OPERATION_ERROR_INTERNAL`; не создавать calibration-specific дубликаты persistence/cancellation/runtime errors.
5. Невозможный после validation command считается existing `INTERNAL`; не добавлять silent default branch. Числовой `candidate.error` писать в существующий локальный log/message path, не расширять wire detail.
6. В `samovar_api.h` определить `PumpCalibrationResult { OK, INVALID_STATE, INVALID_RESULT, PROFILE_PERSIST_FAILED }`; `logic.h::pump_calibrate()` возвращает его, сохраняя текущие side effects/messages. Operation maps invalid state → A-12 `RUNTIME_BUSY`, invalid result → `CALIBRATION_INVALID_RESULT`, persistence failure → A-12 `PROFILE_PERSIST_FAILED`.

## Разрешённый write scope реализации

В этой planning-задаче разрешён только данный файл. Для последующей реализации allowlist закрыт следующим набором:

- production: `operation_store.h`, `Samovar.ino`, `WebServer.ino`, `logic.h`, `samovar_api.h`, `data/i2cstepper.htm`, `data/calibrate.htm`;
- focused tests: новый `tools/smoke_i2c_operation_results.py`, существующие `tools/smoke_operation_store.py`, `tools/smoke_profile_operation.py`, `tools/smoke_i2cstepper_atomic.py`, `tools/smoke_numeric_i2c_contract.py`, `tools/smoke_numeric_misc_routes.py`, `tools/smoke_calibration_ux.py`, `tools/smoke_numeric_input_ui.py`, `tools/smoke_ui_foundations.py`, `tools/smoke_api_routes.py`, новый `tools/test_i2c_operation_results_browser.py` и точечные A-02 ожидания `tools/test_numeric_input_ui_browser.py`;
- UI parity: SHA затронутых sources в `web_src/ui-manifest-v1.json`, соответствующие `EXPECTED_CONTRACT_INPUT_SHA256`/A-10 freeze hashes и пересчитанные `_EXPECTED_UI_TOTALS` в `tools/ui_pack_assets_contract.py`; `maxExpandedSize`/`maxStoredSize`, derived cap и `tools/fixtures/ui_pack_assets_v1/manifests/ui-limit-cases-v1.json` меняются только если фактический expanded/canonical-gzip size пересёк существующий size bucket;
- plan/status после полного PASS: этот task-plan и только строки A-02 в `.claude/experts/plans/samovar-remaining-remediation-2026-07-12.md`/`.claude/experts/plans/samovar-audit-remediation.md`;
- map metadata: `.cli-proxy/.codebase_map/nodes/{operation-store-h,i2cstepper-h,samovar-ino,webserver-ino,logic-h,samovar-api-h,data,tools}.md` и только точечно изменённые mapper index/state/graph entries.

`data/app.js`, `I2CStepper.h`, `Samovar.h`, `runtime_helpers.h`, NVS/profile implementation, mode pages, libraries и build config запрещены к записи. A-02 переиспользует экспортированные A-12 `readOperationAcceptance()`/`waitForOperation()` без изменения. Любой иной production-файл требует остановки и пересмотра allowlist.

Перед первым implementation patch зафиксировать текущий diff каждого allowlisted файла: дерево уже содержит чужую незавершённую работу, её нельзя форматировать, перезаписывать целиком или включать в rollback A-02.

## Шаг 1 — атомарное принятие и wire contract

Изменить только `queue_pending_i2cpump()`, `queue_pending_i2cstepper()`, `queue_pending_i2ccal()` и `queue_pending_local_cal()`:

1. Parse/validation, device/capability check и DTO candidate выполняются до lock.
2. Под одним `pending_command_lock()` повторно проверить `mode_switch_in_progress()`, текущие busy/cross-calibration flags и для I2C device существующий `i2c_stepper_config_busy()`; до reserve любой отказ сохраняет текущий `400/404/503` класс, не создаёт record и ничего не публикует.
3. После всех отказных checks вызвать `operation_store_reserve_locked(operationStore, kind, id)`. `STORE_FULL` даёт `503 operation_store_full`; lock timeout даёт существующий A-12 busy response.
4. При success записать `id` в локальный DTO, скопировать DTO в owner buffer, выполнить `__sync_synchronize()` и поднять ровно его flag. После reserve до publication не должно быть condition/return/failure. Затем unlock и ответ с тем же ID.
5. Запрещены два lock windows reserve/queue, rollback record, overwrite active DTO и orphan record.

Ответы:

- `handle_i2c_stepper_request()` для отсутствующего `cmd`/`cmd=status` вызывает прежний `send_i2c_stepper_json()` как `200`, без operation fields;
- любая принятая мутация `/i2cstepper`, `/i2cpump` или `/calibrate` возвращает единый строгий JSON `202 {operationId,state,error}`. Существующий числовой device field `error` остаётся только в status `200`, поэтому accepted response не смешивает device JSON с operation contract;
- ранние text `OK`/calibration value удаляются только из accepted mutation branches; pre-accept reject responses не маскируются;
- каждая ветка status/accepted/reject использует `Cache-Control: no-store`. HTTP method и route inventory до/после идентичны.

## Шаг 2 — единственный loop-side lifecycle

Для каждого из четырёх DTO применять контракт R2.0/A-12:

Все новые A-02 transition callsites сосредоточить в двух именованных loop-owned функциях `Samovar.ino`: `process_pending_i2c_operations()` выполняет terminal publication и claim/execution, а `cancel_queued_i2c_operations_locked()` завершает только ещё не исполнявшиеся `QUEUED` records при mode-switch discard. Первая вызывается ровно один раз из `loop()` после `process_profile_operation()` и до mode-switch early return. Вторая вызывается из `discard_pending_mode_control_commands()` только под уже взятым `pending_command_lock`; прямые `operation_store_mark_running_locked()`/`operation_store_finish_locked()` в `WebServer.ino` запрещены.

1. Ввести одну loop-owned запись `PendingOperationResult { OperationId id; OperationState state; OperationError error; bool pending; }` с `static_assert(sizeof <= 8)`. Это не новая queue/task: она хранит только уже выполненный terminal result.
2. В начале каждого `loop()`, до mode-switch early return и до любого нового I2C/calibration side effect, при `PendingOperationResult.pending=true` выполнять только terminal publication. Под одним `pending_command_lock` найти единственный поднятый DTO с тем же `operationId`, вызвать `operation_store_finish_locked()`, и только после `OPERATION_ERROR_NONE` атомарно очистить этот DTO/flag и `PendingOperationResult`. При lock busy или неуспешном finish все три объекта остаются без изменений; side effect не повторяется.
3. Только при пустом terminal slot за один проход исполнять максимум один DTO в порядке `i2cstepper → i2cpump → local calibration → i2c calibration`. Под тем же `pending_command_lock`, где копируется DTO и выполняется `QUEUED → RUNNING`, обязательно повторно проверить `mode_switch_in_progress()`. При active barrier DTO/record остаются `QUEUED` для mode-switch discard; при lock busy DTO также остаётся queued. Hardware не запускать, если guard или transition не подтверждён; flag при claim не очищать.
4. Исполнение идёт после unlock и ровно один раз. После фактического результата loop записывает `id/state/error`, затем последним публикует `PendingOperationResult.pending=true`; shared DTO/flag не очищается и не перезаписывается до успешной terminal publication из пункта 2. Это исключает data race, orphan record и повтор hardware/NVS при lock busy.
5. Успех публикуется только после confirmed commit. Любая ветка failure сначала освобождает взятый `i2c_stepper_config_begin()`, затем записывает terminal result; shared DTO/flag остаётся поднятым как correlation owner, но больше не исполняется.
6. `discard_pending_mode_control_commands()` под уже взятым lock делегирует operation-bearing flags в `cancel_queued_i2c_operations_locked()`. Loop-owned helper читает record по `operationId`: только для `QUEUED` вызывает `operation_store_finish_locked(...FAILED, CANCELLED)` и только при success очищает matching DTO/flag. `RUNNING` DTO с уже зафиксированным side effect он не отменяет и не очищает: его terminal slot завершается пунктом 2, после чего mode-switch видит очередь idle. При lookup/transition/internal failure DTO сохраняется. Static inventory должен доказать отсутствие иных голых clear-path.

### `PendingI2CStepperCmd`

- Выбрать confirmed `i2cStepperMixer`/`i2cStepperPump`; при `i2c_stepper_config_begin()` failure завершить `i2c_config_busy`.
- Создать local `I2CStepperDevice candidate = *dev`, затем перенести в него только staged config fields `mode`, `relayMask`, `sensorFlags`, `optionFlags`, `mixerRpm`, `mixerRunSec`, `mixerPauseSec`, `pumpMlHour`, `pumpPauseSec`, `fillingMl`, `fillingMlHour`, `stepsPerMl`.
- Удерживать `i2c_stepper_config_begin()` до confirmed commit/config_end. Dispatch `apply/save/start/stop/calstart/calfinish/relay` на `candidate` и обязательно сохранить реальный `bool`. После true отдельно потребовать `candidate.error == 0`, `i2c_stepper_refresh(candidate, true) == true` и повторно `candidate.error == 0`.
- Только после этих checks присвоить `*dev = candidate`; на failure оставить весь confirmed device byte-for-byte прежним. Generic pump `calstart/calfinish` из `/i2cstepper` не меняет `I2CPumpCalibrating`, `SamSetup` и NVS: его success означает только подтверждённые command+refresh и confirmed device commit, как в исходном поведении.

### `PendingI2CPumpCmd`

- Работать с local candidate `i2cStepperPump`; start сначала меняет только candidate `mode/fillingMl/fillingMlHour/stepsPerMl`, stop не меняет confirmed target заранее.
- Проверить реальный bool `i2c_stepper_start/stop(candidate)`, `candidate.error`, отдельный forced refresh и его `error`.
- Только при полном success одним commit присвоить `i2cStepperPump = candidate`; затем для start присвоить `I2CPumpCmdSpeed`, `I2CPumpTargetSteps`, `I2CPumpTargetMl`, а для stop сохранить текущую семантику reset `I2CPumpCmdSpeed/I2CPumpTargetMl`. Failure не меняет target/running/config globals.

### `PendingI2CCalCmd` и `/calibrate` I2C `calfinish`

- Start меняет только candidate `pumpMlHour/stepsPerMl`, проверяет `write_config && send_command`, device error и forced refresh; лишь затем публикует device candidate, `I2CPumpCmdSpeed`, target reset и `I2CPumpCalibrating=true`.
- Только `PendingI2CCalCmd` finish из `/calibrate` использует owner-side commit-последовательность: command ACK → forced refresh → `SetupEEPROM setupCandidate = SamSetup` → `setupCandidate.StepperStepMlI2C = candidate.stepsPerMl` → проверенный `save_profile_nvs(setupCandidate)` → assignments `SamSetup`, confirmed I2C device и `I2CPumpCalibrating=false` → terminal success. Общий command/refresh helper допустим для устранения дублирования, но profile persist/flag commit остаются только в `PendingI2CCalCmd` owner.
- PersistResult не-OK даёт A-12 `profile_persist_failed`, сохраняет прежние `SamSetup`, confirmed device и calibration flag. `i2c_stepper_config_end()` выполняется после commit/failure cleanup. Не выполнять retry, old-profile rewrite или device rollback; внешний ACK мог физически состояться, поэтому повтор команды автоматически опасен.

### `PendingLocalCalCmd`

- Claim/`RUNNING` выполняется общим owner-порядком, затем вне lock вызвать единственный `pump_calibrate()` и проверить `PumpCalibrationResult`.
- `OK` даёт success; `INVALID_STATE` → `operation_runtime_busy`; `INVALID_RESULT` → `calibration_invalid_result`; `PROFILE_PERSIST_FAILED` → `profile_persist_failed`. Существующие stop/start/message side effects сохраняются; выдуманный hardware ACK не добавляется. Mode-switch discard до исполнения даёт `operation_cancelled`.

## Шаг 3 — UI ждёт `/ajax`

- Не создавать второй waiter: использовать `SamovarApp.waitForOperation(operationId)`, который опрашивает только `/ajax?operationId=...` до `succeeded/failed` и явно завершает missing/expired ID, HTTP/network error и bounded timeout.
- В `data/i2cstepper.htm` изменить `requestJson()`, `sendDevice()` и `toggleRelay()`: `202` означает только accepted; `inFlightActions` и controls остаются busy до terminal. `pendingDeviceConfig.accepted` нельзя выставлять до `succeeded`; после success выполнить обычный `loadDevice()` и только подтверждённым status снять dirty state. На failure оставить edits/confirmed status, показать existing request error и не писать success.
- В `data/calibrate.htm::calibrate()` держать `calibrationInFlight` до terminal. Только `succeeded` меняет `calibrationRunning/calibrationPump`. После finish обновить поле через уже существующий status: local — `StepperStepMl * 100` из `/ajax`, I2C — `stepsPerMl * 100` из `/i2cstepper?device=pump`; failure/timeout не меняет UI state и не использует старое число как fallback.
- Polling может продолжаться, но не закрывает action и не очищает error до terminal operation. Console errors и unhandled rejections запрещены.

## Fault matrix

| Инъекция | Operation/result | Confirmed state и cleanup |
|---|---|---|
| invalid/unsupported/missing device | record отсутствует; `400/404` | DTO/store/globals неизменны |
| pending lock, mode barrier, occupied slot или config busy до reserve | record отсутствует; existing `503` | pending не перезаписан |
| OperationStore full | record отсутствует; `503 operation_store_full` | store и DTO byte-stable |
| mode switch active между acceptance и claim | record остаётся `queued` | guard под claim-lock не запускает hardware; DTO остаётся для discard |
| mode switch discard queued DTO | `failed/operation_cancelled` | его flag снят, hardware не вызван; `running` DTO не отменяется |
| `i2c_stepper_config_begin()` race после acceptance | `running→failed/i2c_config_busy` | flag снят, confirmed прежний |
| config/command write false или ACK timeout без `dev.error` | `failed/i2c_command_failed` | candidate отброшен, config lock освобождён |
| `candidate.error != 0` | `failed/i2c_device_error` | numeric error только в existing log; confirmed прежний |
| forced refresh false | `failed/i2c_refresh_failed` | candidate отброшен |
| refresh true, затем nonzero error | `failed/i2c_device_error` | candidate отброшен |
| start/stop failure | terminal failed | target/config/running не коммитятся; auto retry отсутствует |
| `/calibrate` I2C calfinish ACK/refresh OK, PersistResult failure | `failed/profile_persist_failed` | старые profile/RAM/device/calibration flag; pending снят |
| `/calibrate` I2C calfinish full success | `succeeded` | persist/read-back раньше всех confirmed assignments |
| generic `/i2cstepper` pump `calstart/calfinish` success | `succeeded` | NVS-call count `0`, `I2CPumpCalibrating`/`SamSetup` не меняются; коммитится только refreshed device |
| `/calibrate` I2C `calfinish` success | `succeeded` | NVS-call count `1`; read-back завершён до `SamSetup`/device/flag commit |
| local calibration invalid state | `failed/operation_runtime_busy` | существующий runtime не меняется |
| local calibration invalid measurement | `failed/calibration_invalid_result` | executor сохраняет текущий stop/error-message порядок; profile прежний |
| local calibration persist failure | `failed/profile_persist_failed` | `SamSetup` прежний |
| terminal publication lock busy | record остаётся `running` до retry | correlation DTO/flag и terminal slot сохранены; hardware/NVS/commit counters остаются равны одному; новый DTO не исполняется |
| SysTicker refresh во время transaction | operation не меняется | busy-bit запрещает параллельный global refresh; cache видит old либо committed state, не partial |
| UI poll timeout/network/expired ID | backend сохраняет свой terminal lifecycle | UI не показывает success и не повторяет hardware command |

## Проверки, map и review

1. `tools/smoke_i2c_operation_results.py`: C++11 harness механически включает production `I2CStepper.h` с fake Arduino/Wire/I2C2/FreeRTOS boundaries и извлекает точные owner bodies через `smoke_helpers.extract_function_body`. Он проверяет partial write, ACK timeout, device error, forced-refresh failure/success, config busy, NVS failure, local calibration results, mode barrier между acceptance/claim, terminal lock busy, атомарную очистку matching DTO/flag+slot и отсутствие повторного side effect. Отдельные counters доказывают: generic `/i2cstepper` `calstart/calfinish` вызывает NVS `0` раз и не меняет calibration flag, `/calibrate` I2C finish вызывает verified save ровно `1` раз. `#ifdef TEST`, callback/fault injection в production и копия owner-алгоритма запрещены.
2. Обновить все прямо устаревшие tests из allowlist, включая `tools/smoke_operation_store.py` и `tools/smoke_profile_operation.py`. Их behavioral harness/fault matrix не удалять и не ослаблять; заменить только profile-only source assertions с глобальными exact counts на function-owner inventory:
   - в production существует ровно один zero-initialized `OperationStore operationStore{}` в `Samovar.ino` и ровно один `extern` в `samovar_api.h`; второй store, wrapper, mutex или task запрещён;
   - `operation_store_reserve_locked()` разрешён только внутри `queue_profile_operation()` и четырёх A-02 acceptance owners `queue_pending_i2cstepper()`, `queue_pending_i2cpump()`, `queue_pending_i2ccal()`, `queue_pending_local_cal()`; каждый owner содержит свой reserve после всех отказных checks и до неразрывной DTO/flag publication, а вне этого inventory production reserve отсутствует;
   - `WebServer.ino` и `samovar_api.h` не содержат ни `operation_store_mark_running_locked()`, ни `operation_store_finish_locked()`; WebServer-side queue owners только reserve-ят;
   - в `Samovar.ino` mark/finish разрешены только существующим profile owners `process_profile_operation()`/`publish_profile_operation_terminal()` и новым loop owners `process_pending_i2c_operations()`/`cancel_queued_i2c_operations_locked()`: основной A-02 owner делает `QUEUED → RUNNING` и terminal publication, cancellation owner делает только `QUEUED → FAILED/CANCELLED`, без mark и без hardware;
   - source assertion проверяет единственный вызов `process_pending_i2c_operations()` из `loop()` до mode-switch early return и единственную loop-only цепочку `process_profile_operation() → switch_samovar_mode() → discard_pending_mode_control_commands() → cancel_queued_i2c_operations_locked()`; остальные production functions/files не владеют transition callsites.

   Затем отдельно выполнить `python3 tools/smoke_operation_store.py`, `python3 tools/smoke_profile_operation.py`, новый A-02 fault suite и `smoke_ui_pack_assets.py`. Последний gate обязан подтвердить source/canonical-gzip/manifest SHA parity двух изменённых UI assets и exact `_EXPECTED_UI_TOTALS`; maxima/derived-cap fixture остаются byte-identical, если size bucket не пересечён.
3. Новый `test_i2c_operation_results_browser.py` обязательно запускается через skill `playwright-cli`: `/i2cstepper` present=0/1; `queued→running→succeeded`; command/device/refresh/persist failed; timeout/network/404; config dirty preservation; relay/start/stop; local/I2C calibration start/finish; double click; zero console errors. Проверить, что lookup идёт только через существующий `/ajax`.
4. Затем последовательно: `python3 tools/run_smoke_tests.py`, blocking cppcheck, `pio run -e Samovar`, `pio run -e Samovar_s3`, `pio run -e Samovar_lua_mqtt`, остальные четыре environments (`Samovar_no_power`, `Samovar_rmvk`, `Samovar_sem`, `Samovar_alarm_button`), `git diff --check` и allowlist audit. Не запускать cppcheck и PlatformIO параллельно.
5. Подтвердить `static_assert` budgets: DTO после `OperationId` не больше 64/24/12/8 байт, A-02 static delta не больше 24 байт, terminal result не больше 8 байт. Stack gate — это воспроизводимый per-function/project-visible contract для optimized `Samovar`, а не оценка полного runtime stack:
   - измеренные caps: `loop() <= 736`, `pump_calibrate() <= 576`, `save_profile_nvs() <= 1648` байт; максимальная одновременная вложенная цепочка project-owned codec/writer под `save_profile_nvs()` — `<= 64` байт;
   - project-visible I2C `calfinish` chain: `736 + 1648 + 64 = 2448` байт; local `calfinish` chain: `736 + 576 + 1648 + 64 = 3024` байт; hard project-visible cap для обеих цепочек — `<= 3072` байт. Превышение любого per-function cap или итогового chain cap блокирует приёмку;
   - воспроизвести замер без изменения `platformio.ini` и сохранить `.su`/дизассемблированный call graph как evidence:

     ```bash
     PLATFORMIO_INI_SHA_BEFORE="$(sha256sum < platformio.ini)"
     pio run -e Samovar -t clean
     PLATFORMIO_BUILD_SRC_FLAGS='-fstack-usage' pio run -e Samovar
     SU=.pio/build/Samovar/src/Samovar.ino.cpp.su
     test -s "$SU"
     awk -F '\t' '
       BEGIN { loop_frame = pump_frame = save_frame = -1 }
       $1 ~ /void loop\(\)$/ { loop_frame = $2 }
       $1 ~ /PumpCalibrationResult pump_calibrate\(int\)$/ { pump_frame = $2 }
       $1 ~ /PersistResult save_profile_nvs\(const SetupEEPROM&\)$/ { save_frame = $2 }
       END {
         printf "loop=%d pump_calibrate=%d save_profile_nvs=%d\n", loop_frame, pump_frame, save_frame
         exit !(loop_frame >= 0 && loop_frame <= 736 &&
                pump_frame >= 0 && pump_frame <= 576 &&
                save_frame >= 0 && save_frame <= 1648)
       }
     ' "$SU"
     rg -n 'CanonicalProfileWriter|ProfileBlobCodec.*decode|profile_crc32_iso_hdlc' "$SU"
     OBJDUMP="$HOME/.platformio/packages/toolchain-xtensa-esp32/bin/xtensa-esp32-elf-objdump"
     "$OBJDUMP" -Cd .pio/build/Samovar/firmware.elf > /tmp/samovar-a02-stack.objdump
     rg -n '<loop\(\)>|<pump_calibrate\(int\)>|<save_profile_nvs\(SetupEEPROM const&\)>|call[0-9]*.*<(pump_calibrate|save_profile_nvs|ProfileBlobCodec.*decode|profile_crc32_iso_hdlc)' /tmp/samovar-a02-stack.objdump
     test "$PLATFORMIO_INI_SHA_BEFORE" = "$(sha256sum < platformio.ini)"
     ```

   - `.su` и objdump не покрывают внешние фреймы `Preferences`, NVS/IDF и Arduino `loopTask`; поэтому `3072` нельзя объявлять полным task-stack bound. HIL high-water остаётся непроверенным и фиксируется как ограничение, а не как пройденный gate.
6. После зелёных gates точечно обновить `Last reviewed` nodes `operation-store-h`, `i2cstepper-h`, `samovar-ino`, `webserver-ino`, `logic-h`, `samovar-api-h`, `data`, `tools`; mapper только `update-node`, при failure targeted `repair`, без full regeneration.
7. Reviewer читает весь A-02 diff и возвращает ERROR/WARNING либо точный `PASS: no errors, no warnings`. Любая находка исправляется в том же allowlist, затронутые backend/browser/build gates и review повторяются. Master ledger менять только после чистого PASS.

## Итог реализации — PASS

- Реализация завершена в зафиксированной границе: методы GET и имена routes сохранены, новый endpoint/task/queue/mutex/fallback/security-path не добавлены, generic `/i2cstepper` calibration не получил NVS- или `I2CPumpCalibrating`-side effects.
- Focused static/host gates: 10/10; полный smoke: 54/54; blocking cppcheck: без error/warning diagnostics; PlatformIO: 7/7 environments `SUCCESS`.
- Browser gates через `playwright-cli`: A-02 — 15 сценариев с нулём console/page errors, включая terminal success с ошибкой secondary readback без lifecycle rollback; numeric regression — 36 checks/9 contracts.
- UI source/canonical-gzip/manifest parity и pack/format gates прошли; итоговый maximum pack budget — 126976 байт при LittleFS 786432 байта; `git diff --check` и затронутые codebase-map nodes проверены.
- Stack gate: `loop=736`, `pump_calibrate=576`, `save_profile_nvs=1648`; project-visible chains 2448/3024 байта не превышают cap 3072. Внешние `Preferences`/NVS/Arduino frames и HIL high-water этим измерением не покрыты и честно остаются непроверенными.
- Независимый reviewer после исправления всех находок вернул точный `PASS: no errors, no warnings`.

## Rollback и stop conditions

- Code rollback — только обратный patch собственных строк A-02: DTO fields, error literals, queue/loop transitions, responses, UI waiter wiring, tests/hashes и map metadata откатываются согласованно. `git reset`, checkout и очистка чужого dirty tree запрещены.
- Не оставлять operation-bearing DTO без terminal owner, waiter без producer либо старый ранний-success UI рядом с новым lifecycle. Не оставлять альтернативный I2C path или disabled compatibility code.
- Физически выполненный command при потерянном ACK/refresh и внешний calfinish не откатывать и автоматически не повторять; operation остаётся failed, оператор получает явную ошибку, следующий обычный status refresh лишь показывает наблюдаемое состояние.
- Если A-12 API не позволяет проверить PersistResult до RAM commit либо atomically reserve+publish под существующим lock, остановиться: fallback, second store/lock и частичный commit запрещены.
- Повтор одной ошибки дважды запускает обязательное web-исследование 3–5 решений до следующей попытки.
