# Baseline contracts

Дата фиксации: 2026-03-09

Назначение: зафиксировать текущие внешние и ключевые внутренние контракты legacy-проекта до начала structural refactor.

Источники:

- `WebServer.ino`
- `Samovar.ino`
- `lua.h`
- `NVS_Manager.ino`
- `logic.h`
- `distiller.h`
- `beer.h`
- `nbk.h`
- `sensorinit.h`

## HTTP endpoints

Основные пользовательские и API endpoints:

- `GET|POST /` — если Wi-Fi не подключен, отдается `wifi.htm`; иначе redirect на `/index.htm`.
- `GET /wifi.htm` — страница настройки Wi-Fi.
- `GET /wifi` — redirect на `/wifi.htm`.
- `POST /wifi/save` — сохраняет Wi-Fi credentials. Параметры: `ssid`, `pass`.
- `POST /wifi/clear` — очищает Wi-Fi credentials.
- `GET /rrlog` — отдает reset reason log.
- `GET /data.csv` — отдает текущий log-файл.
- `GET /ajax` — основной JSON snapshot состояния.
- `GET /command` — command endpoint с query-параметрами.
- `POST /program` — загрузка и чтение текущей программы режима.
- `GET /ajax_col_params` — расчет параметров колонны. Параметр: `mat`.
- `GET /calibrate` — endpoint калибровки шаговика и I2C насоса.
- `GET /i2cpump` — прямое управление I2C pump.
- `GET /getlog` — скачать `data.csv`.
- `GET /getoldlog` — скачать `data_old.csv`.
- `GET /lua` — инициировать запуск Lua script task.
- `POST /save` — сохранить форму настроек и при необходимости сменить режим.

Поддерживаемые команды `GET /command`:

- `start`
- `power`
- `setbodytemp`
- `reset`
- `reboot`
- `resetwifi`
- `startst`
- `rescands`
- `stopst`
- `mixer`
- `pnbk`
- `nbkopt`
- `distiller`
- `startbk`
- `startnbk`
- `watert`
- `pumpspeed`
- `pause`
- `voltage`
- `lua`
- `luastr`

Контракт `POST /program`:

- Вход: `WProgram`
- Дополнительные параметры: `vless`, `Descr`
- Выход: текущая строка программы выбранного режима

Контракт `GET /ajax_col_params`:

- Вход: `mat`
- Выходные ключи: `floodPowerW`, `workingPowerW`, `maxFlowMlH`, `theoreticalPlates`, `headsFlowMlH`, `bodyFlowMinMlH`, `bodyFlowMaxMlH`, `bodyEndFlowMlH`, `tailsFlowMlH`, `headsPowerW`, `bodyEndPowerW`, `tailsPowerW`

Контракт `GET /i2cpump`:

- Остановка: `stop`
- Запуск: `speed`, `volume`

Контракт `POST /save`:

- Задержки: `SteamDelay`, `PipeDelay`, `WaterDelay`, `TankDelay`, `ACPDelay`
- Delta-температуры: `DeltaSteamTemp`, `DeltaPipeTemp`, `DeltaWaterTemp`, `DeltaTankTemp`, `DeltaACPTemp`
- Set-температуры: `SetSteamTemp`, `SetPipeTemp`, `SetWaterTemp`, `SetTankTemp`, `SetACPTemp`
- PID/power: `Kp`, `Ki`, `Kd`, `StbVoltage`, `BVolt`, `CheckPower`, `UseST`
- Process/settings: `DistTimeF`, `MaxPressureValue`, `StepperStepMl`, `StepperStepMlI2C`, `stepperstepml`, `WProgram`, `mode`
- Bool flags: `useflevel`, `usepressure`, `useautospeed`, `useDetectorOnHeads`, `ChangeProgramBuzzer`, `UseBuzzer`, `UseBBuzzer`, `UseWS`
- Nbk: `NbkIn`, `NbkDelta`, `NbkDM`, `NbkDP`, `NbkSteamT`, `NbkOwPress`
- Visual/tokens: `videourl`, `blynkauth`, `tgtoken`, `tgchatid`, `SteamColor`, `PipeColor`, `WaterColor`, `TankColor`, `ACPColor`
- Relays: `rele1`, `rele2`, `rele3`, `rele4`
- Sensor addresses: `SteamAddr`, `PipeAddr`, `WaterAddr`, `TankAddr`, `ACPAddr`
- Column params: `ColDiam`, `ColHeight`, `PackDens`

## /ajax JSON keys

Текущие ключи snapshot:

- `bme_temp`
- `bme_pressure`
- `start_pressure`
- `crnt_tm`
- `stm`
- `SteamTemp`
- `PipeTemp`
- `WaterTemp`
- `TankTemp`
- `ACPTemp`
- `DetectorTrend`
- `DetectorStatus`
- `useautospeed`
- `version`
- `VolumeAll`
- `ActualVolumePerHour`
- `PowerOn`
- `PauseOn`
- `WthdrwlProgress`
- `TargetStepps`
- `CurrrentStepps`
- `WthdrwlStatus`
- `CurrrentSpeed`
- `UseBBuzzer`
- `StepperStepMl`
- `BodyTemp_Steam`
- `BodyTemp_Pipe`
- `mixer`
- `ISspd`
- `i2c_pump_present`
- `i2c_pump_speed`
- `i2c_pump_target_ml`
- `i2c_pump_remaining_ml`
- `i2c_pump_running`
- `heap`
- `rssi`
- `fr_bt`
- `PrgType`
- `Msg`
- `msglvl`
- `LogMsg`
- `current_power_volt`
- `target_power_volt`
- `current_power_mode`
- `current_power_p`
- `wp_spd`
- `WFflowRate`
- `WFtotalMl`
- `prvl`
- `alc`
- `stm_alc`
- `TimeRemaining`
- `TotalTime`
- `Status`
- `Lstatus`

Примечание:

- `Msg` и `LogMsg` являются одноразовыми: после выдачи через `/ajax` очищаются.

## Lua API names

Зарегистрированные Lua names:

- `pinMode`
- `digitalWrite`
- `digitalRead`
- `analogRead`
- `exp_pinMode`
- `exp_digitalWrite`
- `exp_digitalRead`
- `exp_analogWrite`
- `exp_analogRead`
- `delay`
- `millis`
- `sendMsg`
- `setPower`
- `setBodyTemp`
- `setAlarm`
- `setNumVariable`
- `setStrVariable`
- `setObject`
- `setLuaStatus`
- `setPumpPwm`
- `setCurrentPower`
- `setMixer`
- `setNextProgram`
- `setPauseWithdrawal`
- `setTimer`
- `setCapacity`
- `openValve`
- `getNumVariable`
- `getStrVariable`
- `getState`
- `getObject`
- `getTimer`
- `http_request`
- `check_I2C_device`
- `set_stepper_by_time`
- `set_stepper_target`
- `get_stepper_status`
- `i2cpump_start`
- `i2cpump_stop`
- `i2cpump_get_speed`
- `i2cpump_get_target_ml`
- `i2cpump_get_remaining_ml`
- `i2cpump_get_running`
- `set_mixer_pump_target`
- `get_mixer_pump_status`
- `get_i2c_rele_state`
- `set_i2c_rele_state`

## NVS namespaces and keys

Namespaces профилей:

- `sam_rect`
- `sam_beer`
- `sam_dist`
- `sam_bk`
- `sam_nbk`
- `sam_suvid`
- `sam_lua`

Meta namespace:

- `sam_meta`
- key: `last_mode`
- key: `migrated`

Wi-Fi credentials:

- используются стандартные сохраненные credentials ESP32 через `WiFi.persistent(true)`
- отдельный namespace в коде Samovar не задается

Ключи в профильном namespace:

- Основные: `flag`, `Mode`, `TimeZone`, `HeaterR`, `LogPeriod`
- Set temperatures: `SetSteam`, `SetPipe`, `SetWater`, `SetTank`, `SetACP`, `DistTemp`
- Delta temperatures: `DeltaSteam`, `DeltaPipe`, `DeltaWater`, `DeltaTank`, `DeltaACP`
- Delays: `SteamDelay`, `PipeDelay`, `WaterDelay`, `TankDelay`, `ACPDelay`
- Stepper and pump: `StepMl`, `StepMlI2C`, `AutoSpeed`, `DetOnHeads`, `SpeedPerc`, `UseWS`
- PID and power: `Kp`, `Ki`, `Kd`, `StbVolt`, `BVolt`, `CheckPwr`, `UseST`
- Relays: `rele1`, `rele2`, `rele3`, `rele4`
- Sensor addresses: `SteamAddr`, `PipeAddr`, `WaterAddr`, `TankAddr`, `ACPAddr`
- Visual and credentials: `SteamCol`, `PipeCol`, `WaterCol`, `TankCol`, `ACPCol`, `blynk`, `video`, `tg_tok`, `tg_id`
- Additional: `Preccure`, `PrgBuzz`, `UseBuzz`, `UseBBuzz`, `DistTimeF`, `UseHLS`, `MaxPress`
- Nbk: `NbkIn`, `NbkDelta`, `NbkDM`, `NbkDP`, `NbkSteamT`, `NbkOwPress`
- Column params: `ColDiam`, `ColHeight`, `PackDens`

## Status codes

`SamovarStatusInt` baseline значения:

- `0` — питание выключено, активного процесса нет
- `10` — rect: выполняется строка программы
- `15` — rect: пауза ожидания внутри программы
- `20` — rect: выполнение программы завершено
- `30` — калибровка
- `40` — пауза
- `50` — разгон колонны
- `51` — разгон завершен, стабилизация или работа на себя
- `52` — стабилизация завершена или работа на себя
- `1000` — режим дистилляции
- `2000` — режим пива
- `3000` — режим бражной колонны
- `4000` — режим НБК

Сопутствующие значения `startval`, которые участвуют в поведении:

- `0` — idle или heatup
- `1` — rect: программа выполняется
- `2` — rect: программа завершена
- `100` — калибровка
- `1000` — запуск dist
- `2000` — запуск beer
- `2001` — beer: разогрев до засыпи солода
- `2002` — beer: ожидание засыпи солода
- `3000` — запуск bk
- `4000` — запуск nbk
- `4001` — nbk: активная строка программы

## Program string formats

Rectification format:

- Строка: `type;volume;speed;capacity;temp;power`
- Разделитель строк: `\n`
- Разрешенные типы по текущей логике: `H`, `B`, `T`, `C`, `P`
- Пример default: `H;450;0.1;1;0;45`

Distillation format:

- Строка: `type;speed;capacity;power`
- Разделитель строк: `\n`
- Разрешенные типы по текущей логике: `T`, `A`, `S`, `P`, `R`
- Пример default: `A;80.00;1;0`

Beer format:

- Строка: `type;temp;time;device^speed^on^off;sensor`
- Разделитель строк: `\n`
- Разрешенные типы по текущей логике: `M`, `P`, `B`, `C`, `F`, `W`, `A`, `L`
- Пример default: `M;45;0;0^-1^2^2;0`

NBK format:

- Строка: `type;speed;power`
- Разделитель строк: `\n`
- Разрешенные типы по текущей логике: `H`, `S`, `O`, `W`
- Default value задается константой `NBK_DEFAULT_PROGRAM`

## not_done

- Полный список query/form fields для каждой HTML-страницы интерфейса не нормализован в отдельную таблицу page-by-page. Для текущей фазы зафиксированы endpoint contracts и именованные параметры, которые реально обрабатываются в firmware-коде.
