//TODO
//
//Проверить на программе С подъем напряжения
//Перейти на GyverPID
//**************************************************************************************************************


// copy partitions/samovar.csv to /Users/user/Library/Arduino15/packages/esp32/hardware/esp32/3.x.x/tools/partitions/samovar.csv
// add to /Users/user/Library/Arduino15/packages/esp32/hardware/esp32/3.x.x/boards.txt
// esp32.menu.PartitionScheme.samovar=Samovar
// esp32.menu.PartitionScheme.samovar.build.partitions=samovar
// esp32.menu.PartitionScheme.samovar.upload.maximum_size=1638400

//**************************************************************************************************************
// Подключение библиотек
//**************************************************************************************************************

// CONFIG_ASYNC_TCP_RUNNING_CORE вынесен в platformio.ini (build_flags) — только оттуда
// он доходит до отдельного TU библиотеки Async_TCP. Локальный #define здесь был мёртвым.

struct AjaxTelemetrySnapshot;
// Arduino вставляет автопрототипы сразу после Arduino.h. WebServer.ino объявляет
// http_sync_complete_get(asyncHTTPrequest&...) — без USE_LUA тип не подтягивается
// из lua.h, прототип ломает разбор (bool http_sync_complete_get как переменная).
class asyncHTTPrequest;

#undef CONFIG_BT_ENABLED
#include <Arduino.h>

#include <esp_wifi.h>

#if defined(ARDUINO_ESP32S3_DEV)
#else
#include "esp32/rom/rtc.h"
#endif

#include <driver/touch_sensor.h>
#include <esp32-hal-cpu.h>
#include <esp_heap_caps.h>
#include <esp_heap_caps_init.h>

#if defined(ARDUINO_ESP32S3_DEV)
//
#else
#include <driver/dac.h>
#endif

#include "esp_log.h"

#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Adafruit_Sensor.h>
#include <LiquidCrystal_I2C.h>
#include <WiFi.h>
#include <AsyncTCP.h>
#include <ESPAsyncWebServer.h>
#include <ESPmDNS.h>
#include <Update.h>
//#include <ESPping.h>

#include <LiquidMenu.h>

#include <EEPROM.h>
#include <Preferences.h>
#include <nvs.h>
#include <ESPAsyncWiFiManager.h>

#include <GyverEncoder.h>

#include <GyverButton.h>

#include <GyverPID.h>

//#include <mString.h>

#include <PID_v1.h>
#include <PID_AutoTune_v0.h>

#include <ESP32Servo.h>

#include <iarduino_I2C_connect.h>

#include "Samovar.h"
#include "samovar_api.h"
#include "operation_store.h"
#include "profile_store.h"
#include "crash_handler.h"
#include "control_numeric_input.h"
#include "time_utils.h"
#include "runtime_event_log.h"
#include "runtime_helpers.h"

#include <ArduinoTrace.h>

// esp_task_wdt.h нужен в ОБОИХ случаях: под __SAMOVAR_NOT_USE_WDT его зовёт
// setup_disable_watchdogs(), без него - [T30] сторож loop() в конце setup().
#include <esp_task_wdt.h>
#ifdef __SAMOVAR_NOT_USE_WDT
#include "soc/rtc_wdt.h"
#endif

#ifdef USE_LUA
#include "lua.h"
#endif

#include <NTPClient.h>
WiFiUDP ntpUDP;
NTPClient NTP(ntpUDP, "ru.pool.ntp.org");

#ifdef USE_MQTT
#include "SamovarMqtt.h"
#endif

#ifdef USE_BME680
#include <Adafruit_BME680.h>
#endif

#ifdef USE_BMP180
#include <Adafruit_BMP085_U.h>
#endif

#ifdef USE_BMP280
#include <Adafruit_BMP280.h>
#endif
#ifdef USE_BME280
#include <Adafruit_BME280.h>
#endif

#ifdef USE_PRESSURE_XGZ
#include <XGZP6897D.h>
XGZP6897D pressure_sensor(USE_PRESSURE_XGZ);
#endif


#include "mod_rmvk.h"

#include "logic.h"

#ifdef USE_UPDATE_OTA
#include <ArduinoOTA.h>
#endif

#ifdef SAMOVAR_USE_BLYNK
//#define BLYNK_PRINT Serial
// [Ревью 24.08] Blynk.run() зовётся из loop() (tick_blynk) и на зависшем сокете блокирует
// его ровно на BLYNK_TIMEOUT_MS: библиотека ставит client->setTimeout(BLYNK_TIMEOUT_MS)
// (BlynkArduinoClient.h) и читает блокирующим readBytes(). Заводские 6000 мс не влезали в
// бюджет ОДНОЙ итерации loop() под сторожем LOOP_WDT_TIMEOUT_S=10 с. Значение снижено до
// 3000 мс флагом сборки -DBLYNK_TIMEOUT_MS в platformio.ini (сторожит
// tools/smoke_loop_budget_vs_watchdog.py). Именно флагом, а не #define здесь: logic.h
// (строка 134 выше) уже втянул BlynkSimpleEsp32.h -> BlynkConfig.h, где значение задано
// через #ifndef, поэтому переопределение в этом месте опаздывает и не работает.
// [Ревью 24.08, ошибка 1] Ожидание подтверждения I2C-команды в бюджет этой итерации
// больше не суммируется: process_pending_i2c_operations() кормит сторож отдельно
// (feedLoopWDT() сразу после операции - см. комментарий там), т.к. цепочка I2C ограничена
// СВОИМИ таймаутами, но может быть длиннее одной итерации. 3000 мс подобраны по бюджету
// Blynk.run() отдельно от I2C: 54 с дисконнект/3 с логин Blynk - см. platformio.ini.
//#define BLYNK_HEARTBEAT 17

#include <BlynkSimpleEsp32.h>

#endif

#if defined(SAMOVAR_USE_BLYNK) || defined(USE_TELEGRAM)
#include <simple_queue.h>
SimpleStringQueue msg_q(5, 200);
#endif

#ifdef USE_TELEGRAM
#include <UrlEncode.h>
#endif

#ifdef USE_WATER_PUMP
#include "pumppwm.h"
#endif

#include "I2CStepper.h"
#include "distiller.h"
#include "beer.h"
#include "BK.h"
#include "nbk.h"
#include "suvid.h"
#include "SPIFFSEditor.h"

//**************************************************************************************************************
// Инициализация сенсоров и функции работы с сенсорами
//**************************************************************************************************************
#include "sensorinit.h"

// Определения буфера времени для LCD (см. extern в Samovar.h)
char tst[32] = "00:00:00   00:00:00";
char* timestr = (char*)tst;

hw_timer_t *timer = NULL;
portMUX_TYPE timerMux = portMUX_INITIALIZER_UNLOCKED;
portMUX_TYPE waterPulseMux = portMUX_INITIALIZER_UNLOCKED;
portMUX_TYPE dsAddressMux = portMUX_INITIALIZER_UNLOCKED;
portMUX_TYPE emergencyStopMux = portMUX_INITIALIZER_UNLOCKED;
// [T29] Защищает SamSetup (копируется присваиванием структуры, ~536 байт - не
// атомарно) и program[]/ProgramLen от рваного чтения: writer'ы живут в loop()
// (приоритет 1), а handleSave()/serialize_program_for_mode() читают их из
// async_tcp (приоритет 5, вытесняет loop() в любой момент). Мьютекс не нужен -
// копирование короткое, ждать в очереди нечего.
portMUX_TYPE configMux = portMUX_INITIALIZER_UNLOCKED;
QueueHandle_t samovar_command_queue = NULL;
StaticQueue_t samovar_command_queue_buffer;
uint8_t samovar_command_queue_storage[SAMOVAR_COMMAND_QUEUE_LENGTH * sizeof(SamovarCommandMsg)];
SemaphoreHandle_t samovar_command_queue_mutex = NULL;
StaticSemaphore_t samovar_command_queue_mutex_buffer;

bool shouldSaveWiFiConfig = false;

// Профиль загрузился в деградированном режиме (fail-open: грузимся на дефолтах/частично
// восстановленных данных, но громко сообщаем об этом). Пишутся один раз в setup(),
// читаются из JSON-статуса телеметрии уже после старта веба — гонок нет.
bool bootDegraded = false;
String bootDegradedReason = "";

// ---------------------------------------------------------------------------
// Отложенные команды для выполнения из loop() (set из async-обработчиков)
// ---------------------------------------------------------------------------
OperationStore operationStore{};
RuntimeEventRing runtimeEventRing{};

enum ProfileOperationFlags : uint8_t {
  PROFILE_OPERATION_HAS_SETTINGS = 0x01,
  PROFILE_OPERATION_HAS_PROGRAM = 0x02,
  PROFILE_OPERATION_METADATA_VOLUME = 0x04,
  PROFILE_OPERATION_METADATA_DESCRIPTION = 0x08,
  PROFILE_OPERATION_MODE_CHANGE = 0x10,
  PROFILE_OPERATION_REQUIRE_PROGRAM_IDLE = 0x20,
};

enum ProfileSensorResetMask : uint8_t {
  PROFILE_SENSOR_RESET_STEAM = 0x01,
  PROFILE_SENSOR_RESET_PIPE = 0x02,
  PROFILE_SENSOR_RESET_WATER = 0x04,
  PROFILE_SENSOR_RESET_TANK = 0x08,
  PROFILE_SENSOR_RESET_ACP = 0x10,
};

enum ProfileOperationPhase : uint8_t {
  PROFILE_OPERATION_EMPTY = 0,
  PROFILE_OPERATION_QUEUED,
  PROFILE_OPERATION_RUNNING,
  PROFILE_OPERATION_MODE_SWITCH,
  PROFILE_OPERATION_TERMINAL_PENDING,
  PROFILE_OPERATION_FAILED_CLOSED,
};

struct ProfileOperationSlot {
  SetupEEPROM settings;
  ProgramDraft program;
  char description[251];
  OperationId id;
  float boilerVolume;
  uint8_t flags;
  uint8_t sensorResetMask;
  uint8_t sourceMode;
  uint8_t targetMode;
  ProfileOperationPhase phase;
  OperationState terminalState;
  OperationError terminalError;
  ProgramUpdateAction programAction;
};

ProfileOperationSlot active_profile_operation{};
static_assert(sizeof(ProfileOperationPhase) == sizeof(uint8_t),
              "ProfileOperationPhase must remain byte-sized");
static_assert(std::is_trivially_copyable<ProfileOperationSlot>::value,
              "ProfileOperationSlot must remain safe for fixed slot copies");
static_assert(sizeof(ProfileOperationSlot) <= 1368,
              "ProfileOperationSlot exceeds replaced pending storage");

static inline ProfileOperationPhase profile_operation_phase_load() {
  return __atomic_load_n(&active_profile_operation.phase, __ATOMIC_ACQUIRE);
}

static inline void profile_operation_phase_store(ProfileOperationPhase phase) {
  __atomic_store_n(&active_profile_operation.phase, phase, __ATOMIC_RELEASE);
}

static void reset_profile_operation_slot() {
  active_profile_operation.settings = SetupEEPROM{};
  active_profile_operation.program = ProgramDraft{};
  memset(active_profile_operation.description, 0,
         sizeof(active_profile_operation.description));
  active_profile_operation.id = 0;
  active_profile_operation.boilerVolume = 0.0f;
  active_profile_operation.flags = 0;
  active_profile_operation.sensorResetMask = 0;
  active_profile_operation.sourceMode = 0;
  active_profile_operation.targetMode = 0;
  active_profile_operation.terminalState = OPERATION_STATE_EMPTY;
  active_profile_operation.terminalError = OPERATION_ERROR_NONE;
  active_profile_operation.programAction = PROGRAM_UPDATE_NONE;
  profile_operation_phase_store(PROFILE_OPERATION_EMPTY);
}

// [W-9] Отложенное сканирование OneWire датчиков
volatile bool pending_rescan_ds_flag = false;

// [W1] Аварийный останов выполняется из loop(), а не из SysTicker/async.
volatile bool pending_emergency_stop_flag = false;
volatile bool pending_emergency_stop_reason_flag = false;
char pending_emergency_stop_reason[EMERGENCY_STOP_REASON_LEN] = "";
char latched_emergency_stop_reason[EMERGENCY_STOP_REASON_LEN] = "";

struct SamovarNvsEntryBackup;

static OperationError queue_profile_operation(
    OperationKind kind,
    const SetupEEPROM* settings,
    uint8_t sensorResetMask,
    const ProgramDraft* programDraft,
    ProgramUpdateAction programAction,
    uint8_t metadataFlags,
    float boilerVolume,
    const char* description,
    bool requireProgramIdle,
    bool modeChange,
    SAMOVAR_MODE sourceMode,
    SAMOVAR_MODE targetMode,
    OperationId& operationId);
static OperationError commit_profile_operation();
static void process_profile_operation();

static void clear_ds_sensor_runtime(DSSensor& sensor) {
  sensor.avgTemp = 0;
  sensor.PrevTemp = 0;
  sensor.ErrCount = 0;
}

// Всё, что перечисляется по пяти датчикам DS18B20 сразу: адрес в профиле, бит сброса
// показаний, уставка, задержка и текст аварии. Порядок строк обязан совпадать с
// sensorList (Samovar.h): Steam,Pipe,Water,Tank,ACP - связка «поле профиля <-> датчик»
// держится только на нём, поэтому его пинит smoke_sensor_fields_staging.py.
struct SensorSetupField {
  uint8_t (SetupEEPROM::*address)[8];
  uint8_t resetBit;
  float SetupEEPROM::*setTemp;
  uint16_t SetupEEPROM::*delay;
  const char* errorMessage;
};

static const SensorSetupField kSensorSetupFields[DS_SENSOR_COUNT] = {
    {&SetupEEPROM::SteamAdress, PROFILE_SENSOR_RESET_STEAM, &SetupEEPROM::SetSteamTemp,
     &SetupEEPROM::SteamDelay, "Ошибка датчика температуры пара!"},
    {&SetupEEPROM::PipeAdress, PROFILE_SENSOR_RESET_PIPE, &SetupEEPROM::SetPipeTemp,
     &SetupEEPROM::PipeDelay, "Ошибка датчика температуры царги!"},
    {&SetupEEPROM::WaterAdress, PROFILE_SENSOR_RESET_WATER, &SetupEEPROM::SetWaterTemp,
     &SetupEEPROM::WaterDelay, "Ошибка датчика температуры воды!"},
    {&SetupEEPROM::TankAdress, PROFILE_SENSOR_RESET_TANK, &SetupEEPROM::SetTankTemp,
     &SetupEEPROM::TankDelay, "Ошибка датчика температуры куба!"},
    {&SetupEEPROM::ACPAdress, PROFILE_SENSOR_RESET_ACP, &SetupEEPROM::SetACPTemp,
     &SetupEEPROM::ACPDelay, "Ошибка датчика температуры в ТСА!"},
};

static void apply_setup_sensor_fields(uint8_t resetMask) {
  // Два прохода, а не один: сперва все пять адресов, только потом сбросы. Порядок
  // «адреса до сбросов» был в исходном коде и зафиксирован smoke-тестом.
  for (uint8_t i = 0; i < DS_SENSOR_COUNT; i++)
    CopyDSAddress(SamSetup.*kSensorSetupFields[i].address, sensorList[i]->Sensor);

  for (uint8_t i = 0; i < DS_SENSOR_COUNT; i++)
    if ((resetMask & kSensorSetupFields[i].resetBit) != 0) clear_ds_sensor_runtime(*sensorList[i]);
#ifdef __SAMOVAR_DEBUG
  debug_ds_bind_runtime_sensors();
#endif
}

static OperationError commit_profile_operation() {
  const bool hasSettings =
      (active_profile_operation.flags & PROFILE_OPERATION_HAS_SETTINGS) != 0;
  const bool hasProgram =
      (active_profile_operation.flags & PROFILE_OPERATION_HAS_PROGRAM) != 0;
  const bool hasMetadata =
      (active_profile_operation.flags &
       (PROFILE_OPERATION_METADATA_VOLUME |
        PROFILE_OPERATION_METADATA_DESCRIPTION)) != 0;
  const bool modeChange =
      (active_profile_operation.flags & PROFILE_OPERATION_MODE_CHANGE) != 0;

  String escapedDescription;
  if ((active_profile_operation.flags &
       PROFILE_OPERATION_METADATA_DESCRIPTION) != 0) {
    escapedDescription = active_profile_operation.description;
    escapedDescription.replace("%", "&#37;");
  }

  bool runtimeLocked = false;
  if (hasMetadata) {
    runtimeLocked = runtime_state_lock(pdMS_TO_TICKS(500));
    if (!runtimeLocked) {
      SendMsg("Операция профиля отменена: runtime state занят.", WARNING_MSG);
      return OPERATION_ERROR_RUNTIME_BUSY;
    }
  }

  bool persistFailed = false;
  // Текст отказа NVS отправляется ТОЛЬКО после runtime_state_unlock: SendMsg идёт
  // в append_runtime_event(), а тот берёт тот же xRuntimeStateSemaphore - обычный,
  // не рекурсивный мьютекс. Под своим же замком вызов честно ждал таймаут 500 мс и
  // возвращал RUNTIME_EVENT_PUBLISH_LOCK_BUSY, то есть аварийное сообщение о
  // расхождении ОЗУ и NVS не доходило ни до консоли, ни до интерфейса - ровно
  // тогда, когда оно нужнее всего.
  String persistFailureMessage;
  if (hasSettings) {
    const PersistResult persistResult = save_profile_nvs(active_profile_operation.settings);
    if (persistResult != PERSIST_OK) {
      // modeChange: режим ниже применяется в RAM несмотря на отказ NVS, поэтому
      // ОЗУ и NVS расходятся - работает новый режим, сохранён прежний. Текст
      // обязан назвать именно расхождение: иначе про откат при перезагрузке
      // пользователь узнает только после неё. Запас до молчаливого усечения в
      // msg_q (200 байт на запись минус приставки SendMsg) - 23 байта при самом
      // длинном коде persist_result_code, длиннее текст делать нельзя.
      persistFailureMessage = modeChange
          ? "Режим переключён, но не сохранён, перезагрузка вернёт прежний: "
          : "Настройки не сохранены: ";
      persistFailureMessage += persist_result_code(persistResult);
      // !modeChange: менять нечего (только настройки) - ранний возврат безопасен.
      // modeChange: применение режима в RAM обязано дойти до конца всегда - см.
      // switch_samovar_mode/force_complete_mode_switch_failed.
      if (!modeChange) {
        runtime_state_unlock(runtimeLocked);
        SendMsg(persistFailureMessage, ALARM_MSG);
        return OPERATION_ERROR_PROFILE_PERSIST_FAILED;
      }
      persistFailed = true;
    }
  }

  if (hasSettings) {
    // [T29] handleSave() читает SamSetup из async_tcp (другая задача/ядро) под
    // тем же спинлоком - без него присваивание структуры (~536 байт) может
    // быть вытеснено async_tcp на середине.
    portENTER_CRITICAL(&configMux);
    SamSetup = active_profile_operation.settings;
    portEXIT_CRITICAL(&configMux);
  }
  if (modeChange) {
    Samovar_Mode = static_cast<SAMOVAR_MODE>(active_profile_operation.targetMode);
    Samovar_CR_Mode = Samovar_Mode;
  }
  if (hasProgram) {
    switch (active_profile_operation.programAction) {
      case PROGRAM_UPDATE_REPLACE:
        program_commit(active_profile_operation.program);
        break;
      case PROGRAM_UPDATE_CLEAR:
        program_clear();
        break;
      case PROGRAM_UPDATE_NONE:
      default:
        break;
    }
  }
  if ((active_profile_operation.flags &
       PROFILE_OPERATION_METADATA_DESCRIPTION) != 0) {
    SessionDescription = escapedDescription;
  }
  if ((active_profile_operation.flags &
       PROFILE_OPERATION_METADATA_VOLUME) != 0) {
    BoilerVolume = active_profile_operation.boilerVolume;
    heatLossCalculated = false;
    heatStartMillis = 0;
  }
  if (hasSettings) {
    apply_setup_sensor_fields(active_profile_operation.sensorResetMask);
  }
  runtime_state_unlock(runtimeLocked);
  if (persistFailureMessage.length() > 0) SendMsg(persistFailureMessage, ALARM_MSG);

  // Вынесено из-под runtime_state_lock: samovar_reset() берёт I2C (reset_focus(),
  // set_menu_screen(3), reset_sensor_counter()->BME_getvalue()), а по LOCK_ORDER
  // (runtime_helpers.h) I2C обязан браться РАНЬШЕ RUNTIME_STATE, не внутри него.
  // Порядок относительно apply_config_runtime() ниже не изменился - сброс по-прежнему
  // раньше.
  if (modeChange) samovar_reset();
  if (hasSettings) apply_config_runtime();
#ifdef USE_LUA
  if (modeChange) {
    // [WP10 п.31] lua_type_script - String, которую задача do_lua_script() читает
    // без своей копии (lua.h, WriteConsoleLog внутри lua_state_lock при периодическом
    // прогоне). Присваивание String может пересоздать буфер (старый освобождается,
    // новый выделяется) - без защиты do_lua_script() мог прочитать буфер, который в
    // этот момент уже уничтожен. Берём/отдаём xLuaSemaphore ТОЛЬКО вокруг самого
    // присваивания и отдаём ДО load_lua_script(): она сама берёт тот же лок внутри,
    // а он не рекурсивный (обычный мьютекс) - держать его здесь было бы мгновенным
    // самовзаимоблокированием.
    // [T30a] portMAX_DELAY здесь означал, что loop() (эту функцию всегда вызывает
    // process_profile_operation() из loop(), core 1) мог зависнуть до ~40 с - ровно
    // на столько периодический прогон do_lua_script() может удержать xLuaSemaphore
    // (два чанка подряд под одним локом, LUA_CHUNK_TIMEOUT_MS=20000 каждый). Ждём
    // не дольше load_lua_script() (тот же прецедент, pdMS_TO_TICKS(300)); при неудаче
    // заявку не теряем - lua_type_script_pending применит её load_lua_script() перед
    // чтением lua_type_script, которую switch_samovar_mode() всё равно вызывает сразу
    // следом и повторяет, пока операция не завершится (mode-switch не станет terminal
    // раньше, чем скрипт реально перечитается).
    bool luaTypeLocked = lua_state_lock(pdMS_TO_TICKS(300));
    if (luaTypeLocked) {
      lua_type_script = get_lua_mode_name();
      lua_state_unlock(true);
    } else {
      lua_type_script_pending = true;
    }
  }
#endif
  return persistFailed ? OPERATION_ERROR_PROFILE_PERSIST_FAILED : OPERATION_ERROR_NONE;
}

static void set_profile_operation_terminal(
    OperationState state,
    OperationError error) {
  active_profile_operation.terminalState = state;
  active_profile_operation.terminalError = error;
  profile_operation_phase_store(PROFILE_OPERATION_TERMINAL_PENDING);
}

static void publish_profile_operation_terminal() {
  PendingCommandLockGuard guard;
  if (!guard) return;
  bool publishFailed = false;
  if (profile_operation_phase_load() == PROFILE_OPERATION_TERMINAL_PENDING) {
    const OperationError finishError = operation_store_finish_locked(
        operationStore,
        active_profile_operation.id,
        active_profile_operation.terminalState,
        active_profile_operation.terminalError);
    if (finishError == OPERATION_ERROR_NONE) {
      reset_profile_operation_slot();
    } else {
      profile_operation_phase_store(PROFILE_OPERATION_FAILED_CLOSED);
      publishFailed = true;
    }
  }
  guard.release();
  if (publishFailed) {
    SendMsg(
        "Операция профиля: terminal state не опубликован; требуется перезагрузка.",
        ALARM_MSG);
  }
}

static void process_profile_operation() {
  if (profile_operation_phase_load() == PROFILE_OPERATION_EMPTY) return;
  if (profile_operation_phase_load() == PROFILE_OPERATION_FAILED_CLOSED) return;
  if (profile_operation_phase_load() == PROFILE_OPERATION_TERMINAL_PENDING) {
    publish_profile_operation_terminal();
    return;
  }

  if (profile_operation_phase_load() == PROFILE_OPERATION_QUEUED) {
    PendingCommandLockGuard guard;
    if (!guard) return;
    bool transitionFailed = false;
    if (profile_operation_phase_load() == PROFILE_OPERATION_QUEUED) {
      const OperationError runningError = operation_store_mark_running_locked(
          operationStore, active_profile_operation.id);
      if (runningError == OPERATION_ERROR_NONE) {
        profile_operation_phase_store(PROFILE_OPERATION_RUNNING);
      } else {
        const OperationError finishError = operation_store_finish_locked(
            operationStore,
            active_profile_operation.id,
            OPERATION_STATE_FAILED,
            OPERATION_ERROR_INTERNAL);
        if (finishError == OPERATION_ERROR_NONE) {
          if ((active_profile_operation.flags &
               PROFILE_OPERATION_MODE_CHANGE) != 0) {
            mode_switch_end();
          }
          reset_profile_operation_slot();
        } else {
          // Барьер смены режима - это "не трогай железо, пока меняется режим",
          // а не аварийный тормоз. Если оставить его поднятым здесь, loop() уходит
          // в ранний return навсегда (см. барьер-return ниже в loop()), а уже
          // включённый нагрев при этом НЕ снимается - барьер только запрещает
          // включение (power_regulator.h), значит аппарат продолжит греть, потеряв
          // управление отбором. Настоящий fail-closed по нагреву обеспечивают
          // alarm_event()/heaterSafetyState.emergencyLatched (они не зависят от
          // барьера - см. mode_dispatch_alarm() выше), а пользователь получает
          // ALARM_MSG "требуется перезагрузка" и может выключить нагрев командой
          // (/command идёт мимо барьера).
          if ((active_profile_operation.flags &
               PROFILE_OPERATION_MODE_CHANGE) != 0) {
            mode_switch_end();
          }
          active_profile_operation.terminalState = OPERATION_STATE_FAILED;
          active_profile_operation.terminalError = OPERATION_ERROR_INTERNAL;
          profile_operation_phase_store(PROFILE_OPERATION_FAILED_CLOSED);
          transitionFailed = true;
        }
      }
    }
    guard.release();
    if (transitionFailed) {
      SendMsg(
          "Операция профиля: record недоступен при запуске; требуется перезагрузка.",
          ALARM_MSG);
    }
    if (profile_operation_phase_load() != PROFILE_OPERATION_RUNNING) return;
  }

  if (profile_operation_phase_load() == PROFILE_OPERATION_RUNNING) {
    const SAMOVAR_MODE sourceMode =
        static_cast<SAMOVAR_MODE>(active_profile_operation.sourceMode);
    const bool requiresProgramIdle =
        (active_profile_operation.flags &
         PROFILE_OPERATION_REQUIRE_PROGRAM_IDLE) != 0;
    if ((requiresProgramIdle && program_update_session_active()) ||
        Samovar_Mode != sourceMode) {
      if ((active_profile_operation.flags &
           PROFILE_OPERATION_MODE_CHANGE) != 0) {
        mode_switch_end();
      }
      set_profile_operation_terminal(
          OPERATION_STATE_FAILED, OPERATION_ERROR_CANCELLED);
      publish_profile_operation_terminal();
      return;
    }
    if ((active_profile_operation.flags &
         PROFILE_OPERATION_MODE_CHANGE) != 0) {
      profile_operation_phase_store(PROFILE_OPERATION_MODE_SWITCH);
    } else {
      const OperationError commitError = commit_profile_operation();
      set_profile_operation_terminal(
          commitError == OPERATION_ERROR_NONE
              ? OPERATION_STATE_SUCCEEDED
              : OPERATION_STATE_FAILED,
          commitError);
      publish_profile_operation_terminal();
      return;
    }
  }

  if (profile_operation_phase_load() == PROFILE_OPERATION_MODE_SWITCH) {
    const ModeSwitchResult switchResult = switch_samovar_mode(
        static_cast<SAMOVAR_MODE>(active_profile_operation.targetMode));
    if (switchResult == MODE_SWITCH_PENDING) return;
    OperationError switchError = active_profile_operation.terminalError;
    if (switchResult == MODE_SWITCH_FAILED &&
        switchError == OPERATION_ERROR_NONE) {
      switchError = OPERATION_ERROR_MODE_SWITCH_FAILED;
    }
    set_profile_operation_terminal(
        switchResult == MODE_SWITCH_SUCCEEDED
            ? OPERATION_STATE_SUCCEEDED
            : OPERATION_STATE_FAILED,
        switchError);
    publish_profile_operation_terminal();
  }
}

#ifdef USE_LUA
// [ISSUE-5] Отложенное исполнение Lua-строки (run_lua_string из async конкурирует
//           с do_lua_script на core 1 за общий lua_State).
String pending_lua_str;
volatile bool pending_lua_flag = false;
#endif

// [W2] Отложенные тяжёлые команды из /command: async только валидирует и ставит флаг.
volatile bool pending_reset_wifi_flag = false;
volatile bool pending_stop_self_test_flag = false;
volatile bool pending_mixer_flag = false;
volatile bool pending_mixer_on = false;
volatile bool pending_water_temp_flag = false;
volatile uint16_t pending_water_temp_value = 0;
volatile bool pending_pump_speed_flag = false;
volatile uint16_t pending_pump_speed_steps = 0;
volatile bool pending_nbkopt_flag = false;
volatile bool pending_log_flush_flag = false;
volatile bool pending_log_close_flag = false;
volatile uint32_t pending_log_flush_seq = 0;
volatile uint32_t log_write_seq = 0;
volatile uint32_t log_flush_seq = 0;

#ifdef SAMOVAR_USE_POWER
volatile bool pending_voltage_flag = false;
volatile float pending_voltage_value = 0;
#endif

#ifdef USE_LUA
volatile bool pending_lua_start_flag = false;
String pending_lua_file;
volatile bool pending_lua_file_flag = false;
String lua_script_list_cache;
volatile bool pending_lua_reload_flag = false;
#endif

// [W-3] Кэш I2C-шагового двигателя — обновляется в SysTicker, читается из async
struct I2CStepperCache {
  bool mixer_present;
  bool pump_present;
  uint16_t pump_current_speed;
  float pump_current_rate;
  uint32_t pump_remaining;
  uint8_t pump_status;
};
volatile I2CStepperCache i2c_stepper_cache = {false, false, 0, 0, 0, 0};

static void refresh_i2c_stepper_cache(I2CStepperDevice& device) {
  if (!i2c_stepper_config_begin(device)) return;

  // Фоновое обновление кэша ждёт мьютекс I2C короче обычного (100 мс вместо 1000):
  // это не пользовательская команда, и подвисание здесь не должно подвешивать SysTicker.
  bool present = i2c_stepper_refresh(device, true, I2C_CACHE_LOCK_WAIT_MS);
  if (device.address == I2CSTEPPER_MIXER_ADDR) {
    i2c_stepper_cache.mixer_present = present;
  } else if (device.address == I2CSTEPPER_PUMP_ADDR) {
    uint16_t stepsPerMl = i2c_stepper_steps_per_ml();
    i2c_stepper_cache.pump_present = present;
    i2c_stepper_cache.pump_current_speed = device.currentSpeed;
    float pumpRate = (present && stepsPerMl > 0)
        ? static_cast<float>(device.currentSpeed) / stepsPerMl
        : 0;
    i2c_stepper_cache.pump_current_rate =
        round(pumpRate * 3.6 * 1000) / 1000.0;
    i2c_stepper_cache.pump_remaining = device.remaining;
    i2c_stepper_cache.pump_status = device.status;
  }

  i2c_stepper_config_end(device);
}

// [T6] Вынесенные блоки тела triggerSysTicker() — размещены здесь (а не в общем
// блоке tick_*-хелперов loop() ниже по файлу), чтобы автогенерация прототипов
// Arduino видела их определения раньше вызова, без ручных прототипов.
static void tick_update_clock_strings() {
  // [C-1] Формируем строки времени в локалах, под замком только присваиваем глобалам.
  String localCrt = NTP.getFormattedDate();
  String uptime = format_uptime((unsigned long)(millis() / 1000UL));
  String localStrCrt = NTP.getFormattedTime() + "     " + uptime;
  snprintf(tst, sizeof(tst), "%s   %s",
           NTP.getFormattedTime().c_str(),
           uptime.c_str());
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (locked) {
    Crt = localCrt;
    StrCrt = localStrCrt;
    runtime_state_unlock(true);
  }
}

static void tick_publish_log_line(const String &baseLine) {
  if (baseLine.length() > 0) {
    String s = baseLine;
    s += ",";
    s += format_float(ACPSensor.avgTemp, 3);
    s += ",";
    s += format_float(ActualVolumePerHour, 3);
    s += ",";
    s += (String)current_power_volt;
    s += ",";
    s += format_float(WFflowRate, 2);

    s += ",";
    s += format_float(get_alcohol(TankSensor.avgTemp), 2);
    s += ",";
    // Для ректификации используем температуру пара, для дистилляции - температуру куба
    s += format_float(get_steam_alcohol(Samovar_Mode == SAMOVAR_RECTIFICATION_MODE ? SteamSensor.avgTemp : TankSensor.avgTemp), 2);
    s += ",";
    s += format_float(pressure_value, 2);

    // ПУНКТ 5: Расширенное логирование v.4
    // Расчет ФЧ (целевого)
    float vaporSpeed = 0;
#ifdef SAMOVAR_USE_POWER
    float netPower = (float)current_power_p - CurrentHeatLoss;
    if (netPower < 0) netPower = 0;
    // Скорость испарения мл/час (используем константу из column_math.h)
    vaporSpeed = netPower * EVAPORATION_FACTOR; 
#endif
    if (ActualVolumePerHour > 0.001f) {
      CalculatedTargetFR = (vaporSpeed / (ActualVolumePerHour * 1000.0f)) - 1.0f;
    } else {
      CalculatedTargetFR = 0;
    }
    if (CalculatedTargetFR < 0) CalculatedTargetFR = 0;

    s += ","; s += format_float(CalculatedTargetFR, 2); // 14: target_fr
    s += ","; s += format_float(CalculatedTargetFR, 2); // 15: actual_fr (в данной системе они совпадают)
    s += ","; s += format_float(impurityDetector.currentTrend, 3); // 16: temp_delta
    s += ","; s += String(impurityDetector.detectorStatus); // 17: alarm_state
    // event_code: 0=норм, 1=пауза
    // event_code используется только для критических событий
    uint8_t eventCode = program_Wait ? 1 : 0;
    s += ","; s += String(eventCode); // 18: event_code
    s += ","; s += String(SamSetup.PackDens); // 19: packing_density
    s += ","; s += format_float(SamSetup.ColHeight, 2); // 20: col_height
    s += ","; s += format_float(SamSetup.ColDiam, 1);   // 21: col_diameter
    s += ","; s += format_float(CurrentHeatLoss, 0);    // 22: heat_loss
    
    // Тип программы: H=головы, B=тело, C=предзахлеб, T=хвосты, P=пауза, пусто=нет программы
    String programType = "";
    ProgramType logProgramType = current_program_type();
    if (!program_type_empty(logProgramType)) {
      programType = program_type_to_string(logProgramType);
    }
    s += ","; s += programType; // 23: program_type
    
    // Режим работы: 0=ректификация, 1=дистилляция, 2=пиво, 3=БК, 4=НБК, 5=сувид, 6=Lua
    s += ","; s += String((int)Samovar_Mode); // 24: mode

#ifdef USE_MQTT
    MqttSendMsg(s, "log", 4);
#endif
  }
}

static void tick_update_withdrawal_progress(ProgramType tickerProgramType) {
  //Считаем прогресс для текущей строки программы и время до конца завершения строки и всего отбора (режим пива)
  if (Samovar_Mode == SAMOVAR_BEER_MODE) {
    float wp;
    if (program[ProgramNum].Time > 0 && begintime > 0) {
      // [Пиво 02.09 C3] Вычитаем накопленный простой строки, как в get_beer_status_text.
      wp = beer_stage_elapsed_ms(millis()) / 1000 / 60 / program[ProgramNum].Time;
    } else
      wp = 0;
    if (wp < 0) wp = 0;
    if (wp > 1) wp = 1;
    //прогресс переводим в проценты
    WthdrwlProgress = wp * 100;
    WthdrwTime = program[ProgramNum].Time * (1 - wp);

    WthdrwTimeAll = WthdrwTime;
    for (uint8_t i = ProgramNum + 1; i < ProgramLen; i++) {
      WthdrwTimeAll += program[i].Time;
    }

    // [C-1] Формируем строки в локалах, под замком только присваиваем глобалам.
    String h, m;
    int hi, mi;
    hi = WthdrwTime / 60;
    mi = WthdrwTime - hi * 60;
    if (hi < 10) h = "0";
    else
      h = "";
    h += (String)hi;
    if (mi < 10) m = "0";
    else
      m = "";
    m += (String)mi;
    String localTimeS = h + ":" + m;

    hi = WthdrwTimeAll / 60;
    mi = WthdrwTimeAll - hi * 60;
    if (hi < 10) h = "0";
    else
      h = "";
    h += (String)hi;
    if (mi < 10) m = "0";
    else
      m = "";
    m += (String)mi;
    String localTimeAllS = h + ":" + m;

    {
      bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
      if (locked) {
        WthdrwTimeS = localTimeS;
        WthdrwTimeAllS = localTimeAllS;
        runtime_state_unlock(true);
      }
    }

  }
  //Считаем прогресс отбора для текущей строки программы и время до конца завершения строки и всего отбора (режим ректификации)
  else if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE && (TargetStepps > 0 || tickerProgramType == 'P')) {
    //считаем прогресс
    float wp;

    //считаем время для текущей строки программы
    if (tickerProgramType == 'P') {
      if (program[ProgramNum].Time > 0) {
        WthdrwTime = (t_min - millis()) / (float)1000 / 60 / 60;
        if (WthdrwTime > program[ProgramNum].Time) WthdrwTime = program[ProgramNum].Time;
        // [П34] Если пауза уже просрочена (t_min в прошлом), WthdrwTime уходит в минус,
        // а wp - выше 1: далее приводится к unsigned int (:821-822 ниже по коду) и
        // отдаётся в веб как WthdrwlProgress (:850, до 100%) - зеркальный нижний кламп
        // к верхнему клампу строкой выше.
        if (WthdrwTime < 0) WthdrwTime = 0;
        wp = 1 - (WthdrwTime / program[ProgramNum].Time);
      } else {
        WthdrwTime = 0;
        wp = 0;
      }
    } else {
      wp = (float)CurrrentStepps / (float)TargetStepps;
      // [П34] Зеркально BEER-ветке (:740-742): CurrrentStepps > TargetStepps даёт wp > 1,
      // а WthdrwTime = Time * (1 - wp) уходит в минус - приведение отрицательного float
      // к unsigned int (:821-822) ниже по коду - неопределённое поведение.
      if (wp < 0) wp = 0;
      if (wp > 1) wp = 1;
      WthdrwTime = program[ProgramNum].Time * (1 - wp);
    }

    //суммируем время текущей строки программы и всех следующих за ней
    WthdrwTimeAll = WthdrwTime;

    for (uint8_t i = ProgramNum + 1; i < ProgramLen; i++) {
      WthdrwTimeAll += program[i].Time;
    }

    // [C-1] Формируем строки в локалах, под замком только присваиваем глобалам.
    String h, m;
    unsigned int mi;
    if (WthdrwTime < 10) h = "0";
    else
      h = "";
    h += (String)((unsigned int)WthdrwTime);
    mi = (unsigned int)((WthdrwTime - (unsigned int)(WthdrwTime)) * 60);
    if (mi < 10) m = "0";
    else
      m = "";
    m += (String)mi;
    String localTimeS = h + ":" + m;

    if (WthdrwTimeAll < 10) h = "0";
    else
      h = "";
    h += (String)((unsigned int)WthdrwTimeAll);
    mi = (unsigned int)((WthdrwTimeAll - (unsigned int)(WthdrwTimeAll)) * 60);
    if (mi < 10) m = "0";
    else
      m = "";
    m += (String)mi;
    String localTimeAllS = h + ":" + m;

    {
      bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
      if (locked) {
        WthdrwTimeS = localTimeS;
        WthdrwTimeAllS = localTimeAllS;
        runtime_state_unlock(true);
      }
    }

    //прогресс переводим в проценты
    WthdrwlProgress = wp * 100;
  } else {
    WthdrwlProgress = 0;
    // [C-1] Сброс под замком.
    bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
    if (locked) {
      WthdrwTimeS = "";
      WthdrwTimeAllS = "";
      runtime_state_unlock(true);
    }
  }
}

#ifdef USE_WATERSENSOR
static void tick_update_water_flow(uint16_t waterPulses, unsigned long &oldTime) {
  if (waterPulses < WATER_FLOW_MIN_PULSES) waterPulses = 0;
  WFflowRate = ((1000.0 / (millis() - oldTime)) * waterPulses) / WF_CALIBRATION;
  WFflowMilliLitres = WFflowRate * 100 / 6;
  WFtotalMilliLitres += WFflowMilliLitres;

  if (mode_water_flow_demanded() && waterPulses == 0) {
    WFAlarmCount++;
  } else {
    WFAlarmCount = 0;
  }

  oldTime = millis();
}
#endif

static void tick_report_sensor_errors() {
  // ErrCount копится всегда ([П17] в DS_getvalue). В ленту — только при нагреве:
  // в простое неподключённые датчики дают 0.0°C и не должны забивать журнал.
  // Lua мог поднять канал нагрева мимо PowerOn — тогда пишем так же, как при PowerOn.
  if (!PowerOn && !lua_heater_channel_raised()) return;

  for (uint8_t i = 0; i < DS_SENSOR_COUNT; i++) {
    if (!sensor_configured(*sensorList[i])) continue;
    if (sensorList[i]->ErrCount > 10) {
      sensorList[i]->ErrCount = -110;
      SendMsg(kSensorSetupFields[i].errorMessage, ALARM_MSG);
    }
  }
}


// [W-4] Отложенная команда /i2cstepper (I2C из async недопустим).
//        staged — приватная копия конфига с применёнными args; не трогаем глобал до loop.
//        device_sel: 0=mixer, 1=pump.
struct PendingI2CStepperCmd {
  I2CStepperDevice staged;
  uint8_t device_sel;  // 0=mixer, 1=pump
  char cmd[16];
  OperationId operationId;
};
static_assert(sizeof(PendingI2CStepperCmd) <= 64,
              "PendingI2CStepperCmd exceeds its request-draft budget");
PendingI2CStepperCmd pending_i2cstepper_buf;
volatile bool pending_i2cstepper_flag = false;

// [W-4] Отложенная команда /i2cpump (stop/start; I2C из async недопустим).
struct PendingI2CPumpCmd {
  bool is_stop;
  uint16_t speedSteps;
  uint32_t targetSteps;
  float targetMl;
  uint16_t fillingMl;
  uint16_t fillingMlHour;
  uint16_t stepsPerMl;
  OperationId operationId;
};
static_assert(sizeof(PendingI2CPumpCmd) <= 24,
              "PendingI2CPumpCmd exceeds its request-draft budget");
PendingI2CPumpCmd pending_i2cpump_buf;
volatile bool pending_i2cpump_flag = false;

// [W-4] Отложенная команда калибровки I2C насоса (i2c_stepper_write_config/send_command
//        из async недопустимы).
struct PendingI2CCalCmd {
  bool is_finish;   // false=start, true=finish
  uint16_t pumpMlHour;
  uint16_t stepsPerMl;
  uint16_t cmdSpeed;
  OperationId operationId;
};
static_assert(sizeof(PendingI2CCalCmd) <= 12,
              "PendingI2CCalCmd exceeds its request-draft budget");
PendingI2CCalCmd pending_i2ccal_buf;
volatile bool pending_i2ccal_flag = false;

struct PendingLocalCalCmd {
  bool is_finish;
  uint16_t speed;
  OperationId operationId;
};
static_assert(sizeof(PendingLocalCalCmd) <= 8,
              "PendingLocalCalCmd exceeds its request-draft budget");
PendingLocalCalCmd pending_local_cal_buf;
volatile bool pending_local_cal_flag = false;

struct PendingOperationResult {
  OperationId id;
  OperationState state;
  OperationError error;
  bool pending;
};
static_assert(sizeof(PendingOperationResult) <= 8,
              "PendingOperationResult exceeds its fixed RAM budget");
PendingOperationResult pending_i2c_operation_result{};

// Явные прототипы нужны Arduino-препроцессору: иначе он генерирует их до
// объявлений Pending*Cmd и ломает сборку root .ino.
static OperationError queue_pending_i2cpump(
    PendingI2CPumpCmd command, OperationId& operationId);
static OperationError queue_pending_i2cstepper(
    PendingI2CStepperCmd command, OperationId& operationId);
static OperationError queue_pending_i2ccal(
    PendingI2CCalCmd command, OperationId& operationId);
static OperationError queue_pending_local_cal(
    PendingLocalCalCmd command, OperationId& operationId);
static OperationError execute_pending_i2c_stepper(
    const PendingI2CStepperCmd& command);
static OperationError execute_pending_i2c_pump(
    const PendingI2CPumpCmd& command);
static OperationError execute_pending_i2c_calibration(
    const PendingI2CCalCmd& command);
static OperationError execute_pending_local_calibration(
    const PendingLocalCalCmd& command);

enum PendingI2COperationOwner : uint8_t {
  PENDING_I2C_OPERATION_NONE = 0,
  PENDING_I2C_OPERATION_STEPPER,
  PENDING_I2C_OPERATION_PUMP,
  PENDING_I2C_OPERATION_LOCAL_CALIBRATION,
  PENDING_I2C_OPERATION_I2C_CALIBRATION,
};

static bool pending_i2c_operation_matches_locked(OperationId id) {
  return (pending_i2cstepper_flag && pending_i2cstepper_buf.operationId == id) ||
         (pending_i2cpump_flag && pending_i2cpump_buf.operationId == id) ||
         (pending_local_cal_flag && pending_local_cal_buf.operationId == id) ||
         (pending_i2ccal_flag && pending_i2ccal_buf.operationId == id);
}

static bool clear_pending_i2c_operation_locked(OperationId id) {
  if (pending_i2cstepper_flag && pending_i2cstepper_buf.operationId == id) {
    pending_i2cstepper_buf = {};
    pending_i2cstepper_flag = false;
    return true;
  }
  if (pending_i2cpump_flag && pending_i2cpump_buf.operationId == id) {
    pending_i2cpump_buf = {};
    pending_i2cpump_flag = false;
    return true;
  }
  if (pending_local_cal_flag && pending_local_cal_buf.operationId == id) {
    pending_local_cal_buf = {};
    pending_local_cal_flag = false;
    return true;
  }
  if (pending_i2ccal_flag && pending_i2ccal_buf.operationId == id) {
    pending_i2ccal_buf = {};
    pending_i2ccal_flag = false;
    return true;
  }
  return false;
}

static void publish_pending_i2c_result(
    OperationId id,
    OperationState state,
    OperationError error) {
  pending_i2c_operation_result.id = id;
  pending_i2c_operation_result.state = state;
  pending_i2c_operation_result.error = error;
  __sync_synchronize();
  pending_i2c_operation_result.pending = true;
}

static OperationError i2c_command_result(
    bool commandSucceeded,
    const I2CStepperDevice& candidate) {
  if (candidate.error != 0) {
    String message = "I2CStepper error: ";
    message += String(candidate.error);
    WriteConsoleLog(message);
    return OPERATION_ERROR_I2C_DEVICE_ERROR;
  }
  return commandSucceeded
      ? OPERATION_ERROR_NONE
      : OPERATION_ERROR_I2C_COMMAND_FAILED;
}

static OperationError confirm_i2c_candidate(I2CStepperDevice& candidate) {
  if (!i2c_stepper_refresh(candidate, true)) {
    return OPERATION_ERROR_I2C_REFRESH_FAILED;
  }
  return i2c_command_result(true, candidate);
}

static OperationError execute_pending_i2c_stepper(
    const PendingI2CStepperCmd& command) {
  I2CStepperDevice* device = command.device_sel == 0
      ? &i2cStepperMixer
      : &i2cStepperPump;
  if (command.device_sel > 1) return OPERATION_ERROR_INTERNAL;
  if (!i2c_stepper_config_begin(*device)) {
    return OPERATION_ERROR_I2C_CONFIG_BUSY;
  }

  I2CStepperDevice candidate = *device;
  candidate.mode = command.staged.mode;
  candidate.relayMask = command.staged.relayMask;
  candidate.sensorFlags = command.staged.sensorFlags;
  candidate.optionFlags = command.staged.optionFlags;
  candidate.mixerRpm = command.staged.mixerRpm;
  candidate.mixerRunSec = command.staged.mixerRunSec;
  candidate.mixerPauseSec = command.staged.mixerPauseSec;
  candidate.pumpMlHour = command.staged.pumpMlHour;
  candidate.pumpPauseSec = command.staged.pumpPauseSec;
  candidate.fillingMl = command.staged.fillingMl;
  candidate.fillingMlHour = command.staged.fillingMlHour;
  candidate.stepsPerMl = command.staged.stepsPerMl;

  bool commandSucceeded = false;
  if (strcmp(command.cmd, "apply") == 0) {
    commandSucceeded = i2c_stepper_apply(candidate);
  } else if (strcmp(command.cmd, "save") == 0) {
    commandSucceeded = i2c_stepper_save(candidate);
  } else if (strcmp(command.cmd, "start") == 0) {
    commandSucceeded = i2c_stepper_start(candidate);
  } else if (strcmp(command.cmd, "stop") == 0) {
    commandSucceeded = i2c_stepper_stop(candidate);
  } else if (strcmp(command.cmd, "calstart") == 0) {
    commandSucceeded = i2c_stepper_write_config(candidate) &&
        i2c_stepper_send_command(candidate, I2CSTEP_CMD_CALIBRATE_START);
  } else if (strcmp(command.cmd, "calfinish") == 0) {
    commandSucceeded = i2c_stepper_send_command(
        candidate, I2CSTEP_CMD_CALIBRATE_FINISH);
  } else if (strcmp(command.cmd, "relay") == 0) {
    commandSucceeded = i2c_stepper_write_config(candidate) &&
        i2c_stepper_send_command(candidate, I2CSTEP_CMD_RELAY);
  } else {
    i2c_stepper_config_end(*device);
    return OPERATION_ERROR_INTERNAL;
  }

  OperationError result = i2c_command_result(commandSucceeded, candidate);
  if (result == OPERATION_ERROR_NONE) result = confirm_i2c_candidate(candidate);
  if (result == OPERATION_ERROR_NONE) *device = candidate;
  i2c_stepper_config_end(*device);
  return result;
}

static OperationError execute_pending_i2c_pump(
    const PendingI2CPumpCmd& command) {
  if (!i2c_stepper_config_begin(i2cStepperPump)) {
    return OPERATION_ERROR_I2C_CONFIG_BUSY;
  }

  I2CStepperDevice candidate = i2cStepperPump;
  bool commandSucceeded = false;
  if (command.is_stop) {
    commandSucceeded = i2c_stepper_stop(candidate);
  } else {
    candidate.mode = I2CSTEP_MODE_FILLING;
    candidate.fillingMl = command.fillingMl;
    candidate.fillingMlHour = command.fillingMlHour;
    candidate.stepsPerMl = command.stepsPerMl;
    commandSucceeded = i2c_stepper_start(candidate);
  }

  OperationError result = i2c_command_result(commandSucceeded, candidate);
  if (result == OPERATION_ERROR_NONE) result = confirm_i2c_candidate(candidate);
  if (result == OPERATION_ERROR_NONE) {
    i2cStepperPump = candidate;
    if (command.is_stop) {
      I2CPumpCmdSpeed = 0;
      I2CPumpTargetMl = 0;
    } else {
      I2CPumpCmdSpeed = command.speedSteps;
      I2CPumpTargetSteps = command.targetSteps;
      I2CPumpTargetMl = command.targetMl;
    }
  }
  i2c_stepper_config_end(i2cStepperPump);
  return result;
}

static OperationError execute_pending_i2c_calibration(
    const PendingI2CCalCmd& command) {
  if (!i2c_stepper_config_begin(i2cStepperPump)) {
    return OPERATION_ERROR_I2C_CONFIG_BUSY;
  }

  I2CStepperDevice candidate = i2cStepperPump;
  bool commandSucceeded = false;
  if (command.is_finish) {
    commandSucceeded = i2c_stepper_send_command(
        candidate, I2CSTEP_CMD_CALIBRATE_FINISH);
  } else {
    candidate.pumpMlHour = command.pumpMlHour;
    candidate.stepsPerMl = command.stepsPerMl;
    commandSucceeded = i2c_stepper_write_config(candidate) &&
        i2c_stepper_send_command(candidate, I2CSTEP_CMD_CALIBRATE_START);
  }

  OperationError result = i2c_command_result(commandSucceeded, candidate);
  if (result == OPERATION_ERROR_NONE) result = confirm_i2c_candidate(candidate);
  if (result == OPERATION_ERROR_NONE && command.is_finish) {
    // Калибровка уже физически завершена: CALIBRATE_FINISH подтверждена насосом,
    // а confirm_i2c_candidate() перечитал новый stepsPerMl из его регистров.
    // Отменить это отказом записи в NVS нельзя, поэтому staging-схема
    // (кандидат -> запись -> применение), уместная для ещё не применённых
    // настроек, здесь неприменима: дозу считает ESP по SamSetup.StepperStepMlI2C
    // (i2c_stepper_steps_per_ml() и производные), и откат RAM заставил бы её
    // лить по старому коэффициенту, пока насос откалиброван по новому.
    // Применяем безусловно, отказ записи только сообщаем.
    SamSetup.StepperStepMlI2C = candidate.stepsPerMl;
    i2cStepperPump = candidate;
    I2CPumpCalibrating = false;
    if (save_profile_nvs(SamSetup) != PERSIST_OK) {
      result = OPERATION_ERROR_PROFILE_PERSIST_FAILED;
    }
  } else if (result == OPERATION_ERROR_NONE) {
    i2cStepperPump = candidate;
    I2CPumpTargetMl = 0;
    I2CPumpCmdSpeed = command.cmdSpeed;
    I2CPumpCalibrating = true;
  }
  i2c_stepper_config_end(i2cStepperPump);
  return result;
}

static OperationError execute_pending_local_calibration(
    const PendingLocalCalCmd& command) {
  switch (pump_calibrate(command.is_finish ? 0 : command.speed)) {
    case PUMP_CALIBRATION_OK:
      if (!command.is_finish) CurrrentStepperSpeed = command.speed;
      return OPERATION_ERROR_NONE;
    case PUMP_CALIBRATION_INVALID_STATE:
      return OPERATION_ERROR_RUNTIME_BUSY;
    case PUMP_CALIBRATION_INVALID_RESULT:
      return OPERATION_ERROR_CALIBRATION_INVALID_RESULT;
    case PUMP_CALIBRATION_PROFILE_PERSIST_FAILED:
      return OPERATION_ERROR_PROFILE_PERSIST_FAILED;
  }
  return OPERATION_ERROR_INTERNAL;
}

static bool cancel_queued_i2c_operations_locked(bool& cancelled) {
  const bool pending[] = {
    pending_i2cstepper_flag,
    pending_i2cpump_flag,
    pending_local_cal_flag,
    pending_i2ccal_flag,
  };
  const OperationId operationIds[] = {
    pending_i2cstepper_buf.operationId,
    pending_i2cpump_buf.operationId,
    pending_local_cal_buf.operationId,
    pending_i2ccal_buf.operationId,
  };
  for (size_t index = 0; index < 4; index++) {
    if (!pending[index]) continue;
    cancelled = true;
    OperationRecord record{};
    if (operation_store_copy_locked(
            operationStore, operationIds[index], record) !=
        OPERATION_ERROR_NONE) {
      return false;
    }
    if (record.state == OPERATION_STATE_RUNNING) continue;
    if (record.state != OPERATION_STATE_QUEUED ||
        operation_store_finish_locked(
            operationStore,
            operationIds[index],
            OPERATION_STATE_FAILED,
            OPERATION_ERROR_CANCELLED) != OPERATION_ERROR_NONE ||
        !clear_pending_i2c_operation_locked(operationIds[index])) {
      return false;
    }
  }
  return true;
}

static void process_pending_i2c_operations() {
  if (pending_i2c_operation_result.pending) {
    PendingCommandLockGuard guard;
    if (!guard) return;
    if (pending_i2c_operation_matches_locked(
            pending_i2c_operation_result.id)) {
      const OperationError finishError = operation_store_finish_locked(
          operationStore,
          pending_i2c_operation_result.id,
          pending_i2c_operation_result.state,
          pending_i2c_operation_result.error);
      if (finishError == OPERATION_ERROR_NONE &&
          clear_pending_i2c_operation_locked(
              pending_i2c_operation_result.id)) {
        pending_i2c_operation_result = {};
      }
    } else {
      // id не совпал - применять результат уже не к чему (владелец записи сменился).
      // Раньше .pending оставался поднятым навсегда и блокировал всю диспетчеризацию.
      pending_i2c_operation_result = {};
    }
    return;
  }

  PendingI2COperationOwner owner = PENDING_I2C_OPERATION_NONE;
  PendingI2CStepperCmd stepperCommand{};
  PendingI2CPumpCmd pumpCommand{};
  PendingLocalCalCmd localCalibrationCommand{};
  PendingI2CCalCmd i2cCalibrationCommand{};
  OperationId operationId = 0;
  PendingCommandLockGuard guard;
  if (!guard) return;
  if (!mode_switch_in_progress()) {
    if (pending_i2cstepper_flag) {
      owner = PENDING_I2C_OPERATION_STEPPER;
      stepperCommand = pending_i2cstepper_buf;
      operationId = stepperCommand.operationId;
    } else if (pending_i2cpump_flag) {
      owner = PENDING_I2C_OPERATION_PUMP;
      pumpCommand = pending_i2cpump_buf;
      operationId = pumpCommand.operationId;
    } else if (pending_local_cal_flag) {
      owner = PENDING_I2C_OPERATION_LOCAL_CALIBRATION;
      localCalibrationCommand = pending_local_cal_buf;
      operationId = localCalibrationCommand.operationId;
    } else if (pending_i2ccal_flag) {
      owner = PENDING_I2C_OPERATION_I2C_CALIBRATION;
      i2cCalibrationCommand = pending_i2ccal_buf;
      operationId = i2cCalibrationCommand.operationId;
    }
    if (owner != PENDING_I2C_OPERATION_NONE &&
        operation_store_mark_running_locked(operationStore, operationId) !=
            OPERATION_ERROR_NONE) {
      owner = PENDING_I2C_OPERATION_NONE;
    }
  }
  guard.release();
  if (owner == PENDING_I2C_OPERATION_NONE) return;

  OperationError result = OPERATION_ERROR_INTERNAL;
  switch (owner) {
    case PENDING_I2C_OPERATION_STEPPER:
      result = execute_pending_i2c_stepper(stepperCommand);
      break;
    case PENDING_I2C_OPERATION_PUMP:
      result = execute_pending_i2c_pump(pumpCommand);
      break;
    case PENDING_I2C_OPERATION_LOCAL_CALIBRATION:
      result = execute_pending_local_calibration(localCalibrationCommand);
      break;
    case PENDING_I2C_OPERATION_I2C_CALIBRATION:
      result = execute_pending_i2c_calibration(i2cCalibrationCommand);
      break;
    case PENDING_I2C_OPERATION_NONE:
      break;
  }
  // [Ревью 24.08, ошибка 1] Сторож loop() (esp_task_wdt, LOOP_WDT_TIMEOUT_S) считает
  // ОДНУ итерацию целиком - три из четырёх веток switch выше идут через шину I2C
  // (i2c_stepper_write_config()/i2c_stepper_send_command(), каждая ждёт семафор шины
  // до I2C_LOCK_WAIT_MS, плюс confirm_i2c_candidate() -> ещё один i2c_stepper_refresh()),
  // и уже не укладываются в бюджет вместе с остальным содержимым итерации (Blynk.run()
  // и т.д.), см. smoke_loop_budget_vs_watchdog.py. Сброс здесь - не маскировка реального
  // зависания: каждое ожидание внутри цепочки ограничено СВОИМ таймаутом семафора/
  // дедлайном по millis(), то есть цепочка целиком тоже ограничена сверху, а не висит
  // бесконечно - именно от таких (бесконечных) зависаний защищает сторож. feedLoopWDT()
  // при выключенном сторожем (esp_task_wdt_reset() не найдёт задачу) молча вызовет
  // log_e() - при -DCORE_DEBUG_LEVEL=0 (platformio.ini, база [env:Samovar]) это
  // do {} while(0), спама нет (проверено по esp32-hal-misc.c/esp32-hal-log.h ядра).
  feedLoopWDT();
  publish_pending_i2c_result(
      operationId,
      result == OPERATION_ERROR_NONE
          ? OPERATION_STATE_SUCCEEDED
          : OPERATION_STATE_FAILED,
      result);
}

// [W-4] Отложенное ручное управление скоростью I2C-насоса (/command?pnbk).
ControlNbkCommand pending_pnbk_value = {};
volatile bool pending_pnbk_flag = false;


#ifdef USE_WEB_SERIAL
static const size_t WEBSERIAL_COMMAND_MAX = 32;

void recvMsg(uint8_t *data, size_t len) {
  if (!data || len == 0 || len > WEBSERIAL_COMMAND_MAX) {
    WebSerial.println("ERR BAD_REQUEST");
    return;
  }
  char command[WEBSERIAL_COMMAND_MAX + 1];
  for (size_t index = 0; index < len; index++) {
    if (data[index] == '\0') {
      WebSerial.println("ERR BAD_REQUEST");
      return;
    }
    command[index] = char(data[index]);
  }
  command[len] = '\0';

  if (strcmp(command, "print") == 0) {
    WebSerial.println("_______________________________________________");
    WebSerial.print("WFpulseCount = ");
    WebSerial.println(water_pulse_count_get());
    WebSerial.println("_______________________________________________");
    return;
  }

  static const char prefix[] = "WFpulseCount=";
  if (strncmp(command, prefix, sizeof(prefix) - 1) != 0) {
    WebSerial.println("ERR UNKNOWN_COMMAND");
    return;
  }
  const char *valueText = command + sizeof(prefix) - 1;
  for (const char *current = valueText; *current; current++) {
    if (numeric_ascii_space(*current)) {
      WebSerial.println("ERR WFpulseCount format");
      return;
    }
  }
  uint16_t value = 0;
  NumericParseResult result = parse_bounded_uint16(valueText, 0, UINT16_MAX, value);
  if (!result.ok()) {
    WebSerial.print("ERR WFpulseCount ");
    WebSerial.println(numeric_parse_error_code(result.error));
    return;
  }
  water_pulse_count_set(value);
  WebSerial.print("WFpulseCount = ");
  WebSerial.println(water_pulse_count_get());
}
#endif

void stopService(void) {
#if (defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3))
  timerWrite(timer, 0);
#else  // ESP_ARDUINO_VERSION_MAJOR >= 3
  timerAlarmDisable(timer);
#endif
}

void startService(void) {
#if (defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3))
  timerAlarm(timer, stepper.getPeriod(), true, 0);
#else  // ESP_ARDUINO_VERSION_MAJOR >= 3
  timerAlarmWrite(timer, stepper.getPeriod(), true);
  timerAlarmEnable(timer);
#endif
}

void IRAM_ATTR StepperTicker(void) {
  portENTER_CRITICAL_ISR(&timerMux);
  StepperMoving = stepper.tickManual();
  portEXIT_CRITICAL_ISR(&timerMux);
}

#ifdef USE_WATERSENSOR
void IRAM_ATTR WFpulseCounter() {
  portENTER_CRITICAL_ISR(&waterPulseMux);
  WFpulseCount++;
  portEXIT_CRITICAL_ISR(&waterPulseMux);
}
#endif

#ifdef ALARM_BTN_PIN
static TaskHandle_t EmergencyButtonTask = nullptr;

void IRAM_ATTR emergencyButtonInterrupt() {
  BaseType_t higherPriorityTaskWoken = pdFALSE;
  if (EmergencyButtonTask != nullptr) {
    vTaskNotifyGiveFromISR(EmergencyButtonTask, &higherPriorityTaskWoken);
  }
  if (higherPriorityTaskWoken == pdTRUE) portYIELD_FROM_ISR();
}

void triggerEmergencyButton(void *parameter) {
  (void)parameter;
  while (true) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    request_emergency_stop("Аварийное отключение: нажата аварийная кнопка");
    vTaskDelay(pdMS_TO_TICKS(30));
  }
}

bool initEmergencyButtonTask() {
  const BaseType_t created = xTaskCreatePinnedToCore(
    triggerEmergencyButton,
    "EmergencyButton",
    2048,
    nullptr,
    3,
    &EmergencyButtonTask,
    1
  );
  if (created != pdPASS || EmergencyButtonTask == nullptr) return false;
  // На классическом ESP32 выводы 34-39 - только вход, без внутренних подтяжек (на DEVKIT
  // аварийная кнопка сидит на GPIO35, поэтому там обязательна внешняя подтяжка). На
  // ESP32-S3 такого ограничения нет (там ALARM_BTN_PIN=48, подтяжка реальна).
  pinMode(ALARM_BTN_PIN, (ALARM_BTN_PIN >= 34 && ALARM_BTN_PIN <= 39) ? INPUT : INPUT_PULLUP);
  attachInterrupt(ALARM_BTN_PIN, emergencyButtonInterrupt, FALLING);
  if (digitalRead(ALARM_BTN_PIN) == LOW) xTaskNotifyGive(EmergencyButtonTask);
  return true;
}
#endif

//Запускаем таск для получения точного времени из интернет
void triggerGetClock(void *parameter) {
  int counter = 0;
  while (true) {
    // Пропускаем все активности во время OTA обновления (кроме проверки WiFi)
    if (ota_running) {
      vTaskDelay(200 / portTICK_PERIOD_MS);  // Увеличиваем задержку во время OTA
      continue;
    }
    
    counter++;
    if (counter > 30) {
      NTP.update();
      counter = 0;
    }
    {
      static unsigned long wifiReconnectTimer = 0;
      if (WiFi.status() != WL_CONNECTED) {
          // попытки переподключиться к WiFi раз в 20 секунд, если не сработала автоматическая попытка переподключиться
          // Но не во время OTA обновления
          if (!ota_running && millis() - wifiReconnectTimer >= 20000) {
            WriteConsoleLog(F("WiFi.reconnect..."));
            WiFi.reconnect();
            wifiReconnectTimer = millis();
          }
      } else {
        wifiReconnectTimer = millis();
      }
    }

    // Пропускаем переподключения во время OTA обновления
    if (!ota_running) {
      // Проверка и переподключение Blynk
#ifdef SAMOVAR_USE_BLYNK
      {
        BlynkLockGuard blynkLock(pdMS_TO_TICKS(500));
        if (blynkLock && !Blynk.connected() && WiFi.status() == WL_CONNECTED && SamSetup.blynkauth[0] != 0) {
          Blynk.connect(BLYNK_TIMEOUT_MS);
          vTaskDelay(50 / portTICK_PERIOD_MS);
        }
      }
#endif

      // Проверка и переподключение MQTT
#ifdef USE_MQTT
      if (!mqttConnected() && WiFi.status() == WL_CONNECTED) {
        connectToMqtt();
      }
#endif
    } else {
      // Во время OTA увеличиваем задержку для освобождения ресурсов
      vTaskDelay(100 / portTICK_PERIOD_MS);
    }

    // Обработка сообщений из очереди: отправка во все включенные сервисы одновременно
    // Пропускаем отправку сообщений во время OTA для освобождения ресурсов
    if (WiFi.status() == WL_CONNECTED && !ota_running) {
      char c[200] = {};
      bool queueHasMessage = false;
      bool queuePopResult = false;
      const BaseType_t queueTakeResult =
          xSemaphoreTake(xMsgSemaphore, (TickType_t)(50 / portTICK_RATE_MS));
      if (queueTakeResult == pdTRUE) {
        queueHasMessage = !msg_q.isEmpty();
        if (queueHasMessage) queuePopResult = msg_q.pop(c);
        xSemaphoreGive(xMsgSemaphore);
      }

      if (queueTakeResult != pdTRUE) {
        WriteConsoleLog(F("notify_queue_pop_lock_busy"));
      } else if (queueHasMessage && !queuePopResult) {
        WriteConsoleLog(F("notify_queue_pop_failed"));
      } else if (queuePopResult) {
        vTaskDelay(5 / portTICK_PERIOD_MS);
        String qMsg(c);

#ifdef USE_TELEGRAM
        bool telegramDeliveryFailed = false;
        if (SamSetup.tg_token[0] != 0 && SamSetup.tg_chat_id[0] != 0) {
          telegramDeliveryFailed =
              http_sync_request_get(String("http://212.237.16.93/bot") + SamSetup.tg_token + "/sendMessage?chat_id=" + SamSetup.tg_chat_id + "&text=" + urlEncode(qMsg)) == "<ERR>";
        }
#endif

#ifdef SAMOVAR_USE_BLYNK
        bool blynkDisconnected = false;
        bool blynkLockBusy = false;
        if (SamSetup.blynkauth[0] != 0) {
          BlynkLockGuard blynkLock(pdMS_TO_TICKS(500));
          if (!blynkLock) {
            blynkLockBusy = true;
          } else if (Blynk.connected()) {
            Blynk.virtualWrite(V26, qMsg);
          } else {
            blynkDisconnected = true;
          }
        }
#endif

#ifdef USE_TELEGRAM
        if (telegramDeliveryFailed) WriteConsoleLog(F("notify_telegram_delivery_failed"));
#endif
#ifdef SAMOVAR_USE_BLYNK
        if (blynkDisconnected) WriteConsoleLog(F("notify_blynk_disconnected"));
        if (blynkLockBusy) WriteConsoleLog(F("notify_blynk_lock_busy"));
#endif
      }
    }
#ifdef USE_TELEGRAM
    else if (SamSetup.tg_chat_id[0] != 0 && WiFi.status() != WL_CONNECTED) {
      Serial.println(F("Проблема с покдлючением к интернету."));
    }
    vTaskDelay(5 / portTICK_PERIOD_MS);
#endif
    {
      vTaskDelay(500 / portTICK_PERIOD_MS);
      BME_getvalue(false);
#if !(defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_MPX))
      vTaskDelay(500 / portTICK_PERIOD_MS);
#else
      vTaskDelay(400 / portTICK_PERIOD_MS);
      pressure_sensor_get();
#endif
      vTaskDelay(3000 / portTICK_PERIOD_MS);
    }
  }
}

// [П4] "Пульс" SysTicker: инкрементируется первой строкой внешнего while(true) в
// triggerSysTicker(). Наблюдатель tick_check_systicker_liveness() (см. ниже, рядом
// с tick_check_stack_headroom()) следит, что пульс не замирает дольше порога - иначе
// mode_dispatch_alarm() внутри этого же таска перестаёт вызываться, а loop() и веб на
// другом ядре продолжают отвечать, маскируя зависшую задачу надзора.
static volatile uint32_t sysTickerHeartbeat = 0;

//Запускаем таск для получения температур и различных проверок
void triggerSysTicker(void *parameter) {
  uint8_t CurMinST = 0;
  uint8_t OldMinST = 0;
  uint8_t tcntST = 0;
  unsigned long oldTime = 0;  // Предыдущее время в милисекундах
#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_MPX) || defined(USE_PRESSURE_1WIRE)
  bool pressure_alarm_sent = false;
#endif

  while (true) {
    // [П4] Инкремент - именно во внешнем цикле, а не внутри секундного гейта ниже:
    // зависание внутри гейта (например, на xSemaphoreTake(xI2CSemaphore, ...) или в
    // DS_getvalue()) не должно быть неотличимо от штатной секундной паузы.
    sysTickerHeartbeat++;
    CurMinST = (millis() / 1000);

    // раз в секунду обновляем время на дисплее, запрашиваем значения давления, напряжения и датчика потока
    if (OldMinST != CurMinST) {
#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_MPX) || defined(USE_PRESSURE_1WIRE)
      // [C-8] Проверка давления выполняется раз в секунду (внутри гейта OldMinST != CurMinST).
      //Проверим, что давление не вышло за пределы, если вышло - авария
      if (SamSetup.MaxPressureValue > 0 && pressure_value >= SamSetup.MaxPressureValue) {
        if (!pressure_alarm_sent) {
          request_emergency_stop("Превышено предельное давление!");
          pressure_alarm_sent = true;
        }
      } else if (pressure_alarm_sent) {
        float pressure_hysteresis = SamSetup.MaxPressureValue * 0.05f;
        if (pressure_hysteresis < 5.0f) pressure_hysteresis = 5.0f;
        if (SamSetup.MaxPressureValue <= 0 || pressure_value < SamSetup.MaxPressureValue - pressure_hysteresis) {
          pressure_alarm_sent = false;
        }
      }
#endif
#ifdef __SAMOVAR_DEBUG1
      Serial.println(F("--------------------------------------------"));
      Serial.print(F("PowerStatusTask = "));
      Serial.println(uxTaskGetStackHighWaterMark(PowerStatusTask));
      Serial.print(F("SysTickerTask1 = "));
      Serial.println(uxTaskGetStackHighWaterMark(SysTickerTask1));
      Serial.print(F("GetClockTask1 = "));
      Serial.println(uxTaskGetStackHighWaterMark(GetClockTask1));
      Serial.print(F("DoLuaScriptTask = "));
      Serial.println(uxTaskGetStackHighWaterMark(DoLuaScriptTask));
      Serial.println(F("--------------------------------------------"));
#endif
#ifdef SAMOVAR_USE_POWER
      get_current_power();
#endif
      
      // Авто-расчет теплопотерь при нагреве (п. 5)
      update_heat_loss_calculation();

      bool rescanDs = false;
      {
        PendingCommandLockGuard guard;
        if (guard && pending_rescan_ds_flag) {
          pending_rescan_ds_flag = false;
          rescanDs = !mode_switch_in_progress();
        }
      }
      if (rescanDs) {
        if (samovar_process_active()) {
          SendMsg("Сканирование датчиков отклонено: процесс активен.", WARNING_MSG);
          DS_getvalue();
        } else {
          scan_ds_adress();
        }
      } else {
        DS_getvalue();
      }

      //проверка параметров работы колонны на критичность и аварийное выключение нагрева, в случае необходимости
      //перенесено сразу после чтения датчиков - раньше вызывалось последним в такте, после кэша I2C и записи лога
      mode_dispatch_alarm();

      vTaskDelay(5 / portTICK_PERIOD_MS);

      // [W-3] Обновляем кэш I2C-шагового двигателя раз в секунду из SysTicker.
      //        Выполняем здесь (не в async), так как I2C защищён xI2CSemaphore внутри функций.
      refresh_i2c_stepper_cache(i2cStepperMixer);
      refresh_i2c_stepper_cache(i2cStepperPump);
      retry_i2c_pump_stop_if_unconfirmed();

      tick_update_clock_strings();

      process_pending_data_log_ops();
      // Снимок состояния пишется вне гейта отбора: он нужен и когда сессия ещё не
      // запущена, а программа уже набрана - её терять при перезагрузке нельзя.
      process_state_snapshot();

      if (startval != SAMOVAR_STARTVAL_IDLE) {
        tcntST++;
        if (tcntST >= SamSetup.LogPeriod) {
          tcntST = 0;
          String s = append_data();  //Записываем данные в память ESP32;
          tick_publish_log_line(s);
        }
      }

      vTaskDelay(5 / portTICK_PERIOD_MS);

      ProgramType tickerProgramType = current_program_type();
      tick_update_withdrawal_progress(tickerProgramType);


      vTaskDelay(5 / portTICK_PERIOD_MS);

#ifdef USE_WATERSENSOR

      uint16_t waterPulses = water_pulse_count_take();
      tick_update_water_flow(waterPulses, oldTime);
      vTaskDelay(5 / portTICK_PERIOD_MS);
#endif

      tick_report_sensor_errors();

      // [C-2/2a] Продвигаем FSM и обновляем кэш SamovarStatus раз в секунду.
      // Все переходы в tick_status_fsm() оперируют секундными интервалами,
      // поэтому секундная каденция достаточна. WthdrwTimeS/WthdrwTimeAllS к этому
      // моменту уже записаны выше под замком — читаем актуальные значения.
      // Замок в этой точке не удерживается → вложенного захвата нет.
      tick_status_fsm();

      OldMinST = CurMinST;
    }
    vTaskDelay(5 / portTICK_PERIOD_MS);
  }
}

// Fail-open: подсистема (профиль, ФС, очередь команд, веб-интерфейс, MQTT...) не
// поднялась штатно. НЕ останавливаем загрузку — владелец решил грузиться дальше в
// degraded-режиме, но громко сообщить об этом. Serial пишем сразу, а лог/ленту сообщений
// — одним пакетом в самом конце setup(): SendMsg/WriteConsoleLog трогают
// xMsgSemaphore/msg_q без null-проверки, да и часть отказов случается уже после того
// места, где семафоры поднялись. Веб-статус отдаётся из bootDegraded/bootDegradedReason
// через AJAX-телеметрию.
static void report_degraded_boot(const char* stage, const char* error) {
  Serial.print(F("WARN: "));
  Serial.print(stage);
  Serial.print(F(" failed: "));
  Serial.println(error);
  const String reason = String(stage) + ": " + String(error);
  if (bootDegraded) {
    bootDegradedReason += "; ";
    bootDegradedReason += reason;
  } else {
    bootDegraded = true;
    bootDegradedReason = reason;
  }
}

// Best-effort инициализация силовых выходов ДО загрузки профиля из NVS — на этот момент
// полярность реле ещё не известна (SamSetup ещё не заполнен). RELE_CHANNEL1 — пускатель
// нагревателя. HIGH здесь безопасен ТОЛЬКО для полярности releN=false (дефолт, см.
// set_default_setup_profile()): нормальный путь пишет !SamSetup.releN, что при false
// даёт HIGH=выключено. Полярность реле — настраиваемая пользователем опция (setup.htm,
// «Настройки уровней для реле»): на платах с releN=true (активный высокий уровень)
// HIGH означает ВКЛЮЧЕНО, т.е. этот вызов на таких платах на мгновение включает нагрев.
// Окно закрывается сразу после загрузки профиля — см. вызов apply_loaded_relay_polarity_off()
// в setup() сразу за присвоением SamSetup из startupProfile, до FS_init/apply_config_runtime
// и проверки кнопки AP. До загрузки профиля скорректировать уровень по факту нечем:
// полярность физически неизвестна раньше этой точки.
static void init_power_outputs_safe_off() {
  pinMode(RELE_CHANNEL1, OUTPUT);
  digitalWrite(RELE_CHANNEL1, HIGH);
  pinMode(RELE_CHANNEL2, OUTPUT);
  digitalWrite(RELE_CHANNEL2, HIGH);
  pinMode(RELE_CHANNEL3, OUTPUT);
  digitalWrite(RELE_CHANNEL3, HIGH);
  pinMode(RELE_CHANNEL4, OUTPUT);
  digitalWrite(RELE_CHANNEL4, HIGH);
}

// Как только профиль загружен (успешно, мигрирован или дефолтный при отказе — во всех
// случаях SamSetup.releN уже валиден), сразу переводим все каналы в реальное «выключено»
// с учётом полярности, не дожидаясь основной инициализации реле ниже в setup(). Закрывает
// окно, которое иначе держало бы releN=true платы включёнными вплоть до неё (FS_init,
// apply_config_runtime, ожидание кнопки AP — секунды). Pin mode уже выставлен в OUTPUT
// в init_power_outputs_safe_off().
static void apply_loaded_relay_polarity_off() {
  digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
  digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
  digitalWrite(RELE_CHANNEL3, !SamSetup.rele3);
  digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
}

// [P8] NVS-чекпоинт сессии: отдельный неймспейс (НЕ sam_cfg — тот несёт основной
// профиль), один uint16 (mode<<8 | номер программы). Смысл — только диагностика:
// после незапланированной перезагрузки владелец узнаёт, что грелось, но нагрев
// НЕ возобновляется автоматически (см. session_checkpoint_report_pending ниже).
static const char* const SESSION_CHECKPOINT_NAMESPACE = "sam_sess";
static const char* const SESSION_CHECKPOINT_KEY = "chk";

static void session_checkpoint_write(uint8_t mode, uint8_t prog) {
  nvs_handle_t handle;
  const esp_err_t openError = nvs_open(SESSION_CHECKPOINT_NAMESPACE, NVS_READWRITE, &handle);
  if (openError != ESP_OK) {
    Serial.print(F("NVS: session checkpoint open failed, err = "));
    Serial.println((int)openError);
    return;
  }
  const uint16_t payload = (uint16_t(mode) << 8) | prog;
  const esp_err_t setError = nvs_set_u16(handle, SESSION_CHECKPOINT_KEY, payload);
  if (setError != ESP_OK) {
    Serial.print(F("NVS: session checkpoint write failed, err = "));
    Serial.println((int)setError);
  }
  const esp_err_t commitError = nvs_commit(handle);
  if (commitError != ESP_OK) {
    Serial.print(F("NVS: session checkpoint commit failed, err = "));
    Serial.println((int)commitError);
  }
  nvs_close(handle);
}

static void session_checkpoint_clear() {
  nvs_handle_t handle;
  const esp_err_t openError = nvs_open(SESSION_CHECKPOINT_NAMESPACE, NVS_READWRITE, &handle);
  if (openError != ESP_OK) {
    Serial.print(F("NVS: session checkpoint open failed, err = "));
    Serial.println((int)openError);
    return;
  }
  const esp_err_t eraseError = nvs_erase_key(handle, SESSION_CHECKPOINT_KEY);
  if (eraseError != ESP_OK && eraseError != ESP_ERR_NVS_NOT_FOUND) {
    Serial.print(F("NVS: session checkpoint erase failed, err = "));
    Serial.println((int)eraseError);
  }
  const esp_err_t commitError = nvs_commit(handle);
  if (commitError != ESP_OK) {
    Serial.print(F("NVS: session checkpoint commit failed, err = "));
    Serial.println((int)commitError);
  }
  nvs_close(handle);
}

// 0 = чекпоинта нет. Заполняется один раз при загрузке (session_checkpoint_capture_pending),
// используется потом в session_checkpoint_report_pending().
static uint16_t pendingCheckpoint = 0;

static void session_checkpoint_capture_pending() {
  nvs_handle_t handle;
  // NVS_READONLY: неймспейса может не быть (обычная ситуация — сессий ещё не было),
  // а NVS_READWRITE в этом случае молча создал бы его, насорив вместо диагностики.
  if (nvs_open(SESSION_CHECKPOINT_NAMESPACE, NVS_READONLY, &handle) != ESP_OK) return;
  uint16_t payload = 0;
  if (nvs_get_u16(handle, SESSION_CHECKPOINT_KEY, &payload) == ESP_OK) {
    pendingCheckpoint = payload;
  }
  nvs_close(handle);
}

static void session_checkpoint_report_pending() {
  if (pendingCheckpoint == 0) return;
  const uint8_t mode = uint8_t(pendingCheckpoint >> 8);
  const uint8_t prog = uint8_t(pendingCheckpoint & 0xFF);
  const String notice = String(F("Обнаружена незавершённая сессия, режим ")) + String(mode) +
                         F(", программа №") + String(prog) +
                         F("; нагрев НЕ возобновлён автоматически.");
  WriteConsoleLog(notice);
  SendMsg(notice, WARNING_MSG);
  // [P8 fix#2] Без этого одно и то же предупреждение повторялось бы на каждой
  // перезагрузке (OTA, отладка), пока пользователь не пройдёт полный цикл
  // BEER/SUVID. pendingCheckpoint != 0 гарантирует, что неймспейс существует
  // (session_checkpoint_capture_pending его читала через NVS_READONLY).
  session_checkpoint_clear();
}

// PowerOn rising edge (BEER/SUVID) -> пишем чекпоинт и держим его "нашим" (checkpointOwned),
// пока сессия жива; falling edge -> стираем, но ТОЛЬКО если чекпоинт писали мы сами в этой
// же сессии (иначе затёрли бы чужой, ещё не прочитанный, чекпоинт предыдущей загрузки).
static void session_checkpoint_tick() {
  static bool prevPowerOn = false;
  static bool checkpointOwned = false;
  static uint16_t lastWrittenPayload = 0;

  if (PowerOn && !prevPowerOn) {
    if (Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_SUVID_MODE) {
      lastWrittenPayload = (uint16_t(Samovar_Mode) << 8) | ProgramNum;
      session_checkpoint_write((uint8_t)Samovar_Mode, ProgramNum);
      checkpointOwned = true;
    }
  } else if (PowerOn && prevPowerOn && checkpointOwned) {
    // [P8 fix#1] Многочасовая варка идёт под одним PowerOn — переходы между
    // строками программы фронта не дают. Перезаписываем чекпоинт при смене
    // ProgramNum, иначе после сбоя на N-й строке отчёт наврёт про стартовую.
    // Пишем только при РЕАЛЬНОМ изменении payload — не молотим NVS каждый loop.
    const uint16_t currentPayload = (uint16_t(Samovar_Mode) << 8) | ProgramNum;
    if (currentPayload != lastWrittenPayload) {
      session_checkpoint_write((uint8_t)Samovar_Mode, ProgramNum);
      lastWrittenPayload = currentPayload;
    }
  } else if (!PowerOn && prevPowerOn) {
    if (checkpointOwned) {
      session_checkpoint_clear();
      checkpointOwned = false;
    }
  }
  prevPowerOn = PowerOn;
}

// Снимок /state.csv: после незапланированной перезагрузки возвращаем в рабочий буфер
// программу, которая шла до сбоя, но нагрев НЕ возобновляем - решает владелец.
// Текст предупреждения копится здесь и уходит в конце setup(), когда уже подняты
// семафоры SendMsg/WriteConsoleLog.
static String pendingStateSnapshotNotice;

// Результат setup_check_ap_button_hold(): нужен и в setup_connect_wifi_and_notify()
// (решает, поднимать WiFiManager или сразу режим AP), и позже в setup() перед
// initMqtt() (не подключаться к MQTT в режиме AP). Обе точки — функции без
// параметров, поэтому значение живёт в файловой области, а не как локальная
// переменная setup().
static bool wifiAP = false;

static void restore_state_snapshot() {
  StateSnapshot snapshot;
  if (!read_state_snapshot(snapshot)) return;
  // Снимок чужого режима не трогаем: у другого режима другой формат программы,
  // а подставлять её в текущий буфер нельзя.
  if (snapshot.mode != (uint8_t)Samovar_Mode) return;

  bool restored = false;
  String programParseFailureReason;
  if (snapshot.programText.length() > 0) {
    ProgramDraft draft{};
    const ProgramParseResult result =
        prepare_program_for_mode(Samovar_Mode, snapshot.programText, draft);
    if (result.ok()) {
      program_commit(draft);
      restored = true;
      // Программа в буфере и в файле совпадают - в простое снимок переписывать нечем.
      state_snapshot_mark_saved();
    } else {
      programParseFailureReason = format_program_parse_error(result);
      Serial.print(F("state snapshot program ignored: "));
      Serial.println(programParseFailureReason);
    }
  }

  // В снимке была программа, но восстановить её не удалось (например, старая программа
  // не проходит новую проверку формата) - об этом нужно предупредить НЕЗАВИСИМО от
  // snapshot.powerOn, иначе пользователь молча получает дефолтную программу вместо своей
  // и не понимает, куда она делась. А вот если программа восстановилась и нагрев в снимке
  // был выключен - это штатное выключение, тревожить незачем (то прежнее поведение).
  const bool programLost = snapshot.programText.length() > 0 && !restored;
  if (!snapshot.powerOn && !programLost) return;

  String notice;
  if (snapshot.powerOn) {
    notice = F("Сессия прервана: строка ");
    notice += String(snapshot.programRow);
    notice += "/";
    notice += String(snapshot.programLen);
    notice += restored ? F(", программа восстановлена") : F(", программа не восстановлена");
    notice += F(". Нагрев не возобновлён.");
    // [T24.2] Только информационная приписка: живой suvidHold.accumulatedMs в это время
    // уже обнулён (check_alarm_suvid() сбрасывает его каждую секунду при !PowerOn) - сюда
    // не пишем, счётчик выдержки просто начнётся заново после включения нагрева.
    if (Samovar_Mode == SAMOVAR_SUVID_MODE && snapshot.suvidHoldAccumulatedSec > 0) {
      notice += F(" Накопленная выдержка Сувида на момент сбоя: ");
      notice += format_uptime(snapshot.suvidHoldAccumulatedSec);
      notice += F(".");
    }
  } else {
    notice = F("Программа из снимка не восстановлена, установлена программа по умолчанию.");
  }
  if (programLost) {
    notice += F(" Причина: ");
    notice += programParseFailureReason;
    notice += F(".");
  }
  pendingStateSnapshotNotice = notice;
}

static void state_snapshot_report_pending() {
  if (pendingStateSnapshotNotice.length() == 0) return;
  WriteConsoleLog(pendingStateSnapshotNotice);
  SendMsg(pendingStateSnapshotNotice, WARNING_MSG);
  pendingStateSnapshotNotice = "";
}

static void setup_check_gpio0_reset_button() {
  // Замыкание GPIO0 на землю стирает сохранённую сеть. Раньше пин настраивался без
  // подтяжки (INPUT), поэтому «висящая» линия ловила наводки, а на части плат GPIO0 занят
  // другой периферией - и настройки WiFi стирались сами при каждом старте.
  // Теперь пин подтянут к питанию и низкий уровень надо удерживать две секунды.
  pinMode(0, INPUT_PULLUP);
  vTaskDelay(50 / portTICK_PERIOD_MS);  // даём подтяжке установить уровень на линии
  if (digitalRead(0) == LOW) {
    uint32_t wifiResetHoldStart = millis();
    while (digitalRead(0) == LOW && millis() - wifiResetHoldStart < 2000) {
      vTaskDelay(20 / portTICK_PERIOD_MS);
    }
    if (digitalRead(0) == LOW) {
      Serial.println(F("GPIO0 held low: erasing WiFi settings"));
      WiFi.mode(WIFI_STA);  // cannot erase if not in STA mode !
      WiFi.persistent(true);
      WiFi.disconnect(true, true);
      WiFi.persistent(false);
    }
  }
}

static void setup_disable_watchdogs() {
#ifdef __SAMOVAR_NOT_USE_WDT
  esp_task_wdt_init(1, false);
  esp_task_wdt_init(2, false);
  rtc_wdt_protect_off();
  rtc_wdt_disable();
  disableCore0WDT();
  disableCore1WDT();
#endif
  heap_caps_enable_nonos_stack_heaps();
}

static void setup_create_semaphores_and_queue() {
  // [WP10 п.23] Мьютекс вместо двоичного семафора: у мьютекса есть владелец (только
  // взявшая его задача может отдать), и приоритетное наследование (низкоприоритетная
  // задача-держатель не застревает вытесненной, пока её ждёт высокоприоритетная).
  // xSemaphoreCreateMutexStatic() возвращает уже СВОБОДНЫЙ мьютекс - в отличие от
  // xSemaphoreCreateBinaryStatic() (создаёт взятый), поэтому лишний Give сразу после
  // создания здесь не нужен и был бы отпусканием невзятого мьютекса.
  xRuntimeStateSemaphore = xSemaphoreCreateMutexStatic(&xRuntimeStateSemaphoreBuffer);
  runtime_event_init(runtimeEventRing);

  xPendingCommandSemaphore = xSemaphoreCreateMutexStatic(&xPendingCommandSemaphoreBuffer);

  if (!init_samovar_command_queue()) {
    // Fail-open: очередь/мьютекс команд не создались — samovar_command_queue остаётся
    // nullptr. Все точки постановки/чтения команд (samovar_command_queue.h:
    // queue_samovar_command/receive_samovar_command/discard_samovar_commands/
    // samovar_command_queue_idle/queue_samovar_reset_command) уже проверяют handle на
    // nullptr и просто отказывают вызывающему, так что деградация не может привести к
    // обращению по NULL-хэндлу. Аварийные пути останова идут мимо очереди
    // (request_emergency_stop()/stop_process() дергают set_power(false) напрямую), а
    // штатное завершение по температуре куба - единственный останов, который очередью
    // пользуется, - при отказе постановки эскалирует в аварийный стоп (см. alarm.h,
    // ветка TankSensor.avgTemp >= DistTemp). Без этой эскалации нагрев при мёртвой
    // очереди остался бы включённым: else с аварийным стопом там уже недостижим.
    report_degraded_boot("command queue", "init failed");
    Serial.println(F("WARN: command queue disabled: starting new modes/power-on from menu, web UI, Blynk and Lua will be rejected as busy; stopping an active process and the emergency-stop/alarm safety path still work directly"));
  }

  xLogFileSemaphore = xSemaphoreCreateMutexStatic(&xLogFileSemaphoreBuffer);

#ifdef USE_LUA
  xLuaSemaphore = xSemaphoreCreateMutexStatic(&xLuaSemaphoreBuffer);
#endif

  xI2CSemaphore = xSemaphoreCreateMutexStatic(&xI2CSemaphoreBuffer);

#ifdef SAMOVAR_USE_BLYNK
  xBlynkSemaphore = xSemaphoreCreateMutexStatic(&xBlynkSemaphoreBuffer);
#endif
}

static void setup_wifi_stack_defaults() {
  // НЕ используем WiFi.disconnect(true) здесь, так как это может очистить сохраненные креденшалы
  // Вместо этого просто отключаемся без очистки сохраненных данных
  WiFi.disconnect(false);
  delay(50);
  WiFi.setSleep(false);
  WiFi.setHostname(host);
  WiFi.setAutoReconnect(true);

  Wire.begin(LCD_SDA, LCD_SCL);
  // Явно задаём скорость и таймаут шины: без этого используются значения по
  // умолчанию библиотеки, которые может перебить lcd.init() внутри LCD-библиотеки.
  Wire.setClock(100000);
  Wire.setTimeOut(10);

  lcd_found = (check_I2C_device(LCD_ADDRESS) == LCD_ADDRESS);

  stepper.disable();

  WFtotalMilliLitres = 0;
}

static void setup_stepper_timer_and_pwm() {
  // Configure the Prescaler at 80 the quarter of the ESP32 is cadence at 80Mhz
  // 80000000 / 80 = 1000000 tics / seconde
#if (defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3))
  timer = timerBegin(1000000);
  // В core 3.x таймер работает через драйвер gptimer, и он не принимает флаг прерывания
  // от скетча: IRAM-безопасность там включается только при сборке IDF
  // (CONFIG_GPTIMER_ISR_IRAM_SAFE). Поэтому здесь остаётся штатная привязка, а
  // USE_STEPPER_IRAM_ISR даёт эффект только на core 2.x.
  timerAttachInterrupt(timer, &StepperTicker);
#else  // ESP_ARDUINO_VERSION_MAJOR >= 3
  timer = timerBegin(2, 80, true);
#ifdef USE_STEPPER_IRAM_ISR
  // ESP_INTR_FLAG_IRAM оставляет прерывание живым, пока идёт запись во флеш и отключён кэш,
  // иначе мотор замирает на всё время записи. Требует, чтобы весь код обработчика лежал
  // в IRAM или в ПЗУ - это обеспечивают правки в libraries/GyverStepper.
  timerAttachInterruptFlag(timer, &StepperTicker, true, ESP_INTR_FLAG_IRAM);
#else
  timerAttachInterrupt(timer, &StepperTicker, true);
#endif
#endif

  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);

#ifdef SERVO_PIN
  servo.setPeriodHertz(50);  // standard 50 hz servo
  // Частоты 500 и 2500 - подобраны для моего серво-привода. Возможно, для других частоты могут отличаться
  // 544 и 2400 - стандартные частоты
  servo.attach(SERVO_PIN, 500, 2500);  // attaches the servo
#endif
}

static bool setup_check_ap_button_hold() {
  // Если при старте кнопка удерживается 2 секунды - Самовар запустится в режиме AP
  bool apRequested = false;
#ifdef BTN_PIN
  btn.resetStates();
  vTaskDelay(35 / portTICK_PERIOD_MS);
  if (btn.state()) {
    uint32_t buttonHoldStart = millis();
    while (btn.state() && millis() - buttonHoldStart < 2000) {
      vTaskDelay(20 / portTICK_PERIOD_MS);
    }
    apRequested = btn.state();
  }
  btn.resetStates();
#endif
  return apRequested;
}

static void setup_start_alarm_button_task() {
#ifdef ALARM_BTN_PIN
  if (!initEmergencyButtonTask()) {
    request_emergency_stop("Аварийное отключение: задача аварийной кнопки не запущена");
  }
#endif
}

static void setup_init_output_pins() {
  //Инициализируем ноги для реле
  pinMode(RELE_CHANNEL1, OUTPUT);
  digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
  pinMode(RELE_CHANNEL2, OUTPUT);
  digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
  pinMode(RELE_CHANNEL3, OUTPUT);
  digitalWrite(RELE_CHANNEL3, !SamSetup.rele3);
  pinMode(RELE_CHANNEL4, OUTPUT);
  digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);

#ifdef USE_WATER_VALVE
  pinMode(WATER_PUMP_PIN, OUTPUT);
  digitalWrite(WATER_PUMP_PIN, !USE_WATER_VALVE);
#endif

  //Инициализируем ногу для пищалки
  pinMode(BZZ_PIN, OUTPUT);
  digitalWrite(BZZ_PIN, LOW);
  setup_start_alarm_button_task();

#ifdef USE_PRESSURE_MPX
  //Инициализируем ногу для датчика давления MPX5010D
  pinMode(LUA_PIN, INPUT);
#endif
}

static void setup_init_menu_display_and_chip_id() {
  //Настраиваем меню
  setupMenu();
  writeString(F("      Samovar "), 1);
  writeString("     Version " + (String)SAMOVAR_VERSION, 2);
  writeString(F("Connecting to WI-FI"), 3);

  for (uint8_t i = 0; i < 17; i = i + 8) {
    chipId |= ((ESP.getEfuseMac() >> (40 - i)) & 0xff) << i;
  }

  Serial.printf("ESP32 Chip model = %s Rev %d\n", ESP.getChipModel(), ESP.getChipRevision());
  Serial.print("Chip ID: ");
  Serial.println(chipId);
}

static void setup_init_crash_handler() {
#ifdef USE_CRASH_HANDLER
  // Инициализация обработчика сбоев (после инициализации файловой системы)
  init_crash_handler();
#endif
}

static void setup_start_web_serial() {
#ifdef USE_WEB_SERIAL
  WebSerial.begin(&server);
  WebSerial.onMessage(recvMsg);
#endif
}

static void setup_attach_water_flow_interrupt() {
#ifdef USE_WATERSENSOR
  //вешаем прерывание на изменения датчика потока воды
  attachInterrupt(WATERSENSOR_PIN, WFpulseCounter, FALLING);
#endif
}

static void setup_configure_head_level_sensor() {
#ifdef USE_HEAD_LEVEL_SENSOR
  //Задаем параметры для сенсора уровня флегмы
#ifdef WHLS_HIGH_PULL
  whls.setType(HIGH_PULL);
#else
  whls.setType(LOW_PULL);
#endif

  whls.setDebounce(50);  //игнорируем дребезг
  whls.setTickMode(MANUAL);
  whls.setTimeout(WHLS_ALARM_TIME * 1000);  //время, через которое сработает тревога по уровню флегмы
#endif
}

static void setup_start_ntp() {
  NTP.setTimeOffset(SamSetup.TimeZone * 3600);
  NTP.setUpdateInterval(1800000);//30 min
  NTP.begin(); 
  delay(100);
  // Принудительная синхронизация при старте с повторными попытками
  if (WiFi.status() == WL_CONNECTED) {
    int attempts = 0;
    while (!NTP.forceUpdate() && attempts < 2) {
      delay(500);
      attempts++;
    }
  }
}

static void setup_finalize_boot_display() {
#ifdef USE_LUA
  lua_init();
#endif

  writeString(F("      Samovar     "), 1);
  writeString("     Version " + (String)SAMOVAR_VERSION, 2);
  writeString(F("                  "), 3);
  writeString(F("      Started     "), 4);
  
  get_task_stack_usage();
  Serial.println("Samovar ready");
  
  detect_i2c_steppers();
  if (i2cStepperMixer.present) {
    Serial.println("I2C Stepper Mixer v2");
  }
  if (i2cStepperPump.present) {
    Serial.println("I2C Stepper Pump/Filling v2");
  }
  used_byte = SPIFFS.usedBytes();

  SamovarStatus.reserve(80);
}

static void setup_report_degraded_boot() {
  // Публикуем итог degraded-загрузки одним пакетом: здесь уже подняты и семафоры для
  // SendMsg/WriteConsoleLog, и все точки отказа (профиль, ФС, очередь команд, веб, MQTT)
  // уже отработали, так что в сообщение попадают ВСЕ причины, а не только ранние.
  // bootDegradedReason сам называет отказавшую подсистему, поэтому текст общий.
  if (bootDegraded) {
    const String notice = String(F("Загрузка с ошибками (")) + bootDegradedReason +
                          F("). Часть функций недоступна, работаем в ограниченном режиме.");
    WriteConsoleLog(notice);
    // WARNING, не ALARM: это отказ конфигурации, а не авария процесса. ALARM
    // включает зацикленную сирену в браузере, хотя оператору нужно спокойно
    // открыть настройки и привязать датчики.
    SendMsg(notice, WARNING_MSG);
  }
}

static void setup_connect_wifi_and_notify() {
  String StIP;

  if (!wifiAP) {
    AsyncWiFiManagerParameter custom_blynk_token("blynk", "blynk token", SamSetup.blynkauth, 33, "blynk token");
    AsyncWiFiManager wifiManager(&server, &dns);

    // Сброс настроек WiFi кнопкой энкодера. Короткое нажатие (или наводка на входе SW -
    // на части плат он без внутренней подтяжки) стирало сеть при старте, поэтому кнопку
    // теперь нужно удержать две секунды - так же, как кнопку запуска в режиме AP выше.
    encoder.tick();  // отработка нажатия
    if (encoder.isPress()) {
      uint32_t encoderHoldStart = millis();
      while (encoder.isHold() && millis() - encoderHoldStart < 2000) {
        vTaskDelay(20 / portTICK_PERIOD_MS);
        encoder.tick();  // опрос ручной: без tick() состояние кнопки не обновится
      }
      if (encoder.isHold()) {
        Serial.println(F("Encoder button held: resetting WiFi settings"));
        wifiManager.resetSettings();
      }
    }
    encoder.resetStates();

    wifiManager.setConfigPortalTimeout(360);
    wifiManager.setSaveConfigCallback(saveConfigCallback);
    wifiManager.setAPCallback(configModeCallback);
    wifiManager.setDebugOutput(false);
    wifiManager.addParameter(&custom_blynk_token);

    if (!wifiManager.autoConnect("Samovar")) {
      WiFi.mode(WIFI_AP);
      WiFi.softAP("Samovar", "SamApp123");
      StIP = WiFi.softAPIP().toString();
    } else {
      StIP = WiFi.localIP().toString();
    }

    if (shouldSaveWiFiConfig) {
      if (strlen(custom_blynk_token.getValue()) == 32) {
        SetupEEPROM profileCandidate{};
        profileCandidate = SamSetup;
        copyStringSafe(
            profileCandidate.blynkauth,
            String(custom_blynk_token.getValue()));
        const PersistResult persistResult = save_profile_nvs(profileCandidate);
        if (persistResult == PERSIST_OK) {
          // [T29] WebServerInit()/server.begin() выше по setup() уже запустили
          // async_tcp - тот же риск рваного чтения, что и в
          // commit_profile_operation()/FinishAutoTune()/pump_calibrate().
          portENTER_CRITICAL(&configMux);
          SamSetup = profileCandidate;
          portEXIT_CRITICAL(&configMux);
        } else {
          Serial.print(F("NVS: Blynk token was not saved: "));
          Serial.println(persist_result_code(persistResult));
        }
      }
    }
    Serial.print(F("Connected to "));
    Serial.println(WiFi.SSID());
  } else {
    WiFi.mode(WIFI_AP);
    WiFi.softAP("Samovar", "SamApp123");
    StIP = WiFi.softAPIP().toString();
    Serial.println(F("Started as WiFi AP"));
  }

  Serial.print(F("IP address: "));
  copyStringSafe(ipst, StIP);

  Serial.println(StIP);

  if (!MDNS.begin(host)) {  //http://samovar.local
    Serial.println(F("Error setting up MDNS responder!"));
  } else {
#ifdef __SAMOVAR_DEBUG
    Serial.println(F("mDNS responder started"));
#endif
  }

  writeString(F("Connected"), 4);

#ifdef SAMOVAR_USE_BLYNK
  // Без BlynkLockGuard: это setup(), задачи (GetClockTicker) и loop() ещё не
  // стартовали (xTaskCreatePinnedToCore ниже по коду) - конкурентного доступа
  // к Blynk здесь быть не может.
  if (SamSetup.blynkauth[0] != 0 && !wifiAP) {
    writeString(F("Connecting to Blynk "), 3);
    writeString(F("               "), 4);
#ifdef __SAMOVAR_DEBUG
    Serial.println(F("Connecting to Blynk"));
#endif
#ifdef BLYNK_SAMOVAR_TOOL
    Blynk.config(SamSetup.blynkauth, BLYNK_SAMOVAR_TOOL, 8080);
#else
    Blynk.config(SamSetup.blynkauth);
#endif
    Blynk.connect(BLYNK_TIMEOUT_MS);
#ifdef __SAMOVAR_DEBUG
    Serial.println(F("Blynk started"));
#endif
  }
#endif

#ifdef USE_TELEGRAM
  if (WiFi.status() == WL_CONNECTED && SamSetup.tg_token[0] != 0 && SamSetup.tg_chat_id[0] != 0) {
    vTaskDelay(5 / portTICK_PERIOD_MS);
    http_sync_request_get(String("http://212.237.16.93/bot") + SamSetup.tg_token + "/sendMessage?chat_id=" + SamSetup.tg_chat_id + "&text=" + urlEncode("Самовар готов к работе; IP=http://" + StIP));
  } else if (SamSetup.tg_chat_id[0] != 0) {
    Serial.println(F("Проблема с покдлючением к интернету."));
  }
#endif

#ifdef USE_UPDATE_OTA
  //Send OTA events to the browser
  ArduinoOTA.onStart([]() {
    ota_running = true;  // Устанавливаем флаг активного OTA обновления
    // [T30] ArduinoOTA::_runUpdate() (framework-arduinoespressif32/libraries/ArduinoOTA)
    // получает и пишет в flash ВЕСЬ образ прошивки одним синхронным вызовом изнутри
    // ArduinoOTA.handle() (tick_ota() в loop()) - на реальном образе это легко больше 10 с,
    // а внутрь этого цикла своего кода вставить нельзя (чужая библиотека). Сторож loop()
    // (LOOP_WDT_TIMEOUT_S = 10, включается в конце setup()) на это время выключаем -
    // иначе любое обновление прошивки по OTA гарантированно перезагружало бы устройство
    // на середине передачи. onEnd()/onError() ниже включают его обратно.
    disableLoopWDT();
    String type;
    if (ArduinoOTA.getCommand() == U_FLASH)
      type = "Sketch";
    else {  // U_SPIFFS
      type = "Filesystem";
      SPIFFS.end();
    }
    type = type + " update start";
    events.send(type.c_str(), "ota");
    
    // Отключаем другие сервисы для освобождения ресурсов
#ifdef SAMOVAR_USE_BLYNK
    {
      // Колбэк ArduinoOTA вызывается из tick_ota() в loop() - таймаут как у tick_blynk().
      BlynkLockGuard blynkLock(pdMS_TO_TICKS(20));
      if (blynkLock && Blynk.connected()) {
        Blynk.disconnect();
      }
    }
#endif
#ifdef USE_MQTT
    disconnectFromMqtt();
#endif
  });
  ArduinoOTA.onEnd([]() {
    ota_running = false;  // Сбрасываем флаг после завершения
    // [T30] Обратная половина disableLoopWDT() из onStart() выше - при успешном
    // обновлении сюда обычно не доходит (ниже по _runUpdate() следует ESP.restart()),
    // но если рестарт на этой сборке отключён, loop() обязан остаться под сторожем.
    enableLoopWDT();
    events.send(("Update End"), "ota");
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    char p[32];
    const uint32_t percent = (total > 0) ? (progress * 100U) / total : 0U;
    strcpy(p, "Progress: ");
    ultoa(percent, p + strlen(p), 10);
    strcat(p, "%\n");
    events.send(p, "ota");
    yield();  // Даем возможность другим задачам выполниться
  });
  ArduinoOTA.onError([](ota_error_t error) {
    ota_running = false;  // Сбрасываем флаг при ошибке
    // [T30] Неудачная OTA НЕ перезагружает устройство (см. _runUpdate()) - без этого
    // вызова loop() остался бы без сторожа до следующей перезагрузки.
    enableLoopWDT();
    if (error == OTA_AUTH_ERROR) events.send("Auth Failed", "ota");
    else if (error == OTA_BEGIN_ERROR)
      events.send(("Begin Failed"), "ota");
    else if (error == OTA_CONNECT_ERROR)
      events.send(("Connect Failed"), "ota");
    else if (error == OTA_RECEIVE_ERROR)
      events.send(("Recieve Failed"), "ota");
    else if (error == OTA_END_ERROR)
      events.send(("End Failed"), "ota");
  });
  ArduinoOTA.setHostname(SAMOVAR_HOST);
  // Увеличиваем таймауты для более стабильной передачи
  ArduinoOTA.setTimeout(30000);  // 30 секунд на операцию (по умолчанию 10)
  ArduinoOTA.begin();
#endif
}

// [T30] Порог сторожа основного loop() (esp_task_wdt) в секундах - см. установку в конце
// setup(). Аудит всех операций, достижимых из loop() (мутекс-локи, I2C, SPIFFS, mode-тики,
// Blynk.run()), подтвердил, что ни одна из них не превышает эту величину - КРОМЕ активной
// OTA-передачи (ArduinoOTA::_runUpdate() пишет весь образ одним синхронным вызовом), поэтому
// сторож на время OTA-сессии выключается отдельно (см. onStart()/onEnd()/onError() выше).
// [Ревью 24.08, предупреждение 2] esp_task_wdt_init(LOOP_WDT_TIMEOUT_S, true) ниже задаёт
// этот порог ГЛОБАЛЬНО для esp_task_wdt, а не только для задачи loop(): в vendored sdkconfig
// этого проекта холостая (idle) задача ядра 0 по умолчанию тоже под этим сторожем
// (CONFIG_ESP_TASK_WDT_CHECK_IDLE_TASK_CPU0=y) с порогом 5 с - вызов ниже молча поднимает его
// до 10 с, то есть контроль зависания ядра 0 становится вдвое менее чувствительным. Это
// приемлемо: ни одна задача прошивки не подписывается на сторож явно через esp_task_wdt_add()
// (проверено поиском по исходникам) - единственный такой вызов в проекте вендорный
// (libraries/Async_TCP/src/AsyncTCP.cpp), и он выключен через CONFIG_ASYNC_TCP_USE_WDT=0
// (см. AsyncTCP.h) - реальный контроль остаётся только за idle-задачей ядра 0.
constexpr uint32_t LOOP_WDT_TIMEOUT_S = 10;

void setup() {
  // Уровни реле должны стать безопасными раньше всего остального: RELE_CHANNEL2 на
  // некоторых платах сидит на strapping-выводе (см. Samovar_pin.h), который при сбросе
  // подтянут вверх, поэтому окно до первого pinMode/digitalWrite нужно закрыть как можно
  // раньше. Serial.begin() к выводам питания отношения не имеет и не должен стоять
  // перед этим вызовом. Стартовая 500 мс задержка тоже к выводам питания не относится,
  // но она намеренно НЕ стоит здесь: до apply_loaded_relay_polarity_off() полярность
  // реле ещё не известна, и на платах с releN=true (активный высокий уровень) init
  // на мгновение включает нагрев (HIGH) — если бы задержка шла сразу за init, это
  // окно длилось бы все 500+ мс вместо десятков миллисекунд чтения профиля. Задержка
  // перенесена вниз, сразу после apply_loaded_relay_polarity_off() (см. её комментарий).
  init_power_outputs_safe_off();
  Serial.begin(115200);

  SetupEEPROM startupProfile{};
  ProfileLoadResult profileResult = load_profile_nvs(startupProfile);
  bool persistStartupProfile = false;
  bool migratedFromLegacy = false;
  if (profileResult == PROFILE_LOAD_NOT_FOUND) {
    profileResult = migrate_from_eeprom(startupProfile);
    if (profileResult == PROFILE_LOAD_OK) {
      persistStartupProfile = true;
      migratedFromLegacy = true;
    } else if (profileResult == PROFILE_LOAD_NOT_FOUND) {
      set_default_setup_profile(startupProfile);
      profileResult = PROFILE_LOAD_OK;
      persistStartupProfile = true;
    }
  }
  if (profileResult != PROFILE_LOAD_OK) {
    // Профиль в NVS битый/нечитаемый: сообщаем и грузимся на безопасных дефолтах
    // (rele1..4=false, т.е. нагрев выключен) вместо неинициализированной структуры.
    report_degraded_boot("load", profile_load_result_code(profileResult));
    set_default_setup_profile(startupProfile);
  }
  // Диапазон HeaterResistant не проверяет ни чтение NVS, ни миграция из EEPROM, а в
  // setup.htm уходит сырое значение. Без лечения страница показывала бы одно, а расчёты
  // мощности — они спрашивают trusted_heater_resistance() — считали бы по другому.
  // Лечим до save_profile_nvs(), чтобы мигрированный профиль починился в NVS насовсем.
  const float storedHeaterR = startupProfile.HeaterResistant;
  nbk_preserve_startup_input_validity(
      storedHeaterR, startupProfile.MainsVoltage);
  startupProfile.HeaterResistant = trusted_heater_resistance(storedHeaterR);
  if (startupProfile.HeaterResistant != storedHeaterR) {
    Serial.print(F("WARN: heater resistance "));
    Serial.print(storedHeaterR, 3);
    Serial.print(F(" out of range, using default "));
    Serial.print(startupProfile.HeaterResistant, 3);
    Serial.println(F(": set the real value in setup.htm, power calculations depend on it"));
  }
  if (migratedFromLegacy) {
    String fixedFields;
    if (sanitize_setup_profile_ranges(startupProfile, fixedFields)) {
      const String reason = String("out of range, reset to defaults: ") + fixedFields;
      report_degraded_boot("profile_migration", reason.c_str());
    }
  }
  if (persistStartupProfile) {
    const PersistResult persistResult = save_profile_nvs(startupProfile);
    if (persistResult != PERSIST_OK) {
      // Сохранить в NVS не удалось, но startupProfile в памяти уже валиден
      // (мигрированный/дефолтный) — продолжаем на нём, просто без персиста.
      report_degraded_boot("migration", persist_result_code(persistResult));
    } else if (migratedFromLegacy) {
      // Новый профиль записан и проверен чтением — только теперь legacy-остатки
      // можно стирать. Обратный порядок оставил бы окно, где пропадание питания
      // уничтожает настройки. Свежие устройства сюда не попадают: там нет ни
      // миграции, ни чего стирать.
      clear_migrated_legacy_profile_data();
    }
  }
  SamSetup = startupProfile;
  // Полярность реле теперь известна — закрываем окно из init_power_outputs_safe_off()
  // (см. её комментарий) немедленно, не дожидаясь основной инициализации реле ниже.
  apply_loaded_relay_polarity_off();
  // Задержка стояла сразу после init_power_outputs_safe_off() (см. её комментарий) —
  // перенесена сюда, чтобы не удлинять окно неверного уровня на платах с releN=true.
  vTaskDelay(500 / portTICK_PERIOD_MS);
  print_nvs_stats("after config load");
  session_checkpoint_capture_pending();

  const FsInitResult fsInitResult = FS_init();
  if (fsInitResult == FS_INIT_FORMATTED) {
    // FS_init() не смонтировал ФС с первой попытки, отформатировал её и смонтировал
    // заново (см. FS.ino) — загрузка продолжается и веб-сервер поднимется как обычно
    // (WebServerInit() ниже больше не смотрит на fsInitResult), но пользовательские
    // Lua-скрипты, логи и /data были стёрты форматированием; get_web_interface()
    // перекачает статический UI с сервера, а вот пользовательский контент — нет.
    report_degraded_boot("filesystem", "formatted, user files lost");
  } else if (fsInitResult != FS_INIT_OK) {
    // Fail-open: и монтирование, и формат провалились (см. FS_init()/FS.ino) — не
    // вешаем загрузку в вечный цикл, а сообщаем и продолжаем. Все обращения к
    // SPIFFS/LittleFS в остальном коде (File::operator bool(), SPIFFS.exists()/
    // usedBytes() и т.д.) уже проверены на безопасное поведение при незамонтированной
    // ФС — см. отчёт аудита.
    report_degraded_boot("filesystem", "mount failed");
  }

  esp_log_level_set("i2c.master", ESP_LOG_NONE);
  setup_check_gpio0_reset_button();

  setup_disable_watchdogs();

#ifdef __SAMOVAR_DEBUG
  esp_log_level_set("*", ESP_LOG_VERBOSE);
  Serial.println("Using ESP object:");
  Serial.println(ESP.getSdkVersion());

  Serial.println("Using lower level function:");
  Serial.println(esp_get_idf_version());
#endif
#if defined(ARDUINO_ESP32S3_DEV)
#else
  touch_pad_intr_disable();
#endif

  // [WP10 п.23] См. комментарий в setup_create_semaphores_and_queue(): мьютекс уже
  // свободен после создания, лишний Give здесь не нужен.
  xMsgSemaphore = xSemaphoreCreateMutexStatic(&xMsgSemaphoreBuffer);
  setup_create_semaphores_and_queue();

  WiFi.mode(WIFI_STA);  // explicitly set mode, esp defaults to STA+AP
  setup_wifi_stack_defaults();

  setup_stepper_timer_and_pwm();

  // Инициализация кнопок и энкодера (обработка в loop())
#ifdef BTN_PIN
  btn.setType(LOW_PULL);
  btn.setTickMode(AUTO);
  btn.setDebounce(30);
  btn.setTimeout(2000);
#endif

#ifdef ALARM_BTN_PIN
  alarm_btn.setType(HIGH_PULL);
  alarm_btn.setTickMode(AUTO);
  alarm_btn.setDebounce(30);
#endif

  wifiAP = setup_check_ap_button_hold();

  apply_config_runtime();

  Serial.print("NVS: Configuration loaded. Flag = ");
  Serial.println(SamSetup.flag);

  // Программа хранится в общем runtime-буфере program[]; после загрузки режима из NVS
  // нужно заполнить его дефолтом именно текущего режима.
  ProgramParseResult defaultProgramResult = load_default_program_for_mode(Samovar_Mode);
  if (!defaultProgramResult.ok()) {
    String error = "Аварийная блокировка: ";
    error += format_program_parse_error(defaultProgramResult);
    Serial.println(error);
    request_emergency_stop(error);
  }

  // Поверх дефолта кладём программу из снимка предыдущей работы, если он от этого же
  // режима. ФС уже смонтирована (FS_init выше), семафор журнала создан.
  restore_state_snapshot();

  setup_init_output_pins();

  setup_init_menu_display_and_chip_id();

  setup_connect_wifi_and_notify();

  alarm_event = false;

  sensor_init();

  startService();
  samovar_reset();

  WebServerInit();
  Serial.println(F("Samovar started"));
  
  setup_init_crash_handler();

#ifdef SAMOVAR_USE_POWER
  //Запускаем таск считывания параметров регулятора
  const BaseType_t powerTaskCreated = xTaskCreatePinnedToCore(
    triggerPowerStatus, /* Function to implement the task */
    "PowerStatusTask",  /* Name of the task */
    POWER_STATUS_STACK_BYTES, /* Stack size in bytes (в ESP-IDF это байты, а не слова) */
    NULL,               /* Task input parameter */
    1,                  /* Priority of the task */
    &PowerStatusTask,   /* Task handle. */
    0);                 /* Core where the task should run */
  const bool powerTaskReady = powerTaskCreated == pdPASS && PowerStatusTask != nullptr;
  set_power_worker_ready(powerTaskReady);
  if (powerTaskReady) {
    //На всякий случай пошлем команду выключения питания на UART
    set_power_mode(POWER_SLEEP_MODE);
  } else {
    request_emergency_stop("Аварийное отключение: задача регулятора не запущена");
  }
#endif

  setup_start_web_serial();

  setup_attach_water_flow_interrupt();

  setup_configure_head_level_sensor();

#ifdef USE_MQTT
  const bool mqttLockReady = init_mqtt_lock();
  if (!mqttLockReady) {
    // Fail-open: мьютекс MQTT не создался (xMqttSemaphore остаётся nullptr). mqtt_lock()
    // в SamovarMqtt.h уже проверяет handle на nullptr и отказывает вызывающему, так что
    // connectToMqtt/disconnectFromMqtt/mqttConnected/MqttSendMsg сами по себе безопасны —
    // но initMqtt() всё равно НЕ вызываем ниже, чтобы не заводить клиент/коллбэки впустую.
    report_degraded_boot("mqtt", "mutex init failed");
    Serial.println(F("WARN: MQTT disabled: cloud status/log publishing will not run; local control, heating and safety logic are unaffected"));
  }
  if (mqttLockReady && !wifiAP) {
    initMqtt();
    vTaskDelay(500);
  }
#endif

  //Запускаем таск для получения температур и различных проверок
  xTaskCreatePinnedToCore(
    triggerSysTicker, /* Function to implement the task */
    "SysTicker",      /* Name of the task */
    SYS_TICKER_STACK_BYTES, /* Stack size in bytes (в ESP-IDF это байты, а не слова) */
    NULL,             /* Task input parameter */
    1,                /* Priority of the task */
    &SysTickerTask1,  /* Task handle. */
    0);               /* Core where the task should run */

  //Запускаем таск для получения точного времени и записи в лог
  xTaskCreatePinnedToCore(
    triggerGetClock,  /* Function to implement the task */
    "GetClockTicker", /* Name of the task */
    GET_CLOCK_STACK_BYTES, /* Stack size in bytes (в ESP-IDF это байты, а не слова) */
    NULL,             /* Task input parameter */
    1,                /* Priority of the task */
    &GetClockTask1,   /* Task handle. */
    1);               /* Core where the task should run */

  setup_start_ntp();

  setup_finalize_boot_display();

  setup_report_degraded_boot();

  session_checkpoint_report_pending();
  state_snapshot_report_pending();

  // [T30] Сторож основного loop() - строго в САМОМ КОНЦЕ setup(), а не в начале: до этой
  // строки setup() ещё выполняет разовую инициализацию (WiFi, задачи, NVS, OTA-колбэки),
  // которая сама может занимать больше LOOP_WDT_TIMEOUT_S секунд, и не обязана укладываться
  // в бюджет ОДНОЙ итерации loop(), для которой сторож рассчитан (esp_task_wdt_reset()
  // в loopTask(), ядро Arduino-ESP32, вызывается РОВНО один раз на итерацию, перед loop()).
  // panic=true: зависший loop() перезагружает контроллер, а не тихо висит - нагрев уже
  // выключен init_power_outputs_safe_off() (первая строка setup() выше) и полярность реле
  // применена до первого pinMode/digitalWrite, так что перезагрузка безопаснее зависания.
  // #ifndef __SAMOVAR_NOT_USE_WDT: setup_disable_watchdogs() (выше по setup(), под этим же
  // макросом) - существующий отладочный рубильник всех сторожей (для работы под JTAG, где
  // сторож ложно сработал бы на точке останова). Без этой проверки код ниже молча
  // включил бы сторож обратно сразу после того, как разработчик его выключил.
#ifndef __SAMOVAR_NOT_USE_WDT
  esp_task_wdt_init(LOOP_WDT_TIMEOUT_S, true);
  enableLoopWDT();
#endif
}

// [П24] Таблица дополнительно наблюдаемых задач для tick_check_stack_headroom().
// Хранится УКАЗАТЕЛЬ на хэндл, а не сам хэндл: часть задач создаётся уже после
// формирования таблицы (или не создаётся вовсе при выключенном фиче-макросе), и на
// этот момент хэндл ещё/навсегда остаётся NULL - это не ошибка, просто задача не
// существует, и такую запись нужно молча пропустить.
struct StackWatchEntry {
  TaskHandle_t* handle;
  const char* name;
};

static const StackWatchEntry stackWatchTable[] = {
  { &SysTickerTask1, "SysTicker" },
  { &GetClockTask1, "GetClockTicker" },
  // GetBMPTask (Samovar.h) нигде не создаётся - хэндл всегда NULL и естественно
  // отфильтруется проверкой ниже.
  { &GetBMPTask, "GetBMPTask" },
#ifdef SAMOVAR_USE_POWER
  { &PowerStatusTask, "PowerStatusTask" },
#endif
#ifdef ALARM_BTN_PIN
  { &EmergencyButtonTask, "EmergencyButtonTask" },
#endif
#ifdef USE_LUA
  { &DoLuaScriptTask, "DoLuaScriptTask" },
#endif
};

static void tick_check_stack_headroom() {
  // Проверка переполнения стека. Порог в БАЙТАХ: uxTaskGetStackHighWaterMark в ESP-IDF
  // считает байты, поэтому прежние 325 срабатывали тогда, когда на отсечку нагрева и
  // отправку сообщения (их кадры плюс временные String — около 200 байт) стека уже не
  // хватало, и сторож падал раньше, чем успевал погасить ТЭН.
  if (uxTaskGetStackHighWaterMark(NULL) < 1024) {
    request_emergency_stop("Аварийное отключение: критически малый остаток стека");
    SendMsg("Стек переполнился. Перезагрузка", ALARM_MSG);
    vTaskDelay(5000);
    ESP.restart();
  }

  // [П24] Раньше проверялся только стек текущей задачи (loop()). PowerStatusTask
  // (самый маленький из рабочих стеков, и именно он на путях отказа регулятора строит
  // длинные String), SysTicker, GetClockTicker и EmergencyButtonTask не проверялись вовсе.
  // Текст причины собираем ЗДЕСЬ, на стеке loop() (эта функция всегда вызывается из
  // loop(), не из проверяемой задачи) - если бы конкатенацию String делала сама
  // задача с уже критически малым остатком стека, это её бы и добило.
  for (size_t i = 0; i < sizeof(stackWatchTable) / sizeof(stackWatchTable[0]); i++) {
    TaskHandle_t handle = *stackWatchTable[i].handle;
    if (handle == nullptr) continue;
    if (uxTaskGetStackHighWaterMark(handle) < 1024) {
      request_emergency_stop(String("Аварийное отключение: критически малый остаток стека задачи ") + stackWatchTable[i].name);
      SendMsg(String("Стек задачи ") + stackWatchTable[i].name + " переполнился. Перезагрузка", ALARM_MSG);
      vTaskDelay(5000);
      ESP.restart();
    }
  }
}

// [П4] Наблюдатель живучести SysTicker: без него зависание задачи (например, на
// xSemaphoreTake(xI2CSemaphore, 1000) при полуживой шине I2C или внутри DS_getvalue())
// молча останавливает mode_dispatch_alarm() - проверки перегрева/воды/датчиков/давления
// перестают выполняться при включённом нагреве, а loop() и веб на другом ядре продолжают
// отвечать, маскируя проблему снаружи. esp_task_wdt тут не годится: единственное место в
// репозитории, где он реально используется - вендоренный AsyncTCP.cpp, и там он дважды
// принудительно выключен, плюс на ядре Arduino-ESP32 3.x (ESP-IDF 5.x) поменялась сигнатура
// esp_task_wdt_init. Поэтому вместо watchdog - счётчик пульса sysTickerHeartbeat.
static void tick_check_systicker_liveness() {
  // Порог 10 секунд: внутри одной секундной итерации SysTicker легитимно может провести
  // несколько секунд - там до двух таймаутов xSemaphoreTake по 1000 мс (шаговый двигатель,
  // датчики) плюс время конверсии DS18B20. 10 с даёт запас и не даёт ложных срабатываний
  // на штатных задержках шины.
  static uint32_t lastHeartbeat = sysTickerHeartbeat;
  static unsigned long lastChangeMs = millis();

  uint32_t currentHeartbeat = sysTickerHeartbeat;
  if (currentHeartbeat != lastHeartbeat) {
    lastHeartbeat = currentHeartbeat;
    lastChangeMs = millis();
    return;
  }

  if (millis() - lastChangeMs > 10000) {
    request_emergency_stop("Аварийное отключение: задача надзора SysTicker зависла");
    SendMsg("Задача надзора SysTicker зависла. Перезагрузка", ALARM_MSG);
    vTaskDelay(5000);
    ESP.restart();
  }
}

static void tick_reload_stepper_timer() {
  //пересчитаем время работы таймера для шагового двигателя
#ifdef USE_STEPPER_ACCELERATION
  portENTER_CRITICAL(&timerMux);
#if (defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3))
  timerAlarm(timer, stepper.getPeriod(), true, 0);
#else  // ESP_ARDUINO_VERSION_MAJOR >= 3
  timerAlarmWrite(timer, stepper.getPeriod(), true);
#endif
  portEXIT_CRITICAL(&timerMux);
#endif  //USE_STEPPER_ACCELERATION
}

static void tick_ota() {
#ifdef USE_UPDATE_OTA
  ArduinoOTA.handle();
  // Во время OTA даем больше времени на обработку и чаще вызываем yield
  if (ota_running) {
    yield();
    delay(1);  // Небольшая задержка для стабильности передачи
  }
#endif
}

static void tick_blynk() {
#ifdef SAMOVAR_USE_BLYNK
  // Отключаем Blynk во время OTA для освобождения ресурсов. Лок короткий: не взяли -
  // пропускаем такт (Blynk.run() позовём на следующем обороте loop()), а не ждём и не
  // блокируем весь loop() ради Blynk. BLYNK_WRITE/BLYNK_READ в Blynk.ino выполняются
  // изнутри Blynk.run(), т.е. уже под этим локом.
  BlynkLockGuard blynkLock(pdMS_TO_TICKS(20));
  if (blynkLock && !ota_running && Blynk.connected()) {
    Blynk.run();
  }
#endif
}

static void tick_alarm_button() {
#ifdef ALARM_BTN_PIN
  alarm_btn.tick();  // отработка нажатия аварийной кнопки
  if (alarm_btn.isPress()) {
    set_alarm();
  }
#endif
}

static void tick_process_recovery_commands() {
  {
    bool hasPendingResetWifi = false;
    PendingCommandLockGuard guard;
    if (guard && pending_reset_wifi_flag) {
      pending_reset_wifi_flag = false;
      hasPendingResetWifi = true;
    }
    guard.release();
    if (hasPendingResetWifi) {
      delay(200);
      menu_reset_wifi();
    }
  }
  {
    bool hasPendingReboot = false;
    PendingCommandLockGuard guard;
    if (guard && is_reboot) {
      is_reboot = false;
      hasPendingReboot = true;
    }
    guard.release();
    if (hasPendingReboot) {
      delay(200);
      ESP.restart();
    }
  }
}

static void tick_reap_stale_operations() {
  // Реапер просроченных операций (PKG-H): не чаще ~1с под pending_command_lock переводит
  // зависшие QUEUED/RUNNING в FAILED и однократно (латч внутри) сигналит ALARM. Выполняется
  // и при активном барьере — стешенная операция могла быть его причиной.
  {
    static uint32_t lastReapMs = 0;
    const uint32_t nowMs = millis();
    if ((int32_t)(nowMs - lastReapMs) >= 1000) {
      lastReapMs = nowMs;
      bool reaped = false;
      PendingCommandLockGuard guard;
      if (guard) {
        reaped = operation_store_reap_stale_locked(operationStore, nowMs);
        // Реапер лечит только карточку на складе; канал I2C, который эту карточку держал,
        // сам не отпускается - без этого цикла флаг зависает навсегда и канал умирает.
        // Цикл идёт ВСЕГДА, а не по значению reaped: reaped - одноразовый признак для
        // ALARM-сообщения (static alarmEmitted внутри operation_store_reap_stale_locked),
        // после первой протухшей операции за сессию он больше не станет true.
        for (size_t index = 0; index < OPERATION_STORE_CAPACITY; index++) {
          const OperationRecord& record = operationStore.records[index];
          if (record.state == OPERATION_STATE_FAILED &&
              record.error == OPERATION_ERROR_STALE_REAPED) {
            clear_pending_i2c_operation_locked(record.id);
          }
        }
      }
      guard.release();
      if (reaped) {
        SendMsg("Просроченная операция принудительно завершена (reaper)", ALARM_MSG);
      }
    }
  }
}

static void tick_apply_pending_self_test_stop() {
  if (take_pending_flag(pending_stop_self_test_flag)) {
    stop_self_test();
  }
}

static void tick_apply_pending_mixer() {
  bool mixerOn = false;
  if (take_pending_value(pending_mixer_flag, pending_mixer_on, mixerOn)) {
    if (set_mixer(mixerOn) == ACTUATOR_COMMAND_FAILED) {
      SendMsg("Команда мешалки не выполнена: исполнитель не подтвердил состояние", ALARM_MSG);
    }
    // [Ревью 24.08, ошибка 1] Та же природа, что в process_pending_i2c_operations()
    // (см. комментарий там): set_mixer() -> set_mixer_state() (beer.h) при найденном
    // I2C-приводе может подряд вызвать set_stepper_by_time() И set_mixer_pump_target() -
    // это i2c_stepper_start()/i2c_stepper_write_config()+i2c_stepper_send_command(),
    // то есть до двух ограниченных, но не мгновенных цепочек ожиданий за один тик.
    // feedLoopWDT() безопасен и при выключенном сторожем - см. обоснование там же.
    feedLoopWDT();
  }
}

static void tick_apply_pending_water_temp() {
  uint16_t waterTemp = 0;
  if (take_pending_value(pending_water_temp_flag, pending_water_temp_value, waterTemp)) {
    set_water_temp(waterTemp);
  }
}

static void tick_apply_pending_pump_speed() {
  uint16_t pumpSpeedSteps = 0;
  if (take_pending_value(pending_pump_speed_flag, pending_pump_speed_steps, pumpSpeedSteps)) {
    set_pump_speed(pumpSpeedSteps, true);
  }
}

static void tick_apply_pending_voltage() {
#ifdef SAMOVAR_USE_POWER
  float voltage = 0;
  if (take_pending_value(pending_voltage_flag, pending_voltage_value, voltage)) {
    set_current_power(voltage);
  }
#endif
}

static void tick_apply_pending_nbkopt() {
  if (take_pending_flag(pending_nbkopt_flag)) {
    if (PowerOn) {
      nbk_Mo = nbk_M;
      nbk_Po = nbk_P;
#ifdef SAMOVAR_USE_POWER
      SendMsg("Установлены оптимальные значения: " + String(fromPower(nbk_Mo), 0) + String(PWR_SIGN) + ",  " + String(nbk_Po, 1) + " л/ч", WARNING_MSG);
#endif
    }
  }
}

static void tick_apply_pending_lua_commands() {
#ifdef USE_LUA
  bool hasPendingLuaReload = false;
  {
    PendingCommandLockGuard guard;
    if (guard && pending_lua_reload_flag) {
      pending_lua_reload_flag = false;
      hasPendingLuaReload = true;
    }
  }
  if (hasPendingLuaReload) {
    if (!load_lua_script()) {
      // Возврат уже принятой заявки, а не постановка новой: queue_pending_flag()
      // отбил бы её при смене режима и при занятом локе, и перезагрузка скрипта
      // потерялась бы молча. Запись одного volatile-флага атомарна, а снимает его
      // только этот такт loop(), поэтому гонки нет.
      pending_lua_reload_flag = true;
    }
  }

  bool hasPendingLuaStart = false;
  {
    PendingCommandLockGuard guard;
    if (guard && pending_lua_start_flag) {
      hasPendingLuaStart = true;
    }
  }
  if (hasPendingLuaStart) {
    if (start_lua_script()) {
      PendingCommandLockGuard guard;
      if (guard && pending_lua_start_flag) {
        pending_lua_start_flag = false;
      }
    }
  }

  bool hasPendingLuaFile = false;
  String luaFile;
  {
    PendingCommandLockGuard guard;
    if (guard && pending_lua_file_flag) {
      luaFile = pending_lua_file;
      hasPendingLuaFile = true;
    }
  }
  if (hasPendingLuaFile) {
    if (run_lua_script(luaFile)) {
      PendingCommandLockGuard guard;
      if (guard && pending_lua_file_flag && pending_lua_file == luaFile) {
        pending_lua_file_flag = false;
      }
    }
  }

  // [W3.1] Исполнение Lua-строки ставится в DoLuaScriptTask; при busy pending остаётся на повтор.
  bool hasPendingLuaString = false;
  String lstr;
  {
    PendingCommandLockGuard guard;
    if (guard && pending_lua_flag) {
      lstr = pending_lua_str;
      hasPendingLuaString = true;
    }
  }
  if (hasPendingLuaString) {
    if (run_lua_string(lstr).length() == 0) {
      PendingCommandLockGuard guard;
      if (guard && pending_lua_flag && pending_lua_str == lstr) {
        pending_lua_flag = false;
      }
    }
  }
#endif
}

static void tick_apply_pending_pnbk() {
  // [W-4] Ручное управление скоростью I2C-насоса (/command?pnbk): get_stepper_speed()/
  //        set_stepper_target() — блокирующий I2C, выполняем здесь. Логика идентична
  //        прежнему async-обработчику; pnbk заменяет request->arg("pnbk").
  bool hasPendingPnbk = false;
  ControlNbkCommand pnbk = {};
  {
    PendingCommandLockGuard guard;
    if (guard && pending_pnbk_flag) {
      pnbk = pending_pnbk_value;
      hasPendingPnbk = true;
    }
  }
  if (hasPendingPnbk) {
    bool pnbkDone = !PowerOn;
    // [W-4] PowerOn проверяем на момент ИСПОЛНЕНИЯ (не только при постановке флага в async):
    //        питание могло выключиться между запросом и выполнением (команда SAMOVAR_POWER
    //        обрабатывается в этом же loop раньше). Флаг сбрасываем всегда — устаревшую
    //        команду при возврате питания не исполняем.
    if (PowerOn) {
      if (pnbk.kind == CONTROL_NBK_INCREMENT) {
        uint16_t deltaSpeed = 0;
        NumericParseResult conversion = checked_rate_to_step_speed(
            float(SamSetup.NbkDP) + 0.0001f,
            SamSetup.StepperStepMlI2C,
            deltaSpeed);
        const uint32_t requestedSpeed = uint32_t(get_stepper_speed()) + deltaSpeed;
        if (!conversion.ok() || requestedSpeed > UINT16_MAX) {
          SendMsg("Команда НБК отклонена: неверная калибровка скорости.", WARNING_MSG);
          pnbkDone = true;
        } else {
          pnbkDone = set_stepper_target(uint16_t(requestedSpeed), 0, 2147483640);
        }
      } else if (pnbk.kind == CONTROL_NBK_DECREMENT) {
        uint16_t currentSpeed = get_stepper_speed();
        float deltaRate = float(SamSetup.NbkDP) - 0.0001f;
        uint16_t deltaSpeed = 0;
        NumericParseResult conversion = deltaRate > 0.0f
            ? checked_rate_to_step_speed(deltaRate, SamSetup.StepperStepMlI2C, deltaSpeed)
            : numeric_parse_result(NUMERIC_PARSE_OK);
        if (!conversion.ok()) {
          SendMsg("Команда НБК отклонена: неверная калибровка скорости.", WARNING_MSG);
          pnbkDone = true;
        } else if (deltaSpeed >= currentSpeed) {
          pnbkDone = set_stepper_target(0, 0, 0);
        } else {
          pnbkDone = set_stepper_target(currentSpeed - deltaSpeed, 0, 2147483640);
        }
      } else if (pnbk.kind == CONTROL_NBK_ABSOLUTE) {
        pnbkDone = set_stepper_target(pnbk.stepSpeed, 0, 2147483640);
      } else if (pnbk.kind == CONTROL_NBK_STOP) {
        pnbkDone = set_stepper_target(0, 0, 0);
      } else {
        pnbkDone = true;
      }
      // [Ревью 24.08, ошибка 1] Та же природа, что в process_pending_i2c_operations()
      // (см. комментарий там): set_stepper_target() при обнаруженном I2C-насосе идёт
      // через i2c_stepper_start()/i2c_stepper_stop() - ограниченную, но не мгновенную
      // цепочку ожиданий семафора шины. feedLoopWDT() безопасен и при выключенном
      // сторожем - см. обоснование в process_pending_i2c_operations().
      feedLoopWDT();
    }
    if (pnbkDone) {
      PendingCommandLockGuard guard;
      if (guard) pending_pnbk_flag = false;
    }
  }
}

// async_tcp (ядро 1, приоритет 5, см. AGENTS.md) вытесняет эту задачу (ядро 1, приоритет 1)
// в произвольной точке - обработчик HTTP-запроса может вклиниться посреди итерации loop().
// Общие данные с ним - только под блокировкой (LOCK_ORDER в runtime_helpers.h).
void loop() {
  tick_check_stack_headroom();
  tick_check_systicker_liveness();
  tick_reload_stepper_timer();

  tick_ota();

  tick_blynk();

  // Обработка кнопок и энкодера
  tick_alarm_button();

  if (pending_emergency_stop_flag) {
    perform_emergency_stop();
    return;
  }

  tick_power_transition();
  cancel_invalid_mode_heating_session();
  tick_self_test();
  tick_nbk_transition();

#ifdef BTN_PIN
  //обработка нажатий кнопки и разное поведение в зависимости от режима работы
  btn.tick();
  const bool mainButtonHeld = btn.isHolded();
  const bool mainButtonClicked = btn.isClick();
  const bool mainButtonPressed = btn.isPress();
  if (!mode_switch_in_progress()) {
    if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
      if (mainButtonHeld && PowerOn &&
          startval != SAMOVAR_STARTVAL_IDLE &&
          startval != SAMOVAR_STARTVAL_CALIBRATION &&
          SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
        menu_samovar_start();
      } else if (mainButtonClicked) {
        //если выключен - включаем
        if (!PowerOn) {
          set_power(true);
        } else if (startval == SAMOVAR_STARTVAL_IDLE && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
          //если включен и программа отбора не работает - запускаем программу
          menu_samovar_start();
        } else if (startval != SAMOVAR_STARTVAL_IDLE && !program_Pause && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
          //если выполняется программа, и программа - не пауза, ставим на паузу или снимаем с паузы
          pause_withdrawal(!PauseOn);
        } else if (startval != SAMOVAR_STARTVAL_IDLE && program_Pause && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
          //если выполняется программа, и программа - пауза, переходим к следующей программе
          menu_samovar_start();
        }
        //Выход из режима калибровки - короткое нажатие на кнопку.
        if (startval == SAMOVAR_STARTVAL_CALIBRATION) {
          startval = SAMOVAR_STARTVAL_IDLE;
          menu_calibrate();
          menu_switch_focus();
        }
      }
    } else if (mainButtonPressed) {
      mode_dispatch_button_press();
    }
  }
#endif

  SamovarCommandMsg commandMsg;
  while (!mode_switch_in_progress() && receive_samovar_command(commandMsg, 0)) {
    switch (commandMsg.command) {
      case SAMOVAR_START:
        mode_apply_power_on_command(commandMsg.command);
        break;
      case SAMOVAR_POWER:
        if (!PowerOn && Samovar_Mode == SAMOVAR_RECTIFICATION_MODE &&
            !rectification_ds_sensors_assigned()) {
          notify_rectification_sensors_unassigned();
          break;
        }
        if (!mode_finish_by_status(SamovarStatusInt)) set_power(!PowerOn);
        if (PowerOn && Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
          SamovarStatusInt = SAMOVAR_STATUS_RECT_ACCEL;
        }
        break;
      case SAMOVAR_POWER_OFF:
        if (!mode_finish_by_status(SamovarStatusInt)) set_power(false);
        break;
      case SAMOVAR_RESET:
        samovar_reset();
        break;
      case CALIBRATE_START:
        pump_calibrate(CurrrentStepperSpeed);
        break;
      case CALIBRATE_STOP:
        pump_calibrate(0);
        break;
      case SAMOVAR_PAUSE:
        // [P2 п.6][Ревью] Тело консолидировано в enter_manual_pause() (logic.h).
        enter_manual_pause();
        break;
      case SAMOVAR_CONTINUE:
        // [P7 п.4][P2 п.6] Тело консолидировано в resume_from_pause() (logic.h).
        resume_from_pause();
        break;
      case SAMOVAR_SETBODYTEMP:
        body_temp_row_base = 0;  // [Ф4] ручная установка - новая опора автоподъёма
        set_body_temp();
        break;
      case SAMOVAR_DISTILLATION:
        mode_apply_power_on_command(commandMsg.command);
        break;
      case SAMOVAR_BEER:
        mode_apply_power_on_command(commandMsg.command);
        break;
      case SAMOVAR_BEER_NEXT:
        run_beer_program(ProgramNum + 1);
        break;
      case SAMOVAR_DIST_NEXT:
        run_dist_program(ProgramNum + 1);
        break;
      case SAMOVAR_BK:
        mode_apply_power_on_command(commandMsg.command);
        break;
      case SAMOVAR_NBK:
#ifdef SAMOVAR_USE_POWER
        mode_apply_power_on_command(commandMsg.command);
#else
        SendMsg("Запуск НБК отклонён: регулятор мощности недоступен в этой сборке.", ALARM_MSG);
#endif
        break;
      case SAMOVAR_NBK_NEXT:
        run_nbk_program(ProgramNum + 1, true);
        break;
      case SAMOVAR_SELF_TEST:
        start_self_test();
        break;
      case SAMOVAR_NONE:
        break;
    }
  }

  // ---------------------------------------------------------------------------
  // Обработка отложенных команд из async-обработчиков
  // ---------------------------------------------------------------------------

  process_profile_operation();
  process_pending_i2c_operations();

  // Recovery-команды (resetwifi/reboot) обрабатываем ДО барьер-return ниже: при застрявшем
  // mode_switch_barrier_active loop() уходит в ранний return, поэтому здесь — единственное
  // место, где рестарт/сброс Wi-Fi (поставленные с bypassBarrier в /command) гарантированно
  // исполнятся. Это закрывает блокер «503 BUSY навсегда после MODE_SWITCH_FAILED».
  tick_process_recovery_commands();

  tick_reap_stale_operations();

  if (mode_switch_in_progress()) {
    process_buzzer();
    vTaskDelay(5 / portTICK_PERIOD_MS);
    return;
  }

  tick_apply_pending_self_test_stop();

  tick_apply_pending_mixer();

  tick_apply_pending_water_temp();

  tick_apply_pending_pump_speed();

  tick_apply_pending_voltage();

  tick_apply_pending_nbkopt();

  // Обработка recovery-команд (reboot/resetwifi) и реапера перенесена ВЫШЕ барьер-return,
  // чтобы застрявший mode_switch_barrier_active не блокировал восстановление устройства.

  tick_apply_pending_lua_commands();

  tick_apply_pending_pnbk();

  mode_dispatch_loop();
  suvid_tick();
  session_checkpoint_tick();

  // Обработка энкодера
  encoder.tick();
  encoder_getvalue();

#ifdef USE_HEAD_LEVEL_SENSOR
  head_level_sensor_tick();
#endif

  process_buzzer();
  vTaskDelay(5 / portTICK_PERIOD_MS);
}

static inline void jsonAddKey(Print &out, bool &first, const char *key) {
  if (!first) out.print(',');
  first = false;
  out.print('\"');
  out.print(key);
  out.print("\":");
}

static void jsonPrintEscaped(Print &out, const String &value) {
  // Результат осознанно отбрасывается: вызывающий jsonFieldString и раньше не проверял
  // ошибок записи, а сигнатура этой функции - void.
  json_write_escaped(out, value.c_str(), value.length());
}

static inline void jsonFieldFloat(Print &out, bool &first, const char *key, float value, int decimals) {
  jsonAddKey(out, first, key);
  out.print(format_float(value, decimals));
}

static inline void jsonFieldString(Print &out, bool &first, const char *key, const String &value) {
  jsonAddKey(out, first, key);
  out.print('"');
  jsonPrintEscaped(out, value);
  out.print('"');
}

static inline void jsonFieldBool(Print &out, bool &first, const char *key, bool value) {
  jsonAddKey(out, first, key);
  out.print(value ? 1 : 0);
}

#include "json_field_raw.h"

static bool runtimeEventWrite(Print& out, const char* value, size_t length) {
  return out.write(reinterpret_cast<const uint8_t*>(value), length) == length;
}

static bool runtimeEventWriteEscaped(Print& out, const char* text, size_t length) {
  return json_write_escaped(out, text, length);
}

static bool runtimeEventWriteUnsigned(Print& out, uint32_t value) {
  char number[11];
  const int length = snprintf(number, sizeof(number), "%lu", static_cast<unsigned long>(value));
  return length > 0 && static_cast<size_t>(length) < sizeof(number) &&
         runtimeEventWrite(out, number, static_cast<size_t>(length));
}

static bool runtimeEventWriteSection(
    Print& out, const RuntimeEventDescriptor& event, const String& packedTexts) {
  if (static_cast<uint32_t>(event.offset) + event.length > packedTexts.length()) {
    return false;
  }
  const char* text = packedTexts.c_str() + event.offset;
  const size_t length = event.length;
  if (!runtimeEventWrite(out, "{", 1)) return false;
  if (event.kind == RUNTIME_EVENT_MESSAGE) {
    if (!runtimeEventWrite(out, "\"Msg\":\"", sizeof("\"Msg\":\"") - 1U) ||
        !runtimeEventWriteEscaped(out, text, length) ||
        !runtimeEventWrite(out, "\",\"msglvl\":", sizeof("\",\"msglvl\":") - 1U) ||
        !runtimeEventWriteUnsigned(out, event.level)) {
      return false;
    }
  } else if (event.kind == RUNTIME_EVENT_CONSOLE) {
    if (!runtimeEventWrite(out, "\"LogMsg\":\"", sizeof("\"LogMsg\":\"") - 1U) ||
        !runtimeEventWriteEscaped(out, text, length) ||
        !runtimeEventWrite(out, "\"", 1)) {
      return false;
    }
  } else {
    return false;
  }
  return runtimeEventWrite(
             out, ",\"messageSequence\":", sizeof(",\"messageSequence\":") - 1U) &&
         runtimeEventWriteUnsigned(out, event.sequence) &&
         runtimeEventWrite(out, "}", 1);
}

static RuntimeAjaxQuery classifyRuntimeAjaxQuery(AsyncWebServerRequest* request) {
  const size_t parameterCount = request->params();
  const AsyncWebParameter* firstParam = nullptr;
  bool allOperationIds = parameterCount > 0;
  for (size_t index = 0; index < parameterCount; index++) {
    const AsyncWebParameter* param = request->getParam(index);
    if (index == 0) firstParam = param;
    if (!param || param->name() != "operationId") allOperationIds = false;
  }

  if (allOperationIds) {
    uint32_t operationId = 0;
    const bool validOperationId =
        parameterCount == 1 && firstParam && !firstParam->isFile() &&
        !firstParam->isPost() && runtime_event_parse_cursor(
            firstParam->value().c_str(), firstParam->value().length(), operationId) &&
        operationId != 0;
    return {validOperationId ? RUNTIME_AJAX_QUERY_OPERATION
                             : RUNTIME_AJAX_QUERY_INVALID_OPERATION,
            validOperationId ? operationId : 0};
  }

  uint32_t messageCursor = 0;
  const bool validCursor =
      parameterCount == 1 && firstParam && firstParam->name() == "messageCursor" &&
      !firstParam->isFile() && !firstParam->isPost() &&
      runtime_event_parse_cursor(
          firstParam->value().c_str(), firstParam->value().length(), messageCursor);
  return {validCursor ? RUNTIME_AJAX_QUERY_TELEMETRY
                      : RUNTIME_AJAX_QUERY_BAD_REQUEST,
          validCursor ? messageCursor : 0};
}

static bool sendRuntimeAjaxQueryError(
    AsyncWebServerRequest* request, RuntimeAjaxQueryKind kind) {
  const char* contentType = nullptr;
  const char* body = nullptr;
  char invalidOperationBody[80];
  if (kind == RUNTIME_AJAX_QUERY_INVALID_OPERATION) {
    contentType = "application/json";
    snprintf(invalidOperationBody, sizeof(invalidOperationBody),
             "{\"operationId\":0,\"error\":\"%s\"}",
             operation_error_code(OPERATION_ERROR_INVALID_ID));
    body = invalidOperationBody;
  } else if (kind == RUNTIME_AJAX_QUERY_BAD_REQUEST) {
    contentType = "text/plain";
    body = "BAD_REQUEST";
  } else {
    return false;
  }
  AsyncWebServerResponse* response = request->beginResponse(400, contentType, body);
  response->addHeader("Cache-Control", "no-store");
  request->send(response);
  return true;
}

static bool sendRuntimeEventResponse(
    AsyncWebServerRequest* request, AsyncResponseStream* response,
    const RuntimeEventDescriptor* events, uint8_t count, const String& packedTexts) {
  Print& out = *response;
  bool ok = count == 0
                ? runtimeEventWrite(out, "}", 1)
                : runtimeEventWrite(out, ",\"events\":[", sizeof(",\"events\":[") - 1U);
  for (uint8_t index = 0; ok && index < count; index++) {
    if (index > 0) ok = runtimeEventWrite(out, ",", 1);
    if (ok) ok = runtimeEventWriteSection(out, events[index], packedTexts);
  }
  if (ok && count > 0) ok = runtimeEventWrite(out, "]}", 2);
  if (ok) {
    request->send(response);
    return true;
  }
  delete response;
  AsyncWebServerResponse* unavailableResponse = request->beginResponse(
      503, "text/plain", "Runtime event response unavailable");
  unavailableResponse->addHeader("Cache-Control", "no-store");
  request->send(unavailableResponse);
  return false;
}

struct AjaxTelemetrySnapshot {
  String crt;
  String uptime;
  String programType;
  String status;
  String luaStatus;
  String currentPowerMode;
  String eventText;
  float bmeTemp;
  float bmePressure;
  float startPressure;
  float steamTemp;
  float pipeTemp;
  float waterTemp;
  float tankTemp;
  float acpTemp;
  float detectorTrend;
  float actualVolumePerHour;
  float steamBodyTemp;
  float pipeBodyTemp;
  float i2cStepperSpeed;
  float i2cPumpTargetMl;
  float i2cPumpRemainingMl;
  float alcohol;
  float steamAlcohol;
#ifdef SAMOVAR_USE_POWER
  float currentPowerVolt;
  float targetPowerVolt;
  uint16_t currentPower;
#endif
#ifdef USE_WATERSENSOR
  float waterFlowRate;
  uint32_t waterFlowTotalMl;
#endif
#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_1WIRE) || defined(USE_PRESSURE_MPX)
  float pressure;
#endif
#ifdef USE_WATER_PUMP
  uint16_t waterPumpSpeed;
#endif
  uint32_t freeHeap;
  int32_t rssi;
  uint32_t freeFsBytes;
  int32_t targetSteps;
  int32_t currentSteps;
  float currentSpeed;
  int volumeAll;
  int timeRemaining;
  int totalTime;
  int rowPredictedTotalTime;
  int processRemainingTime;
  int16_t withdrawalStatus;
  // [Б6.1] Числовой статус для клиентов телеметрии (SamovarStatusInt), не
  // строковое имя status - JSON-ключ ниже называется "SamovarStatusInt" по
  // историческим причинам, а само поле structа - statusInt: smoke_a05_state_owners.py
  // запрещает сериализатору читать глобальные переменные напрямую и держит
  // "SamovarStatusInt" в списке запрещённых токенов, поэтому поле структуры не
  // может называться так же, как глобальная переменная.
  int16_t statusInt;
  uint16_t stepperStepMl;
  uint16_t i2cPumpSpeed;
  uint8_t detectorStatus;
  uint8_t distRowPredictionReason;
  uint8_t distProcessPredictionReason;
  uint8_t boilingEvidence;
  uint8_t withdrawalProgress;
  uint8_t programIndex;
  bool useAutoSpeed;
  bool powerOn;
  bool pauseOn;
  bool beerPaused;  // [Пиво 02.09 C2] Ручная пауза пива (зеркалит beerManualPause) для /ajax
  bool useBrowserBuzzer;
  bool mixer;
  bool i2cStepperPresent;
  bool i2cMixerPresent;
  bool i2cPumpPresent;
  bool i2cPumpRunning;
  bool hasAlcohol;
  bool hasTimePrediction;
  bool rowPredictionAvailable;
  bool processPredictionAvailable;
  RuntimeEventDescriptor runtimeEvents[RUNTIME_EVENT_DESCRIPTOR_CAPACITY];
  uint8_t eventCount;
  bool heaterAlarmLatched;
  String heaterAlarmReason;
  bool boilingDetected;
  bool boilingPrecisionSensorConfigured;
  uint32_t latestMessageSequence;
};

static_assert(sizeof(AjaxTelemetrySnapshot) <= 768,
              "AjaxTelemetrySnapshot exceeds its request stack budget");

static RuntimeAjaxSnapshotResult captureAjaxTelemetrySnapshot(
    uint32_t messageCursor, AjaxTelemetrySnapshot& snapshot) {
  const RuntimeAjaxSnapshotResult snapshotResult = copy_ajax_runtime_snapshot(
      snapshot.crt, snapshot.status, snapshot.luaStatus,
      snapshot.currentPowerMode, messageCursor, snapshot.eventText,
      snapshot.runtimeEvents, snapshot.eventCount,
      snapshot.latestMessageSequence);
  if (snapshotResult != RUNTIME_AJAX_SNAPSHOT_OK) return snapshotResult;

  snapshot.heaterAlarmLatched = heater_safety_latched();
  if (snapshot.heaterAlarmLatched) {
    snapshot.heaterAlarmReason = latched_emergency_stop_reason;
  } else {
    snapshot.heaterAlarmReason = "";
  }
  snapshot.bmeTemp = bme_temp;
  snapshot.bmePressure = bme_pressure;
  snapshot.startPressure = start_pressure;
  snapshot.uptime = format_uptime((unsigned long)(millis() / 1000UL));
  snapshot.steamTemp = SteamSensor.avgTemp;
  snapshot.pipeTemp = PipeSensor.avgTemp;
  snapshot.waterTemp = WaterSensor.avgTemp;
  snapshot.tankTemp = TankSensor.avgTemp;
  snapshot.acpTemp = ACPSensor.avgTemp;
  snapshot.detectorTrend = impurityDetector.currentTrend;
  snapshot.detectorStatus = impurityDetector.detectorStatus;
  snapshot.boilingDetected = boiling_evidence != BOILING_EVIDENCE_NONE;
  snapshot.boilingEvidence = boiling_evidence;
  snapshot.boilingPrecisionSensorConfigured =
      sensor_configured(SteamSensor) || sensor_configured(PipeSensor);
  snapshot.useAutoSpeed = SamSetup.useautospeed;
  snapshot.volumeAll = get_liquid_volume();
  snapshot.actualVolumePerHour = ActualVolumePerHour;
  snapshot.powerOn = PowerOn;
  snapshot.pauseOn = PauseOn;
  snapshot.beerPaused = beerManualPause;  // [Пиво 02.09 C2]
  snapshot.withdrawalProgress = WthdrwlProgress;
  snapshot.targetSteps = stepper_safe_get_target();
  snapshot.currentSteps = stepper_safe_get_current();
  snapshot.withdrawalStatus = startval;
  snapshot.programIndex = ProgramNum;
  snapshot.currentSpeed = round(
      stepper_safe_get_speed() * (uint8_t)stepper_safe_get_state());
  snapshot.useBrowserBuzzer = SamSetup.UseBBuzzer;
  snapshot.stepperStepMl = SamSetup.StepperStepMl;
  snapshot.steamBodyTemp = SteamSensor.BodyTemp;
  snapshot.pipeBodyTemp = PipeSensor.BodyTemp;
  snapshot.mixer = mixer_status;

  const bool i2cMixerPresent = i2c_stepper_cache.mixer_present;
  const bool i2cPumpPresent = i2c_stepper_cache.pump_present;
  snapshot.i2cStepperSpeed = i2c_stepper_cache.pump_current_rate;
  snapshot.i2cStepperPresent = i2cMixerPresent || i2cPumpPresent;
  snapshot.i2cMixerPresent = i2cMixerPresent;
  snapshot.i2cPumpPresent = i2cPumpPresent;
  if (i2cPumpPresent) {
    snapshot.i2cPumpSpeed = i2c_stepper_cache.pump_current_speed;
    snapshot.i2cPumpTargetMl = I2CPumpTargetMl;
    snapshot.i2cPumpRemainingMl = i2c_stepper_cache.pump_remaining;
    snapshot.i2cPumpRunning =
        (i2c_stepper_cache.pump_status & I2CSTEPPER_STATUS_RUNNING) != 0;
  }

  snapshot.freeHeap = ESP.getFreeHeap();
  snapshot.rssi = WiFi.RSSI();
  snapshot.freeFsBytes = total_byte - used_byte;

  const SAMOVAR_MODE mode = Samovar_Mode;
  const int16_t status = SamovarStatusInt;
  snapshot.statusInt = status;  // [Б6.1] числовой статус в телеметрии
  const ProgramType currentType = current_program_type();
  if ((mode == SAMOVAR_RECTIFICATION_MODE || mode == SAMOVAR_BEER_MODE ||
       mode == SAMOVAR_DISTILLATION_MODE || mode == SAMOVAR_NBK_MODE) &&
      (status == SAMOVAR_STATUS_RECT_WITHDRAWAL || status == SAMOVAR_STATUS_RECT_AUTOPAUSE || (status == SAMOVAR_STATUS_BEER && snapshot.powerOn)) &&
      !program_type_empty(currentType)) {
    snapshot.programType = program_type_to_string(currentType);
  }

#ifdef SAMOVAR_USE_POWER
  snapshot.currentPowerVolt = current_power_volt;
  snapshot.targetPowerVolt = target_power_volt;
  snapshot.currentPower = current_power_p;
#endif
#ifdef USE_WATER_PUMP
  snapshot.waterPumpSpeed = water_pump_speed;
#endif
#ifdef USE_WATERSENSOR
  snapshot.waterFlowRate = WFflowRate;
  snapshot.waterFlowTotalMl = WFtotalMilliLitres;
#endif
#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_1WIRE) || defined(USE_PRESSURE_MPX)
  snapshot.pressure = pressure_value;
#endif

  snapshot.hasAlcohol =
      mode == SAMOVAR_DISTILLATION_MODE || mode == SAMOVAR_RECTIFICATION_MODE ||
      mode == SAMOVAR_BK_MODE || mode == SAMOVAR_NBK_MODE;
  if (snapshot.hasAlcohol) {
    snapshot.alcohol = get_alcohol(snapshot.tankTemp);
    snapshot.steamAlcohol = get_steam_alcohol(
        mode == SAMOVAR_RECTIFICATION_MODE ? snapshot.steamTemp : snapshot.tankTemp);
  }

  snapshot.hasTimePrediction =
      snapshot.powerOn && mode == SAMOVAR_DISTILLATION_MODE;
  if (snapshot.hasTimePrediction) {
    snapshot.timeRemaining = int(timePredictor.remainingTime);
    snapshot.totalTime = int(timePredictor.predictedTotalTime);
    snapshot.rowPredictedTotalTime =
        int(timePredictor.rowPredictedTotalTime);
    snapshot.processRemainingTime =
        int(timePredictor.processRemainingTime);
    snapshot.rowPredictionAvailable =
        timePredictor.rowPredictionAvailable;
    snapshot.processPredictionAvailable =
        timePredictor.processPredictionAvailable;
    snapshot.distRowPredictionReason = distRowPredictionReason;
    snapshot.distProcessPredictionReason = distProcessPredictionReason;
  }
  return RUNTIME_AJAX_SNAPSHOT_OK;
}

static void writeAjaxTelemetryFields(
    Print& out, const AjaxTelemetrySnapshot& snapshot) {
  bool first = true;
  out.print('{');

  jsonFieldFloat(out, first, "bme_temp", snapshot.bmeTemp, 3);
  jsonFieldFloat(out, first, "bme_pressure", snapshot.bmePressure, 3);
  jsonFieldFloat(out, first, "start_pressure", snapshot.startPressure, 3);
  jsonFieldString(out, first, "crnt_tm", snapshot.crt);
  jsonFieldString(out, first, "stm", snapshot.uptime);
  jsonFieldFloat(out, first, "SteamTemp", snapshot.steamTemp, 3);
  jsonFieldFloat(out, first, "PipeTemp", snapshot.pipeTemp, 3);
  jsonFieldFloat(out, first, "WaterTemp", snapshot.waterTemp, 3);
  jsonFieldFloat(out, first, "TankTemp", snapshot.tankTemp, 3);
  jsonFieldFloat(out, first, "ACPTemp", snapshot.acpTemp, 3);
  jsonFieldFloat(out, first, "DetectorTrend", snapshot.detectorTrend, 3);
  jsonFieldRaw(out, first, "DetectorStatus", snapshot.detectorStatus);
  jsonFieldBool(out, first, "BoilingDetected", snapshot.boilingDetected);
  jsonFieldRaw(out, first, "BoilingEvidence", snapshot.boilingEvidence);
  jsonFieldBool(out, first, "BoilingPrecisionSensorConfigured", snapshot.boilingPrecisionSensorConfigured);
  jsonFieldBool(out, first, "useautospeed", snapshot.useAutoSpeed);
  jsonAddKey(out, first, "version");
  out.print('"');
  out.print(SAMOVAR_VERSION);
  out.print('"');
  jsonFieldBool(out, first, "boot_degraded", bootDegraded);
  jsonFieldString(out, first, "boot_degraded_reason", bootDegradedReason);
  jsonFieldRaw(out, first, "VolumeAll", snapshot.volumeAll);
  jsonFieldFloat(out, first, "ActualVolumePerHour", snapshot.actualVolumePerHour, 3);
  jsonFieldBool(out, first, "PowerOn", snapshot.powerOn);
  jsonFieldBool(out, first, "PauseOn", snapshot.pauseOn);
  jsonFieldBool(out, first, "BeerManualPause", snapshot.beerPaused);  // [Пиво 02.09 C2]
  jsonFieldRaw(out, first, "WthdrwlProgress", snapshot.withdrawalProgress);
  jsonFieldRaw(out, first, "TargetStepps", snapshot.targetSteps);
  jsonFieldRaw(out, first, "CurrrentStepps", snapshot.currentSteps);
  jsonFieldRaw(out, first, "WthdrwlStatus", snapshot.withdrawalStatus);
  // [Б6.1] Числовой статус (SamovarStatusInt) - клиентам телеметрии, помимо строкового
  // status, нужен и числовой код без парсинга строки.
  jsonFieldRaw(out, first, "SamovarStatusInt", snapshot.statusInt);
  jsonFieldRaw(out, first, "ProgramNum", snapshot.programIndex + 1);
  jsonFieldRaw(out, first, "ProgramIndex", snapshot.programIndex);
  jsonFieldRaw(out, first, "CurrrentSpeed", snapshot.currentSpeed);
  jsonFieldBool(out, first, "UseBBuzzer", snapshot.useBrowserBuzzer);
  jsonFieldRaw(out, first, "StepperStepMl", snapshot.stepperStepMl);
  jsonFieldFloat(out, first, "BodyTemp_Steam", snapshot.steamBodyTemp, 3);
  jsonFieldFloat(out, first, "BodyTemp_Pipe", snapshot.pipeBodyTemp, 3);
  jsonFieldBool(out, first, "mixer", snapshot.mixer);
  jsonFieldFloat(out, first, "ISspd", snapshot.i2cStepperSpeed, 3);
  jsonFieldBool(out, first, "i2c_stepper_present", snapshot.i2cStepperPresent);
  jsonFieldBool(out, first, "i2c_mixer_present", snapshot.i2cMixerPresent);
  jsonFieldBool(out, first, "i2c_pump_present", snapshot.i2cPumpPresent);

  if (snapshot.i2cPumpPresent) {
    jsonFieldRaw(out, first, "i2c_pump_speed", snapshot.i2cPumpSpeed);
    jsonFieldFloat(out, first, "i2c_pump_target_ml", snapshot.i2cPumpTargetMl, 1);
    jsonFieldFloat(out, first, "i2c_pump_remaining_ml", snapshot.i2cPumpRemainingMl, 1);
    jsonFieldBool(out, first, "i2c_pump_running", snapshot.i2cPumpRunning);
  } else {
    jsonFieldRaw(out, first, "i2c_pump_speed", 0);
    jsonFieldRaw(out, first, "i2c_pump_target_ml", 0);
    jsonFieldRaw(out, first, "i2c_pump_remaining_ml", 0);
    jsonFieldRaw(out, first, "i2c_pump_running", 0);
  }

  jsonFieldRaw(out, first, "heap", snapshot.freeHeap);
  jsonFieldRaw(out, first, "rssi", snapshot.rssi);
  jsonFieldRaw(out, first, "fr_bt", snapshot.freeFsBytes);
  jsonFieldString(out, first, "PrgType", snapshot.programType);

#ifdef SAMOVAR_USE_POWER
  jsonFieldFloat(out, first, "current_power_volt", snapshot.currentPowerVolt, 1);
  jsonFieldFloat(out, first, "target_power_volt", snapshot.targetPowerVolt, 1);
  jsonFieldString(out, first, "current_power_mode", snapshot.currentPowerMode);
  jsonFieldRaw(out, first, "current_power_p", snapshot.currentPower);
#else
  jsonFieldRaw(out, first, "current_power_volt", 0);
  jsonFieldRaw(out, first, "target_power_volt", 0);
  jsonAddKey(out, first, "current_power_mode");
  out.print('"');
  out.print(0);
  out.print('"');
  jsonFieldRaw(out, first, "current_power_p", 0);
#endif

#ifdef USE_WATER_PUMP
  jsonFieldRaw(out, first, "wp_spd", snapshot.waterPumpSpeed);
#endif
#ifdef USE_WATERSENSOR
  jsonFieldFloat(out, first, "WFflowRate", snapshot.waterFlowRate, 2);
  jsonFieldRaw(out, first, "WFtotalMl", snapshot.waterFlowTotalMl);
#endif
#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_1WIRE) || defined(USE_PRESSURE_MPX)
  jsonFieldFloat(out, first, "prvl", snapshot.pressure, 2);
#endif

  if (snapshot.hasAlcohol) {
    jsonFieldFloat(out, first, "alc", snapshot.alcohol, 2);
    jsonFieldFloat(out, first, "stm_alc", snapshot.steamAlcohol, 2);
  }
  if (snapshot.hasTimePrediction) {
    jsonFieldBool(out, first, "RowPredictionAvailable", snapshot.rowPredictionAvailable);
    jsonFieldBool(out, first, "ProcessPredictionAvailable", snapshot.processPredictionAvailable);
    jsonFieldRaw(out, first, "RowPredictionReason", snapshot.distRowPredictionReason);
    jsonFieldRaw(out, first, "ProcessPredictionReason", snapshot.distProcessPredictionReason);
    if (snapshot.rowPredictionAvailable) {
      jsonFieldRaw(out, first, "TimeRemaining", String(snapshot.timeRemaining));
      jsonFieldRaw(out, first, "RowTotalTime", String(snapshot.rowPredictedTotalTime));
    }
    if (snapshot.processPredictionAvailable) {
      jsonFieldRaw(out, first, "ProcessTimeRemaining", String(snapshot.processRemainingTime));
      jsonFieldRaw(out, first, "TotalTime", String(snapshot.totalTime));
    }
  }

  jsonFieldString(out, first, "Status", snapshot.status);
  jsonFieldString(out, first, "Lstatus", snapshot.luaStatus);
  jsonFieldBool(out, first, "heaterAlarmLatched", snapshot.heaterAlarmLatched);
  jsonFieldString(out, first, "heaterAlarmReason", snapshot.heaterAlarmReason);
  jsonFieldRaw(out, first, "latestMessageSequence", snapshot.latestMessageSequence);
}

void send_ajax_json(AsyncWebServerRequest *request) {
  const RuntimeAjaxQuery query = classifyRuntimeAjaxQuery(request);
  if (sendRuntimeAjaxQueryError(request, query.kind)) return;

  if (query.kind == RUNTIME_AJAX_QUERY_OPERATION) {
    const OperationId operationId = query.value;
    PendingCommandLockGuard guard;
    if (!guard) {
      char body[96];
      snprintf(body, sizeof(body),
               "{\"operationId\":%lu,\"error\":\"%s\"}",
               static_cast<unsigned long>(operationId),
               operation_error_code(OPERATION_ERROR_LOCK_BUSY));
      AsyncWebServerResponse *lookupResponse =
          request->beginResponse(503, "application/json", body);
      lookupResponse->addHeader("Cache-Control", "no-store");
      request->send(lookupResponse);
      return;
    }

    OperationRecord record{};
    const OperationError lookupError =
        operation_store_copy_locked(operationStore, operationId, record);
    guard.release();

    if (lookupError != OPERATION_ERROR_NONE) {
      char body[96];
      snprintf(body, sizeof(body),
               "{\"operationId\":%lu,\"error\":\"%s\"}",
               static_cast<unsigned long>(operationId),
               operation_error_code(lookupError));
      AsyncWebServerResponse *lookupResponse =
          request->beginResponse(404, "application/json", body);
      lookupResponse->addHeader("Cache-Control", "no-store");
      request->send(lookupResponse);
      return;
    }

    char body[128];
    snprintf(body, sizeof(body),
             "{\"operationId\":%lu,\"state\":\"%s\",\"error\":\"%s\"}",
             static_cast<unsigned long>(record.id),
             operation_state_code(record.state),
             operation_error_code(record.error));
    AsyncWebServerResponse *lookupResponse =
        request->beginResponse(200, "application/json", body);
    lookupResponse->addHeader("Cache-Control", "no-store");
    request->send(lookupResponse);
    return;
  }

  const uint32_t messageCursor = query.value;
  AjaxTelemetrySnapshot snapshot{};
  const RuntimeAjaxSnapshotResult snapshotResult =
      captureAjaxTelemetrySnapshot(messageCursor, snapshot);
  if (snapshotResult == RUNTIME_AJAX_SNAPSHOT_LOCK_BUSY) {
    AsyncWebServerResponse *busyResponse =
        request->beginResponse(503, "text/plain", "Runtime state busy");
    busyResponse->addHeader("Cache-Control", "no-store");
    request->send(busyResponse);
    return;
  }
  if (snapshotResult != RUNTIME_AJAX_SNAPSHOT_OK) {
    AsyncWebServerResponse *unavailableResponse = request->beginResponse(
        503, "text/plain", "Runtime event snapshot unavailable");
    unavailableResponse->addHeader("Cache-Control", "no-store");
    request->send(unavailableResponse);
    return;
  }

  AsyncResponseStream *response = request->beginResponseStream("application/json");
  response->addHeader("Cache-Control", "no-store");

  Print &out = *response;
  writeAjaxTelemetryFields(out, snapshot);
  sendRuntimeEventResponse(
      request, response, snapshot.runtimeEvents, snapshot.eventCount,
      snapshot.eventText);
}

void configModeCallback(AsyncWiFiManager *myWiFiManager) {
  Serial.println(F("Entered config WiFi"));
  Serial.print(F("SSID "));
  Serial.println(myWiFiManager->getConfigPortalSSID());
  Serial.print(F("IP: "));
  Serial.println(WiFi.softAPIP());
  writeString(F("Entered config WiFi "), 1);
  writeString(F("SSID: Samovar       "), 2);
  writeString(F("IP:                 "), 3);
  writeString(WiFi.softAPIP().toString(), 4);
}

void saveConfigCallback() {
  shouldSaveWiFiConfig = true;
}

void apply_config_runtime() {
  nbk_capture_runtime_input_validity(
      SamSetup.HeaterResistant, SamSetup.MainsVoltage);
  for (uint8_t i = 0; i < DS_SENSOR_COUNT; i++) {
    sensorList[i]->SetTemp = SamSetup.*kSensorSetupFields[i].setTemp;
    sensorList[i]->Delay = SamSetup.*kSensorSetupFields[i].delay;
  }
  if (SamSetup.LogPeriod == 0) SamSetup.LogPeriod = 3;
  if (SamSetup.autospeed >= 100) SamSetup.autospeed = 0;
  // [Б1.2] Насос отбора не откалиброван (0 шагов/мл в NVS) - validate_rect_program_startable()
  // блокирует СТАРТ программы, но не лечит уже загруженный профиль. Подтягиваем к
  // заводской калибровке, как остальные поля этой функции.
  if (SamSetup.StepperStepMl == 0) SamSetup.StepperStepMl = STEPPER_STEP_ML;
  // [Б9] Плотность насадки вне рабочего диапазона формы - подтягиваем к заводскому
  // дефолту (profile_setup_fields.h: PackDens=80).
  if (SamSetup.PackDens < 60 || SamSetup.PackDens > 100) SamSetup.PackDens = 80;
  apply_setup_sensor_fields(0);

  // Проверка через валидатор, а не только по верхней границе: SamSetup.Mode — знаковый int
  // из загруженного профиля, и отрицательное значение раньше проходило насквозь. Тогда
  // mode_ops_by_mode() не находит запись реестра и mode_dispatch_alarm() молча не вызывает
  // ни одного обработчика — надзор за авариями пропадает. Семантика прежняя (тихий сброс
  // в 0, а не отказ): это путь загрузки профиля, ронять его нельзя.
  if (!is_valid_samovar_mode(SamSetup.Mode)) SamSetup.Mode = 0;
  Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode;
  change_samovar_mode();

  // [WP17 п.45 tail] Номер режима валиден (проверка выше), но валидный режим может быть
  // НЕ скомпилирован в этой сборке (НБК без регулятора мощности, Lua без USE_LUA) -
  // mode_available_in_build()/mode_unavailable_reason() читают ту же таблицу реестра, что
  // и WebServer.ino handleSave (там - отказ сохранения; здесь другая ситуация: значение уже
  // применяется в рантайме на старте/из меню, отбить нечем). Samovar_Mode при этом уже
  // равен настроенному значению (строка выше) - и остаётся таким: ПОДМЕНЯТЬ его на другой,
  // доступный режим НЕЛЬЗЯ, это та же молчаливая подмена настройки, которую handleSave как
  // раз чинит; пользователь должен узнать правду и переключить сам. Запуска недоступного
  // режима это не открывает: и mode_dispatch_loop(), и nbk.h run_nbk_program() отбивают
  // старт независимо (см. smoke_mode_build_availability). apply_config_runtime() вызывается
  // на КАЖДОЕ применение профиля (не только когда режим реально сменился), поэтому сообщение
  // не шлём повторно, пока режим не изменится - тот же приём "один раз на смену состояния",
  // что и noDZ_message_sent (nbk.h) / pressure_alarm_sent (Samovar.ino, triggerSysTicker).
  // Обе точки вызова apply_config_runtime() в setup() и здесь же в рантайме идут ПОСЛЕ
  // xMsgSemaphore = xSemaphoreCreateMutexStatic(...) в setup() - SendMsg безопасен.
  static int modeUnavailableWarnedFor = -1;  // ни один SAMOVAR_MODE не равен -1
  if (!mode_available_in_build(Samovar_Mode)) {
    if ((int)Samovar_Mode != modeUnavailableWarnedFor) {
      const char* reason = mode_unavailable_reason(Samovar_Mode);
      SendMsg(String("Режим из настроек не активирован: ") +
                  (reason ? reason : "недоступен в этой сборке прошивки"),
              ALARM_MSG);
      modeUnavailableWarnedFor = (int)Samovar_Mode;
    }
  } else {
    modeUnavailableWarnedFor = -1;
  }

  if ((uint8_t)SamSetup.videourl[0] == 0xFF) SamSetup.videourl[0] = '\0';
#ifdef SAMOVAR_USE_BLYNK
  // apply_config_runtime() зовётся и из setup() (до старта задач), и из loop() через
  // process_profile_operation() - в обоих случаях в конечном счёте это контекст loop(),
  // поэтому лок берём с тем же коротким таймаутом, что и tick_blynk(): не взяли - просто
  // пропускаем эту пару обращений, следующее применение профиля повторит попытку.
  {
    BlynkLockGuard blynkLock(pdMS_TO_TICKS(20));
    if (blynkLock) {
      if (strlen(SamSetup.videourl) > 0) Blynk.setProperty(V20, "url", (String)SamSetup.videourl);
      Blynk.virtualWrite(V15, ipst);
    }
  }
#else
  SamSetup.blynkauth[0] = '\0';
#endif

  if (isnan(SamSetup.Kp)) {
    SamSetup.Kp = 150;
  }
  if (isnan(SamSetup.Ki)) {
    SamSetup.Ki = 1.4;
  }
  if (isnan(SamSetup.Kd)) {
    SamSetup.Kd = 1.4;
  }
  heaterPID.SetTunings(SamSetup.Kp, SamSetup.Ki, SamSetup.Kd);
  heaterPID.SetOutputLimits(0, 100);
  heaterPID.SetSampleTime(1000);
  if (isnan(SamSetup.StbVoltage)) {
    SamSetup.StbVoltage = 100;
  }

  // bool-поля не проверяем через isnan()

  if (isnan(SamSetup.BVolt)) {
    SamSetup.BVolt = 230;
  }

  // [Ревью 25.08] Серверный минимум BKPower поднят с 0 до рабочего порога регулятора
  // (WebServer.ino, kSaveFloatFields - power_work_mode_threshold()): мощность БК ниже
  // порога уводит регулятор в спящий режим, и нагрев после закипания тихо встаёт. Но
  // профиль в NVS у уже обновившихся пользователей мог сохранить BKPower из старого
  // диапазона (0; порог) - проверка "<= 0" такое значение не ловила, и форма настроек
  // переставала сохраняться ЦЕЛИКОМ (одно поле вне диапазона отбивает весь запрос -
  // handleSave, collect_save_bad_field), пока пользователь сам не догадается поднять
  // мощность БК. Подтягиваем к рабочему дефолту - тем же приёмом, что уже применён к
  // DistTemp из старого диапазона ниже.
  if (isnan(SamSetup.BKPower) || SamSetup.BKPower < power_work_mode_threshold()) {
#ifndef SAMOVAR_USE_SEM_AVR
    SamSetup.BKPower = 45;
#else
    SamSetup.BKPower = 200;
#endif
  }
  if (isnan(SamSetup.MainsVoltage) || SamSetup.MainsVoltage <= 0) SamSetup.MainsVoltage = 230;

  if (isnan(SamSetup.SetWaterTemp) || SamSetup.SetWaterTemp == 0) SamSetup.SetWaterTemp = TARGET_WATER_TEMP;
  if (isnan(SamSetup.SetACPTemp) || SamSetup.SetACPTemp == 0) SamSetup.SetACPTemp = 43;
  // [П11-фикс 23.08] Серверный минимум DistTemp поднят с 0 до 30 (WebServer.ino,
  // kSaveFloatFields) - условие окончания (TankSensor.avgTemp >= DistTemp) при малых
  // значениях завершает дистилляцию/БК/ректификацию почти мгновенно. Но профиль в NVS у
  // уже обновившихся пользователей мог сохранить DistTemp из старого диапазона (0; 30) -
  // такое значение не ловилось проверкой "<= 0" и оставалось миной до первого запуска
  // процесса. Подтягиваем его так же, как уже подтягивался <=0 и NaN - к тому же самому
  // рабочему дефолту DEFAULT_DIST_TEMP, а не к голому новому минимуму 30: 30°C - это
  // нижняя граница поля ввода, а не осмысленная рабочая температура окончания.
  if (isnan(SamSetup.DistTemp) || SamSetup.DistTemp < 30.0f) SamSetup.DistTemp = DEFAULT_DIST_TEMP;
  if (isnan(SamSetup.DistTimeF)) {
    SamSetup.DistTimeF = 16;
  }
  if (isnan(SamSetup.MaxPressureValue)) {
    SamSetup.MaxPressureValue = 0;
  }


#ifdef USE_HEAD_LEVEL_SENSOR
  // bool-поле не проверяем через isnan()
#endif


#ifdef USE_WATER_PUMP
  pump_regulator.setpoint = SamSetup.SetWaterTemp;  // сообщаем регулятору температуру, которую он должен поддерживать
#endif

#ifdef IGNORE_HEAD_LEVEL_SENSOR_SETTING
  SamSetup.UseHLS = true;
#endif

#ifdef USE_TELEGRAM
  if ((uint8_t)SamSetup.tg_token[0] == 0xFF) {
    SamSetup.tg_token[0] = '\0';
  }
  if ((uint8_t)SamSetup.tg_chat_id[0] == 0xFF) {
    SamSetup.tg_chat_id[0] = '\0';
  }
#else
  SamSetup.tg_token[0] = '\0';
  SamSetup.tg_chat_id[0] = '\0';
#endif
  //Инициализация детектора примесей
  init_impurity_detector();
}

static void printRuntimeEventPublishFailure(
    Print& output, const __FlashStringHelper* name,
    RuntimeEventPublishResult result, size_t length) {
  if (result == RUNTIME_EVENT_PUBLISH_LOCK_BUSY) {
    output.print(F("WARNING! "));
    output.print(name);
    output.println(F(" busy"));
  } else if (result == RUNTIME_EVENT_PUBLISH_TEXT_TOO_LONG) {
    output.print(F("WARNING! "));
    output.print(name);
    output.print(F(" too long: "));
    output.print(static_cast<unsigned long>(length));
    output.print(F(" > "));
    output.println(RUNTIME_EVENT_MAX_TEXT_BYTES);
  } else if (result == RUNTIME_EVENT_PUBLISH_CORRUPT) {
    output.print(F("ERROR! "));
    output.print(name);
    output.println(F(" event store corrupt"));
  }
}

void SendMsg(const String& m, MESSAGE_TYPE msg_type) {
  if (m.length() < 5) return;
  String MsgPl;
#ifdef USE_MQTT
  MsgPl = m;
  MsgPl.replace(",", ";");
  MqttSendMsg(MsgPl + "," + msg_type, "msg");
#endif
#ifdef USE_TELEGRAM
  switch (msg_type) {
    case 0: MsgPl = F("*Тревога!*\n"); break;
    case 1: MsgPl = F("*Предупреждение!*\n"); break;
    case 2: MsgPl = ""; break;
    default: MsgPl = "";
  }
  MsgPl += " Самовар - " + m;
  const BaseType_t queueTakeResult =
      xSemaphoreTake(xMsgSemaphore, (TickType_t)(50 / portTICK_RATE_MS));
  bool queuePushResult = false;
  if (queueTakeResult == pdTRUE) {
    queuePushResult = msg_q.push(MsgPl.c_str());
    xSemaphoreGive(xMsgSemaphore);
  }
  if (queueTakeResult != pdTRUE) {
    WriteConsoleLog(F("notify_queue_push_lock_busy"));
  } else if (!queuePushResult) {
    WriteConsoleLog(F("notify_queue_push_failed"));
  }
#endif

  const RuntimeEventPublishResult publishResult = append_web_message(m, msg_type);
#ifdef USE_WEB_SERIAL
  printRuntimeEventPublishFailure(WebSerial, F("Msg"), publishResult, m.length());
#endif
  printRuntimeEventPublishFailure(Serial, F("Msg"), publishResult, m.length());
}

void WriteConsoleLog(String StringLogMsg) {

  for (size_t i = 0; i < StringLogMsg.length(); i++) {
    if (StringLogMsg[i] == '"') StringLogMsg[i] = '\'';
    else if (StringLogMsg[i] == '\r') StringLogMsg[i] = '^';
    else if (StringLogMsg[i] == '\n') StringLogMsg[i] = ' ';
  }
  const RuntimeEventPublishResult publishResult = append_console_log(StringLogMsg);

#ifdef USE_WEB_SERIAL
  WebSerial.println(StringLogMsg);
  Serial.println(StringLogMsg);
#else
  Serial.println(StringLogMsg);
#endif

#ifdef USE_WEB_SERIAL
  printRuntimeEventPublishFailure(WebSerial, F("LogMsg"), publishResult, StringLogMsg.length());
#endif
  printRuntimeEventPublishFailure(Serial, F("LogMsg"), publishResult, StringLogMsg.length());
}
