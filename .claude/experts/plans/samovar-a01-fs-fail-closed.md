# A-01 — fail-closed mount файловой системы

**Статус:** завершён; независимый reviewer — `PASS: no errors, no warnings`.

**Проверка:** source-extracted/mutation-tested focused gate PASS; полный smoke
`58/58`; blocking cppcheck exit `0`; extended cppcheck — `0 error / 0 warning`,
11 information; семь PlatformIO environments — `7/7 SUCCESS`; все шесть browser
contracts через isolated stable `playwright-cli 0.1.17` — `6/6 PASS`;
`git diff --check` и targeted codebase-map nodes/inventory
`167 tools / 58 smoke / 6 browser` PASS; общий mapper state сохраняет unrelated
`needs_review`. Destructive LittleFS HIL — `NOT RUN (hardware unavailable)`.

**Предпосылка:** A-14 полностью завершён и синхронизирован в обоих master-ledger; reviewer — `PASS: no errors, no warnings`, smoke `57/57`, все firmware/Telegram+Blynk gates зелёные. A-01 выполнен поверх этого зафиксированного baseline.

## 1. Цель и критерий готовности

При ошибке mount прошивка выполняет ровно один `SPIFFS.begin(false)`, не форматирует и не меняет файловый раздел, явно пишет причину в `Serial` и останавливает обычный boot до любого Wi-Fi/server/control startup. Не регистрируются SSE/editor/not-found/upload/body handlers и HTTP routes, не вызываются `server.begin()` и `get_web_interface()`.

Success-path сохраняет текущие handlers, routes, `server.begin()` и updater в единственном экземпляре. Новые recovery UI/route, serial CLI, fallback FS, повторный mount, retry и FreeRTOS task запрещены.

Baseline до A-01: единственный production caller `Samovar.ino::setup()` вызывал
`WebServerInit()`, а тот — `FS_init()`, уже после Wi-Fi/control side effects.
Актуальная цепочка после исправления: `setup()` сначала вызывает `FS_init()` и
останавливается при failure; позднее передаёт результат в
`WebServerInit(fsInitResult)`, который после guard вызывает
`FS_register_web_handlers()`. Поэтому mount-gate действительно предшествует
обычному startup, а не создаёт позднюю деградацию web-части.

## 2. Зафиксированный контракт

В `samovar_api.h` объявить без helper-реализаций и overload/shim:

```cpp
enum FsInitResult : uint8_t {
  FS_INIT_OK = 0,
  FS_INIT_MOUNT_FAILED,
};

enum WebServerInitResult : uint8_t {
  WEB_SERVER_INIT_OK = 0,
  WEB_SERVER_INIT_FS_UNAVAILABLE,
};

FsInitResult FS_init(void);
void FS_register_web_handlers(void);
WebServerInitResult WebServerInit(FsInitResult fsInitResult);
```

| Вход/состояние | Результат | Допустимые side effects |
|---|---|---|
| `SPIFFS.begin(false) == false` | `FS_INIT_MOUNT_FAILED` | Только точная Serial diagnostic; flash bytes и `total_byte` без изменений |
| mount успешен | `FS_INIT_OK` | `total_byte = SPIFFS.totalBytes()`; дальнейший обычный startup |
| `WebServerInit(FS_INIT_MOUNT_FAILED)` | `WEB_SERVER_INIT_FS_UNAVAILABLE` | Только Serial diagnostic; 0 handlers, routes, server/updater starts |
| `WebServerInit(FS_INIT_OK)` | `WEB_SERVER_INIT_OK` | Текущий success-path ровно один раз |

Точные diagnostics, закрепляемые тестом:

- `FS_init()`: `FATAL FS_INIT_MOUNT_FAILED: mount failed; format disabled`;
- ранний gate в `setup()`: `FATAL: normal startup halted: filesystem unavailable`;
- защитный guard `WebServerInit()`: `FATAL: web server not started: filesystem unavailable`.
- проверка результата web startup в `setup()`: `FATAL: normal startup halted: web server unavailable`.

## 3. Порядок реализации по символам

1. `samovar_api.h`
   - добавить отдельные `FsInitResult` и `WebServerInitResult` рядом с остальными cross-module result types;
   - заменить только затронутые декларации на сигнатуры выше; не использовать `FsInitResult` как результат web-server startup и не добавлять overload/shim.

2. `FS.ino::FS_init` и `FS_register_web_handlers`
   - оставить только mount/result ownership: один `SPIFFS.begin(false)`, failure diagnostic/return, затем существующий `total_byte` и success return;
   - удалить `SPIFFS.format()`, второй `SPIFFS.begin(false)` и сообщения о форматировании;
   - существующую регистрацию `events`, `SPIFFSEditor`, not-found, upload и body handlers без изменения тел вынести в `FS_register_web_handlers()` в том же `FS.ino`;
   - сохранить владельца и момент жизни `SPIFFSEditor`; не переносить FS-handlers и его include в `WebServer.ino`;
   - не вызывать на failure `totalBytes()`, `open`, `remove`, `rename`, `format` или любой server API.

3. `Samovar.ino::setup`
   - вызвать `const FsInitResult fsInitResult = FS_init();` сразу после успешной profile load/migration, `SamSetup = startupProfile` и `print_nvs_stats("after config load")`, до `esp_log_level_set`, GPIO-0 Wi-Fi reset, touch/I2C/semaphores/`AsyncWiFiManager`/`startService()`/`xTaskCreatePinnedToCore()`;
   - при failure вывести точную diagnostic и остаться в существующем для fatal boot стиле `while (true) { delay(1000); }`;
   - в прежней точке web startup вызвать `WebServerInit(fsInitResult)`, проверить отдельный `WebServerInitResult` и при любом не-OK результате завершить обычный startup точной diagnostic;
   - существующий `Serial.println(F("Samovar started"))` перенести из pre-Wi-Fi участка сразу после успешной проверки `WebServerInitResult`; текст не менять и не добавлять новый status. `HTTP server started`/готовность также недоступны failure-path.

4. `WebServer.ino::WebServerInit`
   - принимать `FsInitResult`, первым исполняемым блоком проверять его и возвращать failure до любого handler/route/server/updater API;
   - после guard один раз вызвать `FS_register_web_handlers()`, затем оставить существующие route bodies/order, `server.begin()` и `get_web_interface()` без функциональных изменений;
   - удалить дублирующие `onFileUpload`/`onRequestBody` callbacks из `WebServerInit()`; canonical callbacks остаются только в `FS_register_web_handlers()`;
   - завершать success-path `return WEB_SERVER_INIT_OK`.

## 4. Проверки

### Автоматический host/static gate

Создать `tools/smoke_fs_fail_closed.py` без production seam. Тест извлекает из живого `FS.ino` точное тело `FS_init()`, компилирует его во временном каталоге с test-only fake `SPIFFS`/`Serial` и выполняет два сценария:

- mount failure: result `FS_INIT_MOUNT_FAILED`, `begin` вызван один раз с `false`, `format` — 0, fake flash buffer byte-identical, `total_byte` сохраняет sentinel, diagnostic точна;
- success: result `FS_INIT_OK`, один `begin(false)`, 0 format, `total_byte` получает заявленный размер.

Тот же тест статически проверяет production wiring: точные отдельные enum/prototypes; отсутствие handler/server calls и `format` в `FS_init()`; все пять FS-owned handler groups только в `FS_register_web_handlers()`; ранний terminal gate в `setup()` до `AsyncWiFiManager`, `startService()` и первого `xTaskCreatePinnedToCore()`; guard `WebServerInit()` до `FS_register_web_handlers()`, первого `server.` и updater; по одному `server.begin()`, updater и каждому canonical handler. Shape-проверки дополняют, но не заменяют compiled behavioral cases.

Из-за изменения `WebServer.ino` механически пересчитать только `A10_FREEZE_AGGREGATE_SHA256` в `tools/ui_pack_assets_contract.py`; raw UI/manifests/fixtures и остальные frozen значения не менять. В `tools/smoke_profile_store.py` синхронизировать только ожидаемую typed форму вызова `WebServerInit(fsInitResult)`. Оба изменения проверяются существующими smoke, а не обходят их.

### Граница аппаратной проверки

Отдельный destructive HIL-инструмент, который намеренно портит и восстанавливает весь LittleFS-раздел, не создаётся: это новый риск и новый обслуживаемый функционал вне исправления A-01, а доступного стенда в текущем окружении нет. Software acceptance честно доказывает один `begin(false)`, отсутствие `format/open/remove/rename` на failure, byte-identical fake flash и раннюю остановку wiring; live-flash HIL отмечается `NOT RUN (hardware unavailable)` и не выдаётся за выполненный тест.

Success-path существующего интерфейса проверяется на локальном fixture через обязательный `playwright-cli`: `/index.htm` рендерится, новых страниц/recovery UI нет. Если пользователь позже предоставит плату и отдельно разрешит destructive test, HIL выполняется вручную по согласованной процедуре, без добавления firmware hook/fallback.

### Команды gate

```bash
python3 tools/smoke_fs_fail_closed.py
python3 tools/smoke_api_routes.py
python3 tools/smoke_profile_store.py
python3 tools/smoke_ui_pack_assets.py
python3 tools/run_smoke_tests.py --timeout 60
python3 tools/run_cppcheck.py --timeout 180 --report /tmp/samovar-a01-cppcheck.txt
python3 tools/run_cppcheck.py --force --timeout 600 --report /tmp/samovar-a01-cppcheck-extended.txt
pio run -e Samovar
pio run -e Samovar_s3
pio run -e Samovar_lua_mqtt
pio run -e Samovar_no_power
pio run -e Samovar_rmvk
pio run -e Samovar_sem
pio run -e Samovar_alarm_button
stable isolated playwright-cli: все 6 browser contracts
git diff --check
```

Cppcheck и PlatformIO выполняются последовательно. Ожидаемый inventory после нового focused smoke — `167 durable tools / 58 smoke / 6 browser`; `INDEX.md` синхронизирует накопленное фактическое увеличение с 165 до 167 (A-14 + A-01). Browser gate нужен как regression-check success-path регистрации routes/handlers; UI/data не меняются.

## 5. Точный write allowlist реализации

- `FS.ino` — только `FS_init` и новый owner `FS_register_web_handlers` вокруг существующих неизменённых handler bodies;
- `WebServer.ino` — только `WebServerInit`;
- `Samovar.ino` — только `setup`;
- `samovar_api.h` — только `FsInitResult`, `WebServerInitResult`, `FS_init`, `FS_register_web_handlers`, `WebServerInit`;
- новый `tools/smoke_fs_fail_closed.py`;
- `tools/smoke_profile_store.py` — только ожидаемая typed форма web startup;
- `tools/ui_pack_assets_contract.py` — только механически пересчитанный `A10_FREEZE_AGGREGATE_SHA256`;
- metadata only: `.cli-proxy/.codebase_map/nodes/fs-ino.md`, `webserver-ino.md`, `samovar-ino.md`, `samovar-api-h.md`, `tools.md`, `.cli-proxy/.codebase_map/TESTING.md` и tools-count в `.cli-proxy/.codebase_map/INDEX.md`;
- после всех PASS: только status/evidence A-01 в этом плане, `.claude/experts/plans/samovar-audit-remediation.md` и `.claude/experts/plans/samovar-remaining-remediation-2026-07-12.md`.

Запрещены изменения `Samovar.h`, `SPIFFSEditor.h`, `platformio.ini`, partition table, `data/**`, updater logic/assets, raw UI manifests/fixtures и любых иных symbols/files.

## 6. Map, review и rollback

После software code/tests/build PASS обновить `Last reviewed` allowlisted map nodes с формулировкой `A-01 fail-closed mount/startup gate`; при ошибке — только targeted `update-node`/`repair`. Затем reviewer читает task diff и проверяет: один mount; нет format/retry/fallback; failure останавливается до `AsyncWiFiManager` и control tasks; ни один result не игнорируется; FS-handlers имеют одного владельца в `FS.ino`; success routes/methods/updater не изменены; fake-FS fault proof и отсутствие production write-calls; diff не выходит за allowlist. Завершение — только точная строка `PASS: no errors, no warnings`; недоступный live HIL указывается отдельно и не маскируется.

Rollback — обратный patch только A-01 hunks: сигнатуры, ранний gate и перенос handlers откатываются согласованно; новые tests удаляются, status/map не помечаются завершёнными. Запрещены `git reset --hard`, checkout чужих файлов и очистка существующего dirty tree. Если ранний mount нарушает подтверждённый success-path или HIL не может безопасно восстановить raw image, остановиться с evidence; не добавлять поздний mount, auto-format или recovery fallback.
