# R2.0 — минимальный OperationStore

## 1. Решение и критерий завершения

R2.0 создаёт только фиксированное POD-хранилище результатов и optional read-only lookup через существующий `/ajax`. В production-коде R2.0 нет ни одного вызова reserve: текущие `Pending*` DTO ещё не несут `operationId`, а loop ещё не завершает операции. Поэтому R2.0 не может оставить запись навсегда в `queued`.

Первый production consumer — A-12 (`/save` и `/program`), затем тот же контракт применяет A-02 (I2C/калибровка). В каждом consumer reserve операции и публикация pending-буфера выполняются одной транзакцией под существующим `pending_command_lock()`.

R2.0 завершён, когда:

- store состоит только из POD, имеет фиксированную ёмкость и не использует `String`, STL-контейнеры, callback, timestamp, `new`/`malloc`;
- ID — ненулевой `uint32_t`, wrap пропускает `0` и не сталкивается с retained ID;
- активные записи не вытесняются; при отсутствии empty slot переиспользуется oldest terminal record по modular age ненулевого sequential ID относительно `nextId`, а заполненный активными записями store возвращает `operation_store_full` без мутаций;
- разрешены `queued -> running`, `running -> succeeded|failed` и явный `queued -> failed` для отмены/revalidation до execution; `queued -> succeeded` и invalid/repeated terminal transition не меняют запись;
- lookup недеструктивен и копирует запись под `pending_command_lock`, а JSON строится после unlock;
- `/ajax` без `operationId` сохраняет прежний telemetry contract; found lookup возвращает `operationId/state/error`, а invalid/not-found/busy — только `operationId/error` без выдуманного state; все ветки `/ajax` имеют `Cache-Control: no-store`;
- не добавлены route, mutex, task, очередь, server-side session, heap-owned record или fallback;
- production call count `operation_store_reserve_locked(...)` равен нулю до A-12.

## 2. Проверенные точки интеграции

- `runtime_helpers.h::pending_command_lock()` / `pending_command_unlock()` уже владеют `xPendingCommandSemaphore`; файл не менять.
- `Samovar.ino` владеет pending storage рядом с `PendingProgramUpdate`, `PendingSetupSave`, `PendingI2CStepperCmd`, `PendingI2CPumpCmd`, `PendingI2CCalCmd`, `PendingLocalCalCmd`; здесь же должен находиться единственный `OperationStore operationStore`.
- `WebServer.ino` уже публикует pending work в `queue_pending_program()`, `queue_pending_program_metadata()`, `queue_pending_setup_save()`, `queue_pending_i2cpump()`, `queue_pending_i2cstepper()`, `queue_pending_i2ccal()`, `queue_pending_local_cal()` под тем же lock. R2.0 эти helpers не меняет; они являются точными integration points A-12/A-02.
- `Samovar.ino::send_ajax_json(AsyncWebServerRequest*)` — существующий owner `/ajax`; `WebServer.ino` route остаётся `server.on("/ajax", HTTP_GET, ...)` без нового endpoint.
- `samovar_api.h` уже объявляет `send_ajax_json()` и остаётся declaration-only.

## 3. Структура `operation_store.h`

Новый корневой header, C++11, без Arduino/FreeRTOS include:

- `using OperationId = uint32_t`;
- `enum OperationKind : uint8_t`: `NONE`, `SAVE`, `PROGRAM`, `I2C_STEPPER`, `I2C_PUMP`, `CALIBRATION`;
- `enum OperationState : uint8_t`: `EMPTY`, `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`;
- `enum OperationError : uint8_t`: `NONE`, `INVALID_ID`, `NOT_FOUND`, `STORE_FULL`, `LOCK_BUSY`, `INVALID_TRANSITION`, `INTERNAL`; A-12/A-02 добавляют только свои стабильные codes, когда появляется соответствующий failure;
- `OperationRecord { OperationId id; OperationKind kind; OperationState state; OperationError error; }`;
- `OperationStore { OperationRecord records[8]; OperationId nextId; }`; новых per-record age/generation fields нет.

Ёмкость фиксируется как `OPERATION_STORE_CAPACITY = 8`: текущие планируемые consumers допускают не более четырёх независимых active pending categories, ещё четыре slots остаются для terminal polling. Переполнение всё равно является штатной явной ошибкой, а не поводом увеличить store динамически.

Добавить `static_assert` на trivial/standard-layout типов, `sizeof(OperationRecord) <= 8` и RAM budget `sizeof(OperationStore) <= 68`. `nextId` хранит следующий candidate; zero-init означает candidate `1`, а после выдачи allocator продвигает его к следующему ненулевому значению. Inline API принимает `OperationStore&` и имеет суффикс `_locked`; он не берёт lock самостоятельно:

- `operation_store_reserve_locked(store, kind, outId)`;
- `operation_store_copy_locked(store, id, outRecord)`;
- `operation_store_mark_running_locked(store, id)`;
- `operation_store_finish_locked(store, id, terminalState, error)`;
- `operation_state_code(state)` и `operation_error_code(error)` возвращают только указатели на static literals.

Алгоритм reserve:

1. Отклонить `NONE`, не меняя store.
2. Сначала выбрать empty slot с минимальным array index.
3. Если empty нет, среди terminal records выбрать максимальный modular age `uint32_t(nextId - record.id)`. Ненулевые ID выдаются последовательно, retained window равен восьми записям и заведомо `<< 2^31`, поэтому unsigned modular distance однозначно определяет самый старый retained ID даже через wrap; порядок завершения и физический slot на выбор не влияют.
4. Если все slots `QUEUED/RUNNING`, вернуть `STORE_FULL` без изменения `nextId` и records.
5. Взять текущий ненулевой candidate (`0` после zero-init трактуется как `1`), bounded scan-ом исключить совпадение с любым retained ID и после выдачи продвинуть `nextId`, пропуская `0` на wrap.
6. Одной POD-записью опубликовать `{id, kind, QUEUED, NONE}`. Никакой cursor, timestamp, completion counter или age field не добавляется.

`finish` принимает `SUCCEEDED` с `NONE` только из `RUNNING`. `FAILED` с ненулевой ошибкой разрешён из `RUNNING`, а также напрямую из `QUEUED` для явной отмены/revalidation до начала execution. `QUEUED -> SUCCEEDED`, failed с `NONE`, любая другая пара, неизвестный ID и повторный terminal transition возвращают явную ошибку и оставляют record byte-for-byte прежним.

## 4. Изменения по файлам

1. `operation_store.h` — типы, fixed store и pure inline algorithms из раздела 3. Никаких lock/API/HTTP зависимостей.
2. `Samovar.ino`:
   - подключить header в существующем first-party include block;
   - определить единственный zero-initialized `OperationStore operationStore` рядом с pending storage;
   - в начале `send_ajax_json()` отделить lookup-ветку от обычного telemetry path;
   - при наличии ровно одного `operationId` строго разобрать 1–10 decimal digits с overflow check в диапазоне `1..UINT32_MAX`; не применять `toInt()`, sign, whitespace или partial parse;
   - взять `pending_command_lock`, скопировать `OperationRecord`, отпустить lock и только затем сериализовать в fixed stack buffer;
   - без аргумента не брать pending lock и оставить существующую telemetry serialization неизменной, добавив `Cache-Control: no-store` к её response;
   - не добавлять reserve/transition callsite в R2.0.
3. `samovar_api.h` — подключить `operation_store.h` после существующих базовых includes и объявить только `extern OperationStore operationStore`; реализаций и wrapper/shim-функций не добавлять.
4. `WebServer.ino` — source в R2.0 не менять. Existing `/ajax` route продолжает вызывать `send_ajax_json()`. Queue helpers меняются только соответствующими consumer-задачами.
5. `runtime_helpers.h` — не менять: повторно используется существующий pending lock, новый lock запрещён.

Wire contract lookup:

| Условие | HTTP | Тело |
|---|---:|---|
| found | 200 | ровно `operationId`, record `state`, record `error` |
| missing/expired | 404 | ровно requested `operationId`, `error:"operation_not_found"`; `state` отсутствует |
| invalid/duplicate ID | 400 | ровно `operationId:0`, `error:"invalid_operation_id"`; `state` отсутствует |
| pending lock timeout | 503 | ровно requested `operationId`, `error:"operation_store_busy"`; `state` отсутствует |

Wire state `unknown` не вводить. `kind`, timestamps, detail, payload и telemetry fields в lookup-response не включать. Missing ID не переводить в telemetry fallback.

## 5. Обязательный контракт первых consumers

A-12 изменяет `queue_pending_setup_save()`, `queue_pending_program()` и `queue_pending_program_metadata()`; A-02 затем изменяет четыре `queue_pending_i2c*`/`queue_pending_*cal()` helpers. Для каждого helper порядок один:

1. Выполнить parse/validation до lock.
2. Взять `pending_command_lock()` и повторно проверить mode barrier и соответствующие busy flags/slots.
3. Только после всех отказных проверок вызвать `operation_store_reserve_locked()`.
4. При `STORE_FULL` снять lock и вернуть route явный `503 operation_store_full`; pending storage не меняется.
5. При success записать тот же `operationId` в локальную копию pending DTO, скопировать DTO в owner buffer, выполнить существующий publish barrier и выставить flag/action.
6. После reserve не иметь ни одного условного failure/return до pending publication; затем unlock и вернуть accepted result с тем же ID.
7. Loop под этим же lock копирует DTO, снимает pending flag и переводит `QUEUED -> RUNNING`; terminal result записывает повторно взяв lock. Отмена или failed revalidation до execution переводит запись прямо `QUEUED -> FAILED`, без фиктивного `RUNNING`. Любой discard pending-команды обязан завершить связанную operation как failed, а не просто потерять ID.

Это запрещает два отдельных lock windows `reserve()` и `queue()`, rollback-record после неудачной queue, callback-транзакцию и orphan record.

## 6. Failure matrix и тесты

Создать один `tools/smoke_operation_store.py`. Он компилирует C++11 harness во временном каталоге вне репозитория (проектный `.cpp` не создавать) и проверяет поведение, а затем выполняет узкие source assertions.

Behavioral matrix:

- zero-init, первый ID `1`, `UINT32_MAX -> 1`, skip `0`, wrap collision с retained ID;
- empty slots всегда выбираются раньше terminal; без empty выбирается terminal с максимальным modular age относительно `nextId`, включая wrap и независимо от array index/порядка завершения;
- восемь `QUEUED/RUNNING` records -> `STORE_FULL` и полный snapshot store неизменен;
- `QUEUED -> RUNNING -> SUCCEEDED`, `QUEUED -> RUNNING -> FAILED` и explicit cancellation/revalidation `QUEUED -> FAILED`;
- `QUEUED -> SUCCEEDED`, `RUNNING -> RUNNING`, terminal -> anything, success с ошибкой и failed с `NONE` отклоняются без мутации;
- lookup `0`, unknown, found active, found terminal, expired после reuse;
- два reader threads под тестовым mutex получают одинаковый terminal record; чтение ничего не очищает;
- POD/static RAM assertions проходят с `-std=c++11 -Wall -Wextra -Werror`; store не содержит `reuseCursor` или новых per-record ordering fields.

Static gates:

- в `operation_store.h` отсутствуют `String`, STL containers, FreeRTOS semaphore/task/queue calls, `new`, `malloc`, callback и timestamp;
- в production-файлах R2.0 нет вызова `operation_store_reserve_locked` или transition API;
- нет нового `server.on`, mutex/semaphore/task declaration;
- found `/ajax` lookup имеет ровно три поля, failure lookup — ровно два поля без `state`; все имеют `no-store`, обычная ветка сохраняет прежние telemetry keys;
- strict ID parser не содержит `toInt()` и partial/zero acceptance;
- `operation_store.h` добавлен в `tools/static_analysis_sources.json`.

Финальные gates выполнять последовательно:

1. `python3 tools/smoke_operation_store.py`.
2. `python3 tools/run_smoke_tests.py`.
3. Существующий blocking cppcheck gate.
4. `pio run -e Samovar`.
5. `pio run -e Samovar_s3`.
6. `git diff --check` и проверка write allowlist.

UI assets не меняются, production operation ещё не создаётся, поэтому browser lifecycle проверяется не в R2.0, а обязательным `playwright-cli` gate первого consumer и общего Gate W2.

## 7. Write allowlist и codebase map

Разрешены только:

- `operation_store.h`;
- `Samovar.ino`;
- `samovar_api.h`;
- `tools/smoke_operation_store.py`;
- `tools/static_analysis_sources.json`;
- `.cli-proxy/.codebase_map/nodes/operation-store-h.md`;
- metadata/`Last reviewed` только в nodes `samovar-ino.md`, `samovar-api-h.md`, `webserver-ino.md`, `tools.md` и в точечно обновлённых mapper index/state/graph entries для нового header.

`WebServer.ino`, `runtime_helpers.h`, `Samovar.h`, `data/**`, `libraries/**`, `platformio.ini` и существующие smoke tests запрещены к записи. Map обновить targeted-командой; если она меняет посторонние nodes, остановиться и выполнить targeted repair, а не принимать широкий rewrite.

## 8. Rollback и stop conditions

- Rollback — только обратный patch собственных строк/новых файлов из allowlist; `git reset`, checkout и очистка чужого dirty tree запрещены.
- Откатывать header, global/API declaration, lookup branch, test/inventory и map entries согласованно; не оставлять exposed lookup на удалённый store.
- Если в R2.0 появляется production reserve, terminal transition или изменение pending DTO/helper, остановиться: это нарушение wave boundary и риск вечного `queued` record.
- Если A-12 не может поместить reserve и pending publication в один существующий lock window без отказной ветки после reserve, не добавлять rollback/fallback/второй путь — вернуть evidence и пересогласовать consumer plan.
- Повтор одной ошибки дважды запускает обязательное web-исследование 3–5 решений по правилу репозитория.

## 9. Зафиксированное sequencing-противоречие

Требование «атомарный reserve + pending publication» нельзя реализовать end-to-end внутри R2.0 одновременно с исходной границей master plan: operation-bearing DTO и loop terminal transitions появляются только в A-12/A-02. Решение — R2.0 поставляет и тестирует pure store и read-only lookup, но запрещает production reserve; A-12 является первой атомарной интеграцией, A-02 повторяет её. Неразрешённых противоречий после этого разделения нет.
