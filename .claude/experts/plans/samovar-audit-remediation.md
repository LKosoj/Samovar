# Полный план доработки Samovar по аудиту 2026-07-11

## Цель

Дать каждому пункту A-01…A-15 и U-01…U-06 из `ARCHITECTURE_CODE_UI_AUDIT_2026-07-11.md` явный исход: проверенное исправление либо зафиксированное решение пользователя принять риск без доработки. Ничего не переносится в неопределённое «потом»: каждый активный пункт включён в одну из волн, имеет зависимости, write scope, критерии приёмки и обязательный reviewer-loop.

Выбран постепенный вариант архитектуры из audit/design. Зафиксированы четыре решения пользователя:

- A-06: state-changing GET и внешние имена маршрутов сохраняются; auth/security доработка не выполняется;
- U-02: Ace остаётся на CDN; зависимость редактора от интернета принята для домашнего устройства;
- A-15: пункт полностью исключён из scope как security-hardening домашнего устройства;
- scope: исправляются только подтверждённые ошибки, архитектурные границы и существующий UI. Новые режимы, страницы, управляющие действия, endpoints, transport-ы и recovery-инструменты не добавляются. Подтверждены только уже реализованный explicit `clear=1` и минимальные поля `operationId/state/error` плюс message sequence/cursor в существующих ответах и `/ajax`.

Актуальное CDN-решение: `docs/plans/2026-07-12-cdn-ace-scope-decision.md`.

Детальный исполняемый план всех оставшихся задач: `.claude/experts/plans/samovar-remaining-remediation-2026-07-12.md`.

## Неподвижные ограничения

- Не создавать проектные `.cpp` в подкаталогах и не переносить код в `src/`.
- Не размещать реализации в `Samovar.h`; новые функции — корневые `.ino` или профильные inline `.h`.
- Не изменять vendored `libraries/`, если задача решается в first-party коде.
- Не добавлять fallback, автоматическую коррекцию или бесконечные retry без отдельного согласования.
- Не добавлять новые web routes, tasks, экраны, alarm acknowledgement, SSE/WebSocket, priority queue, retry policy, recovery UI/CLI или build-time frontend pipeline.
- Внутренние структуры вводить только там, где без них нельзя исправить доказанный дефект; они не должны расширять возможности устройства.
- Не смешивать независимые рефакторинги с исправлением; каждый diff должен соответствовать конкретному audit ID.
- Любое изменение UI проверяется через `playwright-cli`; существующие source/gzip-пары обновляются и проверяются вместе.
- При намеренном исправлении существующего UI обновлять только его SHA/размеры в текущем manifest-контракте; P1.1, schema и набор assets не расширять, production packs не возвращать.
- После изменения области обновляется `Last reviewed` соответствующих codebase-map nodes.

## Обязательный workflow каждой задачи

1. Сабагент составляет предварительный file/symbol-level plan и перечисляет edge/failure cases.
2. До записи фиксируются baseline targeted tests и точный write scope.
3. Сабагент-разработчик реализует только эту задачу и её тесты.
4. Основной агент проверяет diff, сборку/targeted tests и отсутствие пересечений с чужими изменениями.
5. Reviewer-сабагент читает весь diff задачи и выдаёт `ERROR/WARNING/PASS` с файлами и строками.
6. Любые ERROR/WARNING исправляются тем же developer scope; review повторяется до `PASS: no errors, no warnings`.
7. Только после PASS задача отмечается выполненной и открывается зависимая задача.

## Карта покрытия

| Пункт | Волна | Результат |
|---|---:|---|
| A-03 | 0 | Полный test runner в CI, meaningful behavioral layers, чистый blocking cppcheck |
| A-09 | 1 | Недеструктивный program draft/validate/commit |
| A-10 | 1 | Единый finite/bounded parsing для всех внешних чисел |
| A-11 | 1 | Неблокирующие startup/self-test и измеримый safety upper bound |
| U-01 | 1 | I2C-present polling без DOM exception на пяти mode pages |
| U-02 | — | **WAIVED:** Ace остаётся на CDN; P1.1 и проверенные A/B manifest-данные сохранены как неиспользуемые артефакты |
| A-02 | 2 | Подтверждённый результат каждой I2C-операции |
| A-12 | 2 | Честный результат существующих program/save и один проверяемый NVS profile blob |
| A-13 | 2 | Недеструктивные sequenced messages через существующий `/ajax`, без SSE/acknowledge |
| A-14 | 2 | Существующая очередь: сеть вне mutex, явный overflow/delivery failure, без retry/priority |
| A-06 | 2 | Существующие GET сохранены; validation/no-store/result без новых routes и security |
| A-01 | 3 | Fail-closed mount без автоматического format и без нового recovery UI/CLI |
| A-04 | 3 | Минимальный atomic-update контракт для текущих raw UI-файлов и реального LittleFS `0xC0000`; без Ace/pack runtime |
| A-05 | 4 | Request-local immutable snapshot только normal `/ajax`, без нового owner framework |
| A-07 | 4 | Lua setters/writes используют общую validation и явные ошибки |
| U-06 | 4 | Общий локальный UI runtime без дублирующихся controllers |
| U-03 | 4 | Исправление уже существующей light/dark theme через общие tokens |
| U-04 | 4 | Fluid responsive layout без horizontal overflow |
| U-05 | 4 | Native semantics, labels, keyboard и touch ergonomics |
| A-08 | 5 | Pinned toolchain/dependencies и build metadata |
| A-15 | — | **WAIVED:** security-hardening не требуется для индивидуального домашнего устройства |

## Исполняемый ledger

Статусы обновляются только после фактического gate. `PARTIAL` не считается закрытием пункта; `PASS` означает отдельный reviewer-ответ без ERROR/WARNING.

| ID | Preliminary plan | Development | Review | Verification |
|---|---|---|---|---|
| R2.0 | `.claude/experts/plans/samovar-r20-operation-store.md` | complete | PASS: no errors, no warnings | 51/51 smoke; cppcheck; ESP32/ESP32-S3; map/diff PASS |
| A-01 | `.claude/experts/plans/samovar-a01-fs-fail-closed.md` | complete | PASS: no errors, no warnings | focused mutation gate; smoke 58/58; cppcheck 0 error/warning; 7/7 env; stable isolated Playwright 6/6; targeted map/diff PASS; HIL not run |
| A-02 | `.claude/experts/plans/samovar-a02-i2c-results.md` | complete | PASS: no errors, no warnings | focused 10/10; smoke 54/54; Playwright A-02 15 + numeric 36/9; blocking cppcheck; 7/7 env; stack/UI asset/map/diff PASS; HIL high-water not run |
| A-03 | complete | complete | PASS | smoke runner + CI + cppcheck PASS |
| A-04 | `.claude/experts/plans/samovar-a04-raw-ui-transaction.md` | complete locally; release blocked by external remote parity | PASS: no errors, no warnings (local diff) | focused transaction/capacity PASS; smoke 59/59; cppcheck; buildfs 2/2; 7/7 env; stable isolated Playwright 6/6; map/diff PASS; remote CDN parity OPEN |
| A-05 | `.claude/experts/plans/samovar-a05-state-owners.md` | complete | PASS: no errors, no warnings | focused immutable snapshot/golden PASS; smoke 60/60; cppcheck; 7/7 env; stable isolated Playwright 6/6; map/diff PASS |
| A-06 | `.claude/experts/plans/samovar-a06-get-contract.md` | complete | PASS: no errors, no warnings | contract mitigation PASS; state-changing GET replay risk accepted by user; targeted 9/9 + UI pack; Playwright 15; smoke 55/55; cppcheck; 3/3 env; map/diff PASS |
| A-07 | `.claude/experts/plans/samovar-a07-lua-errors.md` | complete | PASS: no errors, no warnings | focused Lua/numeric matrix; smoke 61/61; cppcheck; 7/7 env + expander feature build; map/diff PASS |
| A-08 | `.claude/experts/plans/samovar-a08-reproducible-builds.md` | complete | PASS: no errors, no warnings | A/B firmware/ELF/inventory byte-identical for ESP32/ESP32-S3; 7/7 env; buildfs 2/2; smoke 66/66; blocking/extended cppcheck without errors or warnings; metadata/map/diff PASS |
| A-09 | `.claude/experts/plans/samovar-a09-integration.md` complete | complete | PASS: no errors, no warnings | 41/41 smoke; Playwright 12 viewports/48 scenarios; 7/7 env; buildfs/cppcheck/diff PASS |
| A-10 | `.claude/experts/plans/samovar-a10-numeric-input.md` refreshed after A-09 | complete | PASS: no errors, no warnings | 48/48 smoke; Playwright numeric 36/9 + I2C 10 + program-clear 12 pages/48 requests; 7/7 env; buildfs/cppcheck/diff PASS; map 68 nodes/530 edges |
| A-11 | detailed trace complete | complete | PASS: no errors, no warnings | 41/41 smoke; cppcheck exit 0; 7/7 env; hardware HIL unavailable/pending |
| A-12 | `.claude/experts/plans/samovar-a12-profile-operation.md` | complete: P1 single blob + P2 compound operation | PASS: no errors, no warnings | focused 9/9; smoke 53/53; blocking cppcheck; 7/7 env; Playwright profile/program-clear/numeric; UI asset/format; diff-check PASS |
| A-13 | `.claude/experts/plans/samovar-a13-event-ring.md` | complete | PASS: no errors, no warnings | focused A-13; smoke 56/56; stable isolated Playwright 6/6; blocking cppcheck; 7/7 env; ring 10448 B / `.bss +10408 B`; stack 368 B; map/diff PASS; HIL high-water not run |
| A-14 | `.claude/experts/plans/samovar-a14-notification-queue.md` | complete | PASS: no errors, no warnings | production-derived + actual vendor queue harness; smoke 57/57; cppcheck blocking/extended no error/warning; 7/7 env + Telegram/Blynk compile; stable isolated Playwright 6/6; map/vendor/config/diff PASS |
| A-15 | user waiver recorded | WAIVED | WAIVED | Home/DIY device; no security work requested |
| U-01 | complete | complete | PASS | Playwright desktop/mobile 10/10 |
| U-02 | CDN decision recorded | WAIVED | WAIVED | Active LittleFS is `0xC0000`; local Ace/P1.2 removed; P1.1 and verified A/B manifest data retained unused |
| U-03 | `.claude/experts/plans/samovar-u03-contrast.md` | complete | PASS: no errors, no warnings | focused 8/8; smoke 63/63; isolated Playwright 8/8 with contrast 60+6+160; buildfs 2/2 and 433187/786432 payload; blocking cppcheck zero error/warning, extended informational-only; 7/7 env; fixed-epoch clean builds byte-identical; raw-update 23/413709; targeted map/diff PASS |
| U-04 | `.claude/experts/plans/samovar-u04-responsive-layout.md` | complete | PASS: no errors, no warnings | focused responsive/static/transaction PASS; isolated Playwright 168/168 and full browser 9/9; smoke 64/64; buildfs 2/2; cppcheck zero error/warning; 7/7 env; fixed-epoch clean builds byte-identical; LittleFS 434245/786432; raw-update 23/414767; targeted map/diff PASS |
| U-05 | `.claude/experts/plans/samovar-u05-accessibility-touch.md` | complete | PASS: no errors, no warnings | focused 8/8; accessibility 88/88 + actions 207/207 + uploads 12/12; visual 20/20; isolated browser 10/10; smoke 65/65; buildfs 2/2; blocking cppcheck clean; fixed-epoch artifacts 5/5 identical; 7/7 env; LittleFS 450742/786432; raw-update 23/431264; targeted map/diff PASS |
| U-06 | `.claude/experts/plans/samovar-u06-shared-ui-controllers.md` | complete | PASS: no errors, no warnings | focused/derived PASS; smoke 62/62; isolated stable Playwright 7/7; buildfs 2/2 and 430349/786432 payload; blocking cppcheck zero warning/error; extended informational-only; 7/7 env; fixed-epoch clean builds byte-identical; targeted map/diff PASS; external A-04 remote parity remains publication/final blocker |

## Dependency-граф

```text
W0 test gates
 ├─> W1 parser/validation ───────────────┐
 ├─> W1 safety state machines            │
 └─> W1 critical UI defects              │
                                         ▼
                              W2 operation results + message ring
                               ├─> I2C results
                               ├─> save/program/NVS results
                               ├─> multi-client messages
                               └─> GET result contract
                                         │
               W3 fail-closed FS + raw-UI atomic update
                                         │
               W4 ownership boundaries + Lua + unified UI
                                         │
               W5 reproducibility
                                         │
               W6 full reviewer / goal / stabilization
```

## Разрешённое распараллеливание

- В волне 1 одновременно: parser/validation; safety timing; UI U-01. Их write scopes не должны пересекаться. U-02 закрыт пользовательским waiver и не имеет implementation scope.
- В волне 2 порядок runtime-разработки: `R2.0 → A-12 → A-02 → A-06`; A-13 можно предварительно планировать независимо, но его production edits выполняются только после освобождения общих `Samovar.ino`/`WebServer.ino` hunks. A-14 следует после стабильного event/log path.
- В волне 3 fail-closed FS mount выполняется до updater commit; параллельная запись в `FS.ino`/`WebServer.ino` запрещена.
- В волне 4 Lua validation можно выполнять параллельно с theme/responsive/accessibility, но общий `app.js` refactor начинается после стабилизации operation/event API.
- Волна 5 содержит только CI/toolchain A-08.

## Волна 0 — воспроизводимый baseline и quality gates

### W0.1 — Зафиксировать baseline

- Записать HEAD, status, версии PlatformIO/cppcheck/Python, размеры обеих прошивок.
- Выполнить все существующие `tools/smoke_*.py`, обе PlatformIO-сборки, blocking и extended cppcheck, gzip parity.
- Отдельно классифицировать уже существующие warnings; новый diff не может их скрыть.

### W0.2 — Закрыть A-03

- Добавить единый deterministic runner first-party smoke без ручного списка.
- Включить runner обязательным CI job вместо одного `smoke_api_routes.py`.
- Исправить или точечно обосновать текущий `memsetClassFloat`; blocking job должен завершаться без warning.
- Добавить host/browser behavioral suites по мере появления pure contracts; shape-smoke не должен закреплять ошибочную реализацию.
- Проверить, что список cppcheck покрывает новые first-party `.h`, а extended report сохраняется как artifact даже при PASS.

**Gate W0:** CI-конфигурация локально воспроизводима; полный текущий набор зелёный, известные baseline warnings устранены или явно классифицированы без глобального suppress.

## Волна 1 — safety и корректность входа

### W1.1 — A-09: атомарное обновление программ

File/symbol-level integration plan, failure matrix, budgets и reviewer acceptance зафиксированы в `.claude/experts/plans/samovar-a09-integration.md`.

- В `program_types.h` определить `ProgramParseError` и результат с номером строки; `ProgramDraft { WProgram rows[PROGRAM_MAX]; uint8_t len; }` оставить в `program_io.h` после полного определения `WProgram`, чтобы не создавать include-cycle. Зафиксировать `sizeof(ProgramDraft)` и stack budget.
- `program_io.h::program_parse_lines()` принимает draft, не трогает `program[]/ProgramLen`, не вызывает `SendMsg`, отвергает лишние строки и возвращает точную ошибку.
- `program_commit()` одним действием копирует полностью проверенный draft и очищает только sentinel-хвост по существующему контракту.
- `set_program`, `set_beer_program`, `set_dist_program`, `set_nbk_program` возвращают результат; все defaults/call sites обязаны его обработать.
- `/program` и `/save` валидируют draft до queue; A-09 заменил сырой pending `String` фиксированным DTO, а принятый A-12 затем встроил `ProgramDraft` в единый `ProfileOperationSlot` и удалил отдельный `PendingProgramUpdate`. Loop повторно проверяет active-session/mode race и только затем commit-ит. Ошибка оставляет предыдущий массив byte-for-byte.
- Пустой текст не очищает программу. Очистка — отдельное явное `clear=1`, отражённое в UI и тестах.
- Host/behavioral tests: round-trip четырёх форматов, CRLF/blank rows/boundaries, NBK H/S/O/W, oversize/extra row/bad type/NaN; при каждом failure старые rows/len неизменны.

### W1.2 — A-10: finite/bounded parsers

Полный inventory, domains, staged-parse contracts, budgets и test matrix зафиксированы в `.claude/experts/plans/samovar-a10-numeric-input.md`.

- Добавить Arduino-независимый корневой inline `numeric_parse.h`: finite float, bounded float/long, exact `0/1`, enum и явный `NumericParseError`; неоднозначный `parseFloatSafe` удалить после миграции callers.
- В `WebServer.ino` перевести `mixer/distiller/startbk/startnbk/state`, `watert`, `voltage`, `pnbk`, `pumpspeed`, `stpstep`, `vless`, I2C mode/flags/relay/uint16 и `/i2cpump` volume/speed на строгие домены.
- `apply_i2c_stepper_args()` возвращает result: все аргументы сначала разбираются во временный объект, staged config меняется только после полного success. Mask/wrap после `toInt()` запрещены.
- `volume * stepsPerMl`, speed conversion и narrowing проверяются до cast; malformed start никогда не ставит `SAMOVAR_POWER`; `vless` не получает fallback 30.
- Тестовая таблица для каждого параметра: min/max, ±1 от границы, empty/trailing garbage/whitespace/overflow/NaN/±Inf/`1e999`; invalid не занимает pending slot и не меняет state.

### W1.3 — A-11: неблокирующий safety path

- Разделить немедленное снятие силового выхода и cleanup: `force_heater_output_off_now()` не использует delay/String/network/I2C/UART wait; логирование, mode cleanup, valve/pump/stepper/reset выполняются позже.
- `request_emergency_stop()` сохраняет только первую причину и выставляет pending-флаг; уже существующий `loop()` обрабатывает cleanup. Новый task/executor и второй runtime-путь не создаются. Конкретный ISR/button integration проверяется отдельно для обеих плат.
- `set_power` перевести на `PowerTransition` с deadline; `mode_start_heating_session`, NBK 2500 ms и `start_self_test` — на tick-driven FSM с cancel на каждой фазе и wrap-safe time helpers.
- Провести inventory всех `delay/vTaskDelay` в loop-owned control paths; static gate запрещает новые blocking waits там, где они увеличивают cutoff latency.
- Software acceptance: повторный alarm идемпотентен, первая причина сохраняется, request→GPIO cutoff укладывается в согласованный budget на каждой фазе startup/NBK/self-test.
- Hardware acceptance: logic analyzer на ESP32 и ESP32-S3 для кнопки, pressure/timer alarm и regulator-loss. До доступности стенда кодовый gate может быть зелёным, но физическая latency в отчёте остаётся непроверенной, а не молча объявленной PASS.

### W1.4 — U-01: I2C DOM contract

- Определить единственный I2C status renderer/обязательную разметку для всех пяти mode pages.
- Не скрывать missing element optional chaining: browser contract должен обнаруживать несогласованность.
- Playwright: present=0/1, два poll, все поля после I2C-блока обновлены, console clean.

### W1.5 — U-02: принятое CDN-исключение

- Решение пользователя зафиксировано в `docs/plans/2026-07-12-cdn-ace-scope-decision.md`.
- Ace продолжает загружаться из CDN; отсутствие интернета остаётся известным ограничением редактора.
- Локальный Ace, importer/generator, `ace.pack`, A/B UI pack runtime, partition migration и отдельный browser gate удалены из плана.
- P1.1 wire-format и уже проверенные A/B manifest-данные сохраняются только как неиспользуемые тестовые/справочные артефакты.
- U-02 имеет статус `WAIVED`, а не `PASS`: offline-функциональность не реализована.

**Gate W1:** invalid input не меняет state; safety path не содержит многосекундных блокировок `loop()`; critical UI scenarios не имеют console errors.

## Волна 2 — корректность существующих async-команд и сообщений

Граница подтверждена пользователем: W2 не добавляет устройству новых действий, routes, экранов или transport-ов. `operationId/state/error` служат только для честного результата уже существующих I2C/program/save-команд, а sequence/cursor — только для устранения destructive `/ajax`. Новый `/operation` endpoint, Lua operation lifecycle, alarm acknowledge, SSE, server-side sessions и UI dashboard в scope не входят. R2.0, A-12/P1+P2, A-02, A-06, A-13 и A-14 приняты с отдельными `PASS: no errors, no warnings`; незакрытых W2-пунктов нет.

### W2.1 — Базовый OperationStore

- Добавить минимальный фиксированный POD/ring без heap: ID, kind, state и error; timestamps и произвольный detail не хранить.
- Определить единственного loop-side владельца transitions; web только читает snapshot через существующий lock.
- Переполнение завершается явной ошибкой; старый pending slot не перезаписывается.
- Определять operation kinds только для существующих I2C/program/save команд; Lua, UI pack/editor и будущие kinds не добавлять.
- Accepted response существующего route получает `operationId`; terminal `state/error` читается через существующий `/ajax`. Новый route не создаётся.
- Добавление нового task, mutex, dynamic allocation или отдельного UI-компонента запрещено.

### W2.2 — A-02: I2C results

**Статус:** завершён; независимый review — `PASS: no errors, no warnings`. Gates: focused 10/10, smoke 54/54, Playwright A-02 15 + numeric 36/9, blocking cppcheck, 7/7 PlatformIO environments, stack/UI asset/map/diff PASS; hardware HIL high-water не запускался.

- Связать каждый `PendingI2CStepperCmd/PendingI2CPumpCmd/PendingI2CCalCmd/PendingLocalCalCmd` с operation ID.
- Не переписывать I2C API: loop обязан проверить существующие `bool`, `dev.error` и forced refresh.
- Status остаётся `200` device JSON; accepted mutation использует отдельный минимальный `202 {operationId,state,error}` без конфликта числового device `error`.
- Loop отмечает `running`, выполняет команду на candidate, удерживает config busy до конца transaction и копирует confirmed state только после полного success.
- I2C `calfinish` из `/calibrate` (`PendingI2CCalCmd`) завершается success только после ACK, refresh и успешного NVS persist; generic `/i2cstepper?cmd=calstart/calfinish` не получает новых profile/flag side effects; local calibration проверяет узкий result-returning executor.
- Недропаемый terminal slot повторяет только публикацию результата; pending снимается без повторного side effect, start/stop failure не меняет отображаемый confirmed target/running state.
- Fault matrix: config-lock busy, command failure/timeout, `dev.error`, refresh failure, NVS failure калибровки и параллельный refresh.

### W2.3 — A-12: program/save/NVS results

**Статус:** P1 и P2 завершены; reviewer — `PASS: no errors, no warnings`. Итоговые gates: focused 9/9, полный smoke 53/53, blocking cppcheck, 7/7 PlatformIO environments, Playwright profile/program-clear/numeric, UI asset/format contracts и `git diff --check` — PASS.

- Setter программ возвращает parse/commit result из W1.
- NVS persistence возвращает `PersistResult`, не теряет `prefs.begin` failure и не считает write успешным без read-back; все callers обязаны проверить результат.
- Заменить набор независимо committed profile keys одним versioned blob `header + canonical field-wise SetupEEPROM payload + CRC`; размер/schema фиксируются, padding структуры не сериализуется, записанный blob перечитывается и сравнивается.
- Использовать одну blob-запись, а не A/B generations, active pointer или commit marker. Старый key-format читается только однократной fail-closed migration; dual write запрещён.
- `/save` и `/program` возвращают `operationId` либо terminal result; существующий UI ждёт terminal state перед сообщением об успехе.
- До успешной persistence не присваивать staged `SamSetup` рабочему state.
- `/save` с program/mode — compound operation: полная validation → persist → RAM program/mode commit; частичный success запрещён.
- Не добавлять новый save-status widget: использовать текущие error/message области и существующий переход после success.
- Tests: ID wrap/ring full/two clients, open/write/read-back/CRC/migration failures, два параллельных save и active-session race.

### W2.4 — A-13: EventLog

- `/ajax` больше не очищает глобальные messages.
- Fixed ring с sequence ID и client-side cursor возвращается только через существующий `/ajax`; переполнение определяется клиентом как явный разрыв sequence.
- Не добавлять SSE, WebSocket, server-side client state, alarm pin/acknowledge или новые controls. Текущий alarm/reset lifecycle не меняется.

### W2.5 — A-14: notifications

- Mutex защищает только queue push/pop; сеть выполняется после release.
- Проверяются mutex, `push/pop` и доступные delivery results; failures публикуются через существующие message/log поля без рекурсивного `SendMsg`.
- Существующий FIFO, ёмкость и порядок сохраняются. Retry, priority/reserved queue, новый dashboard и изменение vendored `simple_queue` запрещены.

### W2.6 — A-06: GET сохраняется

**Статус:** завершён; независимый review — `PASS: no errors, no warnings`. Итог: `contract mitigation PASS; state-changing GET replay risk accepted by user`.

- HTTP methods и внешние имена маршрутов не изменены; numeric I2C/calibration GET уже соответствовали validation/A-02/no-store contract и остались production read-only.
- Inline `/lua` теперь принимает только `{}` либо ровно один query `script`, отклоняет остальные формы до queue и отправляет все `200/400/503` с `Cache-Control: no-store`; новый lifecycle не добавлен.
- Auth/session/token/idempotency/prefetch/security, новые endpoints/UI/tasks/fallback и новый функционал не добавлены.
- Gates: targeted 9/9 + UI pack, Playwright 15, smoke 55/55, blocking cppcheck, 3/3 relevant environments, map/inventory/diff-check PASS.

**Gate W2:**

- Каждая принятая операция достигает terminal `succeeded` или `failed`; fault injection всегда даёт `failed`, а не success/fallback.
- Независимые fast, slow и reconnect cursors получают одну и ту же упорядоченную последовательность без дублей; overflow ring виден как разрыв sequence.
- При искусственной 8-секундной задержке сети producer продолжает работать, queue mutex освобождён до I/O, FIFO-порядок сохраняется, а push/pop/delivery failure виден в существующем log/message path.

## Волна 3 — fail-closed LittleFS и существующий web updater

### W3.1 — A-01: fail-closed mount

- `FS_init()` возвращает типизированный status и никогда не форматирует автоматически.
- При mount failure ordinary routes/hardware control UI не запускаются; ошибка явно пишется в существующий Serial/log path.
- Не добавлять recovery mode, web, route, serial CLI или format/restore command. Восстановление остаётся существующей внешней процедурой перепрошивки/uploadfs.
- Partition label и активный размер `0xC0000` остаются без изменений; миграция разделов не выполняется.

### W3.2 — A-04: atomic update текущих raw UI-файлов

**Статус:** локальные code/review/gates завершены с
`PASS: no errors, no warnings`; внешний remote CDN parity остаётся открытым
publication/final blocker. A-04 release-complete не объявлен.

- Использовать отдельный проверенный task-plan с exact transaction set: 23
  физических raw/gzip UI-файла, 412357 байт; активный LittleFS остаётся
  `0xC0000`.
- Единственный authoring source — schema-validated `raw_update` в существующем
  manifest; firmware компилирует exact typed projection path/size/SHA. Это
  consistency-check существующего updater, не security/signature-контур.
  Локальный Ace и binary pack runtime не входят в набор.
- Полностью проверить candidate, но скачать только changed subset. До первой
  записи доказать capacity для allocation-rounded staging, journal/version и
  измеренного reserve. Full-set staging запрещён: `data +` его копия уже больше
  раздела. Если budget не проходит, операция завершается до мутации; раздел,
  layout и runtime logs не меняются.
- Commit-контракт обязан исключить выдачу смешанной версии и сохранить полностью старую версию при любой инъецированной ошибке. Не добавлять новый endpoint, UI slot, signature/trust anchor или partition layout.

**Gate W3:**

- Инъекция mount failure подтверждает единственный вызов `SPIFFS.begin(false)`: форматирование отсутствует, web server/control routes не запускаются, байты FS не меняются.
- Fault injection на каждом шаге updater даёт только полностью старый или полностью новый UI; при ошибке до доказуемого commit firmware не меняет FS.

## Волна 4 — владельцы state, Lua и единый UI

### W4.1 — A-05: request-local `/ajax` snapshot

**Статус:** завершён; независимый reviewer —
`PASS: no errors, no warnings`.

- Уже закрытые OperationStore, RuntimeEventRing и ProfileStore не переоткрывать.
  Единственный оставшийся дефект: normal `/ajax` перечитывает mutable values во
  время JSON/network serialization.
- В `Samovar.ino` собрать существующие wire values в локальный
  `AjaxTelemetrySnapshot`, после чего писать response только из `const` snapshot.
  Existing runtime helper вызывается один раз и остаётся read-only.
- Сохранить GET, query classification, schema, key order, types, precision,
  statuses/headers и event suffix. Не заявлять общей generation/межполевой
  атомарности там, где у live sources нет общего writer lock.
- Новый header, owner framework, mutex/task/queue/route/UI и изменения
  Web/Lua/Blynk/settings запрещены. Production-derived mutation/golden test
  подтверждает const-only serialization и byte parity.
- Старые static integration checks operation/A-13/API/ProgramType разрешено
  синхронизировать только на source-extract нового capture/writer boundary;
  behavioral harnesses, wire keys/order/types и сценарии остаются неизменными.

### W4.2 — A-07: Lua

**Статус:** завершён; независимый reviewer —
`PASS: no errors, no warnings`.

- Integer args читать через `luaL_checkinteger()` и narrowing из wide integral;
  fractional args — через `luaL_checknumber()`/finite-check. Не пропускать
  `16777217`/`INT32_MAX` через 32-bit float.
- Три mode setters сохраняют разные live-семантики через один узкий owner под
  существующим pending lock; busy, active mode switch и non-empty profile phase
  дают error до mutation, без queue/operation lifecycle.
- I2C write wrappers возвращают Lua error при lock timeout и при реальном
  доступном vendor bool failure. Для void hardware API ACK не выдумывать;
  `pinMode` сохраняет `INPUT/OUTPUT/INPUT_PULLUP`.
- Pump сохраняет существующий speed/calibration choice; positive product
  проверяется в `[1, UINT32_MAX]`. Ни один новый `luaL_error()` path не держит
  живой Arduino `String` через longjmp.
- Новые Lua functions, routes, jobs и operation lifecycle не добавляются.
- Host/compile matrix проверяет min/max, out-of-range, NaN, I2C lock и hardware failure; invalid input и аппаратная ошибка возвращаются как Lua error без изменения state.

### W4.3 — U-06: общий UI runtime

**Статус:** реализация, focused/full gates и независимый review завершены:
`PASS: no errors, no warnings`. External A-04 remote parity остаётся
publication/final blocker и не маскируется локальным U-06 PASS.

- Добавить в существующий `SamovarApp` один lifecycle entrypoint поверх уже
  существующих `init/pollAjax/startPollLoop`; shared scope ограничен polling,
  message/theme/history и connection/request-error ownership.
- На пяти mode pages сохранить local field mapping/rendering,
  `setPowerUnit`, program/PWM/heat actions и page startup. Удалить только local
  polling wrappers; declarative bindings/DSL и перенос mode actions запрещены.
- `chart.htm` использует тот же lifecycle с закрытыми options, но сохраняет
  chart drawing/CSV/data/legend/status/throttle. Удалить только duplicate
  connection/message/audio/theme owners, polling wrapper и orphan chart-local
  `setPowerUnit`; I2C ownership не переносить.
- Не добавлять framework, component library, template generator или build runtime.
- Static/browser contract подтверждает единственное определение общих polling/message/theme/controller helpers в `app.js` и их работу на пяти mode pages плюс shared chart path.

### W4.4 — U-03: темы

- Заменить hard-coded foreground/background на tokens существующей темы; новый theme mode/control не добавлять.
- Проверить light/dark на точной матрице `index`, `beer`, `distiller`, `bk`, `nbk`, `program`, `setup`, `chart`, `i2cstepper`, `calibrate`: contrast не ниже 4.5:1 для обычного текста и 3:1 для крупного.

### W4.5 — U-04: responsive

- Удалить fixed widths/absolute operational layout; применить fluid grid/flex без новых panels/collapsible regions.
- Viewports 320/390/768/desktop без horizontal overflow и overlap.

### W4.6 — U-05: accessibility/touch

- `lang=ru`, unique IDs, native buttons (включая существующие generated plus/minus actions), explicit label/control associations, keyboard support.
- Существующие critical controls получают проектную touch target 44×44; новые controls не добавлять, state не кодируется только цветом.
- Playwright + Chromium CDP AX tree/детерминированный DOM scan без hard failures; keyboard test проходит все interactive controls в логичном Tab-порядке, проверяет видимый focus, активацию Enter/Space и отсутствие focus trap.
- На 320/390 px bounding box каждого critical control не меньше 44×44 CSS px, hit areas не перекрываются, controls не обрезаны и проверены ручным viewport-тестом.

**Gate W4:** ownership contract не находит прямых записей в затронутый state; Lua matrix полностью зелёная; единый `app.js` contract работает на пяти mode pages и shared chart polling/theme/messages; contrast проходит заданную матрицу и пороги; Playwright на 320/390/768/desktop не находит overflow/overlap, console errors или CDP AX/DOM hard failures; keyboard и 44×44 touch-target gates проходят полностью.

## Волна 5 — воспроизводимость

### W5.1 — A-08

- Production начинается только после локального U-05 reviewer PASS и freeze
  всех W4 writers; до этого допустимы только read-only plan/review.
- Pin текущий Espressif platform commit и только пять range-resolved packages;
  existing exact toolchains/partition tool не обновлять.
- Унифицировать оба workflow на Python `3.12`/PlatformIO `6.1.19`, exact
  `tool-scons 4.40801.0` установить штатным PlatformIO package manager; Python
  wheel-lock/bootstrap и собственный installer не создавать.
- Один stdlib read-only helper после build фиксирует Git SHA/dirty,
  `SOURCE_DATE_EPOCH`, Python/Core, platform/package и vendored-library tree
  hashes, raw firmware/map size+SHA; helper ничего не устанавливает и не меняет
  обычный локальный `pio run`.
- R3 подтвердил equal inventories и payload; различались только embedded
  `app_elf_sha256` и производный footer из-за 2077 package debug roots и двух
  project DWARF `comp_dir` paths. В base env заменить macro-only flag exact
  ordered pair: `-ffile-prefix-map=${platformio.packages_dir}=.platformio/packages`,
  затем `-fdebug-prefix-map=${platformio.src_dir}=.`. Standalone macro map,
  Core/build maps, random/build-id flags и post-processing запрещены. File map
  сохраняет package macro mapping и меняет package debug paths; source map
  касается только двух project `comp_dir`.
- Package inventory исключает только у `tool-esptoolpy` pip-generated
  `_contrib/bin/**` и `_contrib/*.dist-info/RECORD`; те же paths в других
  packages, ordinary `_contrib`, manifest/binary и любые другие absolute-path
  bytes остаются hashed.
- После R4 build PASS compatibility write scope ограничен ровно
  `tools/ui_pack_assets_contract.py` и `tools/smoke_ui_pack_assets.py`: parser
  принимает только два exact A-08 base flags. Product/UI/data, manifests,
  suffix semantics и asset inventory не меняются.
- Commit-derived `SOURCE_DATE_EPOCH` задаётся только в двух workflow и A/B gate.
  CI metadata генерируется/проверяется без нового artifact flow; release
  сохраняет map/metadata в existing Archive, release glob остаётся `.bin`.
- Выполнить две полностью изолированные cold-build среды с разными paths.
  Raw `firmware.bin` и dependency inventory для `Samovar`/`Samovar_s3` обязаны
  совпасть A↔B byte-for-byte; raw map сохраняется без normalization. Unexplained
  diff блокирует PASS.
- Pre-pin binary baseline не создаётся и regression относительно него не
  заявляется; существующие hard size/partition ceilings и семь environments
  сохраняются.
- Buildfs выполняется только как прежний regression 2/2, не сравнивается A/B.
- Не добавлять SBOM/security scanner, map parser, pre-script, normalizer или
  новый release workflow/job.

### A-15 — пользовательский waiver

A-15 не реализуется: устройство домашнее и индивидуальное, security-hardening явно исключён пользователем. Это осознанно принятый риск, а не технический `PASS`.

**Gate W5:** две изолированные cold builds дают одинаковые platform/package/
vendored-library hashes и raw `firmware.bin` для `Samovar`/`Samovar_s3`; все
семь environments и buildfs 2/2 проходят. Любое отличие локализуется,
исправляется и повторяется; объяснённый, но оставленный binary drift не является
PASS. Package hash игнорирует только два exact pip-generated path classes, а
raw firmware не переписывается после build. Reviewer возвращает
`PASS: no errors, no warnings`.

## Волна 6 — полная стабилизация и `/goal`

1. Обновить все затронутые codebase-map nodes и проверить карту targeted repair-командами при необходимости.
2. Запустить targeted tests каждой задачи, полный first-party suite, Playwright matrix и deterministic source/gzip parity.
3. Запустить blocking и extended cppcheck; ноль ошибок и необъяснённых warnings.
4. Собрать все семь CI environments из `platformio.ini`: `Samovar`, `Samovar_s3`, `Samovar_no_power`, `Samovar_rmvk`, `Samovar_sem`, `Samovar_lua_mqtt`, `Samovar_alarm_button`; выполнить buildfs для `Samovar` и `Samovar_s3`, проверить hard size/partition gates, а в A-08 — equality raw `firmware.bin` и dependency inventory A↔B без недоказанного pre-pin regression claim. Raw map только сохраняется как evidence.
5. Выполнить `git diff --check`, проверить только ожидаемые файлы, секреты и generated artifacts.
6. Применить `anti-ai-slop` только к собственному diff, не затрагивая пользовательские изменения.
7. Reviewer-сабагент читает весь итоговый diff. При любой ERROR/WARNING исправить, повторить все затронутые gates и снова вызвать reviewer.
8. `/goal` закрывается только после формулировки reviewer: `PASS: no errors, no warnings` и зелёных обязательных gates.

## Rollback

- Каждая задача — отдельный логический diff/write scope; зависимая волна не начинается до PASS.
- При регрессии откатывается только текущая незавершённая задача, без `git reset --hard` и без удаления пользовательских изменений.
- Единственный новый profile blob получает version/size/CRC и обязательный read-back; A/B/commit marker не добавляются.
- Старый GET method сохраняется, поэтому rollback не требует смены URL; strict validation и наблюдаемый result остаются обязательными функциональными контрактами.
