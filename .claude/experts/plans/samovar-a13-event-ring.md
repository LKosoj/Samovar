# A-13: недеструктивная доставка `Msg`/`LogMsg` через существующий `/ajax`

## Статус

- Development: complete.
- Review: `PASS: no errors, no warnings`.
- Verification: focused A-13 contracts; `56/56` full smoke; blocking cppcheck без `error/warning`; extended cppcheck только с `information`; `7/7` PlatformIO environments; `6/6` browser contracts через изолированный stable `playwright-cli 0.1.17`; `git diff --check` PASS; codebase map `72 nodes / 550 edges`, durable inventory `56 smoke / 6 browser`.
- Resources: `RuntimeEventRing` symbol `10448 B`, `.bss +10408 B`, `.data +0`; `send_ajax_json` frame `320 -> 304 B`, project-owned non-inlined chain `368 B <= 384 B`; `platformio.ini` SHA не изменился.
- Limit: HIL free-heap/high-water не запускался из-за отсутствия ESP32 и не объявляется PASS.

## 1. Граница задачи и критерий готовности

Исправить только A-13: первый poll `/ajax` больше не удаляет web-сообщения и console-log для остальных вкладок. Две вкладки с разной частотой polling должны независимо получить одинаковый сохранённый хвост без дублей внутри каждой вкладки; если медленный клиент отстал дальше ограниченного буфера, разрыв sequence должен быть виден в существующей области сообщений.

A-13 не добавляет пользовательскую функцию и не меняет процессные алгоритмы. Вне scope:

- новый endpoint, SSE/WebSocket, использование существующего `/events` для runtime messages;
- server-side client/session state, acknowledgement, retry, priority, alarm pin/reset lifecycle;
- новый widget, экран, control или persistence;
- FreeRTOS task, mutex, queue, heap-backed records, security/hardening;
- A-14 внешняя notification queue и любые MQTT/Telegram transport changes.

Сохраняются route `/ajax`, operation lookup A-02/A-12, JSON-имена `Msg`, `LogMsg`, `msglvl`, Lua-имя `Msg`, фильтр коротких `SendMsg()` и существующие MQTT/Telegram/Serial/WebSerial side effects. Неизбежная protocol-добавка — query `messageCursor` и response `messageSequence`; она нужна только для исправления destructive consumption.

Готово, когда:

1. два независимых browser context получают один mixed FIFO и не влияют друг на друга;
2. `/ajax` и Lua больше нигде не очищают event owner;
3. long console payload `data/rectificat.lua` размером 8691 байт проходит одним event без truncation/split;
4. bounded overflow виден как sequence gap, а oversize/lock/allocation failures завершаются явно;
5. все targeted/backend/frontend/browser gates, full smoke, blocking analysis и семь firmware environments зелёные;
6. codebase map обновлена, независимый reviewer возвращает точную строку `PASS: no errors, no warnings`, и только после этого обновляются master-ledgers.

## 2. Проверенный live baseline после A-02/A-06

- `runtime_helpers.h:146-160` напрямую читает/перезаписывает `Msg`; `consume_ajax_runtime_snapshot()` на `runtime_helpers.h:178-202` копирует и очищает `Msg`, `msg_level`, `LogMsg` под `xRuntimeStateSemaphore`.
- `append_web_message()` на `runtime_helpers.h:233-249` склеивает вызовы через `"; "` до условного порога 250 байт; один длинный message после reset всё равно может быть больше 250. `append_console_log()` на `runtime_helpers.h:251-263` аналогично использует порог 10000 байт, но один вход длиннее 10000 остаётся целиком. Это не настоящий memory bound.
- Единственные production globals находятся в `Samovar.h:605-607`; кроме `runtime_helpers.h`, прямых firmware readers/writers нет.
- `send_ajax_json()` на `Samovar.ino:2633-2722` сначала ищет `operationId`. Текущая lookup-ветка допускает посторонние mixed query params; A-13 сохраняет valid A-02 lookup, но закрывает эту неоднозначность общей exact-one-param dispatch-проверкой. Обычный telemetry snapshot выполняется на `Samovar.ino:2724-2743`, поля `Msg/msglvl` и `LogMsg` условно пишутся на `Samovar.ino:2863-2876`; все ответы уже `no-store`.
- `SendMsg()` на `Samovar.ino:3055-3083` игнорирует строки короче пяти символов, сохраняет MQTT/Telegram side effects и затем вызывает web append. `WriteConsoleLog()` на `Samovar.ino:3085-3099` сначала нормализует `"`, CR/LF, затем пишет web log и полный текст в Serial/WebSerial.
- Lua descriptor `Msg` на `lua.h:446-477` использует `copy_web_message_raw()`/`set_web_message_raw()`; `sendMsg(text, level)` на `lua.h:724-731` идёт через `SendMsg()`.
- `show_lua_script` реально вызывает `WriteConsoleLog(script)` (`lua.h:1184-1187`, `1327-1330`, `1394-1409`). В tracked assets `data/rectificat.lua` равен 8691 байт; editor допускает пользовательские Lua files без найденного общего size limit. Поэтому прежний план с `char[256]` молча ломал существующий web-console path.
- Пять mode pages (`index`, `beer`, `distiller`, `bk`, `nbk`) вызывают `SamovarApp.pollAjax()` и дублируют blocks `Msg`/`LogMsg`. `chart.htm` не подключает `app.js`, имеет собственные message helpers и ровно один scheduler `startPolling() -> loadDoc() -> setTimeout(..., 2000)`, но читает только `Msg` через raw `fetch('/ajax')`.
- A-02 продолжает использовать точный lookup `/ajax?operationId=<id>`; единственный bundled прямой status readback вне общего poll — `data/calibrate.htm`, сейчас он использует пустой `/ajax` и должен перейти на `/ajax?messageCursor=0`. A-06 не менял `/ajax`.

## 3. Рассмотренные варианты и решение

| Вариант | Плюсы | Почему не выбран |
|---|---|---|
| Fixed records `8 x 256` | простая реализация, около 2 KiB BSS | режет 387-byte tracked `SendMsg` и 8691-byte Lua log; явная регрессия |
| SSE через `/events` | естественный replay transport | новый transport/lifecycle, смешанный deploy и функциональный scope, прямо запрещён |
| Fixed byte pool + fixed descriptors | bounded RAM, variable payload, один owner, сохраняет текущий 10 KB log intent | немного сложнее обычного массива, но сложность локальна и host-testable |

Выбран третий вариант. Он минимально исправляет текущий transport и формализует уже существующий 10000-byte `LogMsg` threshold, не создавая восемь больших слотов.

## 4. Зафиксированный backend contract

### 4.1 Единственный owner и memory budget

Новый корневой inline-header `runtime_event_log.h` содержит только bounded data model и pure functions, не Arduino web/Serial code:

```text
RUNTIME_EVENT_DESCRIPTOR_CAPACITY = 16
RUNTIME_EVENT_TEXT_POOL_BYTES = 10240
RUNTIME_EVENT_MAX_TEXT_BYTES = 10000

RuntimeEventDescriptor:
  uint32_t sequence
  uint16_t offset
  uint16_t length
  uint8_t kind       // MESSAGE | CONSOLE
  uint8_t level      // meaningful only for MESSAGE

RuntimeEventRing:
  RuntimeEventDescriptor descriptors[16]
  char textPool[RUNTIME_EVENT_TEXT_POOL_BYTES + 1]
  uint32_t nextSequence
  uint16_t writeOffset
  uint16_t usedBytes
  uint8_t oldestIndex
  uint8_t count
```

Обязательные compile-time gates:

- `sizeof(RuntimeEventDescriptor) <= 12`;
- `sizeof(RuntimeEventRing) <= 10464`;
- один storage `RuntimeEventRing runtimeEventRing` определяется в `Samovar.ino`; header содержит только `extern` declaration и inline operations;
- в record owner нет `String`, `new`, STL containers или retained heap pointers;
- `.bss`/symbol delta, относимая к owner, не превышает 10464 байт; старые `Msg`, `LogMsg`, `msg_level` удаляются, второй event/log storage запрещён.

Логическая ёмкость pool остаётся ровно 10240 байт: последний `textPool[RUNTIME_EVENT_TEXT_POOL_BYTES]` — guard byte со значением `\0`, никогда не учитывается в `usedBytes`, не выдаётся append-у и не перезаписывается. Он делает чтение дополнительного байта безопасным для используемого Arduino core, где `String::concat(ptr, len)` копирует `len + 1` (`WString.cpp:320-333`), в том числе когда первый wrapped span заканчивается на логической границе pool. Payload хранится как exact bytes без NUL requirement. Append допускает `0..10000` байт, умеет wrap двумя segments и перед записью evict-ит только oldest descriptors, пока одновременно хватает descriptor и byte capacity. Eviction никогда не сравнивает sequence арифметически. Empty `Msg`/`LogMsg` сохраняет текущее поведение: event и sequence не создаются.

`10000` выбран не произвольно: это текущий намеренный `LogMsg` threshold и он покрывает tracked 8691-byte Lua script одним event. Payload `10001+` не режется, не split-ится и не заменяется surrogate/fallback: append возвращает `RUNTIME_EVENT_TEXT_TOO_LONG`, ring/sequence не меняются, caller выводит прямую diagnostic с фактической длиной и лимитом в Serial/WebSerial. `WriteConsoleLog()` всё равно печатает исходный полный текст в Serial/WebSerial; `SendMsg()` сохраняет исходные MQTT/Telegram side effects. Если когда-либо потребуется гарантировать arbitrary uploaded script больше 10000 байт именно в web console, это несовместимо с текущим fixed-budget требованием и потребует отдельного явно согласованного storage/transport решения; A-13 его не изобретает.

Request-local `String`, используемый для snapshot/JSON как и сейчас, не является owner storage. Копирование строит отдельный temporary candidate: сначала `reserve(totalLength)`, затем каждый из одного/двух wrapped spans добавляется только через `concat(ptr, spanLength)` с проверкой bool result и итоговой длины. Output String заменяется candidate только после полного успеха. Reserve/concat failure возвращает typed `RUNTIME_EVENT_SNAPSHOT_NO_MEMORY`; invalid descriptor/span/guard или несовпадение итоговой длины — typed `RUNTIME_EVENT_SNAPSHOT_CORRUPT`. Partial String наружу не выходит, ring/cursor не меняются. A-13-owned transient reserve не больше 10000 байт на telemetry request. На stack запрещены payload arrays.

### 4.2 Ownership, lock и публикация

- Pure functions `runtime_event_append_locked()`, `runtime_event_select_locked()`, `runtime_event_copy_text_locked()` сами не берут semaphore; suffix `_locked` означает обязательный caller-held `xRuntimeStateSemaphore`.
- Все поля ring и его pool читаются/пишутся только под существующим `xRuntimeStateSemaphore`. Atomics не добавляются: semaphore является единственной synchronization boundary.
- `runtime_helpers.h` остаётся единственным firmware adapter: берёт lock, вызывает pure owner, копирует snapshot и освобождает lock. `SendMsg`, `WriteConsoleLog`, Lua и `/ajax` не обращаются к storage напрямую.
- Под lock нет JSON serialization, network/filesystem/Serial/WebSerial I/O или delay. Разрешены metadata scan, bounded byte copy и уже существующие runtime `String` snapshots; diagnostics выполняются после unlock.
- `append_web_message()` и `append_console_log()` возвращают typed result (`OK`, `LOCK_BUSY`, `TEXT_TOO_LONG`), а не теряют failure. `consume_ajax_runtime_snapshot()` переименовывается в недеструктивный `copy_ajax_runtime_snapshot()` и возвращает typed snapshot result (`OK`, `LOCK_BUSY`, `NO_MEMORY`, `CORRUPT`).
- `SendMsg()` по-прежнему отбрасывает `m.length() < 5`; один принятый producer call становится одним MESSAGE event с исходным level. Старое склеивание нескольких producer calls в shared `Msg` удаляется как часть destructive accumulator; UI вызывает прежний message sink один раз на каждый producer event.
- `WriteConsoleLog()` сохраняет текущую quote/CR/LF normalization до append; один вызов становится одним CONSOLE event, включая 8691-byte payload без split.

### 4.3 Sequence, cursor, overflow и reboot

- `0` зарезервирован для bootstrap. Первый event получает `1`; после `UINT32_MAX` следующий получает `1`. `nextSequence`, append order и physical descriptor order изменяются только под lock.
- Server выбирает не больше одного event на response и никогда не удаляет его:
  - cursor `0` -> oldest retained;
  - cursor найден -> physical successor; если cursor является latest, event отсутствует;
  - cursor не найден -> oldest retained;
  - empty ring -> event отсутствует.
- Server ищет cursor equality, а не делает `<`/`>` comparisons; это сохраняет порядок при wrap.
- Полный descriptor ring или недостаток text-pool bytes evict-ит oldest целые events. Следующий ответ медленному клиенту имеет sequence, не равный ожидаемому successor; UI показывает один warning через существующий message sink и затем обрабатывает retained event.
- Cursor продвигается только после успешной валидации и синхронной обработки event sink. HTTP/JSON/snapshot/sink failure и malformed event cursor не меняют.
- Network reconnect той же страницы сохраняет in-memory cursor. Full reload начинает с `0` и получает retained oldest без warning: server sessions/persistence запрещены.
- После reboot volatile ring пуст и sequence снова начинается с `1`. Stale cursor может дать mismatch, а при collision с новым retained sequence — не дать его. Это честное ограничение любого protocol без boot epoch; boot epoch/persistence не добавляются. Tests обязаны покрыть и detectable discontinuity, и collision без ложного обещания.

### 4.4 Точные формы `/ajax` после A-02/A-06

До snapshot `send_ajax_json()` классифицирует весь набор params. Valid lookup/telemetry требуют ровно один query parameter; единственное исключение — duplicate-only `operationId`, который сохраняет существующий A-02 invalid-ID JSON contract:

| Request form | Result |
|---|---|
| ровно один query `operationId=<1..4294967295>`, не post/file | существующая A-02/A-12 lookup branch; success/not-found/busy JSON, status codes и `no-store` не меняются |
| ровно один `operationId`, но invalid value/source, либо два и более params, каждый с именем `operationId` | существующий `400 application/json`, exact body `{"operationId":0,"error":"invalid_operation_id"}`, `Cache-Control: no-store` |
| ровно один query `messageCursor=<0..4294967295>`, не post/file | telemetry `200`, максимум один retained event |
| zero params; unknown name; любое смешение `operationId` с другим именем; duplicate `messageCursor`; post/file или invalid decimal/range `messageCursor` | `400 text/plain`, exact body `BAD_REQUEST`, `Cache-Control: no-store`, operation store/runtime snapshot не читаются |

`data/calibrate.htm` меняет свой confirmed-value readback на exact `/ajax?messageCursor=0`; общий UI всегда передаёт текущий cursor. Global legacy cursor/server session и пустой compatibility fallback запрещены. Firmware и bundled UI deploy-ятся version-locked.

Corrected response сохраняет старые payload fields:

- MESSAGE: ровно `Msg`, `msglvl`, `messageSequence`;
- CONSOLE: ровно `LogMsg`, `messageSequence`, без `msglvl`;
- no event: ни одного из этих четырёх fields;
- `Msg` и `LogMsg` не появляются вместе;
- sequence сериализуется как decimal `uint32_t`, безопасный для JS Number;
- A-13 event fields физически дописываются в самом конце telemetry object, строго после всех существующих telemetry fields. Значения существующих fields и их взаимный порядок сохраняются byte-for-byte; A-13 не переставляет и не переписывает их;
- текущие telemetry fields, content type, route method и `Cache-Control: no-store` не меняются;
- lock busy остаётся `503 text/plain Runtime state busy`; snapshot `NO_MEMORY/CORRUPT` получает явный `503 text/plain Runtime event snapshot unavailable`, также `no-store`;
- для новой последней event-секции отдельный checked writer владеет и проверяет возвращённое число байт каждого leading/internal delimiter, event key, escaped payload chunk, level, sequence и финальной закрывающей `}` до `request->send(response)`. После начала event-секции никаких других, в том числе unchecked, response writes нет. No-event branch сохраняет прежний путь закрытия telemetry object и его существующую checked/unchecked семантику без A-13-рефакторинга. Это обязательно, потому что `AsyncResponseStream::write()` при allocation failure может short-write (`libraries/ESP_Async_WebServer/src/WebResponses.cpp:917-933`). При любом short write, включая delimiter после event field или финальную `}`, incomplete stream удаляется/отбрасывается до send, затем отправляется exact `503 text/plain Runtime event response unavailable` с `Cache-Control: no-store`; event ring остаётся недеструктивным, browser cursor не продвигается. Проверка не расширяется на предсуществующие telemetry writes до последней A-13 event section.

### 4.5 Lua compatibility

- Lua variable name `Msg`, read/write access, generic return counts и existing busy-error path сохраняются.
- `getStrVariable("Msg")` недеструктивно возвращает latest retained MESSAGE payload либо `""`; CONSOLE event не выдаётся как `Msg`.
- `setStrVariable("Msg", nonEmpty)` публикует один MESSAGE event с deterministic `NOTIFY_MSG`. Empty setter успешно ничего не публикует: уже опубликованную историю нельзя удалять без возврата destructive bug.
- Только `Msg` получает специализированную typed write-ветку `if (Var == "Msg")` в `lua_wrapper_set_str_variable()` до неизменённого generic descriptor path: `OK -> return 0`, `LOCK_BUSY -> luaL_error("Msg busy")`, `TEXT_TOO_LONG -> luaL_error("Msg too long")`. Boolean `lua_str_set_Msg` adapter удаляется, setter pointer строки `Msg` становится `nullptr`, а её `LUA_VAR_RW`/getter сохраняются; struct/table shape и поведение остальных string descriptors не рефакторятся. Global result side channel, shim и duplicate append запрещены.
- `sendMsg(text, level)` по-прежнему вызывает `SendMsg()` и сохраняет переданный level/external side effects.
- Lua getter/setter используют только `runtime_helpers.h`; отдельного Lua shadow buffer, shim или fallback нет.

## 5. Frontend contract без нового UI

`data/app.js` становится единственным browser owner cursor/protocol для всех шести pages:

1. Один module-local `messageCursor = 0`; helper строит только `/ajax?messageCursor=<decimal>` для bundled UI. Operation lookup helpers остаются exact `/ajax?operationId=<id>`.
2. `pollAjax(renderFn, sinks)` сохраняет существующий default behavior для пяти mode pages и принимает только необходимые sink hooks для `chart.htm`: existing local `addMessage`, `console.log`, `ConnectError(true/false)`. На chart shared `SamovarApp` владеет cursor/schema, а единственным активным message-state owner остаются переданные существующие chart handlers; default `SamovarApp` message store там не инициализируется и не вызывается. Это callback boundary, не shim и не опережающий U-06 refactor.
3. Каждый 2-second poll выполняет ровно один telemetry request и получает максимум один event. Немедленного drain/retry loop нет; сохранённый хвост читается по одному event в следующих обычных polls. Одновременно активен максимум один telemetry request.
4. Event validator требует integer sequence `1..UINT32_MAX`, exact mutually exclusive payload shape и message level, совместимый с текущим numeric `msglvl`. При gap он ровно один раз до retained event вызывает выбранный existing message sink с exact текстом `Пропущены сообщения: обнаружен разрыв последовательности.` и numeric level `1` (`WARNING_MSG`); warning получает `message_1`, не активирует alarm/audio и не вызывает `playSound(true)`. Event sink exception считается failure: cursor не продвигается.
5. Telemetry renderer вызывается один раз на единственный response poll cycle.
6. Из `index.htm`, `beer.htm`, `distiller.htm`, `bk.htm`, `nbk.htm` удаляются только duplicate `Msg`/`LogMsg` blocks; остальной renderer не рефакторится.
7. `chart.htm` подключает `app.js`, сохраняет свои message/history/sound/connection functions как sinks, удаляет raw `/ajax` fetch и собственный scheduler. На `DOMContentLoaded` запускается ровно один `SamovarApp.startPollLoop(loadDoc, 2000)`; `loadDoc` использует общий `pollAjax`. `chart.js` CSV refresh не считается telemetry poll и не меняется.
8. `data/calibrate.htm` меняет только direct confirmed telemetry URL на `/ajax?messageCursor=0`; operation lifecycle/readback semantics A-02 не меняются.
9. Никакого localStorage cursor, boot epoch, acknowledgement, badge, нового warning widget или auto retry вне текущего polling нет.

Bundled UI + firmware образуют один version-locked artifact. Mixed deploy не поддерживается и не маскируется fallback: старый UI с пустым `/ajax` получит явный `400`; если старый firmware вернёт `Msg`/`LogMsg` без `messageSequence`, новый UI отклонит malformed event без cursor advance.

## 6. Реализация по шагам и критерии каждого шага

### Шаг 0 — prerequisite/baseline freeze

- Подтвердить live status A-02 и A-06 как `PASS`, единственный `/ajax` route, operationId branch tokens и отсутствие A-13 symbols.
- Зафиксировать до изменений: семь build summaries, `.bss`, symbol sizes и `-fstack-usage` frame `send_ajax_json()` для optimized `Samovar`; сохранить evidence в `/tmp`, не в repo.
- Зафиксировать SHA изменяемых production/assets/tests и dirty paths; чужие изменения не форматировать/откатывать.

**Verify:** baseline smoke/build state известен; implementation agent видит только allowlist ниже.

### Шаг 1 — сначала красные focused tests

Добавить host/source/browser contracts из раздела 7. До production edits они должны падать только по отсутствующему A-13 behavior, а не по fixture/setup ошибкам.

**Verify:** test plan reviewer подтверждает cases и отсутствие implementation-shaped fake assertions.

### Шаг 2 — bounded pure owner

- Добавить `runtime_event_log.h` с fixed descriptors/byte pool, append/evict/select/copy и strict decimal cursor parser.
- Определить единственный storage в `Samovar.ino`; удалить только осиротевшие `Msg`, `LogMsg`, `msg_level` из `Samovar.h`.
- Перевести helpers на typed results и existing semaphore.

**Verify:** host harness полностью зелёный; size/static/no-heap guards зелёные; production integration ещё не объявляется готовой.

### Шаг 3 — producer/Lua/snapshot integration

- Перевести `SendMsg`, `WriteConsoleLog`, Lua getter/setter на owner без изменения внешних side effects.
- Сделать telemetry snapshot недеструктивным и typed; allocation failure явный.
- В `send_ajax_json()` добавить exact-one-param operationId/cursor dispatch и один event response, сохранив valid operation lookup contract.

**Verify:** source-extracted integration, exact wire/query matrix и existing A-02 operation tests зелёные.

### Шаг 4 — единый browser cursor

- Реализовать cursor/schema/sinks в `app.js` без дополнительного drain loop.
- Удалить пять duplicate consumers.
- Подключить chart к общему owner, сохранив ровно один scheduler и существующие chart sinks.
- Перевести `data/calibrate.htm` и fixtures пяти существующих browser suites на exact cursor telemetry URL: empty fixture не может содержать `Msg/LogMsg` без `messageSequence`; operation lookup остаётся exact прежним.

**Verify:** новый Playwright suite и все пять существующих browser suites зелёные; browser console/page errors равны нулю.

### Шаг 5 — asset contracts и общая стабилизация

- Обновить source SHA восьми фактически изменённых assets (`app.js`, шесть polling pages и `calibrate.htm`), canonical gzip/hash/size totals только через существующий raw UI contract.
- `maxExpandedSize`/`maxStoredSize` разрешено только сохранить или поднять до следующего существующего bucket, если targeted check докажет пересечение; уменьшать maxima нельзя.
- Не создавать generator/importer/pack runtime, local Ace, gzip production copies или новые assets.

**Verify:** UI asset/format contracts, full smoke, cppcheck и семь builds зелёные; diff/allowlist чистые.

### Шаг 6 — map, независимый review, ledger

1. После frozen green diff обновить только затронутые map nodes и зарегистрировать новый node targeted mapper-ом.
2. Независимый reviewer читает production, tests, maps и полный scoped diff. Любой `ERROR`/`WARNING` возвращает работу developer agent; повторить targeted/full gates и review.
3. Только после точного `PASS: no errors, no warnings` отметить A-13 complete в этом plan и двух master-ledgers. До PASS ledger не опережает код.

## 7. Обязательная test matrix

### 7.1 Host C++11: `tools/smoke_runtime_event_ring.py`

Python создаёт temporary `.cpp`, source-extract/include использует реальный `runtime_event_log.h`, компилирует с warnings-as-errors и не оставляет project `.cpp`.

Cases:

- empty, one MESSAGE, one CONSOLE, mixed FIFO; exact kind/level/text;
- cursor `0`, retained cursor, latest, missing/evicted cursor, physical successor;
- два независимых cursors читают одинаковый FIFO без mutation/duplicates;
- descriptor capacity 16; 17th append evicts oldest;
- byte-pool pressure отдельно от descriptor pressure; variable lengths, exact used bytes, wrapped two-segment payload;
- guard byte никогда не allocatable/modified; unwrapped и wrapped snapshot проверяют `reserve` и оба `concat`, а injected reserve/first-span/second-span failure или corrupt descriptor оставляют output неизменным и возвращают exact `NO_MEMORY/CORRUPT`;
- 8691 и 10000 bytes accepted byte-for-byte as one event; 10001 returns `TEXT_TOO_LONG`, no partial write/eviction/sequence advance;
- sequence `UINT32_MAX -> 1`, no zero, physical order across wrap;
- reboot reinit, stale mismatch и stale collision limitation;
- strict decimal parser: `0`, max valid; empty, sign, whitespace, alpha, duplicate handled by integration, overflow invalid;
- compile-time descriptor/ring size caps and no heap-backed owner fields.

### 7.2 Source-extracted/static integration в том же `tools/smoke_runtime_event_ring.py`

- ровно один storage/owner; старые globals/direct access отсутствуют;
- все append/read paths проходят `runtime_helpers.h` и existing semaphore;
- no new task/mutex/queue/route/SSE/session/ack/retry/security/shim;
- lock boundaries: no JSON/network/filesystem/Serial/delay under lock; diagnostics после unlock;
- exact `/ajax` dispatch: valid operation wire unchanged; invalid exact/duplicate-only `operationId` сохраняет JSON `invalid_operation_id`; empty/unknown/mixed и malformed cursor получают generic `BAD_REQUEST`;
- corrected response has exact mutually exclusive fields и no-store; 400/503 bodies exact;
- static source extraction подтверждает, что A-13 event section расположена после последнего существующего telemetry field, относительный порядок прежних fields не изменён, а после event section возможна только принадлежащая checked writer финальная `}`;
- source-extracted checked event writer fault-injects short write отдельно в key/payload/level/sequence, delimiter после event field и финальную закрывающую `}`; во всех точках incomplete stream не отправляется и выбирается exact no-store `503 Runtime event response unavailable`; pre-existing telemetry writer audit до event section остаётся вне scope;
- `SendMsg` short filter, MQTT/Telegram order и `WriteConsoleLog` normalization/Serial side effects сохранены;
- Lua getter/`sendMsg(level)` semantics и specialized `Msg` setter mapping: exact `Msg busy` против exact `Msg too long`, без изменений остальных descriptors;
- source evidence confirms current `LogMsg` threshold 10000 replacement and tracked maximum Lua asset <=10000; synthetic 10001 failure remains mandatory;
- no payload-sized local array; owner/transient/stack caps present.

### 7.3 Frontend static в том же `tools/smoke_runtime_event_ring.py`

- `app.js` is the sole cursor/validator implementation; один poll создаёт ровно один telemetry request;
- five mode pages contain no direct `myObj.Msg`/`myObj.LogMsg` blocks;
- chart includes exact `app.js`, contains no raw `fetch('/ajax')`, has exactly one `startPollLoop` call and no second telemetry scheduler;
- operation lookup URL stays `/ajax?operationId=` and is never mixed with cursor;
- `calibrate.htm` direct readback uses exact `/ajax?messageCursor=0`; bundled production не содержит empty `/ajax` call;
- no new DOM control/widget/ack/session/localStorage cursor;
- manifest source hashes and exact raw UI aggregate totals synchronized.

### 7.4 Browser: `tools/test_runtime_event_ui_browser.py` через обязательный `playwright-cli`

1. Поднять local fixture вне repo; production mock/fallback не добавлять.
2. Два изолированных browser contexts/tabs получают один mixed stream с разной задержкой; проверить independent query cursors, одинаковый order, no duplicates и отсутствие server-side client identifier.
3. Pause/reconnect сохраняет cursor; reload начинает с `0`; overflow вызывает перед oldest retained ровно один warning `Пропущены сообщения: обнаружен разрыв последовательности.` с level `1`; он имеет warning style и не запускает alarm audio.
4. Проверить sequence wrap, detectable reboot discontinuity, reboot collision без ложного warning, malformed payload/sequence, HTTP 400/503, invalid JSON, timeout/network. На failure cursor не меняется.
5. Проверить 8691-byte CONSOLE event: один response/event, exact text до `console.log`, без truncation/split. 10001 тестируется host/integration как explicit producer failure, не через oversized browser fixture.
6. Пройти `index`, `beer`, `distiller`, `bk`, `nbk`, `chart`: message идёт в существующий sink, log — в console, clear/history/sound остаются рабочими, новых controls нет.
7. Для chart network trace подтверждает один scheduler, один request на poll cycle, `max in-flight = 1` и отсутствие второго raw poll. Telemetry render/chart point не дублируется.
8. `playwright-cli console`/page errors: неожиданных errors/warnings `0`; contexts закрыть, trace/screenshots только `/tmp`.

Обязательно повторно запустить пять существующих browser contracts, поскольку их `/ajax` fixtures затрагиваются новым bundled-UI query, но `/ajax?operationId=` assertions должны остаться прежними.

## 8. Final gates и resource evidence

Последовательность (cppcheck и PlatformIO никогда не параллельно):

```text
python3 tools/smoke_runtime_event_ring.py
python3 tools/smoke_operation_store.py
python3 tools/smoke_shared_state_strings.py
python3 tools/smoke_api_routes.py
python3 tools/smoke_ui_foundations.py
python3 tools/smoke_calibration_ux.py
python3 tools/smoke_ui_pack_assets.py
python3 tools/smoke_ui_pack_format.py
python3 tools/test_runtime_event_ui_browser.py
python3 tools/test_i2c_operation_results_browser.py
python3 tools/test_i2c_pump_ui_browser.py
python3 tools/test_numeric_input_ui_browser.py
python3 tools/test_profile_operation_ui_browser.py
python3 tools/test_program_clear_ui_browser.py
python3 tools/run_smoke_tests.py --timeout 60
python3 tools/run_cppcheck.py --timeout 180 --report /tmp/samovar-a13-cppcheck.txt
python3 tools/run_cppcheck.py --force --timeout 600 --report /tmp/samovar-a13-cppcheck-extended.txt
pio run -e Samovar
pio run -e Samovar_s3
pio run -e Samovar_lua_mqtt
pio run -e Samovar_no_power
pio run -e Samovar_rmvk
pio run -e Samovar_sem
pio run -e Samovar_alarm_button
git diff --check
```

Первые targeted builds после focused gates — последовательно `Samovar`, `Samovar_s3`, `Samovar_lua_mqtt` (последний обязателен из-за `lua.h`/long-log path); после них выполняется полный seven-env gate из списка. После добавления одного `smoke_runtime_event_ring.py` и одного `test_runtime_event_ui_browser.py` durable inventory должен стать ровно `56 smoke / 6 browser`; иное число расследуется до review.

Resource acceptance:

- `RuntimeEventRing <= 10464` bytes and owner symbol/`.bss` delta `<= 10464`;
- host size gate подтверждает, что физический `textPool[10241]` с невыделяемым guard всё ещё укладывается в тот же cap;
- request-local A-13 event reserve `<= 10000`; owner has zero retained heap allocations;
- no payload array on stack; `send_ajax_json()` optimized frame grows no more than 128 bytes from captured A-13 baseline, and project-owned `send_ajax_json -> copy_ajax_runtime_snapshot -> runtime_event_*` frame chain grows no more than 384 bytes;
- `-fstack-usage` evidence and objdump call path сохраняются в `/tmp`; `platformio.ini` SHA before/after identical;
- firmware size/RAM summary recorded for all seven env; any budget/cap excess is blocking, not warning/waiver;
- HIL free-heap/high-water measurement, если ESP32 недоступна, честно отмечается `not run` и не заменяется выдуманным PASS; compile/static caps остаются обязательными.

## 9. Exact write allowlist реализации

Текущий planning pass имеет единственный write:

- `.claude/experts/plans/samovar-a13-event-ring.md`.

Отдельной A-13 implementation разрешены только:

**Firmware**

- `runtime_event_log.h` (new), `runtime_helpers.h`, `Samovar.ino`, `Samovar.h`, `lua.h`.

`WebServer.ino`, `FS.ino`, `operation_store.h`, A-02/A-06 routes и process modules read-only.

**UI/assets**

- `data/app.js`, `data/index.htm`, `data/beer.htm`, `data/distiller.htm`, `data/bk.htm`, `data/nbk.htm`, `data/chart.htm`, `data/calibrate.htm`;
- `web_src/ui-manifest-v1.json`, `tools/ui_pack_assets_contract.py` только для доказанных source/canonical-gzip/hash/size changes этих восьми assets.

**Tests**

- `tools/smoke_runtime_event_ring.py` (new, host + source/static + frontend contract), `tools/test_runtime_event_ui_browser.py` (new, постоянный `playwright-cli` contract), `tools/static_analysis_sources.json` (регистрация нового root header);
- `tools/smoke_operation_store.py` только для obsolete `/ajax` dispatch/no-store branch-count assertions; все A-02 OperationStore state/error/wire checks сохраняются;
- `tools/smoke_shared_state_strings.py`, `tools/smoke_api_routes.py`, `tools/smoke_ui_foundations.py`, `tools/smoke_calibration_ux.py` только для замены obsolete destructive/global/empty-telemetry assertions новым exact contract;
- `tools/smoke_chart_ui.py` только для замены obsolete ожидания удалённого `startPolling()` на уже реализованный единый `SamovarApp.startPollLoop(loadDoc, 2000)`;
- `tools/smoke_lua_api_optimizations.py` только для уточнения прежнего blanket-запрета прямого string-dispatch: единственное намеренное исключение `Var == "Msg"` проверяет A-13 publish-before-descriptor path, все остальные прямые сравнения остаются запрещены;
- пять существующих `tools/test_*_browser.py`, перечисленных в final gates, только для cursor-aware telemetry fixtures/traces; operation expectations менять запрещено.

**Map/status после green production**

- `.cli-proxy/.codebase_map/nodes/runtime-event-log-h.md` (new), `runtime-helpers-h.md`, `samovar-ino.md`, `samovar-h.md`, `lua-h.md`, `webserver-ino.md`, `data.md`, `tools.md`;
- `.cli-proxy/.codebase_map/TESTING.md` только для синхронизации durable inventory `56 smoke / 6 browser` и регистрации A-13 browser contract;
- `.cli-proxy/.codebase_map/INDEX.md`, `graph.json`, `state.json` только если targeted mapper регистрирует новый node;
- после reviewer PASS: этот plan status block, `.claude/experts/plans/samovar-audit-remediation.md`, `.claude/experts/plans/samovar-remaining-remediation-2026-07-12.md` только в строках A-13/evidence.

Любая необходимость production/test path вне allowlist останавливает implementation: сначала reviewer проверяет причину и scope плана обновляется явно. Dirty diff вне A-13 не форматировать, не удалять, не откатывать и не включать в task review.

## 10. Review focus и rollback

Независимый reviewer обязан проверить не только happy path, но и:

- variable byte-ring invariants при descriptor/byte eviction и wrap;
- неизменность guard, checked wrapped `String` copy без partial output, последняя позиция event section и отсутствие unchecked writes после неё, checked short-write discard/503 вплоть до финальной `}`;
- 8691/10000/10001 payload boundary и отсутствие 255-byte regression;
- exact operationId/cursor forms, preserved invalid-operation JSON и empty/mixed/unknown strict rejection;
- отсутствие destructive clear, duplicate storage, silent fallback и payload truncation;
- Lua empty/get/latest semantics, `SendMsg`/`WriteConsoleLog` side effects;
- cursor advancement после sink success, one-request/one-event и ровно один chart poll;
- exact RAM/stack/manifest/map evidence и все семь environments.

Rollback — только reverse/revert собственного A-13 diff по allowlist без `reset`/`checkout` чужого dirty tree, затем повторные smoke/build и совместный deploy предыдущих firmware + filesystem assets. Persistent migration отсутствует: owner находится в BSS и исчезает при reboot; OperationStore, NVS, LittleFS data и внешняя notification queue не меняются.
