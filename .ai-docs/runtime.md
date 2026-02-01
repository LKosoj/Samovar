# Запуск и окружение

## Требования к окружению

Для сборки и запуска прошивки "Самовар" требуется:

- **Платформа**: ESP32 (поддерживаются модели: DEVKIT, LILYGO T-RELAY, ESP32S3).
- **Среда разработки**: PlatformIO (рекомендуется) или Arduino IDE.
- **Фреймворк**: Arduino Core для ESP32.
- **Файловая система**: LittleFS или SPIFFS (настраивается через `USE_LittleFS`).
- **Память**: Минимум 4 МБ Flash, из которых до 1.6 МБ выделяется под прошивку (настраивается в `partitions/samovar.csv`).

## Конфигурация сборки

Основная конфигурация задаётся в `platformio.ini`:

```ini
[env:Samovar]
platform = espressif32
board = doit-devkit-v1
framework = arduino
build_type = release
build_flags = -Os -ffunction-sections -fdata-sections -Wl,--gc-sections
board_build.f_cpu = 240000000L
board_build.f_flash = 80000000L
board_build.flash_mode = dio
monitor_speed = 115200
lib_ignore = *
lib_deps = ...
```

Ключевые параметры:
- `build_type = release` — сборка с оптимизацией размера.
- `board_build.f_cpu = 240000000L` — частота CPU 240 МГц.
- `monitor_speed = 115200` — скорость отладочного порта.
- `lib_ignore = *` — игнорирование стандартных библиотек, подключение только указанных.

## Аппаратная конфигурация

Распиновка задаётся в `samovar_pin.h`. Автоматически определяется тип платы по макросам Arduino. Поддерживаются:
- `ESP32S3`
- `LILYGO T-RELAY`
- `ESP32 DEVKIT` (по умолчанию)

Пример конфигурации для DEVKIT:
```c
#define ONE_WIRE_BUS 15
#define STEPPER_STEP 26
#define STEPPER_DIR 27
#define STEPPER_EN 14
#define RELE_CHANNEL1 2
#define RELE_CHANNEL2 4
#define RELE_CHANNEL3 16
#define RELE_CHANNEL4 17
#define ENC_CLK 34
#define ENC_DT 35
#define ENC_SW 32
#define LCD_SDA 21
#define LCD_SCL 22
#define LCD_ADDRESS 0x27
```

## Условная компиляция

Функциональность включается через макросы в `Samovar_ini.h` и `user_config_override.h`:

| Макрос | Назначение |
|-------|-----------|
| `USE_LUA` | Включение интерпретатора Lua |
| `USE_MQTT` | Поддержка MQTT-клиента |
| `USE_TELEGRAM` | Интеграция с Telegram |
| `USE_WEB_SERIAL` | Включение WebSerial |
| `SAMOVAR_USE_BLYNK` | Поддержка Blynk |
| `USE_WATER_PUMP` | Управление водяным насосом |
| `USE_STEPPER_ACCELERATION` | Ускорение шагового двигателя |
| `USE_CRASH_HANDLER` | Обработчик сбоев и стектрейсов |
| `USE_UPDATE_OTA` | OTA-обновления |

## Инициализация системы

При старте выполняется:
1. **Миграция данных**: Перенос настроек из EEPROM в NVS (если флаг миграции ≤ 250).
2. **Загрузка конфигурации**: Чтение `SamSetup` из NVS, применение значений по умолчанию при отсутствии.
3. **Инициализация периферии**:
   - Датчики температуры (DS18B20), давления (BME, XGZ).
   - Дисплей (LiquidCrystal_I2C), энкодер (GyverEncoder).
   - Реле, шаговый двигатель, сервопривод.
4. **Подключение к Wi-Fi**: В режиме STA или AP (если нет сохранённых данных).
5. **Запуск сервисов**:
   - mDNS (`samovar.local`).
   - AsyncWebServer.
   - MQTT, Blynk, Telegram (если включено).
   - Lua-интерпретатор (если `USE_LUA`).
   - NTP-синхронизация времени.

## Запуск прошивки

1. Соберите проект в PlatformIO.
2. Прошейте устройство через USB.
3. При первом запуске:
   - Устройство создаст AP `Samovar-XXXX` с паролем `admin`.
   - Подключитесь к AP и откройте `http://192.168.4.1`.
   - Настройте Wi-Fi в разделе `/wifi.htm`.
4. После подключения к сети — доступ по `http://samovar.local` или IP-адресу.

## Отладка и мониторинг

- **Серийный порт**: Вывод отладочных сообщений на скорости 115200 бод.
- **WebSerial**: Доступен при `USE_WEB_SERIAL`.
- **Веб-интерфейс**: Мониторинг через `/` (автоматическое определение режима).
- **Логи**: Запись в `data.csv` на SPIFFS/LittleFS.
- **Сбои**: При `USE_CRASH_HANDLER` — сохранение стектрейса в `/crash.txt`.

## Обновление прошивки

Поддерживается OTA-обновление:
- Адрес: `http://samovar.local/update`.
- Файл: `firmware.bin`.
- Во время обновления отключаются Blynk, MQTT и Lua для снижения нагрузки.
- Таймаут: 30 секунд.
