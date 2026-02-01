# Модули

```markdown
# Модули

## Управление дистилляцией
Модуль реализует полный цикл управления процессом дистилляции: контроль нагрева, насоса, клапанов, сбор данных и прогнозирование времени завершения. Поддерживает ПИД-регулирование, аварийные сценарии и интеграцию с MQTT.

### Основные функции
- `set_power(bool On)` — включение/выключение нагрева.
- `set_power_mode(String Mode)` — выбор режима питания (`"speed"`, `"power"`).
- `set_pump_pwm(float duty)` — установка ШИМ насоса (0–100%).
- `set_pump_speed_pid(float temp)` — ПИД-управление скоростью насоса по температуре.
- `open_valve(bool Val, bool msg)` — управление клапаном подачи пара.
- `create_data()` — инициализация файла логирования сессии.
- `distiller_finish()` — завершение процесса, отключение нагрева, сброс счётчиков.

### Прогнозирование времени
Реализовано через структуру `TimePredictor`, которая анализирует динамику температуры и спиртуозности.

- `resetTimePredictor()` — сброс данных прогноза.
- `updateTimePredictor()` — обновление на основе текущих данных.
- `get_dist_remaining_time()` — оставшееся время (мин).
- `get_dist_predicted_total_time()` — общее прогнозируемое время (мин).

### Сбор данных и контроль
- `get_liquid_volume()` — текущий объём дистиллята (мл).
- `get_alcohol(float t)` — расчёт спиртуозности по температуре кипения.
- `get_steam_alcohol(float t)` — расчёт спиртуозности пара.
- `set_capacity(uint8_t cap)` — выбор ёмкости для сбора.
- `check_alarm_distiller()` — проверка аварий (перегрев, давление, датчики).
- `set_buzzer(bool On)` — управление звуковой сигнализацией.

### Управление программами
- `set_dist_program(String WProgram)` — установка программы дистилляции.
- `run_dist_program(uint8_t num)` — переход к этапу.
- `get_dist_program()` — получение текущей программы.

---

## Lua-скрипты
Модуль обеспечивает выполнение пользовательских Lua-скриптов для гибкого управления устройством. Поддерживает доступ к GPIO, I2C, насосам, шаговым двигателям и системным переменным.

### Ключевые структуры
- `luaObj` — хранилище пользовательских переменных (ключ-значение).
- `SAMOVAR_MODE` — режимы работы (`dist`, `rect`, `beer` и др.).
- `lua_timer` — 9 таймеров для отложенных задач.

### Обёртки для Lua
- `lua_wrapper_pinMode`, `digitalWrite`, `digitalRead`, `analogRead` — доступ к GPIO.
- `lua_wrapper_exp_*` — аналогичные функции для I2C-расширителей.
- `lua_wrapper_set_power`, `open_valve`, `set_pump_pwm` — управление процессом.
- `lua_wrapper_set_samovar_mode` — смена режима.
- `lua_wrapper_set_mixer`, `set_stepper_*` — управление шаговыми двигателями.
- `lua_wrapper_http_request` — выполнение HTTP-запросов.
- `lua_wrapper_i2cpump_*` — управление I2C-насосами.

### Работа со скриптами
- `get_lua_script_list()` — список доступных скриптов.
- `get_lua_script(String fn)` — чтение скрипта из SPIFFS.
- `run_lua_script(String fn)` — запуск скрипта.
- `run_lua_string(String lstr)` — выполнение кода из строки.
- `do_lua_script()` — фоновая задача FreeRTOS для выполнения скриптов.

---

## Детектор примесей
Модуль анализирует температурный тренд в колонне для автоматического обнаружения примесей и управления паузами отбора.

### Основные функции
- `init_impurity_detector()` — инициализация.
- `reset_impurity_detector()` — полный сброс состояния.
- `detector_on_program_start(const String& wtype)` — обработка старта программы (с грейс-периодом).
- `detector_on_manual_resume()` / `auto_resume()` — реакция на возобновление отбора.

### Анализ температуры
- `update_detector_history(float columnTemp)` — обновление истории.
- `calculate_temperature_trend()` — расчёт тренда (°C/мин) методом линейной регрессии.
- `calculate_temperature_variance()` — вычисление дисперсии для фильтрации шума.
- `check_consecutive_rises(float currentTemp)` — подсчёт последовательных ростов >0.02 °C.
- `get_adaptive_threshold()` — расчёт порога с учётом фазы процесса и скорости отбора.

- `process_impurity_detector()` — основной цикл анализа и принятия решений.

---

## Оценка качества дистилляции
Модуль вычисляет комплексную оценку качества на основе температуры пара и стабильности процесса.

### Параметры
- `IDEAL_STEAM_TEMP` — идеальная температура пара для этанола.
- `TEMP_TOLERANCE` — допустимое отклонение.
- `STABILITY_WINDOW_SIZE` — размер окна анализа стабильности (сек).

### Оценки
- `calculateStabilityScore()` — оценка стабильности (0–100).
- `calculateTempScore()` — соответствие идеальной температуре.
- `calculateAlcoholScore()` — качество спирта с учётом примесей.

- `getQualityAssessment()` — возвращает структуру `QualityParams` с оценками и рекомендацией.

---

## Управление НБК
Модуль автоматизирует процесс в непрерывной барботажной колонне по конечному автомату: разгон, ручной режим, оптимизация, рабочий режим.

### Этапы
- `handle_nbk_stage_heatup()` — разгон до рабочих температур.
- `handle_nbk_stage_manual()` — ручная настройка.
- `handle_nbk_stage_optimization()` — автоматическая подстройка.
- `handle_nbk_stage_work()` — стабильная работа с ПИД-регулированием.

### Контроль и защита
- `check_nbk_critical_alarms()` — проверка перегрева, давления, охлаждения.
- `handle_overflow()` — обработка захлёба (пауза или остановка).
- `nbk_finish()` — завершение сессии, отправка статистики.

### Статистика
- `stats.avgSpeed`, `totalVolume`, `startTime` — сбор данных по сессии.

---

## Управление шаговым двигателем (I2C)
Модуль обеспечивает синхронизированный доступ к I2C-двигателю через семафор FreeRTOS.

### Основные функции
- `set_stepper_target(spd, dir, target)` — движение на заданное число шагов.
- `set_stepper_by_time(spd, dir, time)` — работа в течение времени.
- `get_stepper_speed()`, `get_stepper_status()` — текущие параметры.

### Расчёт объёма
- `get_liquid_volume_by_step()`, `get_liquid_rate_by_step()` — шаги → мл, мл/ч.
- `get_speed_from_rate()` — мл/ч → шаги/с.

### Управление реле и насосом
- `set_i2c_rele_state()`, `get_i2c_rele_state()` — работа с реле.
- `set_mixer_pump_target()`, `get_mixer_pump_status()` — управление насосом смесителя.

---

## Конфигурация пинов (`samovar_pin.h`)
Модуль автоматически подбирает распиновку под плату: ESP32S3, LILYGO T-RELAY, ESP32 DEVKIT.

### Ключевые пины
- `ENC_CLK`, `ENC_DT`, `ENC_SW` — энкодер.
- `STEPPER_STEP`, `DIR`, `EN` — шаговый двигатель.
- `RELE_CHANNEL1–4` — реле (нагрев, клапан, мешалка).
- `ONE_WIRE_BUS` — датчики DS18B20.
- `LCD_SDA`, `LCD_SCL` — I2C-дисплей.
- `WATER_PUMP_PIN` — ШИМ насоса охлаждения.
- `BZZ_PIN` — зуммер.

### Параметры
- `STEPPER_STEPS`, `STEPPER_STEP_ML` — калибровка двигателя.
- `LCD_ADDRESS`, `LCD_COLUMNS`, `ROWS` — настройки дисплея.
- `CAPACITY_NUM` — количество ёмкостей.
- `TARGET_WATER_TEMP` — целевая температура охлаждения.
```

## Список модулей

- [modules/BK](BK.md)
- [modules/I2CStepper](I2CStepper.md)
- [modules/SPIFFSEditor](SPIFFSEditor.md)
- [modules/Samovar](Samovar.md)
- [modules/SamovarMqtt](SamovarMqtt.md)
- [modules/Samovar_ini](Samovar_ini.md)
- [modules/Samovar_pin](Samovar_pin.md)
- [modules/beer](beer.md)
- [modules/column_math](column_math.md)
- [modules/crash_handler](crash_handler.md)
- [modules/distiller](distiller.md)
- [modules/font](font.md)
- [modules/impurity_detector](impurity_detector.md)
- [modules/logic](logic.md)
- [modules/lua](lua.md)
- [modules/mod_rmvk](mod_rmvk.md)
- [modules/nbk](nbk.md)
- [modules/partition_manager](partition_manager.md)
- [modules/pumppwm](pumppwm.md)
- [modules/quality](quality.md)
- [modules/sensorinit](sensorinit.md)
- [modules/wifi_htm_gz](wifi_htm_gz.md)
