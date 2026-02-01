# Зависимости

```markdown
# Зависимости

Проект "Самовар" построен на модульной архитектуре с чётким разделением ответственности. Ниже перечислены ключевые зависимости между компонентами.

## Основные зависимости

| Модуль | Зависит от | Назначение зависимости |
|-------|------------|------------------------|
| `distiller_proc()` | `Samovar.h`, `quality.h`, `SamovarMqtt.h` (опц.) | Основной цикл дистилляции использует глобальные сенсоры, статусы и отправку уведомлений. |
| `Samovar_Lua.h` | `Samovar.h`, `pumppwm.h`, `I2CStepper.h` | Lua-скрипты получают доступ к оборудованию через C++ API. |
| `impurity_detector.h` | `Samovar.h`, `PipeSensor`, `SteamSensor` | Анализ тренда температуры требует данных с датчиков и управления насосом/клапаном. |
| `samovar_s_i.h` | `Samovar.h`, `OneWire`, `DallasTemperature`, `Wire` | Инициализация датчиков и периферии. |
| `Quality.h` | `Samovar.h` (`SteamSensor.avgTemp`) | Оценка качества основана на усреднённой температуре пара. |
| `rmvk_uart.h` | `Samovar.h` | Управление РМВ-К интегрировано в систему питания (`target_power_volt`). |
| `column_math.h` | `Samovar.h` (`SamSetup`) | Расчёт параметров колонны использует калибровочные данные. |
| `SPIFFSEditor.h` | `Samovar.h`, `Samovar_Lua.h` (опц.) | Веб-редактор файлов использует системный веб-сервер и поддерживает Lua. |
| `CrashHandler.h` | `Samovar.h`, `esp_system.h` | Сохранение стектрейса и анализ сбоев. |
| `Samovar_MQTT.h` | `Samovar.h`, `AsyncMqttClient` | Отправка статусов и логов в MQTT-брокер. |
| `pumppwm.h` | `Samovar.h`, `GyverPID` | Управление ШИМ-насосом с PID-регулированием. |
| `I2CStepper.h` | `Samovar.h`, `Wire` | Управление шаговым двигателем и реле по I2C. |

## Условные зависимости (через `#define`)

| Макрос | Активирует зависимость |
|--------|------------------------|
| `USE_LUA` | `Samovar_Lua.h`, `SPIFFSEditor.h` (поддержка `.lua`) |
| `USE_MQTT` | `Samovar_MQTT.h` |
| `USE_WATER_PUMP` | `pumppwm.h` |
| `USE_WATER_VALVE` | Логика управления клапаном в `distiller_proc()` |
| `USE_EXPANDER` | `PCF8575` (через `Wire`) |
| `USE_ANALOG_EXPANDER` | `PCF8591` (через `Wire`) |
| `USE_PRESSURE_XGZ` / `USE_PRESSURE_MPX` | Драйверы датчиков давления |
| `USE_HEAD_LEVEL_SENSOR` | Обработка сигнала с датчика уровня флегмы |
| `USE_BODY_TEMP_AUTOSET` | `quality.h` (для анализа стабильности) |
| `SAMOVAR_USE_POWER` | `rmvk_uart.h`, `KVIC.h` (управление мощностью) |
| `USE_CRASH_HANDLER` | `CrashHandler.h` |
| `USE_TELEGRAM` | `TelegramBot` (библиотека) |

## Внешние библиотеки (PlatformIO)

| Библиотека | Назначение |
|-----------|-----------|
| `ESPAsyncWebServer` | Веб-интерфейс, WebSocket, WebSerial |
| `AsyncTCP` | Асинхронная сеть для ESP32 |
| `ArduinoJson` | Сериализация/десериализация JSON |
| `LittleFS` | Файловая система для хранения скриптов, логов, конфигов |
| `OneWire`, `DallasTemperature` | Работа с датчиками DS18B20 |
| `LiquidCrystal_I2C` | Управление LCD-дисплеем |
| `GyverPID` | PID-регулирование для насоса и нагрева |
| `AsyncMqttClient` | Подключение к MQTT-брокеру |
| `PCF8575`, `PCF8591` | Работа с I2C-экспандерами |
| `LiquidMenu` | Построение меню на LCD |
| `ESP32Servo` | Управление сервоприводом |

## Архитектурные связи

- **`Samovar.h`** — центральный модуль, от которого зависят почти все компоненты. Содержит глобальные переменные, настройки и инициализацию.
- **`Samovar_Lua.h`** — обеспечивает обратную связь: Lua-скрипты могут вызывать функции из `Samovar.h`, `pumppwm.h`, `I2CStepper.h`.
- **`SPIFFSEditor.h`** — интегрируется с веб-сервером из `Samovar.h` и при `USE_LUA` — с загрузкой скриптов.
- **`CrashHandler.h`** — автономен, но использует `Samovar.h` для отправки логов после перезагрузки.

Зависимости обеспечивают гибкость: неиспользуемые модули отключаются на этапе компиляции, что минимизирует размер прошивки.
```
