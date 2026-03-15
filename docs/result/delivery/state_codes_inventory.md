# Шаг 2.1. Инвентаризация state-кодов Samovar

## Scope

- Просканировано `*.h/*.cpp/*.ino`: `1011` файлов из git-дерева.
- Source of truth для enum-команд и enum-режимов: `state/runtime_types.h`.
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

| Значение | Смысл | Владельцы | Где используется |
| --- | --- | --- | --- |
| `0` | Выключено/сброшено. | loop/orchestration | `app/process_common.h:22`; `app/status_text.h:14`; `io/sensor_scan.h:153` |
| `10` | Ректификация: активная строка программы отбора. | loop/orchestration, mode runtime, other, web routes | `app/status_text.h:18,127`; `impurity_detector.h:301,302`; `io/actuators.h:45`; `modes/rect/rect_runtime.h:33`; `ui/web/ajax_snapshot.h:155` |
| `15` | Ректификация: пауза по таймеру программы. | loop/orchestration, mode runtime, web routes | `app/status_text.h:25,127`; `io/actuators.h:45`; `modes/rect/rect_runtime.h:33`; `ui/web/ajax_snapshot.h:155` |
| `20` | Ректификация: программа завершена. | loop/orchestration | `app/status_text.h:28` |
| `30` | Калибровка насоса/шаговика. | loop/orchestration | `app/status_text.h:31` |
| `40` | Ручная пауза отбора. | loop/orchestration, mode runtime | `app/status_text.h:34`; `io/actuators.h:45`; `modes/rect/rect_runtime.h:33` |
| `50` | Разгон колонны. | loop/orchestration, mode runtime | `app/loop_dispatch.h:39`; `app/status_text.h:38`; `modes/rect/rect_runtime.h:374,561` |
| `51` | Разгон завершён, идёт стабилизация/работа на себя. | loop/orchestration, mode runtime | `app/status_text.h:36,39`; `modes/rect/rect_runtime.h:576,597,606` |
| `52` | Стабилизация завершена, колонна работает на себя стабильно. | loop/orchestration, mode runtime | `app/status_text.h:36,41`; `modes/rect/rect_runtime.h:613` |
| `1000` | Режим дистилляции активен. | loop/orchestration, mode runtime, web routes | `app/loop_dispatch.h:29,65,106`; `app/status_text.h:44`; `modes/dist/dist_runtime.h:33`; `ui/web/routes_setup.h:63` |
| `2000` | Режим пива активен. | loop/orchestration, mode runtime, web routes | `app/loop_dispatch.h:30,70,112`; `app/status_text.h:63,127`; `modes/beer/beer_runtime.h:100`; `modes/beer/beer_support.h:9`; `ui/web/ajax_snapshot.h:155`; `ui/web/routes_setup.h:65` |
| `3000` | Режим БК активен. | loop/orchestration, web routes | `app/loop_dispatch.h:32,81,108`; `app/status_text.h:48`; `ui/web/routes_setup.h:67` |
| `4000` | Режим НБК активен. | loop/orchestration, mode runtime, web routes | `app/loop_dispatch.h:34,86,110`; `app/status_text.h:50`; `modes/nbk/nbk_runtime.h:65`; `ui/web/routes_setup.h:69` |

### SamovarStatusInt: диапазонные и compound-предикаты

| Граница | Оператор | Владельцы | Где используется |
| --- | --- | --- | --- |
| `0` | `>` | loop/orchestration | `app/loop_dispatch.h:104` |
| `1000` | `<` | loop/orchestration | `app/loop_dispatch.h:104`; `app/orchestration.h:500,502,504` |

## startval

| Значение | Смысл | Владельцы | Где используется |
| --- | --- | --- | --- |
| `0` | Останов/idle; для rect также разгон до старта программы. | loop/orchestration, menu actions, mode runtime, web routes | `Samovar.ino:344`; `app/orchestration.h:500,502,504,508`; `app/runtime_tasks.h:222`; `app/status_text.h:35`; `io/actuators.h:22,27`; `io/sensor_scan.h:154`; `modes/beer/beer_runtime.h:183`; `modes/rect/rect_runtime.h:583,619`; `ui/menu/actions.h:240,244`; `ui/menu/input.h:226`; `ui/web/routes_service.h:19` |
| `1` | Ректификация: активная строка программы. | loop/orchestration, menu actions, mode runtime | `app/status_text.h:16,19`; `modes/rect/rect_runtime.h:51`; `ui/menu/actions.h:250,255` |
| `2` | Ректификация: программа завершена, ожидается финальный переход. | loop/orchestration, menu actions, mode runtime | `app/status_text.h:26`; `modes/rect/rect_runtime.h:51`; `ui/menu/actions.h:238,241,259` |
| `3` | Ректификация: останов после завершения/ручного завершения. | menu actions | `ui/menu/actions.h:239` |
| `100` | Режим калибровки. | loop/orchestration, menu actions, web routes | `app/orchestration.h:507`; `app/status_text.h:29`; `io/actuators.h:22,35`; `ui/menu/actions.h:199,204,213,221`; `ui/menu/input.h:190,204,225`; `ui/web/routes_service.h:22` |
| `1000` | Стартовый маркер входа в дистилляцию. | loop/orchestration | `app/loop_dispatch.h:66` |
| `2000` | Стартовый маркер входа в пиво до запуска первой строки. | loop/orchestration, mode runtime | `app/loop_dispatch.h:71,112`; `modes/beer/beer_runtime.h:102,118` |
| `2001` | Пиво: разогрев до температуры засыпи солода. | loop/orchestration, mode runtime | `app/status_text.h:69`; `modes/beer/beer_runtime.h:118,271` |
| `2002` | Пиво: ожидание засыпи солода. | loop/orchestration, mode runtime | `app/status_text.h:75`; `modes/beer/beer_runtime.h:275` |
| `3000` | Стартовый маркер входа в БК. | loop/orchestration | `app/loop_dispatch.h:82` |
| `4000` | Стартовый маркер входа в НБК до запуска первой строки. | loop/orchestration, mode runtime | `app/loop_dispatch.h:87`; `modes/nbk/nbk_runtime.h:62` |
| `4001` | НБК: первая программа запущена, stage-текст уже активен. | loop/orchestration, mode runtime | `app/status_text.h:51`; `modes/nbk/nbk_runtime.h:63` |

### startval: диапазонные и compound-предикаты

| Граница | Оператор | Владельцы | Где используется |
| --- | --- | --- | --- |
| `0` | `>` | external control, menu actions | `Blynk.ino:47`; `ui/menu/actions.h:199` |
| `5` | `<` | external control | `Blynk.ino:47` |
| `2000` | `<=` | mode runtime | `modes/beer/beer_runtime.h:190` |

## sam_command_sync

| Число | Токен | Смысл | Владельцы | Где используется |
| --- | --- | --- | --- | --- |
| `0` | `SAMOVAR_NONE` | Нет ожидающей команды. | Lua, loop/orchestration, menu actions, other | `app/loop_dispatch.h:21,95,99`; `io/sensor_scan.h:110,188`; `state/runtime_types.h:7`; `ui/lua/bindings_variables.h:7`; `ui/menu/actions.h:280` |
| `1` | `SAMOVAR_START` | Старт/следующая программа ректификации. | Lua, external control, loop/orchestration, other, web routes | `Blynk.ino:243`; `app/loop_dispatch.h:24`; `state/runtime_types.h:7`; `ui/lua/bindings_process.h:49`; `ui/web/routes_command.h:60` |
| `2` | `SAMOVAR_POWER` | Переключение питания или завершение текущего режима. | Lua, external control, loop/orchestration, menu actions, mode runtime, other, web routes | `Blynk.ino:271`; `app/alarm_control.h:20`; `app/loop_dispatch.h:28`; `modes/bk/bk_alarm.h:63`; `modes/dist/dist_alarm.h:59`; `modes/nbk/nbk_alarm.h:48`; `modes/rect/rect_runtime.h:536`; `state/runtime_types.h:7`; `ui/lua/bindings_process.h:26,28`; `ui/menu/actions.h:178`; `ui/web/routes_command.h:66,70,74,78,80,128,134,140` |
| `3` | `SAMOVAR_RESET` | Полный reset-пайплайн. | external control, loop/orchestration, other, web routes | `Blynk.ino:258`; `app/loop_dispatch.h:42,98`; `io/power_control.h:53`; `state/runtime_types.h:7`; `ui/web/routes_command.h:84` |
| `4` | `CALIBRATE_START` | Старт калибровки насоса. | loop/orchestration, other, web routes | `app/loop_dispatch.h:45`; `state/runtime_types.h:7`; `ui/web/routes_service.h:20` |
| `5` | `CALIBRATE_STOP` | Останов калибровки насоса. | loop/orchestration, other, web routes | `app/loop_dispatch.h:48`; `state/runtime_types.h:7`; `ui/web/routes_service.h:23` |
| `6` | `SAMOVAR_PAUSE` | Пауза отбора. | loop/orchestration, other, web routes | `app/loop_dispatch.h:51`; `state/runtime_types.h:7`; `ui/web/routes_command.h:150` |
| `7` | `SAMOVAR_CONTINUE` | Продолжить отбор и сбросить program_Wait. | loop/orchestration, other, web routes | `app/loop_dispatch.h:54`; `state/runtime_types.h:7`; `ui/web/routes_command.h:148` |
| `8` | `SAMOVAR_SETBODYTEMP` | Зафиксировать температуру тела. | loop/orchestration, other, web routes | `app/loop_dispatch.h:60`; `state/runtime_types.h:7`; `ui/web/routes_command.h:82` |
| `9` | `SAMOVAR_DISTILLATION` | Переключить/запустить режим дистилляции. | Lua, external control, loop/orchestration, menu actions, other, web routes | `Blynk.ino:269`; `app/loop_dispatch.h:63`; `app/orchestration.h:514`; `state/runtime_types.h:7`; `ui/lua/bindings_process.h:24`; `ui/menu/actions.h:154`; `ui/web/routes_command.h:68,126` |
| `10` | `SAMOVAR_BEER` | Переключить/запустить режим пива. | Lua, external control, loop/orchestration, menu actions, other, web routes | `Blynk.ino:263`; `app/loop_dispatch.h:68`; `app/orchestration.h:529`; `state/runtime_types.h:7`; `ui/lua/bindings_process.h:18`; `ui/menu/actions.h:146`; `ui/web/routes_command.h:64` |
| `11` | `SAMOVAR_BEER_NEXT` | Следующая строка программы пива. | Lua, external control, loop/orchestration, other, web routes | `Blynk.ino:239`; `app/loop_dispatch.h:73`; `state/runtime_types.h:7`; `ui/lua/bindings_process.h:51`; `ui/web/routes_command.h:54` |
| `12` | `SAMOVAR_BK` | Переключить/запустить режим БК. | Lua, external control, loop/orchestration, menu actions, other, web routes | `Blynk.ino:265`; `app/loop_dispatch.h:79`; `app/orchestration.h:519`; `state/runtime_types.h:7`; `ui/lua/bindings_process.h:20`; `ui/menu/actions.h:162`; `ui/web/routes_command.h:72,132` |
| `13` | `SAMOVAR_NBK` | Переключить/запустить режим НБК. | Lua, external control, loop/orchestration, menu actions, other, web routes | `Blynk.ino:267`; `app/loop_dispatch.h:84`; `app/orchestration.h:524`; `state/runtime_types.h:7`; `ui/lua/bindings_process.h:22`; `ui/menu/actions.h:170`; `ui/web/routes_command.h:76,138` |
| `14` | `SAMOVAR_SELF_TEST` | Запустить self-test. | loop/orchestration, other, web routes | `app/loop_dispatch.h:92`; `state/runtime_types.h:7`; `ui/web/routes_command.h:90` |
| `15` | `SAMOVAR_DIST_NEXT` | Следующая строка программы дистилляции. | Lua, external control, loop/orchestration, other, web routes | `Blynk.ino:241`; `app/loop_dispatch.h:76`; `state/runtime_types.h:7`; `ui/lua/bindings_process.h:53`; `ui/web/routes_command.h:56` |
| `16` | `SAMOVAR_NBK_NEXT` | Следующая строка программы НБК. | loop/orchestration, other, web routes | `app/loop_dispatch.h:89`; `state/runtime_types.h:7`; `ui/web/routes_command.h:58` |

## Samovar_Mode

| Число | Токен | Смысл | Владельцы | Где используется |
| --- | --- | --- | --- | --- |
| `0` | `SAMOVAR_RECTIFICATION_MODE` | Ректификация. | Lua, loop/orchestration, menu actions, mode runtime, other, storage/profile, web routes | `app/loop_dispatch.h:25,38`; `app/orchestration.h:497`; `app/runtime_tasks.h:241,292,355`; `impurity_detector.h:309`; `modes/rect/rect_runtime.h:181`; `storage/session_logs.h:26,28,82,85`; `ui/lua/bindings_process.h:48`; `ui/menu/actions.h:233`; `ui/web/ajax_snapshot.h:154,222,226`; `ui/web/page_assets.h:54` |
| `1` | `SAMOVAR_DISTILLATION_MODE` | Дистилляция. | Lua, external control, loop/orchestration, menu actions, storage/profile, web routes | `Blynk.ino:180,240,268`; `app/default_programs.h:15`; `app/loop_dispatch.h:64`; `app/orchestration.h:512`; `app/runtime_tasks.h:294`; `storage/session_logs.h:26,34,82`; `ui/lua/bindings_process.h:23,52`; `ui/menu/actions.h:151`; `ui/web/ajax_snapshot.h:154,222,229`; `ui/web/page_assets.h:46`; `ui/web/routes_command.h:55,67`; `ui/web/routes_program.h:9`; `ui/web/template_keys.h:40` |
| `2` | `SAMOVAR_BEER_MODE` | Пиво. | Lua, external control, loop/orchestration, menu actions, mode runtime, storage/profile, web routes | `Blynk.ino:178,238,262`; `app/default_programs.h:13`; `app/loop_dispatch.h:69`; `app/orchestration.h:527`; `app/runtime_tasks.h:300,308`; `modes/beer/beer_runtime.h:117`; `storage/session_logs.h:26,31,82,87`; `ui/lua/bindings_process.h:17,50`; `ui/menu/actions.h:143`; `ui/web/ajax_snapshot.h:154`; `ui/web/page_assets.h:44`; `ui/web/routes_command.h:53,63`; `ui/web/routes_program.h:6`; `ui/web/routes_setup.h:190`; `ui/web/template_keys.h:39,133` |
| `3` | `SAMOVAR_BK_MODE` | Бражная колонна. | Lua, external control, loop/orchestration, menu actions, web routes | `Blynk.ino:264`; `app/loop_dispatch.h:80`; `app/orchestration.h:517`; `app/runtime_tasks.h:296,349`; `ui/lua/bindings_process.h:19`; `ui/menu/actions.h:159`; `ui/web/ajax_snapshot.h:222`; `ui/web/page_assets.h:48`; `ui/web/routes_command.h:71` |
| `4` | `SAMOVAR_NBK_MODE` | НБК. | Lua, external control, loop/orchestration, menu actions, mode runtime, storage/profile, web routes | `Blynk.ino:182,266`; `app/default_programs.h:17`; `app/loop_dispatch.h:85`; `app/orchestration.h:522`; `app/runtime_tasks.h:298,351`; `modes/nbk/nbk_runtime.h:345`; `storage/session_logs.h:26,37,82`; `ui/lua/bindings_process.h:21`; `ui/menu/actions.h:167`; `ui/web/ajax_snapshot.h:154,222`; `ui/web/page_assets.h:50`; `ui/web/routes_command.h:57,75`; `ui/web/routes_program.h:12`; `ui/web/template_keys.h:41` |
| `5` | `SAMOVAR_SUVID_MODE` | Су-вид. | external control, loop/orchestration | `Blynk.ino:178`; `app/default_programs.h:13` |
| `6` | `SAMOVAR_LUA_MODE` | Lua-режим. | — | — |

## Samovar_CR_Mode

Samovar_CR_Mode использует тот же enum `SAMOVAR_MODE`, но применяется как канонический режим для web-страницы, Lua-family и NVS-profile namespace.

| Число | Токен | Смысл | Владельцы | Где используется |
| --- | --- | --- | --- | --- |
| `0` | `SAMOVAR_RECTIFICATION_MODE` | Ректификация. | — | — |
| `1` | `SAMOVAR_DISTILLATION_MODE` | Дистилляция. | Lua | `ui/lua/runtime.h:334` |
| `2` | `SAMOVAR_BEER_MODE` | Пиво. | Lua | `ui/lua/runtime.h:332` |
| `3` | `SAMOVAR_BK_MODE` | Бражная колонна. | Lua | `ui/lua/runtime.h:336` |
| `4` | `SAMOVAR_NBK_MODE` | НБК. | Lua | `ui/lua/runtime.h:338` |
| `5` | `SAMOVAR_SUVID_MODE` | Су-вид. | — | — |
| `6` | `SAMOVAR_LUA_MODE` | Lua-режим. | — | — |

### Прямые точки использования Samovar_CR_Mode

| Переменная | Владельцы | Где используется |
| --- | --- | --- |
| `Samovar_CR_Mode` | Lua, loop/orchestration, other, storage/profile, web routes | `Samovar.ino:255`; `state/globals.h:125`; `storage/nvs_migration.h:41,46,51`; `storage/nvs_profiles.h:31,188`; `ui/lua/bindings_variables.h:48,49,111,112`; `ui/lua/runtime.h:332,334,336,338`; `ui/web/page_assets.h:56`; `ui/web/routes_setup.h:88` |

## Связанные флаги

| Флаг | Роль в state-модели | Владельцы | Где используется |
| --- | --- | --- | --- |
| `PowerOn` | Главный флаг питания: меняет трактовку почти всех status/startval и маршрутизацию команд. | Lua, external control, loop/orchestration, menu actions, mode runtime, other, web routes | `Blynk.ino:44,235,256,262,264,266,268`; `Samovar.ino:307`; `app/alarm_control.h:19`; `app/loop_dispatch.h:37,38`; `app/orchestration.h:498,513,518,523,528`; `app/runtime_tasks.h:425`; `app/status_text.h:14,16,19,26,29,35,104,120,127`; `impurity_detector.h:526`; `io/actuators.h:118`; `io/power_control.h:22,134,223,256,271`; `io/sensors.h:74`; `modes/beer/beer_runtime.h:102,109,117,181,221,264`; `modes/bk/bk_alarm.h:22,43,51,60,68`; `modes/bk/bk_runtime.h:19`; `modes/dist/dist_alarm.h:22,28,45,57,64`; `modes/dist/dist_runtime.h:31,35,79`; `modes/nbk/nbk_alarm.h:16,23,31,46,53`; `modes/nbk/nbk_flow_control.h:17`; `modes/nbk/nbk_runtime.h:345,353`; `modes/rect/rect_runtime.h:374,391,479,485,512,533,541`; `state/globals.h:146`; `ui/lua/bindings_process.h:16,17,19,21,23,27`; `ui/lua/bindings_variables.h:157,158`; `ui/lua/runtime.h:42`; `ui/menu/actions.h:144,152,160,168,176,233`; `ui/web/ajax_snapshot.h:95,96,155,229`; `ui/web/routes_command.h:52,64,68,72,76,101,118`; `ui/web/routes_setup.h:62` |
| `PauseOn` | Переводит rect в статус 40 и переключает web/menu pause/continue. | Lua, external control, loop/orchestration, menu actions, mode runtime, other, web routes | `Blynk.ino:53,249`; `Samovar.ino:308`; `app/orchestration.h:503`; `app/status_text.h:16,32`; `impurity_detector.h:322,324,426,446,504`; `io/sensor_scan.h:155`; `modes/rect/rect_runtime.h:84,133,182,183,254`; `state/globals.h:147`; `ui/lua/bindings_variables.h:167,168`; `ui/lua/runtime.h:43`; `ui/menu/actions.h:187,188`; `ui/web/ajax_snapshot.h:97,98`; `ui/web/routes_command.h:147` |
| `program_Wait` | Различает статусы 10 и 15; сбрасывается при continue/manual resume. | Lua, external control, loop/orchestration, menu actions, mode runtime, other | `Blynk.ino:251`; `Samovar.ino:311`; `app/loop_dispatch.h:57`; `app/runtime_tasks.h:267`; `app/status_text.h:16,19`; `impurity_detector.h:332,425,426,428,445,498,504`; `io/sensor_scan.h:156`; `modes/rect/rect_runtime.h:84,86,98,102,133,135,147,151,170,173,253`; `state/globals.h:150`; `ui/lua/bindings_variables.h:169,170`; `ui/lua/runtime.h:46`; `ui/menu/actions.h:193` |
| `program_Pause` | Меняет поведение кнопки/оркестрации для rect-паузы программы. | Lua, loop/orchestration, mode runtime, other | `Samovar.ino:310`; `app/orchestration.h:502,504`; `modes/rect/rect_runtime.h:40,252,331`; `state/globals.h:149`; `ui/lua/runtime.h:45` |
| `stepper.getState()` | Отделяет разгон/stabilization rect от активного отбора. | loop/orchestration, mode runtime, web routes | `app/status_text.h:35`; `io/actuators.h:36,48`; `modes/rect/rect_runtime.h:182`; `ui/web/ajax_snapshot.h:108` |
| `wetting_autostart` | Связывает rect 51 -> 52 с автозапуском голов после смачивания. | loop/orchestration, mode runtime, other | `Samovar.ino:327`; `io/sensor_scan.h:132`; `modes/rect/rect_runtime.h:583,619,620`; `state/globals.h:166` |
| `boil_started` | Уточняет внутреннюю фазу rect при статусе 51. | loop/orchestration, mode runtime, other | `Samovar.ino:317`; `io/actuators.h:102,103,118,188,197`; `io/sensor_scan.h:177`; `io/sensors.h:52,57`; `modes/rect/rect_runtime.h:597,599`; `state/globals.h:156`; `support/process_math.h:80,177` |

## Примечания по baseline

- `50/51/52` существуют только в rect-runtime и появляются не отдельной командой, а через сочетание `PowerOn`, `startval == 0`, `stepper.getState()`, температур и стабилизации.
- `2000/2001/2002` описывают lifecycle режима пива: вход в режим -> разогрев до засыпи -> ожидание засыпи.
- `4000/4001` описывают lifecycle НБК: вход в режим -> запуск первой программы; при этом `SamovarStatusInt` остаётся `4000`, а деталь фазы хранится в `startval`.
