# ТЗ: structural refactor Samovar без изменения логики

Дата: 2026-03-09

Аудитория: разработчик уровня low-middle.

Цель документа: дать исполнимый план большого structural cutover без shim, без временных слоев совместимости и без изменения пользовательского поведения.

## 1. Цель работ

Нужно разрезать текущую legacy-структуру проекта на понятные модули по владельцам ответственности.

Нужно сохранить 1:1:
- алгоритмы режимов;
- статус-коды и их смысл;
- форматы строк программ;
- HTTP endpoints и JSON keys;
- Lua API и имена Lua-переменных;
- NVS namespaces и keys;
- порядок side effects при переключении режима, запуске, паузе, finish и авариях.

## 2. Что запрещено

- Нельзя вводить `ModeBase`, `AppContext`, `ServiceLocator`, `Facade`, bridge/adapters, runtime wrappers.
- Нельзя держать старый и новый код параллельно дольше одного коммита.
- Нельзя переносить код в новый модуль, оставляя старую копию "на всякий случай".
- Нельзя менять сигнатуры существующих функций в первой волне, если это не требуется сборкой.
- Нельзя менять контракты `/ajax`, `/command`, `/program`, `/save`, `/calibrate`, `/i2cpump`.
- Нельзя менять Lua surface.
- Нельзя исправлять спорное поведение "по дороге".
- Нельзя использовать fallback без отдельного согласования.

## 3. Обязательные инварианты

- `program[30]` остается в текущем формате.
- `SamovarStatusInt`, `startval`, `Samovar_Mode`, `Samovar_CR_Mode` сохраняют текущую семантику.
- `get_Samovar_Status()` сохраняет побочный эффект изменения `SamovarStatusInt`.
- `send_ajax_json()` сохраняет очистку `Msg` и `LogMsg` после отправки.
- `handleSave()` сохраняет текущий порядок смены режима и обновления связанных подсистем.
- `change_samovar_mode()` сохраняет синхронизацию `Samovar_CR_Mode`.
- `get_global_variables()` сохраняет текущее фактическое поведение.

## 4. Целевая структура модулей

- `state/`: типы конфигурации, runtime types, globals.
- `support/`: безопасный парсинг, математика процесса, форматирование.
- `app/`: startup, loop dispatch, process common, status text, messages, runtime tasks.
- `io/`: sensors, power control, actuators, pressure, sensor scan.
- `modes/rect/`
- `modes/dist/`
- `modes/beer/`
- `modes/bk/`
- `modes/nbk/`
- `storage/`: NVS, FS, web asset sync.
- `ui/web/`: server init, routes, template keys, ajax snapshot.
- `ui/lua/`: runtime и bindings.
- `ui/menu/`: strings, screens, actions, input.

## 5. Ownership-карта по исходным файлам

- `Samovar.h` -> `state/config_types.h`, `state/runtime_types.h`, `state/globals.h`, `support/safe_parse.h`.
- `Samovar.ino` -> `app/startup.h`, `app/loop_dispatch.h`, `app/runtime_tasks.h`, `app/config_apply.h`, `app/messages.h`, `ui/web/ajax_snapshot.h`.
- `logic.h` -> `support/process_math.h`, `app/alarm_control.h`, `app/process_common.h`, `io/power_control.h`, `io/actuators.h`, `app/status_text.h`, `modes/beer/beer_support.h`, `modes/rect/rect_program_codec.h`, `modes/rect/rect_runtime.h`.
- `distiller.h` -> `modes/dist/dist_runtime.h`, `modes/dist/dist_program_codec.h`, `modes/dist/dist_alarm.h`, `modes/dist/dist_time_predictor.h`.
- `beer.h` -> `modes/beer/beer_runtime.h`, `modes/beer/beer_program_codec.h`, `modes/beer/beer_alarm.h`, `modes/beer/beer_heater.h`, `modes/beer/beer_mixer.h`, `modes/beer/beer_autotune.h`.
- `BK.h` -> `modes/bk/bk_runtime.h`, `modes/bk/bk_alarm.h`, `modes/bk/bk_finish.h`.
- `nbk.h` -> `modes/nbk/nbk_runtime.h`, `modes/nbk/nbk_program_codec.h`, `modes/nbk/nbk_alarm.h`, `modes/nbk/nbk_math.h`.
- `WebServer.ino` -> `ui/web/server_init.h`, `ui/web/page_assets.h`, `ui/web/template_keys.h`, `ui/web/routes_setup.h`, `ui/web/routes_command.h`, `ui/web/routes_program.h`, `ui/web/routes_service.h`, `storage/web_assets_sync.h`.
- `lua.h` -> `ui/lua/runtime.h`, `ui/lua/bindings_gpio.h`, `ui/lua/bindings_process.h`, `ui/lua/bindings_variables.h`, `ui/lua/bindings_io.h`, `ui/lua/bindings_http.h`.
- `FS.ino` -> `storage/fs_init.h`, `storage/session_logs.h`, `storage/profile_files.h`.
- `NVS_Manager.ino` -> `storage/nvs_profiles.h`, `storage/nvs_wifi.h`, `storage/nvs_migration.h`.
- `Menu.ino` -> `ui/menu/strings.h`, `ui/menu/screens.h`, `ui/menu/actions.h`, `ui/menu/input.h`.
- `sensorinit.h` -> `io/sensors.h`, `io/pressure.h`, `io/sensor_scan.h`, `app/default_programs.h`, `support/format_utils.h`.
- `data/*.htm` -> общие frontend assets только после стабилизации backend.

## 6. Правила выполнения атомарной задачи

Каждая задача считается завершенной только если:
- код собирается;
- старая копия перенесенной функции удалена;
- нет временного дубля;
- callsite обновлен;
- поведение не изменено;
- в diff нет unrelated изменений.

Если для выполнения задачи требуется shim, задача остановлена и должна быть переразбита.

## 7. Фазовый backlog

### Фаза 0. Freeze и baseline

- [ ] T00. Создать отдельную ветку или worktree для big cutover.
- [ ] T01. Зафиксировать baseline build командой `pio run`.
- [ ] T02. Зафиксировать список контрактов: endpoints, JSON keys, Lua names, NVS keys, форматы программ, status codes.
- [ ] T03. Зафиксировать ручные smoke-сценарии rect/dist/beer/bk/nbk.

Gate фазы:
- baseline build успешен;
- список инвариантов записан и больше не меняется без отдельного решения.

### Фаза 1. Разделение state и support

- [ ] T10. Создать `state/config_types.h` и перенести туда конфигурационные типы из `Samovar.h`.
- [ ] T11. Создать `state/runtime_types.h` и перенести туда runtime structs и enums из `Samovar.h`.
- [ ] T12. Создать `state/globals.h` и перенести туда только глобальные переменные.
- [ ] T13. Создать `support/safe_parse.h` и перенести туда `copyStringSafe`, `parseLongSafe`, `parseFloatSafe`.
- [ ] T14. Обновить include graph так, чтобы остальные модули брали типы и globals из новых заголовков.
- [ ] T15. Свести `Samovar.h` к агрегирующему include или удалить его, если сборка уже не зависит от него напрямую.

Gate фазы:
- глобалы и типы больше не смешаны в одном файле;
- сборка проходит без возврата типов обратно в `Samovar.h`.

### Фаза 2. Разбор `logic.h`

- [ ] T20. Создать `support/process_math.h` и перенести туда парсинг, объемную математику, температурные и спиртовые расчеты.
- [ ] T21. Создать `app/alarm_control.h` и перенести `set_alarm`, `process_buzzer`, `set_buzzer`.
- [ ] T22. Создать `app/process_common.h` и перенести `stop_process`, `start_self_test`, `stop_self_test`.
- [ ] T23. Создать `io/power_control.h` и перенести туда весь общий контур регулятора, включая `set_power`, `set_current_power`, `set_power_mode`, `check_power_error`, `triggerPowerStatus`.
- [ ] T24. Создать `io/actuators.h` и перенести туда `pump_calibrate`, `set_pump_speed`, `set_capacity`, `next_capacity`, `open_valve`, `set_boiling`, `check_boiling`.
- [ ] T25. Создать `app/status_text.h` и перенести туда `get_Samovar_Status`.
- [ ] T26. Создать `modes/beer/beer_support.h` и перенести туда `getBeerCurrentTemp`.
- [ ] T27. Создать `modes/rect/rect_program_codec.h` и перенести туда `set_program`, `get_program`.
- [ ] T28. Создать `modes/rect/rect_runtime.h` и перенести туда rect-only runtime: `withdrawal`, `pause_withdrawal`, `run_program`, `set_body_temp`, `check_alarm`, `column_wetting`.
- [ ] T29. Удалить `logic.h` полностью.

Gate фазы:
- в репозитории нет `logic.h`;
- регулятор не находится в `modes/rect`;
- status builder не находится в режиме.

### Фаза 3. Разбор `Samovar.ino`

- [ ] T30. Создать `app/runtime_tasks.h` и перенести туда `triggerGetClock`, `triggerSysTicker`, service helpers и связанные ISR-safe куски.
- [ ] T31. Создать `app/messages.h` и перенести туда `SendMsg`, `WriteConsoleLog`.
- [ ] T32. Создать `ui/web/ajax_snapshot.h` и перенести туда `jsonAddKey`, `jsonPrintEscaped`, `send_ajax_json`.
- [ ] T33. Создать `app/config_apply.h` и перенести туда `read_config`.
- [ ] T34. Создать `app/loop_dispatch.h` и вынести туда обработку `sam_command_sync` и dispatch режимов.
- [ ] T35. Свести `setup()` и `loop()` в `Samovar.ino` к тонкому orchestration-коду.

Gate фазы:
- `Samovar.ino` больше не хранит web snapshot и сообщения;
- центральный loop dispatch остается единым и не превращается в OO runtime.

### Фаза 4. Разбор режимов

- [ ] T40. Разрезать `distiller.h` на runtime, codec, alarm и predictor.
- [ ] T41. Разрезать `beer.h` на runtime, codec, alarm, heater, mixer, autotune.
- [ ] T42. Разрезать `BK.h` на runtime, alarm и finish.
- [ ] T43. Разрезать `nbk.h` на runtime, codec, alarm и math.
- [ ] T44. Удалить `SetSpeed()` из `nbk.h` после переноса статистики в реального владельца.
- [ ] T45. Проверить, что ни один режим не держит у себя shared helper другого режима.

Gate фазы:
- каждый режим собран в собственном каталоге;
- codec программы отделен от runtime во всех режимах, где он есть.

### Фаза 5. Разбор web

- [ ] T50. Создать `ui/web/server_init.h` и вынести туда только регистрацию маршрутов.
- [ ] T51. Создать `ui/web/page_assets.h` и перенести `change_samovar_mode`, `handleFileWithGzip`, `handleWifiHtmFromMemory`, static assets.
- [ ] T52. Создать `ui/web/template_keys.h` и перенести все template processors.
- [ ] T53. Создать `ui/web/routes_setup.h` и разложить `handleSave` на plain helpers внутри модуля по группам полей.
- [ ] T54. Создать `ui/web/routes_command.h` и перенести `web_command`.
- [ ] T55. Создать `ui/web/routes_program.h` и перенести `web_program`.
- [ ] T56. Создать `ui/web/routes_service.h` и перенести `calibrate_command`, `/i2cpump`, `/ajax_col_params`, `get_data_log`.
- [ ] T57. Создать `storage/web_assets_sync.h` и перенести `get_web_interface`, `get_web_file`, `http_sync_request_get`, `http_sync_request_post`.
- [ ] T58. Удалить `WebServer.ino`.

Gate фазы:
- в репозитории нет `WebServer.ino`;
- все endpoints работают с прежними параметрами и полями ответа.

### Фаза 6. Разбор Lua

- [ ] T60. Создать `ui/lua/runtime.h` и перенести туда task lifecycle, загрузку скриптов и `lua_init`.
- [ ] T61. Создать `ui/lua/bindings_gpio.h` и вынести туда pin/digital/analog/expander wrappers.
- [ ] T62. Создать `ui/lua/bindings_process.h` и вынести туда process-facing wrappers.
- [ ] T63. Создать `ui/lua/bindings_variables.h` и вынести туда numeric/string/object accessors и timers.
- [ ] T64. Создать `ui/lua/bindings_io.h` и вынести туда mixer/valve/power/stepper/I2C bindings.
- [ ] T65. Создать `ui/lua/bindings_http.h` и вынести туда `http_request`.
- [ ] T66. Удалить `lua.h`.

Gate фазы:
- Lua names полностью сохранены;
- mode scripts, button scripts и direct string execution работают как раньше.

### Фаза 7. Разбор storage и sensor/support слоя

- [ ] T70. Создать `storage/fs_init.h`, `storage/session_logs.h`, `storage/profile_files.h` и разрезать `FS.ino`.
- [ ] T71. Удалить `save_profile`, `load_profile`, `get_prf_name` как лишние прокладки.
- [ ] T72. Создать `storage/nvs_profiles.h`, `storage/nvs_wifi.h`, `storage/nvs_migration.h` и разрезать `NVS_Manager.ino`.
- [ ] T73. Создать `io/sensors.h`, `io/pressure.h`, `io/sensor_scan.h`, `support/format_utils.h` и разрезать `sensorinit.h`.
- [ ] T74. Создать `app/default_programs.h` и перенести туда `load_default_program_for_mode`.
- [ ] T75. Проверить, что sensor модуль больше не хранит режимные default programs.

Gate фазы:
- storage больше не завязан на FS wrappers;
- default programs отделены от сенсоров.

### Фаза 8. Разбор меню и frontend

- [ ] T80. Создать `ui/menu/strings.h`, `ui/menu/screens.h`, `ui/menu/actions.h`, `ui/menu/input.h` и разрезать `Menu.ino`.
- [ ] T81. Проверить, что меню вызывает уже существующую runtime-логику, а не хранит дублирующие правила переходов.
- [ ] T82. Вынести общий JS-каркас из `data/index.htm`, `data/distiller.htm`, `data/beer.htm`, `data/bk.htm`, `data/nbk.htm` в общие frontend assets.
- [ ] T83. Оставить в режимных страницах только режимные различия.
- [ ] T84. Не менять endpoints, JSON keys, имена form fields и template placeholders.

Gate фазы:
- frontend избавлен от дублирования;
- backend contract не изменен.

### Фаза 9. Финальная зачистка

- [ ] T90. Удалить все пустые legacy-файлы и остаточные include.
- [ ] T91. Проверить, что в дереве не осталось временных compatibility helpers.
- [ ] T92. Прогнать полную сборку `pio run`.
- [ ] T93. Пройти ручные smoke-сценарии по всем режимам.
- [ ] T94. Подготовить change summary и список остаточных рисков.

Gate фазы:
- проект собран;
- legacy остатки не мешают читать структуру;
- нет дублирующих old/new контуров.

## 8. Ручные сценарии приемки

- Rect: включение питания, старт программы, пауза, continue, `set body temp`, finish.
- Dist: старт, переходы между строками программы, finish по температуре, finish по расчетной спиртуозности.
- Beer: разогрев, пауза, кипячение, охлаждение, мешалка, насос, autotune, Lua step.
- BK: старт, работа по охлаждению, аварийное завершение.
- NBK: heatup, setup, optimization, work, overflow, finish.
- Web: `/ajax`, `/command`, `/program`, `/save`, `/calibrate`, `/i2cpump`.
- Lua: `script.lua`, mode script, button script, `setPower`, `setNextProgram`, `http_request`.
- Storage: сохранение профиля, перезагрузка, восстановление профиля, Wi-Fi credentials.

## 9. Признаки неправильного рефакторинга

- Появился новый слой "manager/service/context", которого раньше не было.
- Одна и та же функция существует в старом и новом месте.
- Для совместимости добавлен wrapper вместо переноса ownership.
- Rect-модуль владеет power regulator или общими web/Lua функциями.
- В storage или sensor модуль попал режимный код.
- Для упрощения были изменены HTTP/Lua/NVS контракты.

## 10. Definition of done

Работа считается завершенной только если:
- проект собран;
- поведение режимов не изменилось;
- внешний контракт не изменился;
- структура кода читается по каталогам без знания legacy;
- в diff нет shim, adapter и duplicate code;
- mixed-монолиты удалены, а не просто переименованы.
