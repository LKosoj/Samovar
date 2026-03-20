# Шаг 2.1. Инвентаризация state-кодов Samovar

## Scope

- Просканировано `*.h/*.cpp/*.ino`: `1015` файлов из git-дерева.
- Source of truth для status/command: `src/core/state/status_codes.h`.
- Source of truth для mode/startval: `src/core/state/mode_codes.h`.
- Source of truth для runtime-диспетча и входа в режимы: `app/loop_dispatch.h`, `app/orchestration.h`.
- Source of truth для текстовой интерпретации статусов: `app/status_text.h`.

## Владельцы

- `mode runtime` (modes/*): `modes/beer/beer_runtime.h`, `modes/beer/beer_support.h`, `modes/bk/bk_alarm.h`, `modes/dist/dist_alarm.h`, `modes/dist/dist_runtime.h`, `modes/nbk/nbk_alarm.h`, `modes/nbk/nbk_runtime.h`, `modes/rect/rect_runtime.h`
- `web routes` (ui/web/*): `ui/web/ajax_snapshot.h`, `ui/web/page_assets.h`, `ui/web/routes_command.h`, `ui/web/routes_program.h`, `ui/web/routes_service.h`, `ui/web/routes_setup.h`, `ui/web/template_keys.h`
- `menu actions` (ui/menu/*): `ui/menu/actions.h`, `ui/menu/input.h`
- `Lua` (ui/lua/*): `ui/lua/bindings_process.h`, `ui/lua/bindings_variables.h`, `ui/lua/runtime.h`
- `loop/orchestration` (app/*, io/*, Samovar.ino): `Samovar.ino`, `app/alarm_control.h`, `app/config_apply.h`, `app/default_programs.h`, `app/loop_dispatch.h`, `app/orchestration.h`, `app/process_common.h`, `app/runtime_tasks.h`, `app/status_text.h`, `io/actuators.h`, `io/power_control.h`, `io/sensor_scan.h`
- `storage/profile` (storage/*): `storage/nvs_migration.h`, `storage/nvs_profiles.h`, `storage/session_logs.h`
- `external control` (Blynk.ino): `Blynk.ino`
- `other` (прочие файлы): `impurity_detector.h`, `state/globals.h`

## SamovarStatusInt

| Число | Токен | Смысл | Владельцы | Где используется |
| --- | --- | --- | --- | --- |
| `0` | `SAMOVAR_STATUS_OFF` | Выключено/сброшено. | loop/orchestration, other | `app/process_common.h:23`; `app/status_text.h:16`; `io/sensor_scan.h:153`; `src/core/state/status_codes.h:6,21` |
| `10` | `SAMOVAR_STATUS_RECTIFICATION_RUN` | Ректификация: активная строка программы отбора. | loop/orchestration, other | `app/status_text.h:20`; `impurity_detector.h:302`; `src/core/state/status_codes.h:7,25,31` |
| `15` | `SAMOVAR_STATUS_RECTIFICATION_WAIT` | Ректификация: пауза по таймеру программы. | loop/orchestration, other | `app/status_text.h:27`; `src/core/state/status_codes.h:8,26,32` |
| `20` | `SAMOVAR_STATUS_RECTIFICATION_COMPLETE` | Ректификация: программа завершена. | loop/orchestration, other | `app/status_text.h:30`; `src/core/state/status_codes.h:9` |
| `30` | `SAMOVAR_STATUS_CALIBRATION` | Калибровка насоса/шаговика. | loop/orchestration, other | `app/status_text.h:33`; `src/core/state/status_codes.h:10` |
| `40` | `SAMOVAR_STATUS_RECTIFICATION_PAUSE` | Ручная пауза отбора. | loop/orchestration, other | `app/status_text.h:36`; `src/core/state/status_codes.h:11,27` |
| `50` | `SAMOVAR_STATUS_RECTIFICATION_WARMUP` | Разгон колонны. | loop/orchestration, mode runtime, other | `app/loop_dispatch.h:39`; `app/status_text.h:41`; `modes/rect/rect_runtime.h:337,519`; `src/core/state/status_codes.h:12` |
| `51` | `SAMOVAR_STATUS_RECTIFICATION_STABILIZING` | Разгон завершён, идёт стабилизация/работа на себя. | loop/orchestration, mode runtime, other | `app/status_text.h:38,42`; `modes/rect/rect_runtime.h:531,547,555`; `src/core/state/status_codes.h:13` |
| `52` | `SAMOVAR_STATUS_RECTIFICATION_STABILIZED` | Стабилизация завершена, колонна работает на себя стабильно. | loop/orchestration, mode runtime, other | `app/status_text.h:39,44`; `modes/rect/rect_runtime.h:563`; `src/core/state/status_codes.h:14` |
| `1000` | `SAMOVAR_STATUS_DISTILLATION` | Режим дистилляции активен. | loop/orchestration, mode runtime, other, web routes | `app/loop_dispatch.h:29,65,106`; `app/status_text.h:47`; `modes/dist/dist_runtime.h:33`; `src/core/state/status_codes.h:15,21`; `ui/web/routes_setup.h:58` |
| `2000` | `SAMOVAR_STATUS_BEER` | Режим пива активен. | loop/orchestration, mode runtime, other, web routes | `app/loop_dispatch.h:30,70,112`; `app/status_text.h:66,131`; `modes/beer/beer_runtime.h:100`; `modes/beer/beer_support.h:10`; `src/core/state/status_codes.h:16`; `ui/web/ajax_snapshot.h:156`; `ui/web/routes_setup.h:60` |
| `3000` | `SAMOVAR_STATUS_BK` | Режим БК активен. | loop/orchestration, other, web routes | `app/loop_dispatch.h:32,81,108`; `app/status_text.h:51`; `src/core/state/status_codes.h:17`; `ui/web/routes_setup.h:62` |
| `4000` | `SAMOVAR_STATUS_NBK` | Режим НБК активен. | loop/orchestration, mode runtime, other, web routes | `app/loop_dispatch.h:34,86,110`; `app/status_text.h:53`; `modes/nbk/nbk_runtime.h:65`; `src/core/state/status_codes.h:18`; `ui/web/routes_setup.h:64` |

### SamovarStatusInt: диапазонные и compound-предикаты

_Raw numeric range-comparisons по этой переменной не найдены; оставшаяся семантика вынесена в именованные helper-предикаты в state headers._

## startval

| Число | Токен | Смысл | Владельцы | Где используется |
| --- | --- | --- | --- | --- |
| `0` | `SAMOVAR_STARTVAL_RECT_IDLE` | Останов/idle; для rect также разгон до старта программы. | loop/orchestration, menu actions, mode runtime, other, web routes | `Samovar.ino:344`; `app/orchestration.h:500,502,504,508`; `app/runtime_tasks.h:222`; `app/status_text.h:37`; `io/actuators.h:24,29`; `io/sensor_scan.h:154`; `modes/beer/beer_runtime.h:183`; `modes/rect/rect_runtime.h:534,569`; `src/core/state/mode_codes.h:16,30,34`; `ui/menu/actions.h:240,244`; `ui/menu/input.h:226`; `ui/web/routes_service.h:19` |
| `1` | `SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING` | Ректификация: активная строка программы. | loop/orchestration, menu actions, mode runtime, other | `app/status_text.h:18,21`; `modes/rect/rect_runtime.h:120`; `src/core/state/mode_codes.h:17`; `ui/menu/actions.h:250,255` |
| `2` | `SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE` | Ректификация: программа завершена, ожидается финальный переход. | loop/orchestration, menu actions, mode runtime, other | `app/status_text.h:28`; `modes/rect/rect_runtime.h:121`; `src/core/state/mode_codes.h:18`; `ui/menu/actions.h:238,241,259` |
| `3` | `SAMOVAR_STARTVAL_RECT_STOPPED` | Ректификация: останов после завершения/ручного завершения. | menu actions, other | `src/core/state/mode_codes.h:19,30`; `ui/menu/actions.h:239` |
| `100` | `SAMOVAR_STARTVAL_CALIBRATION` | Режим калибровки. | loop/orchestration, menu actions, other, web routes | `app/orchestration.h:507`; `app/status_text.h:31`; `io/actuators.h:24,37`; `src/core/state/mode_codes.h:20,34`; `ui/menu/actions.h:204,213,221`; `ui/menu/input.h:190,204,225`; `ui/web/routes_service.h:22` |
| `1000` | `SAMOVAR_STARTVAL_DISTILLATION_ENTRY` | Стартовый маркер входа в дистилляцию. | loop/orchestration, other | `app/loop_dispatch.h:66`; `src/core/state/mode_codes.h:21` |
| `2000` | `SAMOVAR_STARTVAL_BEER_ENTRY` | Стартовый маркер входа в пиво до запуска первой строки. | loop/orchestration, mode runtime, other | `app/loop_dispatch.h:71,112`; `modes/beer/beer_runtime.h:102,118`; `src/core/state/mode_codes.h:22,38` |
| `2001` | `SAMOVAR_STARTVAL_BEER_MALT_HEATING` | Пиво: разогрев до температуры засыпи солода. | loop/orchestration, mode runtime, other | `app/status_text.h:72`; `modes/beer/beer_runtime.h:118,271`; `src/core/state/mode_codes.h:23` |
| `2002` | `SAMOVAR_STARTVAL_BEER_MALT_WAIT` | Пиво: ожидание засыпи солода. | loop/orchestration, mode runtime, other | `app/status_text.h:78`; `modes/beer/beer_runtime.h:275`; `src/core/state/mode_codes.h:24` |
| `3000` | `SAMOVAR_STARTVAL_BK_ENTRY` | Стартовый маркер входа в БК. | loop/orchestration, other | `app/loop_dispatch.h:82`; `src/core/state/mode_codes.h:25` |
| `4000` | `SAMOVAR_STARTVAL_NBK_ENTRY` | Стартовый маркер входа в НБК до запуска первой строки. | loop/orchestration, mode runtime, other | `app/loop_dispatch.h:87`; `modes/nbk/nbk_runtime.h:62`; `src/core/state/mode_codes.h:26` |
| `4001` | `SAMOVAR_STARTVAL_NBK_PROGRAM_RUNNING` | НБК: первая программа запущена, stage-текст уже активен. | loop/orchestration, mode runtime, other | `app/status_text.h:54`; `modes/nbk/nbk_runtime.h:63`; `src/core/state/mode_codes.h:27` |

### startval: диапазонные и compound-предикаты

_Raw numeric range-comparisons по этой переменной не найдены; оставшаяся семантика вынесена в именованные helper-предикаты в state headers._

## sam_command_sync

| Число | Токен | Смысл | Владельцы | Где используется |
| --- | --- | --- | --- | --- |
| `0` | `SAMOVAR_NONE` | Нет ожидающей команды. | Lua, loop/orchestration, menu actions, other | `app/loop_dispatch.h:21,95,99`; `io/sensor_scan.h:110,188`; `src/core/state/status_codes.h:36,55`; `ui/lua/bindings_variables.h:7`; `ui/menu/actions.h:280` |
| `1` | `SAMOVAR_START` | Старт/следующая программа ректификации. | Lua, external control, loop/orchestration, other, web routes | `Blynk.ino:232`; `app/loop_dispatch.h:24`; `src/core/state/status_codes.h:37,56`; `ui/lua/bindings_process.h:49`; `ui/web/routes_command.h:60` |
| `2` | `SAMOVAR_POWER` | Переключение питания или завершение текущего режима. | Lua, external control, loop/orchestration, menu actions, mode runtime, other, web routes | `Blynk.ino:260`; `app/alarm_control.h:20`; `app/loop_dispatch.h:28`; `modes/bk/bk_alarm.h:63`; `modes/dist/dist_alarm.h:59`; `modes/nbk/nbk_alarm.h:48`; `modes/rect/rect_runtime.h:495`; `src/core/state/status_codes.h:38,57`; `ui/lua/bindings_process.h:26,28`; `ui/menu/actions.h:178`; `ui/web/routes_command.h:66,70,74,78,80,128,134,140` |
| `3` | `SAMOVAR_RESET` | Полный reset-пайплайн. | external control, loop/orchestration, other, web routes | `Blynk.ino:247`; `app/loop_dispatch.h:42,98`; `io/power_control.h:53`; `src/core/state/status_codes.h:39,58`; `ui/web/routes_command.h:84` |
| `4` | `CALIBRATE_START` | Старт калибровки насоса. | loop/orchestration, other, web routes | `app/loop_dispatch.h:45`; `src/core/state/status_codes.h:40,59`; `ui/web/routes_service.h:20` |
| `5` | `CALIBRATE_STOP` | Останов калибровки насоса. | loop/orchestration, other, web routes | `app/loop_dispatch.h:48`; `src/core/state/status_codes.h:41,60`; `ui/web/routes_service.h:23` |
| `6` | `SAMOVAR_PAUSE` | Пауза отбора. | loop/orchestration, other, web routes | `app/loop_dispatch.h:51`; `src/core/state/status_codes.h:42,61`; `ui/web/routes_command.h:150` |
| `7` | `SAMOVAR_CONTINUE` | Продолжить отбор и сбросить program_Wait. | loop/orchestration, other, web routes | `app/loop_dispatch.h:54`; `src/core/state/status_codes.h:43,62`; `ui/web/routes_command.h:148` |
| `8` | `SAMOVAR_SETBODYTEMP` | Зафиксировать температуру тела. | loop/orchestration, other, web routes | `app/loop_dispatch.h:60`; `src/core/state/status_codes.h:44,63`; `ui/web/routes_command.h:82` |
| `9` | `SAMOVAR_DISTILLATION` | Переключить/запустить режим дистилляции. | Lua, external control, loop/orchestration, menu actions, other, web routes | `Blynk.ino:258`; `app/loop_dispatch.h:63`; `app/orchestration.h:514`; `src/core/state/status_codes.h:45,64`; `ui/lua/bindings_process.h:24`; `ui/menu/actions.h:154`; `ui/web/routes_command.h:68,126` |
| `10` | `SAMOVAR_BEER` | Переключить/запустить режим пива. | Lua, external control, loop/orchestration, menu actions, other, web routes | `Blynk.ino:252`; `app/loop_dispatch.h:68`; `app/orchestration.h:529`; `src/core/state/status_codes.h:46,65`; `ui/lua/bindings_process.h:18`; `ui/menu/actions.h:146`; `ui/web/routes_command.h:64` |
| `11` | `SAMOVAR_BEER_NEXT` | Следующая строка программы пива. | Lua, external control, loop/orchestration, other, web routes | `Blynk.ino:228`; `app/loop_dispatch.h:73`; `src/core/state/status_codes.h:47,66`; `ui/lua/bindings_process.h:51`; `ui/web/routes_command.h:54` |
| `12` | `SAMOVAR_BK` | Переключить/запустить режим БК. | Lua, external control, loop/orchestration, menu actions, other, web routes | `Blynk.ino:254`; `app/loop_dispatch.h:79`; `app/orchestration.h:519`; `src/core/state/status_codes.h:48,67`; `ui/lua/bindings_process.h:20`; `ui/menu/actions.h:162`; `ui/web/routes_command.h:72,132` |
| `13` | `SAMOVAR_NBK` | Переключить/запустить режим НБК. | Lua, external control, loop/orchestration, menu actions, other, web routes | `Blynk.ino:256`; `app/loop_dispatch.h:84`; `app/orchestration.h:524`; `src/core/state/status_codes.h:49,68`; `ui/lua/bindings_process.h:22`; `ui/menu/actions.h:170`; `ui/web/routes_command.h:76,138` |
| `14` | `SAMOVAR_SELF_TEST` | Запустить self-test. | loop/orchestration, other, web routes | `app/loop_dispatch.h:92`; `src/core/state/status_codes.h:50,69`; `ui/web/routes_command.h:90` |
| `15` | `SAMOVAR_DIST_NEXT` | Следующая строка программы дистилляции. | Lua, external control, loop/orchestration, other, web routes | `Blynk.ino:230`; `app/loop_dispatch.h:76`; `src/core/state/status_codes.h:51,70`; `ui/lua/bindings_process.h:53`; `ui/web/routes_command.h:56` |
| `16` | `SAMOVAR_NBK_NEXT` | Следующая строка программы НБК. | loop/orchestration, other, web routes | `app/loop_dispatch.h:89`; `src/core/state/status_codes.h:52,71`; `ui/web/routes_command.h:58` |

## Samovar_Mode

| Число | Токен | Смысл | Владельцы | Где используется |
| --- | --- | --- | --- | --- |
| `0` | `SAMOVAR_RECTIFICATION_MODE` | Ректификация. | Lua, loop/orchestration, menu actions, mode runtime, other, storage/profile, web routes | `app/loop_dispatch.h:25,38`; `app/runtime_tasks.h:241`; `impurity_detector.h:309`; `modes/rect/rect_runtime.h:153`; `storage/session_logs.h:22,68,71`; `ui/lua/bindings_process.h:48`; `ui/menu/actions.h:233`; `ui/web/ajax_snapshot.h:154,223,227` |
| `1` | `SAMOVAR_DISTILLATION_MODE` | Дистилляция. | Lua, external control, loop/orchestration, menu actions, storage/profile, web routes | `Blynk.ino:229,257`; `app/loop_dispatch.h:64`; `storage/session_logs.h:22,68`; `ui/lua/bindings_process.h:23,52`; `ui/menu/actions.h:151`; `ui/web/ajax_snapshot.h:154,223,230`; `ui/web/routes_command.h:55,67` |
| `2` | `SAMOVAR_BEER_MODE` | Пиво. | Lua, external control, loop/orchestration, menu actions, mode runtime, storage/profile, web routes | `Blynk.ino:227,251`; `app/loop_dispatch.h:69`; `modes/beer/beer_runtime.h:117`; `storage/session_logs.h:22,68,73`; `ui/lua/bindings_process.h:17,50`; `ui/menu/actions.h:143`; `ui/web/ajax_snapshot.h:154`; `ui/web/routes_command.h:53,63` |
| `3` | `SAMOVAR_BK_MODE` | Бражная колонна. | Lua, external control, loop/orchestration, menu actions, web routes | `Blynk.ino:253`; `app/loop_dispatch.h:80`; `ui/lua/bindings_process.h:19`; `ui/menu/actions.h:159`; `ui/web/ajax_snapshot.h:223`; `ui/web/routes_command.h:71` |
| `4` | `SAMOVAR_NBK_MODE` | НБК. | Lua, external control, loop/orchestration, menu actions, mode runtime, storage/profile, web routes | `Blynk.ino:255`; `app/loop_dispatch.h:85`; `modes/nbk/nbk_runtime.h:345`; `storage/session_logs.h:22,68`; `ui/lua/bindings_process.h:21`; `ui/menu/actions.h:167`; `ui/web/ajax_snapshot.h:154,223`; `ui/web/routes_command.h:57,75` |
| `5` | `SAMOVAR_SUVID_MODE` | Су-вид. | — | — |
| `6` | `SAMOVAR_LUA_MODE` | Lua-режим. | — | — |

## Samovar_CR_Mode

Samovar_CR_Mode использует тот же enum `SAMOVAR_MODE`, но применяется как канонический режим для web-страницы, Lua-family и NVS-profile namespace.

| Число | Токен | Смысл | Владельцы | Где используется |
| --- | --- | --- | --- | --- |
| `0` | `SAMOVAR_RECTIFICATION_MODE` | Ректификация. | — | — |
| `1` | `SAMOVAR_DISTILLATION_MODE` | Дистилляция. | — | — |
| `2` | `SAMOVAR_BEER_MODE` | Пиво. | — | — |
| `3` | `SAMOVAR_BK_MODE` | Бражная колонна. | — | — |
| `4` | `SAMOVAR_NBK_MODE` | НБК. | — | — |
| `5` | `SAMOVAR_SUVID_MODE` | Су-вид. | — | — |
| `6` | `SAMOVAR_LUA_MODE` | Lua-режим. | — | — |

### Прямые точки использования Samovar_CR_Mode

| Переменная | Владельцы | Где используется |
| --- | --- | --- |
| `Samovar_CR_Mode` | Lua, loop/orchestration, other, storage/profile, web routes | `Samovar.ino:255`; `state/globals.h:92`; `storage/nvs_migration.h:41,46,51`; `storage/nvs_profiles.h:21,178`; `ui/lua/bindings_variables.h:48,49,111,112`; `ui/lua/runtime.h:332`; `ui/web/page_assets.h:47`; `ui/web/routes_setup.h:83` |

## Связанные флаги

| Флаг | Роль в state-модели | Владельцы | Где используется |
| --- | --- | --- | --- |
| `PowerOn` | Главный флаг питания: меняет трактовку почти всех status/startval и маршрутизацию команд. | Lua, external control, loop/orchestration, menu actions, mode runtime, other, web routes | `Blynk.ino:41,224,245,251,253,255,257`; `Samovar.ino:307`; `app/alarm_control.h:19`; `app/loop_dispatch.h:37,38`; `app/orchestration.h:498,513,518,523,528`; `app/runtime_tasks.h:425`; `app/status_text.h:16,18,21,28,31,37,107,123,131`; `impurity_detector.h:526`; `io/actuators.h:120`; `io/power_control.h:22,134,223,256,271`; `io/sensors.h:74`; `modes/beer/beer_runtime.h:102,109,117,181,221,264`; `modes/bk/bk_alarm.h:22,43,51,60,68`; `modes/bk/bk_runtime.h:19`; `modes/dist/dist_alarm.h:22,28,45,57,64`; `modes/dist/dist_runtime.h:31,35,79`; `modes/nbk/nbk_alarm.h:16,23,31,46,53`; `modes/nbk/nbk_flow_control.h:17`; `modes/nbk/nbk_runtime.h:345,353`; `modes/rect/rect_runtime.h:339,355,437,443,475,493,500`; `state/globals.h:154`; `ui/lua/bindings_process.h:16,17,19,21,23,27`; `ui/lua/bindings_variables.h:157,158`; `ui/lua/runtime.h:42`; `ui/menu/actions.h:144,152,160,168,176,233`; `ui/web/ajax_snapshot.h:95,96,156,230`; `ui/web/routes_command.h:52,64,68,72,76,101,118`; `ui/web/routes_setup.h:57` |
| `PauseOn` | Переводит rect в статус 40 и переключает web/menu pause/continue. | Lua, external control, loop/orchestration, menu actions, mode runtime, other, web routes | `Blynk.ino:50,238`; `Samovar.ino:308`; `app/orchestration.h:503`; `app/status_text.h:18,34`; `impurity_detector.h:322,324,426,446,504`; `io/sensor_scan.h:155`; `modes/rect/rect_runtime.h:68,154,155,220`; `state/globals.h:237`; `ui/lua/bindings_variables.h:167,168`; `ui/lua/runtime.h:43`; `ui/menu/actions.h:187,188`; `ui/web/ajax_snapshot.h:97,98`; `ui/web/routes_command.h:147` |
| `program_Wait` | Различает статусы 10 и 15; сбрасывается при continue/manual resume. | Lua, external control, loop/orchestration, menu actions, mode runtime, other | `Blynk.ino:240`; `Samovar.ino:311`; `app/loop_dispatch.h:57`; `app/runtime_tasks.h:267`; `app/status_text.h:18,21`; `impurity_detector.h:332,425,426,428,445,498,504`; `io/sensor_scan.h:156`; `modes/rect/rect_runtime.h:68,70,81,85,142,145,219`; `state/globals.h:239`; `ui/lua/bindings_variables.h:169,170`; `ui/lua/runtime.h:46`; `ui/menu/actions.h:193` |
| `program_Pause` | Меняет поведение кнопки/оркестрации для rect-паузы программы. | Lua, loop/orchestration, mode runtime, other | `Samovar.ino:310`; `app/orchestration.h:502,504`; `modes/rect/rect_runtime.h:108,218,297`; `state/globals.h:238`; `ui/lua/runtime.h:45` |
| `stepper.getState()` | Отделяет разгон/stabilization rect от активного отбора. | loop/orchestration, mode runtime, web routes | `app/status_text.h:37`; `io/actuators.h:38,50`; `modes/rect/rect_runtime.h:154`; `ui/web/ajax_snapshot.h:108` |
| `wetting_autostart` | Связывает rect 51 -> 52 с автозапуском голов после смачивания. | loop/orchestration, mode runtime, other | `Samovar.ino:327`; `io/sensor_scan.h:132`; `modes/rect/rect_runtime.h:534,569,570`; `state/globals.h:241` |
| `boil_started` | Уточняет внутреннюю фазу rect при статусе 51. | loop/orchestration, mode runtime, other | `Samovar.ino:317`; `io/actuators.h:104,105,120,190,199`; `io/sensor_scan.h:177`; `io/sensors.h:52,57`; `modes/rect/rect_runtime.h:547,549`; `state/globals.h:216`; `support/process_math.h:80,177` |

## Helper-предикаты state semantics

- `samovar_status_is_rectification(status)` — именует rect-family диапазон `status > OFF && status < DISTILLATION` для runtime dispatch и menu/orchestration.
- `samovar_status_allows_rectification_withdrawal(status)` — заменяет повторяющиеся проверки статусов `RUN/WAIT/PAUSE` в rect runtime и UI snapshot/status text.
- `samovar_status_has_rectification_program_progress(status)` — именует более узкую rect-semantics `RUN/WAIT` там, где pause не должна считаться активным прогрессом программы.
- `startval_is_rect_program_state(value)` — именует rect program-state диапазон `1..3` для внешнего контроля/Blynk.
- `startval_is_active_non_calibration(value)` — именует запрет калибровки во всех активных state, кроме отдельного calibration-state.
- `startval_is_beer_program_started(value)` — именует границу между beer entry и уже идущими beer steps.

## Примечания по baseline

- `50/51/52` существуют только в rect-runtime и появляются не отдельной командой, а через сочетание `PowerOn`, `startval == SAMOVAR_STARTVAL_RECT_IDLE`, `stepper.getState()`, температур и стабилизации.
- `2000/2001/2002` описывают lifecycle режима пива: вход в режим -> разогрев до засыпи -> ожидание засыпи.
- `4000/4001` описывают lifecycle НБК: вход в режим -> запуск первой программы; при этом `SamovarStatusInt` остаётся `4000`, а деталь фазы хранится в `startval`.
