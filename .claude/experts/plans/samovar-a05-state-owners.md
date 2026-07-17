# A-05 / R4.1 — immutable request-local `/ajax` telemetry snapshot

## 1. Цель и граница

Закрыть единственный оставшийся live-дефект A-05: normal telemetry-ветка
`Samovar.ino::send_ajax_json()` копирует protected status/event fields, но после
начала JSON response напрямую перечитывает mutable sensors, settings, stepper,
I2C cache, mode, power и predictor state. Один response поэтому может смешать
значения, изменившиеся уже во время serialization/network I/O.

Готово, когда каждый telemetry request сначала получает локальный
`AjaxTelemetrySnapshot`, а затем сериализуется только из
`const AjaxTelemetrySnapshot&`. Гарантия ограничена одним response: snapshot
после capture не меняется. Общая транзакция runtime и одинаковая generation для
двух readers не обещаются, потому что общего writer lock в live tree нет.

Не добавлять owner framework, header, task, queue, mutex, route, setting, UI,
fallback, shim или compatibility path. GET `/ajax` и весь существующий wire
contract сохраняются.

## 2. Prerequisites и уже закрытый scope

Реализацию начинать только после Gate W3 и стабильного `Samovar.ino`:

- A-12 — `PASS: no errors, no warnings`: OperationStore, ProfileOperationSlot,
  profile persistence и committed `SamSetup` не переоткрывать;
- A-13 — `PASS: no errors, no warnings`: RuntimeEventRing, недеструктивный cursor,
  `copy_ajax_runtime_snapshot()` и checked event suffix не менять;
- A-14 — `PASS: no errors, no warnings`: notification queue/delivery не менять.

Перед patch сохранить в `/tmp` scoped SHA и точный baseline operation/query/error/
event blocks и key order. Чужой dirty diff не форматировать и не откатывать.

Live `runtime_helpers.h::copy_ajax_runtime_snapshot()` уже под существующим
`xRuntimeStateSemaphore` копирует `Crt`, `SamovarStatus`, `Lua_status`,
`current_power_mode` и максимум один A-13 event, затем освобождает lock. Он
остаётся read-only и вызывается новым capture ровно один раз. Если без его
изменения correctness невозможна, остановиться и пересогласовать allowlist;
wrapper/overload/второй helper не создавать.

Operation lookup остаётся отдельной ранней веткой
`operation_store_copy_locked()` под `pending_command_lock()` и не входит в
telemetry snapshot.

## 3. Неизменяемый observable contract

Сохраняются:

- GET `/ajax` и exact query classification `operationId`/`messageCursor`;
- operation success/not-found/lock-busy bodies, status codes и `no-store`;
- telemetry `200 application/json`, `Cache-Control: no-store`;
- `503 Runtime state busy` для runtime lock busy;
- `503 Runtime event snapshot unavailable` для A-13 allocation/corruption;
- `503 Runtime event response unavailable` для checked event-write failure;
- JSON escaping, types, precision, conditions, braces и event/no-event paths.

Operation/query/error helpers и `runtimeEventWriteSection()`/
`sendRuntimeEventResponse()` — read-only. Serializer сохраняет live key order:

```text
bme_temp, bme_pressure, start_pressure, crnt_tm, stm,
SteamTemp, PipeTemp, WaterTemp, TankTemp, ACPTemp,
DetectorTrend, DetectorStatus, useautospeed, version,
VolumeAll, ActualVolumePerHour, PowerOn, PauseOn, WthdrwlProgress,
TargetStepps, CurrrentStepps, WthdrwlStatus, ProgramNum, ProgramIndex,
CurrrentSpeed, UseBBuzzer, StepperStepMl, BodyTemp_Steam, BodyTemp_Pipe,
mixer, ISspd,
i2c_stepper_present, i2c_mixer_present, i2c_pump_present,
i2c_pump_speed, i2c_pump_target_ml, i2c_pump_remaining_ml,
i2c_pump_running,
heap, rssi, fr_bt, PrgType,
current_power_volt, target_power_volt, current_power_mode, current_power_p,
[wp_spd], [WFflowRate, WFtotalMl], [prvl],
[alc, stm_alc], [TimeRemaining, TotalTime],
Status, Lstatus,
[Msg, msglvl, messageSequence | LogMsg, messageSequence]
```

Квадратные скобки — только текущие compile/runtime conditions. Event fields
по-прежнему дописываются последними неизменённым A-13 checked writer.

Обязательная byte parity:

- precision 3: BME/sensors/trend/body/actual rate/`ISspd`; precision 1: power и
  present-I2C target/remaining; precision 2: water flow/pressure/alcohol;
- `ProgramNum + 1`, zero-based `ProgramIndex` и прежний `round(speed * state)`;
- при absent I2C pump четыре pump fields — integer `0`;
- без `SAMOVAR_USE_POWER`: `0`, `0`, string `"0"`, `0`;
- прежние mode/status/PowerOn predicates для `PrgType`, alcohol и predictor;
- прежние `USE_WATER_PUMP`, `USE_WATERSENSOR` и pressure guards;
- один captured `millis()` для uptime и по одному capture heap/RSSI/free bytes.

## 4. Минимальная реализация

В `Samovar.ino`, рядом с единственным consumer, определить private:

```text
AjaxTelemetrySnapshot
captureAjaxTelemetrySnapshot(messageCursor, snapshot)
writeAjaxTelemetryFields(Print&, const AjaxTelemetrySnapshot&)
```

Snapshot хранит только wire scalars/final derived values и уже существующие
request-local strings (`crt`, statuses, power mode, computed program type,
`eventText`), A-13 descriptor и `hasEvent`. Не копировать целые `SetupEEPROM`,
`DSSensor`, detector, stepper/cache или predictor objects; не хранить mutable
references/pointers.

Capture:

1. вызывает неизменённый `copy_ajax_runtime_snapshot()` ровно один раз;
2. до response creation по одному разу получает остальные final wire values,
   включая результаты `get_liquid_volume()`, stepper getters, `round()`, alcohol,
   program type и predictor conditions;
3. использует только короткие существующие locks/getters и возвращается без
   удерживаемого lock;
4. для settings/I2C cache и других источников без общего lock сохраняет текущую
   best-effort field-copy semantics; writer/lock policy не меняется и
   межполевая атомарность не заявляется.

После query/operation branches `send_ajax_json()` создаёт local snapshot,
обрабатывает прежние typed capture errors, только при success вызывает
`beginResponseStream()`, пишет normal fields через const serializer и передаёт
только snapshot event members в неизменённый A-13 suffix.

Новый header отвергнут: consumer один. Общий owner/lock отвергнут как big-bang
rewrite. Whole-JSON `String` отвергнут как лишняя request heap allocation.

## 5. Порядок работ

1. Freeze prerequisites, scoped hashes и exact wire baseline.
2. Добавить красный `tools/smoke_a05_state_owners.py`: live normal branch обязан
   падать из-за mutable reads после `beginResponseStream()`.
3. Добавить только local snapshot/capture/serializer в `Samovar.ino`.
4. Перевести normal telemetry writes на const snapshot; operation/query/event
   paths не редактировать.
5. Довести focused test до green, выполнить regressions/parity/resource gates.
6. После software/browser/build PASS обновить только affected map metadata.
7. Выполнять independent reviewer-loop до точного
   `PASS: no errors, no warnings`; только затем обновить A-05 status/ledgers.

## 6. Production-derived focused test

`tools/smoke_a05_state_owners.py` source-extract-ит фактические snapshot/capture/
serializer из `Samovar.ino`, компилирует временный C++11 harness с минимальными
fixtures/stubs и не оставляет project `.cpp`. Копировать production mapping или
serializer в Python/C++ fixture запрещено.

Обязательные cases:

- **red-before-green:** post-capture serializer не содержит зафиксированных
  mutable source symbols/global-reading helpers;
- **mutation:** capture A → mutation всех source fixtures → serialization A
  byte-identical; capture B отражает mutation. Это независимые request copies,
  не shared generation;
- **golden parity:** byte-for-byte expected JSON для default и feature matrices;
  golden фиксирует wire contract, а не дублирует algorithm;
- **compile/runtime guards:** power on/off, water/pump/pressure defines, I2C
  present/absent, rectification/distillation/BK/NBK/other modes, program type,
  predictor, MESSAGE/CONSOLE/no event;
- **failure mapping:** existing helper `LOCK_BUSY`/`NO_MEMORY`/`CORRUPT` даёт
  прежний no-store 503 до response stream, без partial JSON;
- **operation isolation:** pre-patch operation/query/error block byte-identical и
  прежние success/not-found/lock-busy/invalid behaviors зелёные;
- **A-13 regression:** event snapshot не потребляется, checked suffix неизменён;
  existing A-13 tests остаются authoritative для cursor/overflow/short write;
- **scope:** один local type/capture/serializer, один helper call, нет нового
  header/global/route/task/queue/mutex/fallback/shim.

## 7. Exact write allowlist

Текущий planning-pass меняет только этот файл. Реализации разрешены:

- `Samovar.ino` — только private snapshot/capture/serializer и normal telemetry
  wiring внутри `send_ajax_json()`;
- `tools/smoke_a05_state_owners.py` (new);
- только stale static integration assertions в
  `tools/smoke_runtime_event_ring.py`, `tools/smoke_operation_store.py`,
  `tools/smoke_api_routes.py` и `tools/smoke_program_type_contract.py`: после
  переноса ownership они source-extract-ят новый capture/writer boundary;
  behavioral harnesses, ключи, порядок, типы и сценарии не меняются;
- после green gates: `.cli-proxy/.codebase_map/nodes/samovar-ino.md`,
  `.cli-proxy/.codebase_map/nodes/tools.md`,
  `.cli-proxy/.codebase_map/TESTING.md` (`60 smoke / 6 browser`: 58 после A-01,
  59 после A-04 и 60 после нового A-05 smoke);
- после reviewer PASS: status этого plan и только A-05/evidence строки двух
  master-ledgers.

Read-only: `runtime_helpers.h`, `runtime_event_log.h`, `operation_store.h`,
`profile_store.h`, `Samovar.h`, `samovar_api.h`, `WebServer.ino`, `Blynk.ino`,
`lua.h`, `NVS_Manager.ino`, `I2CStepper.h`, `data/**`, `web_src/**`, `libraries/**`,
`platformio.ini`, workflows и UI pack tools/contracts. Новый map node/graph
topology не нужны. Необходимость выйти за allowlist останавливает работу.

Изначальная read-only граница для четырёх перечисленных smoke-файлов была
скорректирована после RED: проверки были текстово привязаны к старой inline
serialization, поэтому корректный ownership move ломал только их static
boundary. Shim/comment/unreachable path отвергнуты; Tree-sitter и Clang
LibTooling/ASTMatchers отвергнуты как новые непропорциональные dependencies.

## 8. Resource и verification gates

- `static_assert(sizeof(AjaxTelemetrySnapshot) <= 512)` ограничивает stack object,
  но не маскирует heap уже существующих request-local Arduino `String` payloads;
- новые global/retained heap buffers запрещены;
- записать `sizeof(snapshot)`, optimized `-fstack-usage` для `send_ajax_json`,
  capture/serializer, before/after stack frames, `.bss`, `.data`, RAM/flash delta;
- hardware free-heap/high-water при отсутствии ESP32 честно отметить `not run`.

Cppcheck и PlatformIO выполнять последовательно на frozen source:

```text
python3 tools/smoke_a05_state_owners.py
python3 tools/smoke_operation_store.py
python3 tools/smoke_profile_operation.py
python3 tools/smoke_runtime_event_ring.py
python3 tools/smoke_notification_queue.py
python3 tools/run_smoke_tests.py --timeout 60
python3 tools/run_cppcheck.py --timeout 300 --report /tmp/samovar-a05-cppcheck.txt
python3 tools/run_cppcheck.py --force --timeout 600 --report /tmp/samovar-a05-cppcheck-extended.txt
pio run -e Samovar
pio run -e Samovar_s3
pio run -e Samovar_lua_mqtt
pio run -e Samovar_no_power
pio run -e Samovar_rmvk
pio run -e Samovar_sem
pio run -e Samovar_alarm_button
git diff --check
```

Обязательно повторить существующий `tools/test_runtime_event_ui_browser.py`
через isolated stable `playwright-cli 0.1.17` из `/tmp`; browser/session/output
artifacts также только в `/tmp`. Это regression production `/ajax`, а не UI
разработка: новый browser test и изменения `data/**` запрещены.

После green gates обновить только allowlisted map nodes/TESTING. Full map
regeneration запрещена; targeted `repair` допустим только после ошибки update
конкретного node.

## 9. Review, rollback и stop conditions

Reviewer проверяет exact scope, GET/wire/status/header parity, const-only
serialization, release locks до JSON/network, mutation/compile guards, resource
evidence, browser regression, full smoke/cppcheck и 7/7 builds. Любой
ERROR/WARNING исправляется в том же allowlist; affected gates и review
повторяются до `PASS: no errors, no warnings`.

Rollback — reverse/revert только собственного A-05 diff без `reset`, `checkout`
или очистки чужого dirty tree; затем focused test, основные builds, browser
regression и `git diff --check`. Persistent/UI migration отсутствует.

Остановиться, если нужен новый header/owner/mutex/task/queue/global buffer, lock
нужно держать при JSON/network/I2C, нарушается response parity, требуется
UI/route/query change или общий runtime writer rewrite. После второго повтора
одной ошибки изучить web и сравнить 3–5 решений по правилу репозитория; fallback
не добавлять.
