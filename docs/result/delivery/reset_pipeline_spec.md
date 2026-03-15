# Шаг 2.4. Reset Pipeline Spec

## Outcome

### 1. Уровни reset-пайплайна

| Уровень | Entry point | Что делает | Код |
| --- | --- | --- | --- |
| Runtime reset | `reset_sensor_counter()` | Сбрасывает runtime state, stepper, I2C pump, sensor counters, временные флаги, status/startval и Lua status string | `io/sensor_scan.h:109-200` |
| Menu/UI reset | `samovar_reset()` | Переводит menu/UI в экран остановки и делегирует runtime cleanup в `reset_sensor_counter()` | `ui/menu/actions.h:272-280` |
| Full mode-switch reset | `handleSaveProcessSettings()` | Гасит активный режим, останавливает Lua loop, вызывает `samovar_reset()`, меняет режим, перезагружает профиль/дефолтную программу/Lua script и перевязывает `indexHandler` | `ui/web/routes_setup.h:52-100` |
| Command-triggered reset | `process_sam_command_sync()` при `SAMOVAR_RESET` | Делегирует в `samovar_reset()` без смены профиля и без rebinding web route | `app/loop_dispatch.h:20-44` |

### 2. Полная последовательность mode-switch reset

1. `handleSaveProcessSettings()` проверяет, что `mode` действительно меняется; при одинаковом режиме pipeline не запускается.
   Код: `ui/web/routes_setup.h:52-60`
2. Если режим активен (`PowerOn`), вызывается mode-specific finisher по `SamovarStatusInt` (`distiller_finish/beer_finish/bk_finish/nbk_finish`) либо generic `set_power(false)` для rect/generic branch.
   Код: `ui/web/routes_setup.h:62-74`
3. Если включён loop Lua (`loop_lua_fl`), выставляется `SetScriptOff = true`, loop останавливается через `loop_lua_fl = false`, затем даётся `delay(100)` на остановку текущего цикла.
   Код: `ui/web/routes_setup.h:76-82`
4. Выполняется `samovar_reset()`: menu/UI возвращается в экран остановки и далее вызывается `reset_sensor_counter()`.
   Код: `ui/web/routes_setup.h:84`, `ui/menu/actions.h:272-280`
5. Новый режим становится каноническим: `SamSetup.Mode = nextMode`, `Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode`, `Samovar_CR_Mode = Samovar_Mode`.
   Код: `ui/web/routes_setup.h:86-88`
6. Для нового режима загружается программа по умолчанию.
   Код: `ui/web/routes_setup.h:90`
7. Текущий профиль сохраняется в namespace, вычисленный от `Samovar_CR_Mode`, затем немедленно читается обратно через `load_profile_nvs()`.
   Код: `ui/web/routes_setup.h:91-92`, `storage/nvs_profiles.h:30-36`, `storage/nvs_profiles.h:80-183`, `storage/nvs_profiles.h:185-205`
8. Lua-family перенастраивается на новый режим: вычисляется `lua_type_script = get_lua_mode_name(true)`, затем обновляются `script1/script2` через `load_lua_script()`.
   Код: `ui/web/routes_setup.h:94-97`, `ui/lua/runtime.h:269-272`, `ui/lua/runtime.h:330-343`
9. Web root route перевязывается: старый `indexHandler` удаляется, создаётся новый `serveStatic("/index.htm", ...)`, затем `Samovar_CR_Mode` синхронизируется с итоговым `Samovar_Mode`.
   Код: `ui/web/routes_setup.h:99`, `ui/web/page_assets.h:38-57`

### 3. Детализация runtime reset (`reset_sensor_counter`)

#### Runtime status reset

- Сразу очищается очередь команд: `sam_command_sync = SAMOVAR_NONE`.
- `SamovarStatusInt = 0`, `startval = 0`.
- `PauseOn = false`, `program_Wait = false`, `is_self_test = false`.
- Пересчитывается статус через `get_Samovar_Status()`.

Код: `io/sensor_scan.h:110`, `io/sensor_scan.h:152-169`, `io/sensor_scan.h:187-189`

#### Power / stepper / I2C pump cleanup

- Останавливается сервис шаговика: `stopService()`.
- Stepper переводится в нулевое состояние: `setMaxSpeed(0)`, `brake()`, `disable()`, `setCurrent(0)`, `setTarget(0)`.
- Сбрасывается текущая ёмкость: `set_capacity(0)`.
- Отключается питание: `set_power(false)`.
- Очищаются I2C-pump state fields: `I2CPumpTargetSteps`, `I2CPumpTargetMl`, `I2CPumpCmdSpeed`, `I2CPumpCalibrating`.

Код: `io/sensor_scan.h:111-118`, `io/sensor_scan.h:159-163`, `io/sensor_scan.h:187`

#### Sensor counters / process metrics cleanup

- Сбрасываются alarm timers и временные счётчики (`alarm_h_min`, `alarm_t_min`, `alarm_c_min`, `alarm_c_low_min`, `t_min`, `d_s_time_min`, `b_t_time_min`, `b_t_time_delay`, `d_s_temp_prev`, `d_s_temp_finish`).
- Сбрасываются process counters (`ProgramNum`, `WthdrwlProgress`, `TargetStepps`, `ActualVolumePerHour`, `begintime`).
- Сбрасываются `BodyTemp/PrevTemp/Start_Pressure` у всех датчиков.
- Закрывается текущий лог-файл `fileToAppend`, если он открыт.
- Обновляется базовое давление (`start_pressure = bme_pressure`), при необходимости вызывается `BME_getvalue(false)`.

Код: `io/sensor_scan.h:119-180`

#### Lua state reset

- В runtime reset обнуляется `Lua_status`.
- В full mode-switch path до `samovar_reset()` останавливается loop Lua: `SetScriptOff = true`, `loop_lua_fl = false`, `delay(100)`.
- После смены режима подгружается новый mode-specific script через `get_lua_mode_name(true)` и `load_lua_script()`.

Код: `ui/web/routes_setup.h:76-82`, `io/sensor_scan.h:197-199`, `ui/web/routes_setup.h:94-97`, `ui/lua/runtime.h:269-272`, `ui/lua/runtime.h:330-343`

### 4. Menu/UI reset side effects

- `power_text_ptr` возвращается к `menu_text_power_on`.
- `reset_focus()` очищает menu focus.
- `set_menu_screen(3)` переводит UI в экран остановки.
- Очередь команд после `reset_sensor_counter()` ещё раз фиксируется в `SAMOVAR_NONE`.

Код: `ui/menu/actions.h:276-280`

### 5. Profile save/load sequence

1. `save_profile_nvs()` сохраняет `SamSetup` в namespace, вычисленный через `current_profile_namespace()`, который читает `Samovar_CR_Mode`.
2. После `prefs.end()` вызывается `write_last_mode_meta((uint8_t)SamSetup.Mode)`.
3. `load_profile_nvs()` сначала читает `last_mode` из `sam_meta`, пишет его в `Samovar_CR_Mode`, а затем открывает namespace этого режима и загружает `SamSetup`.
4. `read_config()` всегда стартует с `load_profile_nvs()`, после чего синхронизирует `Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode`.

Код: `storage/nvs_profiles.h:30-36`, `storage/nvs_profiles.h:80-183`, `storage/nvs_profiles.h:185-205`, `app/config_apply.h:11-33`

### 6. Route rebinding

- `change_samovar_mode()` удаляет старый `indexHandler`, если он уже был создан.
- Затем перевязывает `/index.htm` на mode-specific page: `beer.htm`, `distiller.htm`, `bk.htm`, `nbk.htm` или `index.htm` для rect/fallback.
- В fallback-ветке `Samovar_Mode` принудительно нормализуется в `SAMOVAR_RECTIFICATION_MODE`.
- После rebinding `Samovar_CR_Mode = Samovar_Mode`.

Код: `ui/web/page_assets.h:38-57`

## Ограничения

- Numeric state-коды и enum-значения не меняются.
- HTTP/JSON/Lua/Menu contracts не меняются.
- Этот spec описывает именно reset/mode-switch pipeline; boot-time init из `ui/web/server_init.h:164-166` не считается mode-switch reset, потому что выполняется в startup path до полноценной runtime-активности.

## Проверки

- Regression test: `python3 tools/tests/test_reset_pipeline_invariant.py`
- Regression log: `docs/result/delivery/step2_regression_log.md`
- Build check: `pio run -e Samovar`
