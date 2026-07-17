# A-14: короткая критическая секция очереди уведомлений

**Статус:** завершён 2026-07-13; независимый review после двух test-hardening итераций — `PASS: no errors, no warnings`.

**Проверка:** production-derived и actual-vendor focused harness PASS; полный smoke `57/57`; blocking cppcheck без error/warning; extended cppcheck без error/warning (11 information); все 7 PlatformIO environments SUCCESS; отдельная process-scoped сборка реальных `USE_TELEGRAM` + `SAMOVAR_USE_BLYNK` веток SUCCESS; stable isolated Playwright regression `6/6`; map `72 nodes / 550 edges`; vendor queue и `platformio.ini` byte-identical baseline; `git diff --check` PASS.

## 1. Цель и критерий готовности

Устранить тихую потерю внешних уведомлений и удержание `xMsgSemaphore` во время сети, не меняя продуктовый контракт очереди.

Готово, когда искусственный 8-секундный Telegram I/O идёт после освобождения mutex, параллельный producer продолжает ставить сообщения, а ошибки lock/push/pop и доступные ошибки Telegram/Blynk видны через локальный event/log owner без рекурсивного уведомления.

A-13 — обязательная предпосылка: реализация начинается только после появления и PASS единого `append_console_log()` owner. Если owner отсутствует или его contract иной, A-14 блокируется и перепланируется; Serial-only замена не вводится.

## 2. Проверенный baseline и неизменяемый контракт

- `Samovar.ino` владеет `SimpleStringQueue msg_q(5, 200)`: сохраняются capacity `5`, FIFO, 200-байтовый vendor item и текущее однократное извлечение.
- `libraries/simple_queue/simple_queue.h` остаётся без изменений; `push()`/`pop()` и их `false` — единственный queue-result API.
- `SendMsg()` ждёт `xMsgSemaphore` 50 мс; MQTT-путь, фильтр `m.length() < 5`, формат payload и compile guards не меняются.
- `triggerGetClock()` остаётся единственным consumer; OTA/Wi-Fi guards, порядок Telegram → Blynk и период task не меняются.
- `http_sync_request_get()` и его 8-секундный timeout не меняются; Telegram failure — только точный результат `"<ERR>"`.
- Для Blynk наблюдаем только `Blynk.connected()`. Отсутствующий delivery ACK для `virtualWrite()` не выдумывается и success не декларируется.

Не добавляются новый task/queue/route/dashboard, retry/requeue, priority/reserve, counters, acknowledge или новая delivery policy.

## 3. Реализация

### 3.1 Producer: `SendMsg()`

1. Сформировать payload и выполнить существующий MQTT side effect до `xMsgSemaphore`.
2. Попытаться взять mutex с прежним timeout 50 мс.
3. При успехе выполнить под lock ровно один `msg_q.push(MsgPl.c_str())`, сохранить `bool` и немедленно освободить mutex. Под lock запрещены дополнительное форматирование/явное создание `String`, event/log, Serial, delay и сеть; внутреннее хранение vendor `SimpleStringQueue` не переписывается.
4. После release отдельно сообщить точную строку `"notify_queue_push_failed"`, если `push()` вернул `false`; timeout lock сообщить точной строкой `"notify_queue_push_lock_busy"`.
5. Не повторять push и не менять capacity/формат/compile guards. Исходный web-message по-прежнему добавляется обычным A-13 owner path.

### 3.2 Consumer: `triggerGetClock()`

1. Сохранить существующие условия Wi-Fi/OTA и единственного consumer; чтение `msg_q.isEmpty()` вне `xMsgSemaphore` запрещено, потому что vendor `count` не атомарен.
2. В stack buffer `char c[200]` взять mutex, под тем же lock проверить `msg_q.isEmpty()` и только для непустой очереди выполнить ровно один `msg_q.pop(c)`. Сохранить `bool`, затем немедленно вызвать `xSemaphoreGive()`. Пустая очередь — штатный no-op; преобразование в `String` выполняется только после release.
3. Timeout lock сообщить точной строкой `"notify_queue_pop_lock_busy"`. `false` после `isEmpty() == false` сообщить точной строкой `"notify_queue_pop_failed"`; сеть в обоих случаях не запускать.
4. После успешного pop независимо попытаться доставить сообщение во все текущие настроенные integrations:
   - Telegram: результат `"<ERR>"` даёт точную строку `"notify_telegram_delivery_failed"`;
   - Blynk: настроенный, но `!Blynk.connected()` даёт точную строку `"notify_blynk_disconnected"`; при соединении вызывается прежний `virtualWrite()`, без фиктивного ACK.
5. Ошибка одного integration не отменяет попытку другого. После pop сообщение не requeue-ится даже при частичной/полной ошибке доставки; FIFO и one-shot semantics сохраняются.

### 3.3 Локальная диагностика без нового reporter-а

После освобождения `xMsgSemaphore` использовать существующий `WriteConsoleLog()` с одной из шести точных bounded строк:

```text
notify_queue_push_lock_busy
notify_queue_push_failed
notify_queue_pop_lock_busy
notify_queue_pop_failed
notify_telegram_delivery_failed
notify_blynk_disconnected
```

`WriteConsoleLog()` уже публикует через A-13 `append_console_log()`, не вызывает `SendMsg()`/внешнюю очередь и при отказе owner выдаёт существующую терминальную Serial/WebSerial diagnostic. Новый helper/reporter запрещён как дублирование. Второй append, рекурсия, payload сообщения, token, chat ID и полный URL в diagnostic запрещены.

## 4. Behavioral tests

Новый `tools/smoke_notification_queue.py` создаёт C++11 harness только во временном каталоге; repository `.cpp` не создаётся. Behavioral часть честно проверяет actual `SimpleStringQueue` API и lock-release concurrency contract на минимальном coordinator fixture; она не заявляет, что компилирует весь `Samovar.ino` под stubs. Отдельный static source gate связывает fixture с production: exact one push/pop, `isEmpty()` и `pop()` под одним lock, сохранение bool-result, `xSemaphoreGive()` до `String`/event/Telegram/Blynk и отсутствие recursive notification path. Новый production header/test seam ради harness запрещён.

Обязательные сценарии:

1. Queue содержит `A`; consumer извлекает `A`, освобождает mutex и входит в fake Telegram с настроенным logical timeout 8000 мс. Fake transport ждёт на barrier, а не делает реальный восьмисекундный sleep; producer за это время должен поставить `B` и завершиться в пределах 100 мс, после чего test освобождает barrier. Mutex в течение логической сетевой паузы доступен.
2. `A/B/C` доставляются FIFO; capacity остаётся 5, шестой push возвращает failure и создаёт ровно один local event.
3. Отдельные injections: push-lock timeout, `push=false`, pop-lock timeout, `pop=false` после locked non-empty check, Telegram `"<ERR>"`, Blynk disconnected до `virtualWrite()`; каждый случай даёт ровно одну из шести точных строк раздела 3.3.
4. После delivery failure очередь не содержит повторно вставленного сообщения; Telegram failure не пропускает доступный Blynk и наоборот.
5. Каждый failure даёт один ожидаемый code через существующий `WriteConsoleLog()`, который не вызывает notification path; lock освобождён до event/log и сети.
6. Static guard сохраняет текущие `USE_TELEGRAM`, `SAMOVAR_USE_BLYNK` и `USE_MQTT` ветви и отсутствие нового Blynk-only enqueue behavior; отдельный isolated PlatformIO gate ниже обязательно компилирует реальную совместную Telegram+Blynk production-ветку. Одна static token-проверка без этого build недостаточна.

Static guard в том же тесте подтверждает `msg_q(5, 200)`, отсутствие network/delay/logging между successful take/give, locked `isEmpty()`/`pop()`, проверку обоих queue results, вызов только существующего `WriteConsoleLog()` после release и отсутствие изменений vendor header. Static assertions дополняют, но не заменяют behavioral harness и isolated production build.

Web/UI contract не меняется, поэтому frontend-файлы и Playwright в A-14 не затрагиваются.

## 5. Порядок и gates

1. Подтвердить PASS A-13 и снять scoped baseline diff разрешённых файлов.
2. Добавить красный behavioral/static gate: на pre-A-14 source ordering он фиксирует сеть до release/слишком широкую critical section; barrier-harness доказывает требуемую interleaving semantics без реальной восьмисекундной задержки.
3. Хирургически изменить только notification blocks в `Samovar.ino`; затем прогнать targeted harness.
4. Последовательно выполнить:

```text
python3 tools/smoke_notification_queue.py
python3 tools/run_smoke_tests.py --timeout 60
blocking cppcheck gate
extended cppcheck gate
pio run -e Samovar
pio run -e Samovar_s3
pio run -e Samovar_lua_mqtt
pio run -e Samovar_no_power
pio run -e Samovar_rmvk
pio run -e Samovar_sem
pio run -e Samovar_alarm_button
process-scoped isolated PlatformIO compile with USE_TELEGRAM + existing SAMOVAR_USE_BLYNK
git diff --check
```

Ожидаемый durable inventory после нового smoke — `57 smoke / 6 browser`. Isolated compile добавляет только `-DUSE_TELEGRAM` процессным `PLATFORMIO_BUILD_FLAGS=-DUSE_TELEGRAM` и задаёт процессный `PLATFORMIO_BUILD_DIR` под `/tmp`; PlatformIO сам объединяет этот флаг с `env:Samovar.build_flags`, а `SAMOVAR_USE_BLYNK` уже включён в `Samovar_ini.h`. Повторно передавать resolved build flags нельзя: это дублирует `--specs=nano.specs`. Команда не меняет `platformio.ini`, repo или глобальное окружение и компилирует реальные production branches. Cppcheck и PlatformIO не запускать одновременно. После зелёных gates обновить `Last reviewed` только у реально затронутых map nodes.

## 6. Write allowlist

Текущий planning-pass создаёт только `.claude/experts/plans/samovar-a14-notification-queue.md`.

Отдельной реализации разрешены только:

- `Samovar.ino`;
- `tools/smoke_notification_queue.py` (new);
- `.cli-proxy/.codebase_map/nodes/samovar-ino.md`;
- `.cli-proxy/.codebase_map/nodes/tools.md`;
- `.cli-proxy/.codebase_map/TESTING.md` только для `57 smoke / 6 browser` и A-14 backend contract;
- после reviewer PASS: status этого плана и только строки A-14/evidence в `.claude/experts/plans/samovar-audit-remediation.md` и `.claude/experts/plans/samovar-remaining-remediation-2026-07-12.md`.

`Samovar.h`, `WebServer.ino`, `runtime_helpers.h`, `libraries/simple_queue/**`, UI/data, queue capacity и HTTP implementation — read-only. Если для PASS потребуется иной write path, работа останавливается до явного расширения allowlist.

## 7. Review и rollback

Reviewer читает полный scoped diff и проверяет: push/pop-only critical sections, release до heap/I/O/logging, все шесть failure classes, отсутствие рекурсии, сохранение FIFO/capacity/vendor/compile guards/one-shot delivery и отсутствие запрещённых расширений. Любой `ERROR`/`WARNING` исправляется в том же allowlist; tests/build/review повторяются до точного `PASS: no errors, no warnings`.

Rollback — точный reverse/revert только собственного A-14 diff без `reset`, `checkout` и вмешательства в dirty tree, затем targeted harness, обе основные firmware-сборки и `git diff --check`. Persistent migration нет; A-13 event ring и существующая volatile queue остаются отдельными owners.
