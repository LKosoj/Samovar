# A-12 — единый профиль и честная операция save/program/mode

## Статус реализации

- P1 single-blob persistence: **complete**.
- P2 compound profile operation: **complete**.
- Reviewer: **`PASS: no errors, no warnings`**.
- Gates: focused A-12 9/9, полный smoke 53/53, blocking cppcheck, все 7 PlatformIO environments, Playwright profile/program-clear/numeric, UI asset/format contracts и `git diff --check` — PASS.

Принятый контракт соответствует live tree на 2026-07-13: `profile_store.h` задаёт canonical field-wise payload и единственный blob `sam_cfg/profile`; `OperationStore` и один `ProfileOperationSlot` связывают `/save` и изменяющий `/program` с loop-side результатом. Phase читается/публикуется только acquire/release atomic helpers, а `reset_profile_operation_slot()` очищает payload и последним release-store публикует `EMPTY`. `/save` и изменяющий `/program` отвечают `202` с operation contract; `SamovarApp.waitForOperation()` опрашивает существующий `/ajax?operationId=...`, обрабатывает terminal failure/expired/network cases и завершает ожидание bounded timeout через 45 секунд. Старые split pending DTO/flags, redirect `301` и NVS compaction path удалены.

## Цель и критерий готовности

Закрыть A-12 после `R2.0 OperationStore`: HTTP сообщает success только после фактического loop-side результата, профиль хранится одним проверяемым NVS blob, а `/save` с программой и сменой режима завершается как одна операция без частичного RAM commit.

Готово, когда:

- `/save` и изменяющий `/program` возвращают `202` с `operationId/state/error`, а UI ждёт terminal `succeeded/failed` через существующий `/ajax`;
- единственный актуальный профиль — один NVS key с layout `header + SetupEEPROM + CRC32`, записанный одним `putBytes()` и успешно перечитанный;
- до подтверждённого read-back `SamSetup`, mode, program и sensor runtime не меняются;
- corrupt существующий blob блокирует normal boot; legacy/default fallback в этом случае отсутствует;
- targeted tests, browser gate, все семь PlatformIO environments и reviewer-loop проходят без ошибок и предупреждений.

## Жёсткие решения и границы

1. `R2.0` должен быть реализован и иметь отдельный `PASS` до начала A-12: он даёт типы, fixed store и lookup/transition, но не production reserve. A-12 — первый consumer и обязан под одним существующим `pending_command_lock` атомарно создать operation record вместе с публикацией pending save/program DTO. При любой ошибке не остаётся ни record без DTO, ни DTO без record; active records не перезаписываются.
2. Использовать существующий namespace `sam_cfg` и один новый key `profile`; это единственная запись актуального профиля. Поле `SetupEEPROM::Mode` заменяет отдельный `last_mode` после migration.
3. Новый корневой `profile_store.h` — C++11/Arduino-free inline generic fixed-payload codec/template: он не включает `Samovar.h` и не знает имя `SetupEEPROM`. Blob имеет exact layout `SMPF` + little-endian `uint16` version `1` + little-endian `uint32` payload size `516` + canonical payload `516` bytes + little-endian CRC-32/ISO-HDLC (`0xEDB88320`, init/final XOR `0xFFFFFFFF`) по `header + payload`, итого `530` bytes. Generic header владеет bounded canonical byte writer/reader и blob codec; `NVS_Manager.ino` единожды задаёт field-wise projection `SetupEEPROM` в wire payload.
   Canonical v1 payload кодирует поля строго в порядке объявления `SetupEEPROM`: integers little-endian, `float` как IEEE-754 binary32 bits little-endian, `bool` только `0/1`, char/address arrays как exact fixed bytes; весь оставшийся reserved tail до 516 bytes равен нулю и decoder это проверяет. Encoder/decoder не копируют object representation, поэтому CRC не зависит от C++ padding; poisoned padding одинаковых logical candidates даёт byte-identical blob. Текущий ESP32 ELF подтверждает `sizeof(SetupEEPROM) == 0x204` (516 байт); production держит отдельные `sizeof`, trivially-copyable, `sizeof(float) == 4`, `sizeof(int) == 4` и IEC-559 assertions. При изменении field projection/ABI format version обязан измениться; тип не переносить и не дублировать.
4. Запрещены A/B generations, active pointer, commit marker, custom compaction/backup, retry, namespace clear/repair, dual write, per-key write и любой silent fallback. Не создавать shim, новый route, task, mutex или recovery UI/CLI.
5. Legacy keys/EEPROM читаются только при точном отсутствии key `profile`. Любой существующий `profile`, включая blob с неверным header/version/size/CRC, закрывает legacy path и при corruption даёт fail-closed. Успешную migration отмечает сам blob; `migrated` flag не нужен. Старые данные не удалять и больше не писать.
6. Сохраняются имена и методы `/save` и `/program`, а также поля `/program` `ok/err/program`; добавляются только поля R2.0. Никаких redirect/fallback responses до terminal success.
7. A-12 добавляет ровно четыре terminal error category в `OperationError`: `OPERATION_ERROR_CANCELLED` → `operation_cancelled` для session/mode race до side effect; `OPERATION_ERROR_PROFILE_PERSIST_FAILED` → `profile_persist_failed`; `OPERATION_ERROR_MODE_SWITCH_FAILED` → `mode_switch_failed`; `OPERATION_ERROR_RUNTIME_BUSY` → `operation_runtime_busy` для metadata/runtime lock. Детальный `PersistResult` остаётся в существующем local message/log; `STORE_FULL`, `LOCK_BUSY` и `INTERNAL` сохраняются без изменения.

## Разрешённый write scope реализации

- новый `profile_store.h`;
- `NVS_Manager.ino`, `Samovar.ino`, `WebServer.ino`, `FS.ino`, `Menu.ino`, `samovar_api.h`, `operation_store.h` только для A-12 error codes и `selftest.h` только для замены удаляемого `pending_switch_mode_flag` уже существующим `mode_switch_in_progress()`;
- `logic.h::pump_calibrate()` и `beer.h::FinishAutoTune()` — только два подтверждённых caller-а удаляемого `save_profile()` wrapper: local candidate, checked persist/read-back, затем commit; остальной mode-код read-only;
- `data/app.js`, `data/setup.htm`;
- `data/program.htm`, `data/index.htm`, `data/beer.htm`, `data/distiller.htm`, `data/bk.htm`, `data/nbk.htm`, `data/brewxml.htm` только если их существующий текст раннего `accepted/queued` обязан быть заменён terminal-success текстом; логика остаётся в `app.js` и не дублируется по страницам;
- новый focused A-12 host/static/browser test, `tools/static_analysis_sources.json`, а также только прямо устаревающие контракты `tools/smoke_nvs_compaction_durable.py`, `tools/smoke_handle_save_staging.py`, `tools/smoke_shared_state_strings.py`, `tools/smoke_api_routes.py`, `tools/smoke_numeric_misc_routes.py`, `tools/smoke_safety_timing.py`, `tools/smoke_program_ux.py`, `tools/smoke_numeric_input_ui.py`, `tools/smoke_sensor_fields_staging.py`, `tools/smoke_pump_pwm_nonblocking.py`, `tools/smoke_ci_contract.py`, `tools/test_numeric_input_ui_browser.py`, `tools/test_program_clear_ui_browser.py`;
- только при фактическом изменении `data/**`: соответствующие `source_sha256` в `web_src/ui-manifest-v1.json`, exact frozen input/tree hashes в `tools/ui_pack_assets_contract.py` и focused `tools/smoke_ui_pack_assets.py`; schema, raw/P1.1 semantics и unrelated fixtures не менять;
- только затронутые nodes `.cli-proxy/.codebase_map/nodes/{nvs-manager-ino,samovar-ino,webserver-ino,fs-ino,menu-ino,samovar-api-h,operation-store-h,selftest-h,logic-h,beer-h,data,tools}.md` и новый node для `profile_store.h`, если mapper его создаёт;
- этот task-plan и строка A-12 master ledger — только после полного PASS.

Любой дополнительный production-файл требует остановки и явного пересмотра allowlist. Соседние refactor/formatting запрещены.

## Шаг 0 — точный caller inventory

Перед patch выполнить targeted `rg` по всему checkout для `save_profile_nvs`, `load_profile_nvs`, `save_profile`, `read_config`, `set_default_setup_profile`, `set_current_profile_mode`, `migrate_from_eeprom`, `profile_exists` и `recover_pending_nvs_compaction`. Зафиксировать каждый definition/caller в тестовом allowlist; после смены API ни один реальный caller не может игнорировать result.

Уже подтверждённый минимум:

| Контур | Текущий caller/роль | Требуемый итог |
|---|---|---|
| `NVS_Manager.ino` | legacy namespace migration, EEPROM migration, recursive save/compaction, load из per-key schema | один absent-only local-candidate migration; compaction/retry/per-key writer удалить |
| `Samovar.ino::setup()` | recovery → migration → `read_config()` → default save | один load result; absent создаёт и сохраняет default candidate, corrupt/I/O error останавливает boot до web/control |
| `Samovar.ino` | Wi-Fi token save, pending `/save`, I2C calibration, `read_config()` | каждый вызов проверяет `PersistResult`; RAM меняется только после success |
| `WebServer.ino::switch_samovar_mode()` | отдельные mode/meta writes и `save_profile()` | persistence входит в owner compound operation; второй NVS write удалить |
| `WebServer.ino::handleSave()` / `web_program()` | queue и ранние `301`/`202` | одна operation с terminal result; busy не создаёт record |
| `FS.ino::save_profile()` | void wrapper | удалить без замены/shim; callers используют owner API |
| `Menu.ino` | локальные default/save/mode callers | обновить каждый найденный targeted inventory caller и явно обработать failure |
| `logic.h::pump_calibrate()` | после остановки помпы напрямую меняет `SamSetup.StepperStepMl`, вызывает `save_profile(); read_config();` | вычислить candidate, persist/read-back, затем присвоить калибровку; failure оставляет прежний `SamSetup` и сообщает ошибку |
| `beer.h::FinishAutoTune()` | напрямую меняет Kp/Ki/Kd и PID до `save_profile(); read_config();` | сохранить рассчитанные коэффициенты в candidate, persist/read-back, затем при success обновить `SamSetup`; при success/failure восстановить PID из committed `SamSetup`, вызвать `set_heater_state()`, и только после него вернуть `ATuneModeRemember`, чтобы stop helper не оставил PID в `AUTOMATIC` |
| `samovar_api.h` | void declarations | только точные result-returning signatures; implementation в header не добавлять |
| `setup.htm` / `app.js` | ранний redirect/queued program success | общий waiter R2.0, success только terminal |

## Шаг 1 — один blob и fail-closed load

1. Ввести bounded enums `PersistResult` и `ProfileLoadResult` со стабильными кодами как минимум для `not_found`, open, write/short-write, reopen, stored-size, read/short-read, magic, version, payload-size, CRC и read-back mismatch.
2. `save_profile_nvs(const SetupEEPROM& candidate)`:
   - field-wise кодирует candidate в canonical 516-byte payload и один local fixed-size blob без чтения object padding;
   - открывает `sam_cfg`, делает ровно один `putBytes("profile", ...)` и требует exact byte count;
   - закрывает writer, заново открывает `sam_cfg` read-only через low-level NVS, требует exact key lookup/size, читает весь blob, повторно validate-ит header/version/size/CRC и сравнивает все encoded bytes; decoder переиспользует исходный payload buffer, а второй `SetupEEPROM` на stack не создаётся, так как encoder уже гарантировал canonical payload, а exact compare отвергает любое изменение read-back;
   - fixed byte buffers на stack: save `516 + 530 + 530 = 1576` bytes, load `530 + 516 + 516 = 1562` bytes; heap/global buffers не добавлять;
   - возвращает result без retry, clear, compaction или RAM mutation.
3. `load_profile_nvs(SetupEEPROM& candidate)` использует low-level `nvs_open`/`nvs_get_blob`: только exact `ESP_ERR_NVS_NOT_FOUND` для namespace/key означает absence; type mismatch, length-query/read/open и любые другие ошибки fatal. Валидный blob field-wise декодируется только в local candidate. Existing-but-invalid возвращает fatal error и не читает legacy/default.
4. Только при exact absence один legacy reader строит local candidate из текущих per-key NVS/legacy namespaces/EEPROM с зафиксированным существующим precedence и существующими migration defaults. Все legacy typed/string/blob getters имеют tri-state `found/absent/error`: optional absent сохраняет default, exact required-marker absence разрешает следующий источник, type/read error немедленно прекращает migration. Candidate становится загруженным только после `save_profile_nvs()` и его read-back.
5. Если blob и валидный legacy отсутствуют, boot создаёт default candidate, сохраняет/read-back и лишь затем публикует его. Default-save failure блокирует normal boot.
6. Удалить profile compaction backup/recovery, `sam_tmp`, recursive retry, per-key writers, migration flag writes, legacy clears, runtime writes `last_mode`, `FS.ino::save_profile()` и ставшие orphan declarations. Legacy code остаётся read-only и ровно в одном месте.
7. `set_default_setup_profile` и все non-HTTP save callers работают с local `SetupEEPROM` candidate: сначала persist/read-back, затем assignment. Wi-Fi, calibration, menu и boot/default paths при failure сохраняют прежний RAM и дают явный caller-specific error; global-mutating compatibility overload не оставлять.

## Шаг 2 — одна compound operation

1. `/save` полностью парсит и валидирует `SetupEEPROM`, sensor-reset mask, optional `WProgram` и target mode. Для mode change без явной программы route заранее готовит и проверяет существующий default draft; явный `WProgram` имеет приоритет. Единственная именованная production-точка `queue_profile_operation(...)` в `WebServer.ino`, не зависящая от HTTP response types, под одним захватом существующего `pending_command_lock` сначала проверяет active session, mode switch, единый DTO slot и OperationStore capacity, затем резервирует record, записывает его ID и публикует fixed POD-поля единственного compound DTO. После успешного reserve plain-copy не имеет отдельной failure-ветки; искусственный production fault hook не добавлять. Busy/lock/store failure возвращает explicit `409/503` и оставляет store и DTO неизменными.
2. Compound DTO владеет одним `OperationId`, settings candidate, optional program draft/action, optional program metadata, sensor-reset mask и optional target mode. Он заменяет, а не дополняет, `pending_setup_save_buf`/flag, `pending_program_update`, `pending_program_metadata`/flag и `pending_switch_mode_flag`/value. `mode_switch_barrier_active` остаётся отдельным существующим safety barrier. Полный DTO не копировать на loop stack: после публикации active slot неизменяем до terminal cleanup.
3. Изменяющий `/program` также получает `OperationId`; parse-only/read response может остаться синхронным `200`. Program/metadata action завершается terminal только после loop-side commit либо explicit failure.
4. Loop переводит record `queued → running`, повторяет session/target checks и выполняет всю относящуюся к owner-commit отказную работу до NVS: metadata lock/preparation, mode actuator/log/Lua-stop cleanup и mode FSM preparation. Default/explicit program уже полностью проверен route-ом. Active-program-session guard хранится отдельным DTO bit: он включён для standalone `/program` и `/save` с явным `WProgram`, но выключен для settings-only save и mode change с route-staged default program, сохраняя существующее поведение safe-stop FSM. Обнаруженный race даёт terminal `failed` без side effects.
5. При mode change FSM сначала безопасно останавливает процесс/приводы, очищает управляющие очереди, закрывает лог и использует уже подготовленный final program draft. До persistence он не меняет `SamSetup`, `Samovar_Mode`, `Samovar_CR_Mode` или live program. Cleanup failure оставляет старый профиль/RAM, завершает operation `failed`; безопасно остановленные приводы автоматически не перезапускаются.
6. Последняя отказная операция атомарной A-12 owner-границы — `save_profile_nvs(candidate)` с read-back. Перед ней должны быть гарантированы matching `running` record, bounded `terminal-pending` storage и все commit prerequisites; terminal record публикуется только после фактического результата. После NVS запрещены повтор NVS, parsing и функции, чей результат входит в A-12 success/failure.
7. После success один loop-owned участок публикует owner-state: assignment `SamSetup`, mode scalars, prepared `program_commit/program_clear`, prepared scalar metadata и sensor copies/resets. Затем сохраняются существующие void-процедуры `apply_config_runtime()` и, в `USE_LUA`-сборках при любом mode change, `load_lua_script()` с текущей logging-семантикой, после чего снимается mode barrier и публикуется terminal `succeeded`. Их внутренние runtime/Lua ошибки не откатывают уже подтверждённый profile/program commit и не требуют нового transactional API; Lua validation/result отдельно закрывает A-07. Текущий post-save `read_config()` удалить из operation path.
8. Любая ошибка до read-back завершает record стабильным `failed/error`, очищает только собственный pending DTO и сохраняет прежние settings/mode/program RAM. Barrier снимается для race до начала mode FSM; после фактического mode-cleanup failure он остаётся latched по существующей safe-stop семантике до перезагрузки. Нельзя отменять или перезаписывать чужую operation.
9. Единственная именованная loop-owner production-точка `process_profile_operation()` в `Samovar.ino` вызывается из `loop()`. Она не держит `pending_command_lock` во время NVS, FS, I2C, Lua или mode-cleanup работы: переводит operation в `running` коротким lock window и работает с неизменяемым active DTO без большой stack-копии; после фактического commit сохраняет bounded `terminal-pending` state/error и повторяет только короткую публикацию результата при временном lock-busy. Это не retry операции и не повтор NVS/hardware side effect: выполненная работа запускается ровно один раз, а record не остаётся навсегда `running` и не получает выдуманный failure.

## Шаг 3 — UI contract

1. `/save` отвечает `Cache-Control: no-store` JSON `202 {operationId,state,error}` вместо `301`. `setup.htm` сохраняет dirty state и disabled submit до terminal result; только `succeeded` очищает dirty state и делает существующий переход на `/`.
2. `failed`, unknown/expired operation, poll/network error и bounded timeout показываются в существующем error area, не редиректят и не объявляют настройки сохранёнными.
3. `app.js` расширяет единый `waitForOperation()`/program response parser полями R2.0. `postProgram()` и `clearProgram()` сообщают success только после terminal `succeeded`; `queued` — не success.

## Failure matrix и проверки

- Blob host tests: exact 530-byte layout, field-wise encode/decode, CRC vectors, mutation каждого header/payload/CRC byte, wrong magic/version/payload size, truncated/oversize/nonzero-reserved data и poisoned C++ padding при одинаковых logical fields.
- NVS fault tests: host fake запускает production save/load path для namespace open, exact key absence, key lookup/type error, `putBytes` 0/short, reopen, length, read short/error, CRC/canonical/read-back byte mismatch; ровно один write attempt и ноль retry/compaction/clear/rollback writes.
- Migration/boot: host fake проверяет tri-state legacy required/optional keys, type/read error без следующего fallback, valid common per-key, legacy-mode и EEPROM sources; после blob legacy не читается; corrupt blob не использует legacy/default; no-data default save; migration/default save failure блокирует boot before web/control.
- PID fault test: `FinishAutoTune()` публикует новые Kp/Ki/Kd только при `PERSIST_OK`, но на обеих ветках восстанавливает tunings/limits/sample time из committed `SamSetup`, вызывает `set_heater_state()` до финального `heaterPID.SetMode(ATuneModeRemember)`.
- Caller/static gate: targeted `rg` inventory совпадает с allowlist; нет ignored `PersistResult`, `save_profile()` wrapper, recursive retry, `sam_tmp`, A/B/dual-write/last-mode writes; profile writer содержит один current-profile `putBytes`.
- Obsolete-test gate: прежний `smoke_nvs_compaction_durable.py` удалён/переименован в точный single-blob contract, а остальные перечисленные существующие smoke/browser tests больше не требуют `301`, `queued`-success, независимые save/program flags или compaction recovery. Не оставлять misleading filename с противоположным контрактом.
- Operation tests: атомарность первого production reserve + fixed POD publication, OperationStore full, pending-lock busy, occupied slot, совпадение record/DTO ID, two saves, save+program, save+mode+program, standalone program/clear/metadata, active session and mode race; exact old RAM/NVS visibility before success and one terminal result. Искусственную failure-ветку после успешного reserve не создавать: plain-copy не может отказать.
- Behavioral harness извлекает и компилирует точные bodies `queue_profile_operation()` и `process_profile_operation()`; fake разрешены только на lock/NVS/mode/program/metadata/runtime/Lua boundaries. Копия owner-алгоритма, `#ifdef TEST`, callback injection, production fault hook или тестовый header запрещены.
- Terminal-publication test: временный lock-busy после commit повторяет только `operation_store_finish_locked`; счётчики NVS/program/metadata/mode/Lua side effects остаются равны одному.
- Route default-program test: validation failure до `202` возвращает `400`, не создаёт record/DTO/barrier и не запускает cleanup.
- Mode fault tests: failure на cleanup/log/persist/read-back; old settings/mode/program remain, no partial commit, no automatic actuator restart.
- Browser — обязательно через skill `playwright-cli`: mock `queued→running→succeeded`, `queued→failed`, timeout/network/expired id, `409/503`, double submit; проверить no early redirect/success, dirty/button/error state, `/program` terminal message и ноль console errors.

## Финальные gates и review

1. Запустить focused A-12 host/static tests, затем `python3 tools/run_smoke_tests.py` и blocking cppcheck с новым header в source manifest.
2. Собрать минимум `pio run -e Samovar`, `pio run -e Samovar_s3`, `pio run -e Samovar_lua_mqtt`, затем `pio run` для всех семи environments; source фиксируется на время builds.
3. Выполнить `git diff --check` и проверить diff строго по allowlist.
4. Обновить `Last reviewed` перечисленных map nodes; для нового header выполнить targeted mapper `update-node`, при failure — `repair`, не full regeneration.
5. Reviewer читает весь A-12 diff и возвращает ERROR/WARNING либо точный `PASS: no errors, no warnings`. Любая находка возвращается в тот же scope; tests/build/browser/review повторяются до чистого PASS. Только затем обновить master ledger.

## Rollback semantics

- До NVS write failure rollback не нужен: persisted profile и RAM остаются прежними. После начатого `putBytes`/неуспешного read-back не пытаться восстанавливать старые bytes: operation `failed`, RAM остаётся прежним, следующий boot fail-closed при invalid blob.
- Mode cleanup физически не откатывается: при failure устройство остаётся безопасно остановленным; автоматический restart запрещён.
- Legacy keys сохраняются для ручного firmware rollback, но после первого нового save они заведомо stale, потому что dual write запрещён. Downgrade требует явного backup/export и ручного restore/reset; firmware не делает format/fallback автоматически.
- Code rollback — обычный revert только A-12 allowlist. Не оставлять обе persistence реализации, compatibility shim или выключенный альтернативный путь.
