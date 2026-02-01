# Модули

```markdown
# Модули

Модуль реализует логику управления процессом дистилляции в устройстве "Самовар", включая контроль нагрева, насоса, клапанов, сбор данных и прогнозирование времени. Поддерживает работу с датчиками, ПИД-регулирование скорости насоса, обработку аварийных ситуаций и взаимодействие с пользователем через сообщения. Интегрирован с внешними системами (MQTT) и обеспечивает сохранение данных сессии.

## Ключевые структуры данных

- `TimePredictor` — Структура для прогнозирования оставшегося и общего времени дистилляции на основе изменения температуры и спиртуозности.
- `QualityParams` — Структура, содержащая оценку качества процесса дистилляции, включая общий балл и рекомендации.
- `program` — Массив структур, определяющих этапы дистилляции (тип, скорость, ёмкость, мощность).
- `timePredictor` — Экземпляр `TimePredictor` для хранения данных прогнозирования времени завершения этапа.

## Основные функции

### Управление процессом
- `distiller_finish()` — Завершает процесс: отключает нагрев, формирует сообщение о времени работы и останавливает процесс.
- `stop_process(String message)` — Останавливает текущий технологический процесс и отправляет завершающее сообщение.
- `_program(0)` — Инициализирует состояние дистилляции и сбрасывает прогноз времени.

### Управление нагревом
- `set_power(bool On)` — Включает или отключает подачу мощности на нагреватель.
- `set_power_mode(String Mode)` — Устанавливает режим питания устройства (например, "speed", "power").
- `set_current_power(float power)` — Устанавливает текущее значение мощности нагрева в ваттах.
- `set_current_power(float voltage)` — Устанавливает целевое напряжение на нагреватель для регулирования мощности.

### Управление насосом
- `set_pump_pwm(float duty)` — Устанавливает значение ШИМ для управления насосом (0.0–1.0).
- `set_pump_pwm(int pwmValue)` — Устанавливает ШИМ-сигнал для управления скоростью водяного насоса (0–255).
- `set_pump_speed(float speed, bool msg)` — Устанавливает скорость насоса вручную.
- `set_pump_speed_pid(float temp)` — Устанавливает скорость насоса на основе ПИД-регулирования по целевой температуре.

### Управление клапанами
- `open_valve(bool Val, bool msg)` — Открывает или закрывает клапан подачи пара.
- `open_valve(bool open, bool force)` — Открывает или закрывает клапан подачи охлаждающей воды (с опцией игнорирования блокировок).

### Программирование процесса
- `set_dist_program(String WProgram)` — Устанавливает программу дистилляции из строки в формате, определённом протоколом.
- `get_dist_program()` — Возвращает текущую программу дистилляции в виде строки.
- `run_dist_program(uint8_t num)` — Переходит к выполнению указанной строки программы дистилляции.

### Прогнозирование времени
- `resetTimePredictor()` — Сбрасывает и инициализирует таймер прогнозирования времени начала и завершения дистилляции.
- `updateTimePredictor()` — Обновляет внутренний прогноз времени завершения процесса дистилляции на основе текущих температур.
- `update_distillation_time_prediction(float dS, float alcoholChangeRate, float currentTime)` — Обновляет предиктор времени дистилляции на основе текущих данных.
- `get_dist_remaining_time()` — Возвращает расчётное оставшееся время дистилляции в минутах.
- `get_dist_predicted_total_time()` — Возвращает расчётное общее время дистилляции в минутах.

### Сбор данных и сенсоры
- `create_data()` — Создаёт файл для записи данных текущей сессии дистилляции.
- `get_liquid_volume()` — Возвращает текущий объём жидкости в приёмнике в миллилитрах.
- `reset_sensor_counter()` — Сбрасывает счётчики импульсов с датчиков расхода.
- `set_body_temp()` — Устанавливает текущую температуру тела колонны на основе данных с датчика.

### Обработка аварий
- `check_alarm_distiller()` — Проверяет наличие аварийных ситуаций (перегрев, ошибки датчиков и т.п.).
- `check_power_error()` — Проверяет наличие ошибок в цепи питания и при необходимости отключает нагрев.
- `check_water_temp()` — Проверяет температуру воды и при превышении порога инициирует аварийные действия.

### Взаимодействие с пользователем
- `SendMsg(const String& m, MESSAGE_TYPE msg_type)` — Отправляет сообщение пользователю через доступные интерфейсы (например, MQTT, дисплей).
- `set_buzzer(bool On)` — Включает или выключает звуковой сигнал (бuzzer).
- `get_Samovar_Status()` — Возвращает текстовое описание текущего статуса устройства.

### Расчётные функции
- `get_alcohol(float t)` — Рассчитывает спиртуозность дистиллята по температуре пара.
- `get_steam_alcohol(float t)` — Рассчитывает спиртуозность пара по температуре.
- `get_speed_from_rate(float rate)` — Рассчитывает скорость насоса на основе текущего расхода.

### Управление ёмкостями
- `set_capacity(uint8_t cap)` — Устанавливает активную ёмкость для сбора дистиллята.
```

## Список модулей

- [modules/BK__h](BK__h.md)
- [modules/Blynk__ino](Blynk__ino.md)
- [modules/FS__ino](FS__ino.md)
- [modules/I2CStepper__h](I2CStepper__h.md)
- [modules/Menu__ino](Menu__ino.md)
- [modules/NVS_Manager__ino](NVS_Manager__ino.md)
- [modules/SPIFFSEditor__h](SPIFFSEditor__h.md)
- [modules/SamovarMqtt__h](SamovarMqtt__h.md)
- [modules/Samovar__h](Samovar__h.md)
- [modules/Samovar__ino](Samovar__ino.md)
- [modules/Samovar_ini__h](Samovar_ini__h.md)
- [modules/Samovar_pin__h](Samovar_pin__h.md)
- [modules/WebServer__ino](WebServer__ino.md)
- [modules/beer__h](beer__h.md)
- [modules/column_math__h](column_math__h.md)
- [modules/crash_handler__h](crash_handler__h.md)
- [modules/crash_handler__ino](crash_handler__ino.md)
- [modules/data/beer__htm](data/beer__htm.md)
- [modules/data/bk__htm](data/bk__htm.md)
- [modules/data/brewxml__htm](data/brewxml__htm.md)
- [modules/data/calibrate__htm](data/calibrate__htm.md)
- [modules/data/chart__htm](data/chart__htm.md)
- [modules/data/distiller__htm](data/distiller__htm.md)
- [modules/data/edit__htm](data/edit__htm.md)
- [modules/data/index__htm](data/index__htm.md)
- [modules/data/nbk__htm](data/nbk__htm.md)
- [modules/data/program__htm](data/program__htm.md)
- [modules/data/setup__htm](data/setup__htm.md)
- [modules/data/style__css](data/style__css.md)
- [modules/data/wifi__htm](data/wifi__htm.md)
- [modules/distiller__h](distiller__h.md)
- [modules/font__h](font__h.md)
- [modules/impurity_detector__h](impurity_detector__h.md)
- [modules/logic__h](logic__h.md)
- [modules/lua__h](lua__h.md)
- [modules/mod_rmv__ino](mod_rmv__ino.md)
- [modules/mod_rmvk__h](mod_rmvk__h.md)
- [modules/nbk__h](nbk__h.md)
- [modules/partition_manager__py](partition_manager__py.md)
- [modules/pumppwm__h](pumppwm__h.md)
- [modules/quality__h](quality__h.md)
- [modules/sensorinit__h](sensorinit__h.md)
- [modules/wifi_htm_gz__h](wifi_htm_gz__h.md)
