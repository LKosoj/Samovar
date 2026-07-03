# План устранения находок AUDIT.md

Дата: 2026-07-03.

Источник: `AUDIT.md` от 2026-07-02. План охватывает все actionable-находки и предложения аудита. Пункты сгруппированы в рабочие пакеты, чтобы исправлять причины, а не размножать точечные патчи по копиям.

## 0. Допущения и правила выполнения

- "Все пункты аудита" означает: все критичные, существенные, средние и мелкие находки, а также предложения по улучшению, если они устраняют найденный класс проблем.
- Ничего не откладывается "на потом": низкорисковые и низкоприоритетные пункты получают место в очереди, но не должны обгонять аварийные и data-loss проблемы.
- Новый firmware-код не выносится в `.cpp` и не переносится в `src/`; новые общие firmware-хелперы оформляются как `inline` в профильных `.h`.
- Не вводятся fallback-пути без явного согласования. Ошибка должна быть явной: `400/429/503`, сообщение оператору или отказ от применения настройки.
- Для каждого рабочего пакета используется цикл:
  1. детальный план сабагента;
  2. реализация в ограниченном наборе файлов;
  3. локальная проверка;
  4. code-review сабагента;
  5. исправление замечаний до чистого результата.
- Параллелить можно только пакеты с непересекающимися write-set. При конфликте приоритет у пакетов безопасности процесса и async runtime.

## 1. Волны и зависимости

### Wave 0. Быстрые безопасные исправления

Цель: закрыть низкорисковые ошибки, которые не требуют новой архитектуры и уменьшают дальнейший шум.

Пакеты:

- `W0.1 UI shell`: добавить `<!DOCTYPE html>` и `<meta name="viewport">` во все страницы `data/*.htm`, кроме уже исправленных; проверить standards mode.
- `W0.2 UI confirmations`: `confirm()` для выключения нагрева, следующей программы, reset, reboot, resetwifi; не трогать start/pause без необходимости.
- `W0.3 AJAX I2C cache`: в `/ajax` заменить блокирующий `get_stepper_speed()` на `i2c_stepper_cache.pump_current_speed`.
- `W0.4 NVS empty string`: исправить `saveStringIfChanged`, чтобы пустая строка не считалась сбоем записи.
- `W0.5 Blynk token`: длина токена 32, копирование через `copyStringSafe`, без переполнения `blynkauth`.
- `W0.6 mode returns`: добавить `return` после `distiller_finish()` и симметрично проверить `BK`.
- `W0.7 include/partition hygiene`: `#pragma once` в ключевые режимные `.h`; убрать или синхронизировать устаревший корневой `partitions.csv`; поправить инструкцию в `Samovar.ino`.
- `W0.8 millis lint pass`: исправить явно найденные naive millis comparisons в `distiller.h`, `BK.h`, `impurity_detector.h`.
- `W0.9 small UB fixes`: `set_capacity` bounds, `char == 255`, кламп beer progress, `StepperStepMl` кламп, `portENTER_CRITICAL_ISR` в task-контексте, дубль `temprature_sens_read`.

Проверка: `pio run -e Samovar`, `pio run -e Samovar_s3`, `python tools/smoke_api_routes.py`, targeted grep по исправленным паттернам.

Параллельность: `W0.1/W0.2` может идти отдельно от firmware `W0.3-W0.9`, если UI-ветка не трогает `WebServer.ino`.

### Wave 1. Безопасность процесса и аварийные пути

Цель: исключить повторное включение ТЭНа и продолжение нагрева при недостоверных датчиках.

Пакеты:

- `W1.1 emergency stop path`: все аварийные ветки режимов переводятся на единый безопасный путь останова через loop-контекст; прямые `set_power(false)` из SysTicker удаляются там, где они создают гонку.
- `W1.2 heating sensor validity`: общий `sensor_valid(...)`/`process_sensor_failed(...)`; контуры нагрева beer, distiller, BK, NBK останавливают процесс при отказе управляющего датчика.
- `W1.3 NBK critical alarms`: аварии НБК больше не делают `delay`, `SetSpeed`, `run_nbk_program`, `set_power` из SysTicker; только диагностируют и ставят команду loop.
- `W1.4 BK ACP protection`: добавить защиту БК по температуре ТСА по образцу distiller, но через общий безопасный путь.
- `W1.5 program apply guard`: `POST /program` не применяет новую программу при активной сессии соответствующего режима; оператор получает явную ошибку.
- `W1.6 OneWire scan gate`: `scan_ds_adress()` не конкурирует с `DS_getvalue`; скан только в безопасном состоянии или в одном контексте опроса.
- `W1.7 pressure alarm guard`: защита от ежесекундного повторного `set_alarm()` при удержании давления, с гистерезисом сброса.

Проверка: сборка двух env, grep на прямые `set_power(false)` в `check_alarm_*`, статический сценарий "датчик невалиден -> команда остановки", review всех call-chain `SysTicker -> alarm`.

Параллельность: `W1.1-W1.4` трогают одни режимные файлы и должны идти последовательно. `W1.5-W1.7` можно планировать параллельно, но интегрировать после `W1.1`.

### Wave 2. Async-safe command pipeline

Цель: довести идиому `pending_*` до 100% и убрать блокировки из async_tcp.

Пакеты:

- `W2.1 resetwifi/reboot/reset`: `resetwifi` отвечает клиенту и выполняется в loop; reboot/reset остаются через отложенные команды.
- `W2.2 pending voltage`: `/command?voltage=` только валидирует и ставит pending; `set_current_power` выполняется в loop.
- `W2.3 pending mixer/watert/pumpspeed/nbkopt`: все I2C, PID и stepper-операции уходят из async; `nbk_Mo/nbk_Po` не пишутся напрямую из web.
- `W2.4 pending self-test stop/log flush`: `stop_self_test` и `fileToAppend.flush()` выполняются в безопасном контексте или под единым file-lock.
- `W2.5 pending Lua file/reload`: `/lua?script=...` и upload `.lua` не читают SPIFFS и не грузят Lua из async.
- `W2.6 command responses`: `/command` различает `OK`, `BUSY`, `IGNORED`, `POWER_OFF`, `BAD_REQUEST`; throttling не съедает разные команды с ответом `OK`.
- `W2.7 upload/body debug`: `Serial.write(data, len)` для catch-all body/upload ограничен debug-режимом или безопасным лимитом.
- `W2.8 I2CStepper atomic refresh/apply`: `i2c_config_in_flight` и блочное/атомарное чтение u16/u32, чтобы refresh не перетирал staged config и не давал рваные значения.

Проверка: `tools/smoke_api_routes.py`, сборка, grep direct async calls (`set_current_power`, `set_mixer`, `menu_reset_wifi`, `run_lua_script`, `flush`) в `WebServer.ino`; ручной статический trace `handler -> pending -> loop`.

Параллельность: `W2.1/W2.4/W2.7` независимы. `W2.2/W2.3/W2.6` связаны контрактом `/command` и идут одной веткой. `W2.5` можно вести отдельно от command pipeline, но ревьюить вместе с Lua mutex.

### Wave 3. Lua, shared state и data races

Цель: закрыть оставшиеся гонки String/POD и общих буферов.

Пакеты:

- `W3.1 lua execution serialization`: единая обёртка `lua_exec` с mutex или очередь в `DoLuaScriptTask`; все `lua.Lua_dostring` проходят через неё.
- `W3.2 button Lua off SysTicker`: `btn_script` не исполняется в SysTicker; ставится в очередь Lua.
- `W3.3 shared String locking`: `SessionDescription`, `pending_program_str`, `Lua_status`, `Msg` из Lua, `program_Wait_Type` получают lock/enum/буфер без UAF.
- `W3.4 program WType`: убрать или закрыть гонки чтения `program[].WType` в `/ajax` и авариях; предпочтительно перейти к компактному типу для wait/program tags.
- `W3.5 MQTT buffers`: `MqttSendMsg` использует локальные буферы или mutex; нет общих static буферов между задачами.
- `W3.6 fileToAppend ownership`: закрытие/flush/println общего лога происходит в одном контексте или под lock.
- `W3.7 program limits`: ввести `PROGRAM_MAX`, заменить `30`/`CAPACITY_NUM*2`/sentinel-индексы, добавить `static_assert`.

Проверка: сборка, cppcheck, grep на `Lua_dostring`, `SessionDescription`, `program_Wait_Type`, `program[ProgramNum].WType`, static buffers in MQTT.

Параллельность: `W3.1-W3.2` одна ветка; `W3.5-W3.6` можно вести параллельно; `W3.3-W3.4-W3.7` требуют общей модели `program[]`.

### Wave 4. Persistence and settings correctness

Цель: настройки применяются атомарно, валидируются и не теряются при compaction.

Пакеты:

- `W4.1 handleSave staging`: `handleSave` парсит в локальную/staged `SetupEEPROM`, валидирует диапазоны через `string_utils.h`, затем применяет целиком в loop.
- `W4.2 sensor fields staging`: изменения DS-адресов/счётчиков и reset sensor fields не происходят из async по частям.
- `W4.3 durable NVS compaction`: compaction сохраняет backup во временный NVS namespace или LittleFS-файл до erase; восстановление при старте по маркеру.
- `W4.4 get_web_file writes` — done 2026-07-03: скачивание web UI проверяет `open`, размер записи и ошибку FS; запись идёт через atomic tmp+backup+rollback helper; при ошибке возвращает явный fail, не оставляет битый файл и не обновляет `/version.txt`.
- `W4.5 crash handler cleanup`: убрать ложный shutdown crash handler, неиспользуемый 2К stacktrace buffer и неверный `verbose_print_reset_reason`.

Проверка: сборка, targeted smoke для `/save`, audit grep `toInt()/toFloat()` в `handleSave`, статический тест/скрипт для `saveStringIfChanged`, review NVS failure path.

Параллельность: `W4.5` независим. `W4.1-W4.3` лучше делать последовательно. `W4.4` можно планировать отдельно.

### Wave 5. Mode common and command architecture

Цель: убрать дубли, которые уже породили разное аварийное поведение.

Пакеты:

- `W5.1 mode_common.h alarms` — done 2026-07-03: общий inline-хелпер для аварий воды/ТСА, закрытия клапана при охлаждении и overflow-safe пауз; сборки двух env, полный smoke suite, codebase-map metadata и reviewer-loop clean.
- `W5.2 mode_common.h heating start` — done 2026-07-03: общий start-heating path для distiller/BK, чтобы гонка автоперезапуска не вернулась.
- `W5.3 program parser/serializer common` — done 2026-07-03: общий скелет parse/serialize для rect/dist/beer/nbk с режимными таблицами полей; внешние форматы сохранены явно.
- `W5.4 pump PID common` — done 2026-07-03: единые helpers для PID воды, direct water-valve setpoint и снижения мощности с `PWR_FACTOR`.
- `W5.5 FreeRTOS command queue`: одноместный mailbox заменён на статическую очередь `SamovarCommandMsg`; оставшиеся payload-heavy `pending_*`-флаги мигрировать в async-pipeline пакетах W2.
- `W5.6 mode registry`: `ModeOps` для диспетчеров loop/alarm/finish/page/start/status; миграция по одному диспетчеру.
- `W5.7 samovar_api.h`: единая точка forward declarations вместо стен прототипов.
- `W5.8 logic.h split` — done 2026-07-03: механический split `logic.h` в `alarm.h`, `power_regulator.h`, `valve_buzzer.h`, `selftest.h` без изменения поведения; include order и smoke-контракт закреплены.

Проверка: сборка после каждого подпакета, code review на отсутствие изменения семантики, grep на дубли аварийных блоков и прототипов, ручной mapping mode dispatch до/после.

Параллельность: `W5.7-W5.8` можно готовить отдельно после include guards. `W5.1-W5.4` идут после Wave 1. `W5.5-W5.6` идут после Wave 2, потому что меняют фундамент команд.

### Wave 6. Web UI foundations

Цель: честная обратная связь, мобильность, отсутствие копипасты и фальшивых аварий.

Пакеты:

- `W6.1 app.js extraction` — done 2026-07-03: общий JS для connection state, messages/history/audio/theme/tabs/sendbutton/poll-loop вынесен в `data/app.js`.
- `W6.2 command UI contract` — done 2026-07-03: фронт обрабатывает `OK/BUSY/IGNORED/POWER_OFF/BAD_REQUEST`; команды `/command` больше не показывают безусловный success-alert.
- `W6.3 audio unlock` — done 2026-07-03: `sound.play()` обрабатывает rejected Promise, unlock выполняется по user gesture, оператор получает визуальное сообщение о блокировке звука.
- `W6.4 DOM update errors` — done 2026-07-03: сетевые ошибки отделены от ошибок DOM; TypeError в `loadDoc` не превращается в "Обрыв связи".
- `W6.5 message/history rendering` — done 2026-07-03: HTML-string surgery удалена, рендер идёт через `map(...).join('')`, история ограничена 500 записями, удаление последнего сообщения не переписывает HTML строками.
- `W6.6 form button types`: все action-кнопки `type="button"`; Enter не вызывает `SetVoltage`.
- `W6.7 dead mode UI cleanup`: удалить мёртвый `I2CPump` tab, недостижимый `Prog` в `bk.htm`, неиспользуемые функции `sendpumpspeed/sendwaterpwm`, висячий `PipeTemp.toFixed`.
- `W6.8 dark theme tokens`: заменить инлайн-цвета статус-баров и темных элементов на CSS-переменные.
- `W6.9 NBK getProgram`: пустая программа не алертит при загрузке, цикл ограничен размером UI.
- `W6.10 i2cstepper polling`: интервалы зависят от наличия устройства; кнопки не позволяют повторный запуск на старом состоянии.

Проверка: Playwright по обязательному правилу проекта, статический grep `type='submit'`, `innerHTML = historyArray`, `replace(\"onclick=...`)`, визуальные скриншоты desktop/mobile.

Параллельность: `W6.1-W6.5` единая ветка. `W6.6-W6.10` можно делать параллельно, если не мешают `app.js`.

### Wave 7. Main UI, chart, programs and CSS

Цель: главные страницы работают офлайн, не лгут оператору и не перегружают ESP32.

Пакеты:

- `W7.1 chart offline`: график не умирает без CDN; `startPolling()` запускается независимо от chart lib. Затем локальный lightweight chart asset вместо CDN.
- `W7.2 chart incremental data`: не перечитывать полный `data.csv` каждые 15 секунд; добавить offset/decimation или увеличить частоту как промежуточный шаг без fallback.
- `W7.3 /ajax ProgramNum/status code`: UI не парсит `Прг №` из локализованной строки.
- `W7.4 /program JSON contract`: явный `{ok, err, program}`; beer/distiller не затирают textarea старой программой; brewxml debug alert убран.
- `W7.5 index/program UX`: confirm перед перезатиранием изменённой программы шаблоном, сетевые ошибки показываются, `sendbutton` возвращает результат.
- `W7.6 calibration UX`: состояние кнопки меняется только после `resp.ok`, хранится в переменной, не в тексте.
- `W7.7 style.css cleanup`: исправить глобальные селекторы `.prgline input, img, select`, `.message-box`, мёртвые стили, lightgreen contrast.
- `W7.8 HTML cleanup`: `className` -> `class`, `visibility:hidden` holes, invalid `#FFF;`, units in CSS, implicit globals where touched.
- `W7.9 CORS/command method`: убрать `Access-Control-Allow-Origin: *` для управляющих routes или перевести опасные команды на POST с явным контрактом.
- `W7.10 toasts`: заменить блокирующие `alert()` на неблокирующие сообщения там, где это влияет на poll/alarm.

Проверка: Playwright desktop/mobile, smoke routes, static grep CDN/offline guard, build filesystem assets if gzip changes.

Параллельность: `W7.1-W7.2` отдельная chart-ветка. `W7.4` зависит от backend contract. `W7.7-W7.8` можно делать после app.js.

### Wave 8. Remaining firmware cleanup and low-severity fixes

Цель: закрыть все остаточные пункты аудита и снизить будущий шум.

Пакеты:

- `W8.1 quality.h decision`: удалить мёртвый quality module или довести до осознанного использования; если удалить, убрать include/commented block.
- `W8.2 RMVK cleanup`: `RMVK_cmd` возвращает ошибку/last valid вместо `conn`, удалить `rmvkFn`, решить вопрос кириллических `АТ` с явным комментарием или ASCII на обеих сторонах.
- `W8.3 pump PWM nonblocking`: убрать `delay(1000)` из SysTicker path, обновлять PID setpoint при сохранении настроек/старте.
- `W8.4 impurity detector heat loss`: deltaT guard, reset heat-loss state при новой сессии.
- `W8.5 NBK small fixes`: overheat static reset, `NBK_OPERATING_RANGE / 100.0f`, пустая программа -> явная авария, `nbk_work_next_time` init, finish stats guard, сравнение WType без heap churn.
- `W8.6 beer small fixes`: `WFpulseCount` под mux, fractional mash pause.
- `W8.7 dist/BK small fixes`: simultaneous water/ACP messages, PWR_FACTOR reduction via common helper.
- `W8.8 FS/editor hygiene`: `/pong.htm`, `SPIFFSEditor download arg`, FS editor creds/auth decision.
- `W8.9 Lua scripts`: `beer.lua` статус после формирования, `rectificat.lua` nil/global issues.
- `W8.10 build warnings`: включить/подготовить `-Wall -Wextra` там, где это не ломает vendored libraries; зафиксировать suppressions отдельно.

Проверка: сборка, cppcheck, grep по каждому удалённому smell, Lua/script smoke where possible.

Параллельность: эти пакеты можно распределять по непересекающимся файлам после Waves 1-4.

## 1.1. Статус выполнения

- `W0.1-W0.8 quick fixes`: закрыты по фактической сверке; все `data/*.htm` имеют doctype/viewport, опасные UI-команды подтверждаются `confirm()`, `/ajax` читает I2CStepper cache без блокирующего I2C, empty string в NVS не считается ошибкой, Blynk token принимает 32 символа через safe copy, distiller/BK finish paths не проваливаются дальше, partition/include hygiene синхронизированы, naive millis deadline comparisons заменены overflow-safe формой.
- `W0.9 small UB fixes`: закрыт; `set_capacity()` проверяет bounds, DS address sentinels сравниваются как `(uint8_t)==0xFF`, stepper calibration/zero paths клампят или ошибкуют, task-context critical sections не используют `portENTER_CRITICAL_ISR`, duplicate `temprature_sens_read` отсутствует, Lua `setCapacity()` валидирует `0..CAPACITY_NUM` до `uint8_t` narrowing и возвращает Lua error на неверный номер ёмкости; `tools/smoke_lua_serialization.py` закрепляет этот контракт.
- `W8.6 beer small fixes`: закрыт; `WFpulseCount` защищён `waterPulseMux` в ISR и task-side `set/get/take`, `triggerSysTicker()` забирает импульсы через `water_pulse_count_take()`, дробная пауза/кипячение в beer считаются через `60000.0f`, а `tools/smoke_beer_small_fixes.py` закрепляет firmware-контракт; ранее закрытый BrewXML/UI-срез сохранён, полный smoke suite, сборки двух env и reviewer-loop clean.
- `W5.7 samovar_api.h`: закрыт; общая поверхность forward declarations вынесена из локальных стен прототипов, сборки двух env и reviewer-loop clean.
- `W5.5 FreeRTOS command queue`: закрыт; `sam_command_sync` заменён статической FreeRTOS-очередью `SamovarCommandMsg`, reset semantics сохранены через `xQueueSendToFront`, сборки двух env, API smoke и reviewer-loop clean.
- `W5.6 mode registry`: закрыт полностью срезами `page`, `alarm`, `process-loop`, `start-command`, `finish`, `status`; каждый срез прошёл `pio run -e Samovar`, `pio run -e Samovar_s3`, `python3 tools/smoke_api_routes.py`, `git diff --check` и отдельный reviewer-loop до clean.
- `W1.1 emergency stop path`: закрыт; аварии прекращения подачи воды в rect/distiller/BK/NBK идут через `request_emergency_stop()`, `request_emergency_stop()` больше не вызывает `SendMsg()` из SysTicker-path, причина аварии буферизуется и отправляется из `perform_emergency_stop()` в `loop()`; сборки двух env, API smoke, whitespace/JSON checks и reviewer-loop clean.
- `W1.2 heating sensor validity`: закрыт; общий `sensor_valid(...)` теперь считает `avgTemp < 2.0f` недостоверным, старты beer/distiller/BK/NBK валидируют управляющие датчики до включения нагрева, alarm-guards проверяют обязательные/опциональные DS18B20 до температурной логики, beer alarm path не вызывает `beer_finish()` из SysTicker; сборки двух env, heating/API/I2C smoke, py_compile, whitespace checks и reviewer-loop clean.
- `W1.3 NBK critical alarms`: закрыт; `check_nbk_critical_alarms()` больше не меняет `nbk_M/nbk_P` и не содержит stop/action-вызовов, критика только ставит `request_emergency_stop()`, а `nbk_emergency_finish()` выполняет NBK-specific cleanup из `perform_emergency_stop()` в loop-контексте до generic stepper stop; сборки двух env, NBK/heating/API/I2C smoke, py_compile, whitespace checks и reviewer-loop clean.
- `W1.4 BK ACP protection`: закрыт; текущий `check_alarm_bk()` сохраняет optional TCA semantics, открывает охлаждение по `MAX_ACP_TEMP - 5`, аварийно останавливает через `request_emergency_stop()` по `MAX_ACP_TEMP` с явной причиной `ТСА`, а `tools/smoke_heating_sensor_validity.py` закрепляет этот контракт; сборки двух env, heating/NBK/API/I2C smoke, py_compile, whitespace checks и reviewer-loop clean.
- `W1.5 program apply guard`: закрыт; `/program` и `/save` с `WProgram` возвращают явный `409 text/plain`, если активна program-owning сессия, pending-program consumer в `loop()` повторно проверяет `program_update_session_active()` перед `set_*_program`, а `tools/smoke_api_routes.py` закрепляет порядок 503-before-409 и запрет применения программы из active-reject ветки; сборки двух env, API/heating/NBK/I2C smoke, py_compile, whitespace checks и reviewer-loop clean.
- `W1.6 OneWire scan gate`: закрыт; `/command?rescands` при активном процессе возвращает `409 BUSY`, иначе только ставит `pending_rescan_ds_flag`, `scan_ds_adress()` не вызывается из async/menu/loop, runtime-скан сериализован внутри `triggerSysTicker()` рядом с `DS_getvalue()`, а `tools/smoke_api_routes.py` закрепляет структуру веток brace-aware проверками; сборки двух env, API/heating/NBK/I2C smoke, py_compile, whitespace checks и reviewer-loop clean.
- `W1.7 pressure alarm guard`: закрыт; pressure alarm в `triggerSysTicker()` стал one-shot через локальный `pressure_alarm_sent` без зависимости от глобального `alarm_event`, сброс происходит только через гистерезис, тяжёлая аварийная работа остаётся в pending emergency path, а `tools/smoke_pressure_alarm_guard.py` закрепляет порядок threshold/guard/request/hysteresis; сборки двух env, pressure/API/heating/NBK/I2C smoke, py_compile, whitespace checks и reviewer-loop clean.
- `W2.1 resetwifi/reboot/reset`: закрыт; `/command?reset` идёт через `SamovarCommandMsg` queue, `/command?reboot` и `/command?resetwifi` ставят pending-флаги под `pending_command_lock`, а `ESP.restart()`/`menu_reset_wifi()` выполняются из `loop()` после ответа клиенту; сборки двух env, API smoke, whitespace/JSON checks и reviewer-loop clean.
- `W2.4 pending self-test stop/log flush`: закрыт; `/command?stopst` только ставит pending-флаг, consume идёт под `pending_command_lock`, `stop_self_test()` выполняется после unlock, `fileToAppend.flush()` находится в `flush_data_log()` под `log_file_lock`; сборки двух env, API smoke, whitespace/JSON checks и reviewer-loop clean.
- `W2.7 upload/body debug`: закрыт без нового кода; все `Serial.write(data, len)` в catch-all upload/body находятся под `#ifdef __SAMOVAR_DEBUG`, `SPIFFSEditor::handleUpload()` не дампит body в Serial; подтверждено reviewer-loop clean.
- `W2.2/W2.3/W2.6 command pipeline`: закрыт; `voltage/mixer/watert/pumpspeed/nbkopt/pnbk` проходят через pending-флаги и исполняются в `loop()`, `/command` возвращает только `OK/BUSY/IGNORED/POWER_OFF/BAD_REQUEST`, throttling ключуется по распознанной команде, `tools/smoke_api_routes.py` закрепляет static contract; сборки двух env, API smoke, whitespace/JSON checks и reviewer-loop clean.
- `W2.5 pending Lua file/reload`: закрыт; `/lua?script=...` и `/command?lua=...` только ставят `pending_lua_file_flag`, `/lua` без `script` ставит `pending_lua_start_flag`, upload `.lua` только планирует reload или возвращает `503 BUSY`, а `load_lua_script()`/`start_lua_script()`/`run_lua_script()` выполняются из `loop()` после unlock; сборки двух env, API smoke/py_compile, whitespace/JSON checks и reviewer-loop clean.
- `W2.8 I2CStepper atomic refresh/apply`: закрыт; `i2c_config_in_flight` защищает staged config от SysTicker refresh, `read_u16/read_u32` читают регистры через один block `Wire.requestFrom` без per-byte fallback, `/i2cstepper` остаётся staged/pending; сборки двух env, API/I2C smoke, py_compile, whitespace/JSON checks и reviewer-loop clean.
- `W3.1-W3.2 Lua serialization/button off SysTicker`: закрыт; Lua VM выполняется только из `DoLuaScriptTask`, `triggerSysTicker()` больше не планирует Lua, `/lua`/`luastr`/file/button work ставятся в one-shot Lua job slot, pending start/file/string flags очищаются только после успешной постановки, Blynk V22 сообщает `Lua queued`, а `tools/smoke_lua_serialization.py` закрепляет отсутствие direct Lua execution и silent-loss paths; сборки двух env, Lua/API/pressure/heating/NBK/I2C smoke, py_compile, whitespace checks и reviewer-loop clean.
- `W3.3 shared String locking`: закрыт; `SessionDescription`, `Lua_status`, `Msg`/`LogMsg`/`msg_level`, `program_Wait_Type` и `pending_program_str` закреплены helper/lock-контрактами, `copy_mqtt_session_description()` больше не мутирует глобальное описание при sanitation, а `tools/smoke_shared_state_strings.py` запрещает прямые shared-String обращения и проверяет pending-program mailbox; сборки двух env, shared-state/Lua/API/heating/NBK/I2C/pressure smoke, py_compile, whitespace checks и reviewer-loop clean.
- `W3.4 program WType`: закрыт; bounded helper `program_type_at(index)`/`current_program_type()` живёт в `runtime_helpers.h` рядом с runtime locks, возвращает `PROGRAM_TYPE_NONE` за пределами `PROGRAM_MAX`, а `triggerSysTicker()`, `send_ajax_json()`, `withdrawal()`, `process_impurity_detector()`, status/alarm helpers в `logic.h`, `check_alarm_beer()`, `SetSpeed()` и NBK critical alarm path используют локальные ProgramType snapshots; `tools/smoke_program_type_contract.py` закрепляет запрет прямого `program[ProgramNum].WType` в этих hot paths; program-type/program-limit/shared-state/API/heating/NBK smoke прошли.
- `W3.5 MQTT buffers`: закрыт; `SamovarMqtt.h` владеет `mqttClient` через отдельный static mutex и wrappers `connectToMqtt()`/`disconnectFromMqtt()`/`mqttConnected()`, `MqttSendMsg()` использует локальные `topic`/`payload` buffers, не вызывает `SendMsg()` из MQTT error path и сериализует publish/retry под `mqtt_lock`, а `Samovar.ino` инициализирует MQTT mutex до `initMqtt()` и больше не обращается к `mqttClient.*` напрямую; `tools/smoke_mqtt_buffers.py` закрепляет этот контракт, обычные сборки двух env и временные сборки двух env с `-DUSE_MQTT` прошли.
- `W3.6 fileToAppend ownership`: закрыт; `FS.ino` остаётся владельцем `static File fileToAppend`, `create_data()` больше не вызывает `append_data()` напрямую и сбрасывает log-state, внешние режимы ставят закрытие через `request_data_log_close()`, а `process_pending_data_log_ops()` в SysTicker выполняет pending close/flush с приоритетом close и не снимает pending-флаги до успешной операции; `WebServer.ino` отдаёт log endpoints только при `LOG_FLUSH_READY`, а при queued/busy flush возвращает `503 BUSY`; `tools/smoke_data_log_ownership.py` закрепляет отсутствие прямого `fileToAppend`, `append_data()`, `flush_data_log()` и `close_data_log()` вне разрешённых владельцев.
- `W3.7 program limits`: закрыт; `program_types.h` остаётся единственным источником `ProgramType`, `PROGRAM_MAX`, `PROGRAM_END`, `NBK_PROGRAM_MAX` и static_assert-контрактов, `Samovar.h` держит `WProgram program[PROGRAM_MAX]`, а `tools/smoke_program_limits.py` запрещает возврат `program[30]`, program-loop `< 30`, `CAPACITY_NUM*2` вне `program_types.h` и `run_program(CAPACITY_NUM*2)`; сборки двух env, program-limit/shared-state/Lua/API smoke, py_compile и whitespace checks clean.
- `W4.1 handleSave staging`: закрыт; `handleSave()` создаёт `PendingSetupSave`, парсит и валидирует поля в `setupSave.staged` через safe parse/apply helpers, invalid input возвращает `400 text/plain`, busy pending-slot возвращает `503 text/plain`, успешный `/save` сохраняет `301 Location: /`, `setupKeyProcessor()` больше не нормализует `SamSetup.*` при NaN из async template context, а `loop()` применяет staged `SamSetup` до pending mode switch и pending program apply; контракт закреплён `tools/smoke_handle_save_staging.py`.
- `W4.2 sensor fields staging`: закрыт; DS18B20 registry (`DSAddr`/`DScnt`) обновляется через локальный scan и короткий commit под `dsAddressMux`, web/template paths используют `DSAddressSnapshot` и сохранённые `SamSetup.*Adress`, `/save` валидирует DS index по одному snapshot и инвалидирует все 8 байт при `NONE`, runtime `DSSensor.Sensor`/readings применяются только из loop-side `apply_setup_sensor_fields()`, а `tools/smoke_sensor_fields_staging.py` закрепляет запрет live `DScnt`/`DSAddr` в `WebServer.ino`.
- `W4.3 durable NVS compaction`: закрыт; pending compaction backup восстанавливается явным startup gate `recover_pending_nvs_compaction()` в `setup()` до `migrate_from_eeprom()` и `read_config()`, ошибка восстановления печатает `FATAL` и останавливает boot без fallback, поздний one-shot recovery из `load_profile_nvs()` удалён, а `tools/smoke_nvs_compaction_durable.py` закрепляет порядок backup/erase/restore и startup recovery.
- `W4.4 get_web_file writes`: закрыт; web UI downloads больше не пишутся прямо в целевой файл, `write_web_file_atomic()` пишет во временный файл, проверяет фактическую длину через reopen/size, заменяет через backup+rename и делает rollback при провале, `get_web_file()` возвращает `<ERR>` на пустой body/ошибку записи, а `/version.txt` обновляется только после полного `updateOk`; контракт закреплён `tools/smoke_web_file_writes.py`.
- `W4.5 crash handler cleanup`: закрыт; ложный shutdown crash handler, неиспользуемый stacktrace buffer и `verbose_print_reset_reason` удалены из runtime/codebase-map, публичные crash-handler API сохранены, stale references в `samovar-ino.md`/crash nodes убраны, reviewer-loop clean.
- `W5.1 mode_common.h alarms`: закрыт; общие inline helpers вынесены в `mode_common.h`, rectification/distiller/BK/NBK используют общие predicates/actions для water/TCA guards, valve close/open, water-flow emergency, `alarm_t_min` pause и NBK overflow-safe deadlines; `mode_deadline_expired()` сохраняет wrap-safe NBK semantics, `alarm_t_min` sentinel остаётся в clear helper, rectification ACP close hysteresis сохранён по `ACPSensor.avgTemp`; `tools/smoke_mode_common_alarms.py` закрепляет helper usage и запрещает heavy stop/delay/finish calls в helper/alarm paths; codebase-map `mode-common-h` metadata добавлена в `INDEX.md`, `rules.yaml`, `graph.json`, `state.json`; сборки двух env, полный smoke suite, py_compile, diff-check и reviewer-loop clean.
- `W5.2 mode_common.h heating start`: закрыт; общий `mode_start_heating_session()` в `mode_common.h` централизует `create_data()`/MQTT-description copy/`set_power(true)`/power-mode setup/start-message для distiller/BK, блокирует старт при `alarm_event` до логов/MQTT/нагрева, повторно проверяет `alarm_event`/status/`PowerOn` после power-on и power-mode setup, а при post-power гонке выключает нагрев через `set_power(false, false)` без перехвата emergency reset ownership; `distiller_proc()` и `bk_proc()` оставляют только mode-specific post-start side effects, `tools/smoke_heating_sensor_validity.py` и `tools/smoke_mode_common_alarms.py` закрепляют safe order; сборки двух env, полный smoke suite, py_compile, diff-check и reviewer-loop clean.
- `W5.3 program parser/serializer common`: закрыт; общий inline parser/serializer вынесен в `program_io.h`, `logic.h`/`distiller.h`/`beer.h`/`nbk.h` оставляют тонкие wrappers, legacy text formats сохранены включая integer `Time` в beer serializer и NBK H/S/O/W semantics, а `tools/smoke_program_io_contract.py` закрепляет skeleton, wrappers и beer regression; codebase-map `program-io-h` и `program-types-h` согласованы в `INDEX.md`, `rules.yaml`, `graph.json`, `state.json`; сборки двух env, полный smoke suite, py_compile, diff-check и reviewer-loop clean.
- `W5.4 pump PID common`: закрыт; `mode_common.h` получил `mode_update_water_pump_pid()`, `mode_reduce_power_for_water_alarm_by_volts()` и `mode_update_water_valve_by_setpoint()`, rectification/distiller/NBK используют общий water-pump PID с mode-specific ACP thresholds, distiller/BK используют общий `PWR_FACTOR` reduction helper, NBK оставлен warning-only, а `tools/smoke_mode_common_alarms.py` запрещает возврат raw PID/valve/reduction копий; сборки двух env, полный smoke suite, py_compile, diff-check и reviewer-loop clean.
- `W5.8 logic.h split`: закрыт; alarm/emergency/sensor helpers вынесены в `alarm.h`, valve/buzzer helpers в `valve_buzzer.h`, heating power/regulator helpers в `power_regulator.h`, self-test helpers в `selftest.h`, а `logic.h` оставляет прежний внешний include surface и ожидаемый порядок `impurity_detector.h -> alarm.h -> valve_buzzer.h -> power_regulator.h -> selftest.h`; `tools/smoke_logic_split.py` закрепляет отсутствие дубликатов в `logic.h`, новые smoke checks читают moved helpers из `alarm.h`, codebase-map `alarm-h`/`valve-buzzer-h`/`power-regulator-h`/`selftest-h` согласована в `INDEX.md`, `rules.yaml`, `graph.json`, `state.json`; полный smoke suite, py_compile, diff-check, сборки двух env и reviewer-loop clean.
- `W6.1-W6.5 Web UI foundations`: закрыты; `data/app.js` стал единым владельцем connection/audio/messages/history/theme/tabs/command transport, пять mode-страниц подключают его и больше не держат старые common-функции, `tools/smoke_ui_foundations.py` закрепляет static contract, Playwright smoke по mock HTTP прошёл по `index/beer/distiller/nbk/bk`, `buildfs` и сборки двух env прошли. Служебный codebase-map не обновлялся в этом срезе из-за явной команды пользователя не менять связанные служебные файлы.
- `W6.6-W6.10 Web UI foundations`: закрыты; action-кнопки переведены на `type="button"`, мёртвые mode UI hooks удалены, инлайн-цвета режимных страниц переведены на CSS-переменные, `nbk.htm getProgram()` корректно принимает пустую программу и валидирует размер до записи в UI, `i2cstepper.htm` получил adaptive polling и in-flight action locks; `tools/smoke_ui_foundations.py` закрепляет эти контракты, Playwright desktop/mobile smoke, `buildfs`, сборки двух env и reviewer-loop clean.
- `W7.1-W7.2 chart offline/incremental`: закрыты; CDN/amCharts удалены, локальный `data/chart.js` строит canvas-график офлайн, старт polling не зависит от chart lib, полный `data.csv` читается только при начальной загрузке, дальнейшие точки добавляются из `/ajax` с throttling/decimation; `tools/smoke_chart_ui.py`, Playwright canvas/network checks, `buildfs`, сборки двух env и reviewer-loop clean.
- `W7.3 /ajax ProgramNum/status code`: закрыт; `/ajax` отдаёт числовые `ProgramNum` и `ProgramIndex`, `data/index.htm` больше не парсит номер программы из локализованного `Status`, а `tools/smoke_api_routes.py` закрепляет порядок и запрет старого `Прг №` parsing; полный smoke suite, Playwright mock `/ajax`, сборки двух env и reviewer-loop clean.
- `W7.4 /program JSON contract`: закрыт; `/program` отвечает `application/json` контрактом `{ok, err, program}`, busy/error ветки возвращают JSON 503/409, `/save` сохраняет старый text/plain/redirect contract, все UI-клиенты используют `SamovarApp.postProgram`, валидируют типы `ok/err/program` и не перезаписывают textarea старой `program` из ответа; `tools/smoke_api_routes.py` запрещает старый `text/"OK"` protocol и новый `result.program` regression, Playwright success/busy/invalid-contract checks, полный smoke suite, `buildfs` двух env и reviewer-loop clean.
- `W7.5 index/program UX`: закрыт; `program.htm` больше не перетирает изменённую программу шаблоном без confirm, cancel возвращает выбор шаблона и не меняет программу/параметры, ошибки загрузки шаблона и `/ajax_col_params` видны оператору, локальный stale `sendbutton()` удалён, а `tools/smoke_program_ux.py` закрепляет baseline/dirty/error-flow; Playwright initial/cancel/accept/HTTP-error checks, полный smoke suite, `buildfs` двух env и reviewer-loop clean.
- `W7.6 calibration UX`: закрыт; `calibrate.htm` хранит фазу калибровки в `calibrationRunning`, не читает её из текста кнопки, меняет label только после успешного HTTP-ответа `/calibrate`, сохраняет состояние при `503`/сетевой ошибке и обновляет `stepperstepml` только после успешного numeric finish response; `tools/smoke_calibration_ux.py`, Playwright rendered-template start/finish error checks, полный smoke suite, `buildfs` двух env и reviewer-loop clean.
- `W7.7 style.css cleanup`: закрыт; `.prgline` selectors больше не захватывают глобальные `img/select`, `.message-box` алиаснут к `.messages_box` включая mobile override, подтверждённо неиспользуемые CSS utility selectors удалены, `--state-active-bg` заменён на контрастный `#2f7d4a`, `style.css.gz` синхронизирован; `tools/smoke_style_cleanup.py`, Playwright computed-style/contrast checks, полный smoke suite, `buildfs` двух env и reviewer-loop clean.
- `W7.8 HTML cleanup`: закрыт; `brewxml.htm` использует HTML `class` вместо `className`, скрытый `WProgram` больше не занимает место и остаётся в `FormData`, unitless inline-CSS исправлен в `brewxml/index/program`, дефолтный `#FFF;` заменён на валидный цвет, `z/q` в изменённых функциях `index.htm` не текут в `window`; `tools/smoke_html_cleanup.py`, Playwright DOM checks, полный smoke suite, `buildfs` двух env и reviewer-loop clean.
- `W7.9 CORS/command method`: закрыт; глобальный wildcard CORS удалён, `/command` стал POST-only без GET fallback, command params читаются только из POST body через `getParam(name, true)`, `SamovarApp.sendCommand()` и `setup.htm` переведены на form-urlencoded POST с сохранением token-контракта; `tools/smoke_api_routes.py`/`tools/smoke_ui_foundations.py`, Playwright POST transport checks, полный smoke suite, `buildfs` и сборки двух env, reviewer-loop clean.
- `W7.10 toasts`: закрыт; блокирующие `alert()` удалены из пяти polling/alarm страниц `index/beer/distiller/bk/nbk`, ошибки и результаты идут через общий `SamovarApp.notify()`/`pushMessage()` в `#messages`, `confirm()` для опасных действий сохранён; `tools/smoke_ui_foundations.py`, Playwright invalid-input checks, полный smoke suite, `buildfs` двух env и reviewer-loop clean.
- `W8.1 quality.h decision`: закрыт; мёртвый `quality.h` удалён, runtime и актуальные docs больше не содержат `QualityParams/getQualityAssessment/quality__h`, `mkdocs.yml` и `.ai-docs` очищены, `ai_docs_site` пересобран через `python3 -m mkdocs build --strict --clean`, `tools/smoke_quality_cleanup.py` закрепляет отсутствие stale-ссылок; полный smoke suite, сборки двух env и reviewer-loop clean.
- `W8.2 RMVK cleanup`: закрыт; `RMVK_cmd()` возвращает `RMVK_ERROR` на timeout/invalid/busy, typed getters сохраняют last-valid значения до валидного ответа, `OFF` для `RMVK_ON` остаётся валидным `0`, dead `rmvkFn` удалён, а SEM_AVR/Samovar power-команды используют явный legacy UTF-8 A/T prefix helper вместо визуально-неотличимых кириллических строк; `tools/smoke_rmvk_contract.py`, полный smoke suite, сборки двух env и reviewer-loop clean.
- `W8.3 pump PWM nonblocking`: закрыт контрактным срезом; `set_pump_pwm()`/`set_pump_speed_pid()` не блокируют `delay/vTaskDelay`, `set_pump_speed_pid()` и `init_pump_pwm()` синхронизируют PID setpoint с `SamSetup.SetWaterTemp`, а staged `/save` применяет новый setpoint через `loop() -> read_config() -> apply_config_runtime()`; `tools/smoke_pump_pwm_nonblocking.py`, полный smoke suite, сборки двух env и reviewer-loop clean.
- `W8.4 impurity detector heat loss`: закрыт; расчёт теплопотерь имеет `deltaT >= 15°C` guard до `CurrentHeatLoss`, `reset_heat_loss_calculation()` чистит всё состояние, start helper сбрасывает heat-loss по `resetHeatLoss`, а ректификационный `set_power(true)` дополнительно сбрасывает состояние при переходе из выключенного нагрева до `PowerOn = true`; `tools/smoke_impurity_heat_loss.py`, полный smoke suite, сборки двух env и reviewer-loop clean.
- `W8.5 NBK small fixes`: закрыт; таймер перегрева НБК вынесен в состояние режима и сбрасывается при старте/финише, пустая или битая стартовая строка НБК ставит `request_emergency_stop()` вместо штатного `nbk_finish()`, итоговая статистика не отправляется без реальной `stats.startTime`, а `NBK_OPERATING_RANGE / 100.0f`, deadline при входе в `W` и compact `ProgramType` закреплены `tools/smoke_nbk_small_fixes.py`; полный smoke suite, `py_compile`, `git diff --check`, сборки двух env и reviewer-loop clean.
- `W8.6 beer small fixes`: закрыт; добавлен `tools/smoke_beer_small_fixes.py`, который закрепляет `WFpulseCount` под `waterPulseMux` в ISR/task context, `water_pulse_count_take()` в SysTicker и дробный таймер beer `P/B` через `/ 60000.0f`; полный smoke suite, `py_compile`, `git diff --check`, сборки двух env и reviewer-loop clean.
- `W8.7 dist/BK small fixes`: закрыт; аварийные сообщения distiller/BK при одновременном перегреве воды и ТСА теперь накапливают оба признака независимыми `if`, снижение мощности остаётся через общий `mode_reduce_power_for_water_alarm_by_volts()` без raw `target_power_volt - 5`/`PWR_FACTOR` копий, а `tools/smoke_dist_bk_small_fixes.py` закрепляет контракт; полный smoke suite, `py_compile`, `git diff --check`, сборки двух env и reviewer-loop clean.
- `W8.8 FS/editor hygiene`: закрыт; `/pong.htm` отдаёт HTML-страницу с audio `/alarm.mp3`, `SPIFFSEditor` download-ветка читает `request->arg("download")`, мёртвые editor credentials удалены, а решение оставить `/edit` unauthenticated для DIY явно зафиксировано без auth shim/fallback; `tools/smoke_fs_editor_hygiene.py`, полный smoke suite, `py_compile`, `git diff --check`, сборки двух env и reviewer-loop clean.
- `W8.9 Lua scripts`: закрыт; `beer.lua` публикует `setLuaStatus(status)` только после формирования `status`, `rectificat.lua` читает `WFflowRate` строковым ключом, реально интегрирует расход по времени с сохранением `last_reading_*`/`total_volume`, валидирует `target_volume`/`flow_factor` как `> 0`, а `tools/smoke_lua_scripts.py` закрепляет эти контракты; полный smoke suite, `buildfs`, `py_compile`, `git diff --check`, сборки двух env и reviewer-loop clean.
- `W8.10 build warnings`: закрыт; `-Wall`/`-Wextra` закреплены в `build_src_flags` для проектных исходников без включения на vendored dependencies, warning-suppression через `-Wno-*` запрещён без отдельной документации, а `tools/smoke_build_warnings.py` закрепляет этот контракт; полный smoke suite, `py_compile`, `git diff --check`, сборки двух env и reviewer-loop clean.
- `Final reviewer-loop`: закрыт; финальный read-only reviewer нашёл два блокера (`program_parse_rect_row()` считал `P`-строку по очищенному `program[rowIndex].WType`, а custom `bk_pwm` в БК мог остаться на стартовом PWM), оба исправлены и закреплены `tools/smoke_program_io_contract.py`/`tools/smoke_pump_pwm_nonblocking.py`; повторный reviewer-loop вернул `STRICT CLEAN`, полный smoke suite, `py_compile`, `git diff --check`, служебный grep, `buildfs`, сборки `Samovar`/`Samovar_s3` и build warning/error grep чистые.

## 2. Сабагентная схема

Планирование:

- `architect firmware safety`: `W1`, зависимости от `W2/W3`.
- `cpp-dev async runtime`: `W2`, `W3`, `W4`.
- `reviewer UI`: `W6`, `W7`, обязательный Playwright plan.
- `tester`: тестовая матрица для всех волн, включая отсутствие hardware и границы статических проверок.
- `architect structural`: `W5`, порядок миграции command queue/mode registry.

Разработка:

- Firmware workers получают disjoint ownership: режимы (`distiller.h/BK.h/beer.h/nbk.h`), web backend (`WebServer.ino/Samovar.ino/logic.h/I2CStepper.h`), persistence (`NVS_Manager.ino/WebServer.ino/string_utils.h`), Lua (`lua.h/Samovar.ino/Blynk.ino/data/*.lua`), UI (`data/*.htm/style.css/app.js`).
- Worker должен писать изменения в своём scope, не откатывать чужие изменения, в финале перечислить изменённые файлы и проверки.

Ревью:

- После каждого пакета reviewer-сабагент получает diff только этого пакета.
- Критерий перехода дальше: нет CRITICAL/WARNING по пакету. Nitpick допускается только если он не относится к найденным в AUDIT проблемам; иначе исправляется.
- Финальный `/goal`-цикл: полный diff ветки -> reviewer; если есть ошибки или предупреждения, исправить и повторить до чистого результата.

## 3. Общие проверки

Минимальный gate после каждого firmware-пакета:

```bash
pio run -e Samovar
pio run -e Samovar_s3
python tools/smoke_api_routes.py
```

Дополнительный gate для web-пакетов:

```bash
pio run -t buildfs
```

И обязательный browser-gate через skill `playwright-cli` для изменений в `data/`.

Статические grep-checks:

- async direct calls in `WebServer.ino`: `set_current_power`, `set_mixer`, `menu_reset_wifi`, `run_lua_script`, `load_lua_script`, `fileToAppend.flush`.
- unsafe millis: `<= millis()`, `> now`, `< now +`.
- UI false success: `alert("Установлено.")`, `response !== "OK"` contracts, submit buttons.
- duplicated dead UI: `I2CPump`, `showHystory`, `PipeTemp.toFixed(3)`.
- Lua direct execution: `lua.Lua_dostring`.

## 4. Codebase map updates

После изменения зоны обновить `Last reviewed` в соответствующем node:

- firmware core: `samovar-ino.md`, `logic-h.md`, `runtime-helpers-h.md`, `sensorinit-h.md`, `samovar-h.md`;
- modes: `distiller-h.md`, `bk-h.md`, `beer-h.md`, `nbk-h.md`, `impurity-detector-h.md`, `pumppwm-h.md`;
- web/backend: `webserver-ino.md`, `nvs-manager-ino.md`, `fs-ino.md`, `spiffseditor-h.md`, `lua-h.md`, `i2cstepper-h.md`;
- UI assets: `data.md`;
- build/config: `platformio-ini.md`, `partitions.md`, `partitions-csv.md`.

Если обновление node ломает карту, выполнить targeted repair для конкретного node.
