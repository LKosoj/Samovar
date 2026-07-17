//TODO
//
//Проверить на С подъем напряжения
//Перейти на GyverPID

// copy partitions/samovar.csv to /Users/user/Library/Arduino15/packages/esp32/hardware/esp32/3.x.x/tools/partitions/samovar.csv
// add to /Users/user/Library/Arduino15/packages/esp32/hardware/esp32/3.x.x/boards.txt
// esp32.menu.PartitionScheme.samovar=Samovar
// esp32.menu.PartitionScheme.samovar.build.partitions=samovar
// esp32.menu.PartitionScheme.samovar.upload.maximum_size=1638400

//**************************************************************************************************************
// Подключение библиотек
//**************************************************************************************************************

//#define Serial2 Serial

// CONFIG_ASYNC_TCP_RUNNING_CORE вынесен в platformio.ini (build_flags) — только оттуда
// он доходит до отдельного TU библиотеки Async_TCP. Локальный #define здесь был мёртвым.

struct AjaxTelemetrySnapshot;

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

#ifndef __SAMOVAR_DEBUG
#define ARDUINOTRACE_ENABLE 0  // Disable all traces
#endif
#include <ArduinoTrace.h>

#ifdef __SAMOVAR_NOT_USE_WDT
#include "soc/rtc_wdt.h"
#include <esp_task_wdt.h>
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

//#include "font.h"
#include "logic.h"

#ifdef USE_UPDATE_OTA
#include <ArduinoOTA.h>
#endif

#ifdef SAMOVAR_USE_BLYNK
//#define BLYNK_PRINT Serial
//#define BLYNK_TIMEOUT_MS 888
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
#include "SPIFFSEditor.h"

//#include <HTTPClient.h>
//HTTPClient client;
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

volatile bool mode_switch_barrier_active = false;

// [W-9] Отложенное сканирование OneWire датчиков
volatile bool pending_rescan_ds_flag = false;

// [W1] Аварийный останов выполняется из loop(), а не из SysTicker/async.
volatile bool pending_emergency_stop_flag = false;
volatile bool pending_emergency_stop_reason_flag = false;
char pending_emergency_stop_reason[EMERGENCY_STOP_REASON_LEN] = "";

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

static void apply_setup_sensor_fields(uint8_t resetMask) {
  CopyDSAddress(SamSetup.SteamAdress, SteamSensor.Sensor);
  CopyDSAddress(SamSetup.PipeAdress, PipeSensor.Sensor);
  CopyDSAddress(SamSetup.WaterAdress, WaterSensor.Sensor);
  CopyDSAddress(SamSetup.TankAdress, TankSensor.Sensor);
  CopyDSAddress(SamSetup.ACPAdress, ACPSensor.Sensor);

  if ((resetMask & PROFILE_SENSOR_RESET_STEAM) != 0) clear_ds_sensor_runtime(SteamSensor);
  if ((resetMask & PROFILE_SENSOR_RESET_PIPE) != 0) clear_ds_sensor_runtime(PipeSensor);
  if ((resetMask & PROFILE_SENSOR_RESET_WATER) != 0) clear_ds_sensor_runtime(WaterSensor);
  if ((resetMask & PROFILE_SENSOR_RESET_TANK) != 0) clear_ds_sensor_runtime(TankSensor);
  if ((resetMask & PROFILE_SENSOR_RESET_ACP) != 0) clear_ds_sensor_runtime(ACPSensor);
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
  if (hasSettings) {
    const PersistResult persistResult = save_profile_nvs(active_profile_operation.settings);
    if (persistResult != PERSIST_OK) {
      // modeChange: режим ниже применяется в RAM несмотря на отказ NVS, поэтому
      // ОЗУ и NVS расходятся - работает новый режим, сохранён прежний. Текст
      // обязан назвать именно расхождение: иначе про откат при перезагрузке
      // пользователь узнает только после неё. Запас до молчаливого усечения в
      // msg_q (200 байт на запись минус приставки SendMsg) - 23 байта при самом
      // длинном коде persist_result_code, длиннее текст делать нельзя.
      String message = modeChange
          ? "Режим переключён, но не сохранён, перезагрузка вернёт прежний: "
          : "Настройки не сохранены: ";
      message += persist_result_code(persistResult);
      SendMsg(message, ALARM_MSG);
      // !modeChange: менять нечего (только настройки) - ранний возврат безопасен.
      // modeChange: применение режима в RAM обязано дойти до конца всегда - см.
      // switch_samovar_mode/force_complete_mode_switch_failed.
      if (!modeChange) {
        runtime_state_unlock(runtimeLocked);
        return OPERATION_ERROR_PROFILE_PERSIST_FAILED;
      }
      persistFailed = true;
    }
  }

  if (modeChange) samovar_reset();
  if (hasSettings) SamSetup = active_profile_operation.settings;
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

  if (hasSettings) apply_config_runtime();
#ifdef USE_LUA
  if (modeChange) {
    lua_type_script = get_lua_mode_name();
    load_lua_script();
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
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return;
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
  pending_command_unlock(true);
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
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (!locked) return;
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
            portENTER_CRITICAL(&emergencyStopMux);
            mode_switch_barrier_active = false;
            portEXIT_CRITICAL(&emergencyStopMux);
          }
          reset_profile_operation_slot();
        } else {
          active_profile_operation.terminalState = OPERATION_STATE_FAILED;
          active_profile_operation.terminalError = OPERATION_ERROR_INTERNAL;
          profile_operation_phase_store(PROFILE_OPERATION_FAILED_CLOSED);
          transitionFailed = true;
        }
      }
    }
    pending_command_unlock(true);
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
        portENTER_CRITICAL(&emergencyStopMux);
        mode_switch_barrier_active = false;
        portEXIT_CRITICAL(&emergencyStopMux);
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

bool is_valid_samovar_mode(long mode);

#ifdef USE_LUA
bool set_lua_mode_value(LuaModeTarget target, int32_t value) {
  if (!is_valid_samovar_mode(value)) return false;
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  if (profile_operation_phase_load() != PROFILE_OPERATION_EMPTY ||
      mode_switch_in_progress()) {
    pending_command_unlock(true);
    return false;
  }

  const SAMOVAR_MODE mode = static_cast<SAMOVAR_MODE>(value);
  switch (target) {
    case LUA_MODE_TARGET_SETUP:
      SamSetup.Mode = value;
      break;
    case LUA_MODE_TARGET_ACTIVE:
      if (Samovar_Mode != mode) {
        Samovar_Mode = mode;
        change_samovar_mode();
      }
      break;
    case LUA_MODE_TARGET_CONTROL:
      Samovar_CR_Mode = mode;
      break;
    default:
      pending_command_unlock(true);
      return false;
  }

  pending_command_unlock(true);
  return true;
}

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

  bool present = i2c_stepper_refresh(device, true);
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
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (!locked) return;
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
    }
    pending_command_unlock(true);
    return;
  }

  PendingI2COperationOwner owner = PENDING_I2C_OPERATION_NONE;
  PendingI2CStepperCmd stepperCommand{};
  PendingI2CPumpCmd pumpCommand{};
  PendingLocalCalCmd localCalibrationCommand{};
  PendingI2CCalCmd i2cCalibrationCommand{};
  OperationId operationId = 0;
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return;
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
  pending_command_unlock(true);
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

// void reset_migration_flag(); // Только для тестирования миграции

#ifdef __SAMOVAR_DEBUG
//LOG_LOCAL_LEVEL ESP_LOG_VERBOSE
//CORE_DEBUG_LEVEL ARDUHAL_LOG_LEVEL_VERBOSE
#endif

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
  //timerEnd(timer);
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
  pinMode(ALARM_BTN_PIN, INPUT_PULLUP);
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
      if (!Blynk.connected() && WiFi.status() == WL_CONNECTED && SamSetup.blynkauth[0] != 0) {
        Blynk.connect(BLYNK_TIMEOUT_MS);
        vTaskDelay(50 / portTICK_PERIOD_MS);
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
        if (SamSetup.blynkauth[0] != 0) {
          if (Blynk.connected()) {
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
        bool locked = pending_command_lock(pdMS_TO_TICKS(50));
        if (locked && pending_rescan_ds_flag) {
          pending_rescan_ds_flag = false;
          rescanDs = !mode_switch_in_progress();
        }
        pending_command_unlock(locked);
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
      vTaskDelay(5 / portTICK_PERIOD_MS);

      // [W-3] Обновляем кэш I2C-шагового двигателя раз в секунду из SysTicker.
      //        Выполняем здесь (не в async), так как I2C защищён xI2CSemaphore внутри функций.
      refresh_i2c_stepper_cache(i2cStepperMixer);
      refresh_i2c_stepper_cache(i2cStepperPump);

      // [C-1] Формируем строки времени в локалах, под замком только присваиваем глобалам.
      {
        String localCrt = NTP.getFormattedDate();
        //String localStrCrt = localCrt.substring(6) + "   " + NTP.getUptimeString();
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

      process_pending_data_log_ops();

      if (startval != 0) {
        tcntST++;
        if (tcntST >= SamSetup.LogPeriod) {
          tcntST = 0;
          String s = append_data();  //Записываем данные в память ESP32;
          if (s.length() > 0) {
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
      }

      //проверка параметров работы колонны на критичность и аварийное выключение нагрева, в случае необходимости
      mode_dispatch_alarm();

      vTaskDelay(5 / portTICK_PERIOD_MS);

      //Считаем прогресс для текущей строки программы и время до конца завершения строки и всего отбора (режим пива)
      ProgramType tickerProgramType = current_program_type();
      if (Samovar_Mode == SAMOVAR_BEER_MODE) {
        float wp;
        if (program[ProgramNum].Time > 0 && begintime > 0) {
          wp = float(millis() - begintime) / 1000 / 60 / program[ProgramNum].Time;
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

      } else if (Samovar_Mode == SAMOVAR_BK_MODE) {

      } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {

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
            wp = 1 - (WthdrwTime / program[ProgramNum].Time);
          } else {
            WthdrwTime = 0;
            wp = 0;
          }
        } else {
          wp = (float)CurrrentStepps / (float)TargetStepps;
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


      vTaskDelay(5 / portTICK_PERIOD_MS);

#ifdef USE_WATERSENSOR

      uint16_t waterPulses = water_pulse_count_take();

      if (waterPulses < 3) waterPulses = 0;
      WFflowRate = ((1000.0 / (millis() - oldTime)) * waterPulses) / WF_CALIBRATION;
      WFflowMilliLitres = WFflowRate * 100 / 6;
      WFtotalMilliLitres += WFflowMilliLitres;

      if (TankSensor.avgTemp > (OPEN_VALVE_TANK_TEMP + 2) && PowerOn && waterPulses == 0 && SamSetup.UseWS) {
        WFAlarmCount++;
      } else {
        WFAlarmCount = 0;
      }

      oldTime = millis();
      vTaskDelay(5 / portTICK_PERIOD_MS);
#endif

      //Проверяем, что температурные датчики считывают температуру без проблем, если есть проблемы - пишем оператору
      if (SteamSensor.ErrCount > 10) {
        SteamSensor.ErrCount = -110;
        SendMsg(("Ошибка датчика температуры пара!"), ALARM_MSG);
      }
      if (PipeSensor.ErrCount > 10) {
        PipeSensor.ErrCount = -110;
        SendMsg(("Ошибка датчика температуры царги!"), ALARM_MSG);
      }
      if (WaterSensor.ErrCount > 10) {
        WaterSensor.ErrCount = -110;
        SendMsg(("Ошибка датчика температуры воды!"), ALARM_MSG);
      }
      if (TankSensor.ErrCount > 10) {
        TankSensor.ErrCount = -110;
        SendMsg(("Ошибка датчика температуры куба!"), ALARM_MSG);
      }
      if (ACPSensor.ErrCount > 10) {
        ACPSensor.ErrCount = -110;
        SendMsg(("Ошибка датчика температуры в ТСА!"), ALARM_MSG);
      }

      // [C-2/2a] Продвигаем FSM и обновляем кэш SamovarStatus раз в секунду.
      // Все переходы в get_Samovar_Status() оперируют секундными интервалами,
      // поэтому секундная каденция достаточна. WthdrwTimeS/WthdrwTimeAllS к этому
      // моменту уже записаны выше под замком — читаем актуальные значения.
      // Замок в этой точке не удерживается → вложенного захвата нет.
      get_Samovar_Status();

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

void setup() {
  vTaskDelay(500 / portTICK_PERIOD_MS);
  Serial.begin(115200);
  init_power_outputs_safe_off();

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
  startupProfile.HeaterResistant = trusted_heater_resistance(storedHeaterR);
  if (startupProfile.HeaterResistant != storedHeaterR) {
    Serial.print(F("WARN: heater resistance "));
    Serial.print(storedHeaterR, 3);
    Serial.print(F(" out of range, using default "));
    Serial.print(startupProfile.HeaterResistant, 3);
    Serial.println(F(": set the real value in setup.htm, power calculations depend on it"));
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
  print_nvs_stats("after config load");

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
  pinMode(0, INPUT);
  vTaskDelay(600 / portTICK_PERIOD_MS);
  if (digitalRead(0) == LOW) {
    WiFi.mode(WIFI_STA);  // cannot erase if not in STA mode !
    WiFi.persistent(true);
    WiFi.disconnect(true, true);
    WiFi.persistent(false);
  }
#ifdef __SAMOVAR_NOT_USE_WDT
  esp_task_wdt_init(1, false);
  esp_task_wdt_init(2, false);
  rtc_wdt_protect_off();
  rtc_wdt_disable();
  disableCore0WDT();
  disableCore1WDT();
#endif
  heap_caps_enable_nonos_stack_heaps();

#ifdef __SAMOVAR_DEBUG
  esp_log_level_set("*", ESP_LOG_VERBOSE);
  Serial.println("Using ESP object:");
  Serial.println(ESP.getSdkVersion());

  Serial.println("Using lower level function:");
  Serial.println(esp_get_idf_version());
#endif
  //delay(2000);
  //  dac_output_disable(DAC_CHANNEL_1);
  //  dac_output_disable(DAC_CHANNEL_2);
  //  touch_pad_isr_deregister();
  //  touch_pad_deinit();
#if defined(ARDUINO_ESP32S3_DEV)
#else
  touch_pad_intr_disable();
#endif

  xMsgSemaphore = xSemaphoreCreateBinaryStatic(&xMsgSemaphoreBuffer);
  xSemaphoreGive(xMsgSemaphore);

  xRuntimeStateSemaphore = xSemaphoreCreateBinaryStatic(&xRuntimeStateSemaphoreBuffer);
  runtime_event_init(runtimeEventRing);
  xSemaphoreGive(xRuntimeStateSemaphore);

  xPendingCommandSemaphore = xSemaphoreCreateBinaryStatic(&xPendingCommandSemaphoreBuffer);
  xSemaphoreGive(xPendingCommandSemaphore);

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

  xI2CSemaphore = xSemaphoreCreateBinaryStatic(&xI2CSemaphoreBuffer);
  xSemaphoreGive(xI2CSemaphore);

  WiFi.mode(WIFI_STA);  // explicitly set mode, esp defaults to STA+AP
  // НЕ используем WiFi.disconnect(true) здесь, так как это может очистить сохраненные креденшалы
  // Вместо этого просто отключаемся без очистки сохраненных данных
  WiFi.disconnect(false);
  delay(50);
  WiFi.setSleep(false);
  WiFi.setHostname(host);
  WiFi.setAutoReconnect(true);

  Wire.begin(LCD_SDA, LCD_SCL);
  //Wire.begin();

  lcd_found = (check_I2C_device(LCD_ADDRESS) == LCD_ADDRESS);

  stepper.disable();

  WFtotalMilliLitres = 0;

  // Configure the Prescaler at 80 the quarter of the ESP32 is cadence at 80Mhz
  // 80000000 / 80 = 1000000 tics / seconde
#if (defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3))
  timer = timerBegin(1000000);
  timerAttachInterrupt(timer, &StepperTicker);
#else  // ESP_ARDUINO_VERSION_MAJOR >= 3
  timer = timerBegin(2, 80, true);
  timerAttachInterrupt(timer, &StepperTicker, true);
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

  // Инициализация кнопок и энкодера (обработка в loop())
#ifdef BTN_PIN
  btn.setType(LOW_PULL);
  btn.setTickMode(AUTO);
  btn.setDebounce(30);
#endif

#ifdef ALARM_BTN_PIN
  alarm_btn.setType(HIGH_PULL);
  alarm_btn.setTickMode(AUTO);
  alarm_btn.setDebounce(30);
#endif

  // Если при старте кнопка удерживается 2 секунды - Самовар запустится в режиме AP
  bool wifiAP = false;
#ifdef BTN_PIN
  btn.resetStates();
  vTaskDelay(35 / portTICK_PERIOD_MS);
  if (btn.state()) {
    uint32_t buttonHoldStart = millis();
    while (btn.state() && millis() - buttonHoldStart < 2000) {
      vTaskDelay(20 / portTICK_PERIOD_MS);
    }
    wifiAP = btn.state();
  }
  btn.resetStates();
#endif

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

#ifdef ALARM_BTN_PIN
  if (!initEmergencyButtonTask()) {
    request_emergency_stop("Аварийное отключение: задача аварийной кнопки не запущена");
  }
#endif

#ifdef USE_PRESSURE_MPX
  //Инициализируем ногу для датчика давления MPX5010D
  pinMode(LUA_PIN, INPUT);
#endif

  //Настраиваем меню
  setupMenu();
  writeString(F("      Samovar "), 1);
  writeString("     Version " + (String)SAMOVAR_VERSION, 2);
  //delay(2000);
  writeString(F("Connecting to WI-FI"), 3);

  //Serial.print("Reset reason: ");
  //Serial.println(vr);
  for (uint8_t i = 0; i < 17; i = i + 8) {
    chipId |= ((ESP.getEfuseMac() >> (40 - i)) & 0xff) << i;
  }
  //uint8_t *MAC = ESP.getEfuseMac();
  //Serial.printf("%02x%02x%02x%02x%02x%02x\n", MAC[5], MAC[4], MAC[3], MAC[2], MAC[1], MAC[0]);

  Serial.printf("ESP32 Chip model = %s Rev %d\n", ESP.getChipModel(), ESP.getChipRevision());
  //Serial.printf("This chip has %d cores\n", ESP.getChipCores());
  Serial.print("Chip ID: ");
  Serial.println(chipId);

  String StIP;
  //esp_wifi_set_ps( WIFI_PS_NONE );

  if (!wifiAP) {
    AsyncWiFiManagerParameter custom_blynk_token("blynk", "blynk token", SamSetup.blynkauth, 33, "blynk token");
    AsyncWiFiManager wifiManager(&server, &dns);

    encoder.tick();  // отработка нажатия
    if (encoder.isPress()) wifiManager.resetSettings();

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
          SamSetup = profileCandidate;
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

  //connectWiFi();
  writeString(F("Connected"), 4);

#ifdef SAMOVAR_USE_BLYNK
  if (SamSetup.blynkauth[0] != 0 && !wifiAP) {
    //Blynk.begin(auth, ssid, password);
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
    if (Blynk.connected()) {
      Blynk.disconnect();
    }
#endif
#ifdef USE_MQTT
    disconnectFromMqtt();
#endif
  });
  ArduinoOTA.onEnd([]() {
    ota_running = false;  // Сбрасываем флаг после завершения
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

  alarm_event = false;

  sensor_init();

  startService();
  samovar_reset();

  WebServerInit();
  Serial.println(F("Samovar started"));
  
#ifdef USE_CRASH_HANDLER
  // Инициализация обработчика сбоев (после инициализации файловой системы)
  init_crash_handler();
#endif

#ifdef SAMOVAR_USE_POWER
  //Запускаем таск считывания параметров регулятора
  const BaseType_t powerTaskCreated = xTaskCreatePinnedToCore(
    triggerPowerStatus, /* Function to implement the task */
    "PowerStatusTask",  /* Name of the task */
    1800,               /* Stack size in words */
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

#ifdef USE_WEB_SERIAL
  WebSerial.begin(&server);
  WebSerial.onMessage(recvMsg);
#endif

#ifdef USE_WATERSENSOR
  //вешаем прерывание на изменения датчика потока воды
  attachInterrupt(WATERSENSOR_PIN, WFpulseCounter, FALLING);
#endif

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

  //WiFi.hostByName(ntpServerName, timeServerIP);

  //Запускаем таск для получения температур и различных проверок
  xTaskCreatePinnedToCore(
    triggerSysTicker, /* Function to implement the task */
    "SysTicker",      /* Name of the task */
    3200,             /* Stack size in words */
    NULL,             /* Task input parameter */
    1,                /* Priority of the task */
    &SysTickerTask1,  /* Task handle. */
    0);               /* Core where the task should run */

  //Запускаем таск для получения точного времени и записи в лог
  xTaskCreatePinnedToCore(
    triggerGetClock,  /* Function to implement the task */
    "GetClockTicker", /* Name of the task */
    3400,             /* Stack size in words */
    NULL,             /* Task input parameter */
    1,                /* Priority of the task */
    &GetClockTask1,   /* Task handle. */
    1);               /* Core where the task should run */

  //  //Запускаем таск для чтения давления
  //  xTaskCreatePinnedToCore(
  //    triggerGetBMP,      /* Function to implement the task */
  //    "GetBMPTicker",     /* Name of the task */
  //    1400,               /* Stack size in words */
  //    NULL,               /* Task input parameter */
  //    1,                  /* Priority of the task */
  //    &GetBMPTask,        /* Task handle. */
  //    0);                 /* Core where the task should run */

  //  //write reset reason
  //  if (!SPIFFS.exists("/resetreason.css")) {
  //    File f = SPIFFS.open("/resetreason.css", FILE_WRITE);
  //    f.close();
  //  }
  //  File f1 = SPIFFS.open("/resetreason.css", FILE_APPEND);
  //  f1.println(vr);
  //  f1.close();
  //  vr.replace(",",";");

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
  //Serial.println(sizeof(SamSetup));

  SamovarStatus.reserve(80);

  // Публикуем итог degraded-загрузки одним пакетом: здесь уже подняты и семафоры для
  // SendMsg/WriteConsoleLog, и все точки отказа (профиль, ФС, очередь команд, веб, MQTT)
  // уже отработали, так что в сообщение попадают ВСЕ причины, а не только ранние.
  // bootDegradedReason сам называет отказавшую подсистему, поэтому текст общий.
  if (bootDegraded) {
    const String notice = String(F("Загрузка с ошибками (")) + bootDegradedReason +
                          F("). Часть функций недоступна, работаем в ограниченном режиме.");
    WriteConsoleLog(notice);
    SendMsg(notice, ALARM_MSG);
  }
}

void loop() {
  // Проверка переполнения стека
  if (uxTaskGetStackHighWaterMark(NULL) < 325) {
    request_emergency_stop("Аварийное отключение: критически малый остаток стека");
    SendMsg("Стек переполнился. Перезагрузка", ALARM_MSG);
    vTaskDelay(5000);
    ESP.restart();
  }
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

#ifdef USE_UPDATE_OTA
  ArduinoOTA.handle();
  // Во время OTA даем больше времени на обработку и чаще вызываем yield
  if (ota_running) {
    yield();
    delay(1);  // Небольшая задержка для стабильности передачи
  }
#endif

#ifdef SAMOVAR_USE_BLYNK
  // Отключаем Blynk во время OTA для освобождения ресурсов
  if (!ota_running && Blynk.connected()) {
    Blynk.run();
  }
#endif

  // Обработка кнопок и энкодера
#ifdef ALARM_BTN_PIN
  alarm_btn.tick();  // отработка нажатия аварийной кнопки
  if (alarm_btn.isPress()) {
    set_alarm();
  }
#endif

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
  if (!mode_switch_in_progress() && btn.isPress()) {
    if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
      //если выключен - включаем
      if (!PowerOn) {
        set_power(true);
      } else if (startval == 0 && SamovarStatusInt < 1000) {
        //если включен и программа отбора не работает - запускаем программу
        menu_samovar_start();
      } else if (startval != 0 && !program_Pause && SamovarStatusInt < 1000) {
        //если выполняется программа, и программа - не пауза, ставим на паузу или снимаем с паузы
        pause_withdrawal(!PauseOn);
      } else if (startval != 0 && program_Pause && SamovarStatusInt < 1000) {
        //если выполняется программа, и программа - пауза, переходим к следующей программе
        menu_samovar_start();
      }
      //Выход из режима калибровки - нажатие на кнопку.
      if (startval == 100) {
        startval = 0;
        menu_calibrate();
        menu_switch_focus();
      }
    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
      //если дистилляция включаем или выключаем
      if (!PowerOn) {
        if (!queue_samovar_command(SAMOVAR_DISTILLATION)) SendMsg("Очередь команд занята: старт дистилляции не поставлен", WARNING_MSG);
      } else
        distiller_finish();
    } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
      //если дистилляция включаем или выключаем
      if (!PowerOn) {
        if (!queue_samovar_command(SAMOVAR_BK)) SendMsg("Очередь команд занята: старт БК не поставлен", WARNING_MSG);
      } else
        bk_finish();
    } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
      //если НБК включаем или выключаем
      if (!PowerOn) {
        if (!queue_samovar_command(SAMOVAR_NBK)) SendMsg("Очередь команд занята: старт НБК не поставлен", WARNING_MSG);
      } else
        nbk_finish();
    } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
      //если пиво включаем или двигаем программу
      if (!PowerOn) {
        if (!queue_samovar_command(SAMOVAR_BEER)) SendMsg("Очередь команд занята: старт пива не поставлен", WARNING_MSG);
      } else
        run_beer_program(ProgramNum + 1);
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
        if (!mode_finish_by_status(SamovarStatusInt)) set_power(!PowerOn);
        if (PowerOn && Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
          SamovarStatusInt = 50;
        }
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
        pause_withdrawal(true);
        break;
      case SAMOVAR_CONTINUE:
        pause_withdrawal(false);
        t_min = 0;
        program_Wait = false;
        if (!set_program_wait_type(PROGRAM_WAIT_NONE, pdMS_TO_TICKS(500))) SendMsg("Не удалось сбросить тип автоматической паузы.", WARNING_MSG);
        detector_on_manual_resume();
        break;
      case SAMOVAR_SETBODYTEMP:
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
        mode_apply_power_on_command(commandMsg.command);
        break;
      case SAMOVAR_NBK_NEXT:
        run_nbk_program(ProgramNum + 1);
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
  {
    bool hasPendingResetWifi = false;
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (locked && pending_reset_wifi_flag) {
      pending_reset_wifi_flag = false;
      hasPendingResetWifi = true;
    }
    pending_command_unlock(locked);
    if (hasPendingResetWifi) {
      delay(200);
      menu_reset_wifi();
    }
  }
  {
    bool hasPendingReboot = false;
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (locked && is_reboot) {
      is_reboot = false;
      hasPendingReboot = true;
    }
    pending_command_unlock(locked);
    if (hasPendingReboot) {
      delay(200);
      ESP.restart();
    }
  }

  // Реапер просроченных операций (PKG-H): не чаще ~1с под pending_command_lock переводит
  // зависшие QUEUED/RUNNING в FAILED и однократно (латч внутри) сигналит ALARM. Выполняется
  // и при активном барьере — стешенная операция могла быть его причиной.
  {
    static uint32_t lastReapMs = 0;
    const uint32_t nowMs = millis();
    if ((int32_t)(nowMs - lastReapMs) >= 1000) {
      lastReapMs = nowMs;
      bool reaped = false;
      bool locked = pending_command_lock(pdMS_TO_TICKS(50));
      if (locked) {
        reaped = operation_store_reap_stale_locked(operationStore, nowMs);
      }
      pending_command_unlock(locked);
      if (reaped) {
        SendMsg("Просроченная операция принудительно завершена (reaper)", ALARM_MSG);
      }
    }
  }

  if (mode_switch_in_progress()) {
    process_buzzer();
    vTaskDelay(5 / portTICK_PERIOD_MS);
    return;
  }

  bool hasPendingStopSelfTest = false;
  {
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (locked && pending_stop_self_test_flag) {
      pending_stop_self_test_flag = false;
      hasPendingStopSelfTest = true;
    }
    pending_command_unlock(locked);
  }
  if (hasPendingStopSelfTest) {
    stop_self_test();
  }

  bool hasPendingMixer = false;
  bool mixerOn = false;
  {
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (locked && pending_mixer_flag) {
      mixerOn = pending_mixer_on;
      pending_mixer_flag = false;
      hasPendingMixer = true;
    }
    pending_command_unlock(locked);
  }
  if (hasPendingMixer) {
    set_mixer(mixerOn);
  }

  bool hasPendingWaterTemp = false;
  uint16_t waterTemp = 0;
  {
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (locked && pending_water_temp_flag) {
      waterTemp = pending_water_temp_value;
      pending_water_temp_flag = false;
      hasPendingWaterTemp = true;
    }
    pending_command_unlock(locked);
  }
  if (hasPendingWaterTemp) {
    set_water_temp(waterTemp);
  }

  bool hasPendingPumpSpeed = false;
  uint16_t pumpSpeedSteps = 0;
  {
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (locked && pending_pump_speed_flag) {
      pumpSpeedSteps = pending_pump_speed_steps;
      pending_pump_speed_flag = false;
      hasPendingPumpSpeed = true;
    }
    pending_command_unlock(locked);
  }
  if (hasPendingPumpSpeed) {
    set_pump_speed(pumpSpeedSteps, true);
  }

#ifdef SAMOVAR_USE_POWER
  bool hasPendingVoltage = false;
  float voltage = 0;
  {
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (locked && pending_voltage_flag) {
      voltage = pending_voltage_value;
      pending_voltage_flag = false;
      hasPendingVoltage = true;
    }
    pending_command_unlock(locked);
  }
  if (hasPendingVoltage) {
    set_current_power(voltage);
  }
#endif

  bool hasPendingNbkOpt = false;
  {
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (locked && pending_nbkopt_flag) {
      pending_nbkopt_flag = false;
      hasPendingNbkOpt = true;
    }
    pending_command_unlock(locked);
  }
  if (hasPendingNbkOpt) {
    if (PowerOn) {
      nbk_Mo = nbk_M;
      nbk_Po = nbk_P;
#ifdef SAMOVAR_USE_POWER
      SendMsg("Установлены оптимальные значения: " + String(fromPower(nbk_Mo), 0) + String(PWR_SIGN) + ",  " + String(nbk_Po, 1) + " л/ч", WARNING_MSG);
#endif
    }
  }

  // Обработка recovery-команд (reboot/resetwifi) и реапера перенесена ВЫШЕ барьер-return,
  // чтобы застрявший mode_switch_barrier_active не блокировал восстановление устройства.

#ifdef USE_LUA
  bool hasPendingLuaReload = false;
  {
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (locked && pending_lua_reload_flag) {
      pending_lua_reload_flag = false;
      hasPendingLuaReload = true;
    }
    pending_command_unlock(locked);
  }
  if (hasPendingLuaReload) {
    load_lua_script();
  }

  bool hasPendingLuaStart = false;
  {
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (locked && pending_lua_start_flag) {
      hasPendingLuaStart = true;
    }
    pending_command_unlock(locked);
  }
  if (hasPendingLuaStart) {
    if (start_lua_script()) {
      bool locked = pending_command_lock(pdMS_TO_TICKS(50));
      if (locked && pending_lua_start_flag) {
        pending_lua_start_flag = false;
      }
      pending_command_unlock(locked);
    }
  }

  bool hasPendingLuaFile = false;
  String luaFile;
  {
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (locked && pending_lua_file_flag) {
      luaFile = pending_lua_file;
      hasPendingLuaFile = true;
    }
    pending_command_unlock(locked);
  }
  if (hasPendingLuaFile) {
    if (run_lua_script(luaFile)) {
      bool locked = pending_command_lock(pdMS_TO_TICKS(50));
      if (locked && pending_lua_file_flag && pending_lua_file == luaFile) {
        pending_lua_file_flag = false;
      }
      pending_command_unlock(locked);
    }
  }

  // [W3.1] Исполнение Lua-строки ставится в DoLuaScriptTask; при busy pending остаётся на повтор.
  bool hasPendingLuaString = false;
  String lstr;
  {
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (locked && pending_lua_flag) {
      lstr = pending_lua_str;
      hasPendingLuaString = true;
    }
    pending_command_unlock(locked);
  }
  if (hasPendingLuaString) {
    if (run_lua_string(lstr).length() == 0) {
      bool locked = pending_command_lock(pdMS_TO_TICKS(50));
      if (locked && pending_lua_flag && pending_lua_str == lstr) {
        pending_lua_flag = false;
      }
      pending_command_unlock(locked);
    }
  }
#endif

  // [W-4] Ручное управление скоростью I2C-насоса (/command?pnbk): get_stepper_speed()/
  //        set_stepper_target() — блокирующий I2C, выполняем здесь. Логика идентична
  //        прежнему async-обработчику; pnbk заменяет request->arg("pnbk").
  bool hasPendingPnbk = false;
  ControlNbkCommand pnbk = {};
  {
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (locked && pending_pnbk_flag) {
      pnbk = pending_pnbk_value;
      hasPendingPnbk = true;
    }
    pending_command_unlock(locked);
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
    }
    if (pnbkDone) {
      bool locked = pending_command_lock(pdMS_TO_TICKS(50));
      if (locked) pending_pnbk_flag = false;
      pending_command_unlock(locked);
    }
  }

  mode_dispatch_loop();

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
  for (size_t i = 0; i < value.length(); i++) {
    char c = value[i];
    if (c == '\"' || c == '\\') {
      out.print('\\');
      out.print(c);
    } else if (c == '\n') {
      out.print("\\n");
    } else if (c == '\r') {
      out.print("\\r");
    } else if (c == '\t') {
      out.print("\\t");
    } else {
      out.print(c);
    }
  }
}

static bool runtimeEventWrite(Print& out, const char* value, size_t length) {
  return out.write(reinterpret_cast<const uint8_t*>(value), length) == length;
}

static bool runtimeEventWriteEscaped(Print& out, const String& value) {
  static const char hexDigits[] = "0123456789ABCDEF";
  size_t plainStart = 0;
  for (size_t index = 0; index < value.length(); index++) {
    const char character = value[index];
    const uint8_t byte = static_cast<uint8_t>(character);
    const char* escaped = nullptr;
    size_t escapedLength = 0;
    char unicodeEscape[6];
    if (character == '"') {
      escaped = "\\\"";
      escapedLength = 2;
    } else if (character == '\\') {
      escaped = "\\\\";
      escapedLength = 2;
    } else if (character == '\n') {
      escaped = "\\n";
      escapedLength = 2;
    } else if (character == '\r') {
      escaped = "\\r";
      escapedLength = 2;
    } else if (character == '\t') {
      escaped = "\\t";
      escapedLength = 2;
    } else if (character == '\b') {
      escaped = "\\b";
      escapedLength = 2;
    } else if (character == '\f') {
      escaped = "\\f";
      escapedLength = 2;
    } else if (byte < 0x20) {
      unicodeEscape[0] = '\\';
      unicodeEscape[1] = 'u';
      unicodeEscape[2] = '0';
      unicodeEscape[3] = '0';
      unicodeEscape[4] = hexDigits[byte >> 4];
      unicodeEscape[5] = hexDigits[byte & 0x0F];
      escaped = unicodeEscape;
      escapedLength = sizeof(unicodeEscape);
    }
    if (!escaped) continue;
    if (index > plainStart &&
        !runtimeEventWrite(out, value.c_str() + plainStart, index - plainStart)) {
      return false;
    }
    if (!runtimeEventWrite(out, escaped, escapedLength)) return false;
    plainStart = index + 1;
  }
  return plainStart == value.length() ||
         runtimeEventWrite(out, value.c_str() + plainStart, value.length() - plainStart);
}

static bool runtimeEventWriteUnsigned(Print& out, uint32_t value) {
  char number[11];
  const int length = snprintf(number, sizeof(number), "%lu", static_cast<unsigned long>(value));
  return length > 0 && static_cast<size_t>(length) < sizeof(number) &&
         runtimeEventWrite(out, number, static_cast<size_t>(length));
}

static bool runtimeEventWriteSection(
    Print& out, const RuntimeEventDescriptor& event, const String& eventText) {
  if (event.kind == RUNTIME_EVENT_MESSAGE) {
    if (!runtimeEventWrite(out, ",\"Msg\":\"", sizeof(",\"Msg\":\"") - 1U) ||
        !runtimeEventWriteEscaped(out, eventText) ||
        !runtimeEventWrite(out, "\",\"msglvl\":", sizeof("\",\"msglvl\":") - 1U) ||
        !runtimeEventWriteUnsigned(out, event.level)) {
      return false;
    }
  } else if (event.kind == RUNTIME_EVENT_CONSOLE) {
    if (!runtimeEventWrite(out, ",\"LogMsg\":\"", sizeof(",\"LogMsg\":\"") - 1U) ||
        !runtimeEventWriteEscaped(out, eventText) ||
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
    const RuntimeEventDescriptor& event, const String& eventText) {
  if (runtimeEventWriteSection(*response, event, eventText)) {
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
  RuntimeEventDescriptor runtimeEvent;
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
  int16_t withdrawalStatus;
  uint16_t stepperStepMl;
  uint16_t i2cPumpSpeed;
  uint8_t detectorStatus;
  uint8_t withdrawalProgress;
  uint8_t programIndex;
  bool useAutoSpeed;
  bool powerOn;
  bool pauseOn;
  bool useBrowserBuzzer;
  bool mixer;
  bool i2cStepperPresent;
  bool i2cMixerPresent;
  bool i2cPumpPresent;
  bool i2cPumpRunning;
  bool hasAlcohol;
  bool hasTimePrediction;
  bool hasRuntimeEvent;
  bool heaterAlarmLatched;
  uint32_t latestMessageSequence;
};

static_assert(sizeof(AjaxTelemetrySnapshot) <= 512,
              "AjaxTelemetrySnapshot exceeds its request stack budget");

static RuntimeAjaxSnapshotResult captureAjaxTelemetrySnapshot(
    uint32_t messageCursor, AjaxTelemetrySnapshot& snapshot) {
  const RuntimeAjaxSnapshotResult snapshotResult = copy_ajax_runtime_snapshot(
      snapshot.crt, snapshot.status, snapshot.luaStatus,
      snapshot.currentPowerMode, messageCursor, snapshot.eventText,
      snapshot.runtimeEvent, snapshot.hasRuntimeEvent,
      snapshot.latestMessageSequence);
  if (snapshotResult != RUNTIME_AJAX_SNAPSHOT_OK) return snapshotResult;

  snapshot.heaterAlarmLatched = heater_safety_latched();
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
  snapshot.useAutoSpeed = SamSetup.useautospeed;
  snapshot.volumeAll = get_liquid_volume();
  snapshot.actualVolumePerHour = ActualVolumePerHour;
  snapshot.powerOn = PowerOn;
  snapshot.pauseOn = PauseOn;
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
  const ProgramType currentType = current_program_type();
  if ((mode == SAMOVAR_RECTIFICATION_MODE || mode == SAMOVAR_BEER_MODE ||
       mode == SAMOVAR_DISTILLATION_MODE || mode == SAMOVAR_NBK_MODE) &&
      (status == 10 || status == 15 || (status == 2000 && snapshot.powerOn)) &&
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
  }
  return RUNTIME_AJAX_SNAPSHOT_OK;
}

static void writeAjaxTelemetryFields(
    Print& out, const AjaxTelemetrySnapshot& snapshot) {
  bool first = true;
  out.print('{');

  jsonAddKey(out, first, "bme_temp");
  out.print(format_float(snapshot.bmeTemp, 3));
  jsonAddKey(out, first, "bme_pressure");
  out.print(format_float(snapshot.bmePressure, 3));
  jsonAddKey(out, first, "start_pressure");
  out.print(format_float(snapshot.startPressure, 3));
  jsonAddKey(out, first, "crnt_tm");
  out.print('"');
  jsonPrintEscaped(out, snapshot.crt);
  out.print('"');
  jsonAddKey(out, first, "stm");
  out.print('"');
  jsonPrintEscaped(out, snapshot.uptime);
  out.print('"');
  jsonAddKey(out, first, "SteamTemp");
  out.print(format_float(snapshot.steamTemp, 3));
  jsonAddKey(out, first, "PipeTemp");
  out.print(format_float(snapshot.pipeTemp, 3));
  jsonAddKey(out, first, "WaterTemp");
  out.print(format_float(snapshot.waterTemp, 3));
  jsonAddKey(out, first, "TankTemp");
  out.print(format_float(snapshot.tankTemp, 3));
  jsonAddKey(out, first, "ACPTemp");
  out.print(format_float(snapshot.acpTemp, 3));
  jsonAddKey(out, first, "DetectorTrend");
  out.print(format_float(snapshot.detectorTrend, 3));
  jsonAddKey(out, first, "DetectorStatus");
  out.print(snapshot.detectorStatus);
  jsonAddKey(out, first, "useautospeed");
  out.print(snapshot.useAutoSpeed);
  jsonAddKey(out, first, "version");
  out.print('"');
  out.print(SAMOVAR_VERSION);
  out.print('"');
  jsonAddKey(out, first, "boot_degraded");
  out.print(bootDegraded ? 1 : 0);
  jsonAddKey(out, first, "boot_degraded_reason");
  out.print('"');
  jsonPrintEscaped(out, bootDegradedReason);
  out.print('"');
  jsonAddKey(out, first, "VolumeAll");
  out.print(snapshot.volumeAll);
  jsonAddKey(out, first, "ActualVolumePerHour");
  out.print(format_float(snapshot.actualVolumePerHour, 3));
  jsonAddKey(out, first, "PowerOn");
  out.print(snapshot.powerOn);
  jsonAddKey(out, first, "PauseOn");
  out.print(snapshot.pauseOn);
  jsonAddKey(out, first, "WthdrwlProgress");
  out.print(snapshot.withdrawalProgress);
  jsonAddKey(out, first, "TargetStepps");
  out.print(snapshot.targetSteps);
  jsonAddKey(out, first, "CurrrentStepps");
  out.print(snapshot.currentSteps);
  jsonAddKey(out, first, "WthdrwlStatus");
  out.print(snapshot.withdrawalStatus);
  jsonAddKey(out, first, "ProgramNum");
  out.print(snapshot.programIndex + 1);
  jsonAddKey(out, first, "ProgramIndex");
  out.print(snapshot.programIndex);
  jsonAddKey(out, first, "CurrrentSpeed");
  out.print(snapshot.currentSpeed);
  jsonAddKey(out, first, "UseBBuzzer");
  out.print(snapshot.useBrowserBuzzer);
  jsonAddKey(out, first, "StepperStepMl");
  out.print(snapshot.stepperStepMl);
  jsonAddKey(out, first, "BodyTemp_Steam");
  out.print(format_float(snapshot.steamBodyTemp, 3));
  jsonAddKey(out, first, "BodyTemp_Pipe");
  out.print(format_float(snapshot.pipeBodyTemp, 3));
  jsonAddKey(out, first, "mixer");
  out.print(snapshot.mixer);
  jsonAddKey(out, first, "ISspd");
  out.print(format_float(snapshot.i2cStepperSpeed, 3));
  jsonAddKey(out, first, "i2c_stepper_present");
  out.print(snapshot.i2cStepperPresent ? 1 : 0);
  jsonAddKey(out, first, "i2c_mixer_present");
  out.print(snapshot.i2cMixerPresent ? 1 : 0);
  jsonAddKey(out, first, "i2c_pump_present");
  out.print(snapshot.i2cPumpPresent ? 1 : 0);

  if (snapshot.i2cPumpPresent) {
    jsonAddKey(out, first, "i2c_pump_speed");
    out.print(snapshot.i2cPumpSpeed);
    jsonAddKey(out, first, "i2c_pump_target_ml");
    out.print(format_float(snapshot.i2cPumpTargetMl, 1));
    jsonAddKey(out, first, "i2c_pump_remaining_ml");
    out.print(format_float(snapshot.i2cPumpRemainingMl, 1));
    jsonAddKey(out, first, "i2c_pump_running");
    out.print(snapshot.i2cPumpRunning ? 1 : 0);
  } else {
    jsonAddKey(out, first, "i2c_pump_speed");
    out.print(0);
    jsonAddKey(out, first, "i2c_pump_target_ml");
    out.print(0);
    jsonAddKey(out, first, "i2c_pump_remaining_ml");
    out.print(0);
    jsonAddKey(out, first, "i2c_pump_running");
    out.print(0);
  }

  jsonAddKey(out, first, "heap");
  out.print(snapshot.freeHeap);
  jsonAddKey(out, first, "rssi");
  out.print(snapshot.rssi);
  jsonAddKey(out, first, "fr_bt");
  out.print(snapshot.freeFsBytes);
  jsonAddKey(out, first, "PrgType");
  out.print('"');
  jsonPrintEscaped(out, snapshot.programType);
  out.print('"');

#ifdef SAMOVAR_USE_POWER
  jsonAddKey(out, first, "current_power_volt");
  out.print(format_float(snapshot.currentPowerVolt, 1));
  jsonAddKey(out, first, "target_power_volt");
  out.print(format_float(snapshot.targetPowerVolt, 1));
  jsonAddKey(out, first, "current_power_mode");
  out.print('"');
  jsonPrintEscaped(out, snapshot.currentPowerMode);
  out.print('"');
  jsonAddKey(out, first, "current_power_p");
  out.print(snapshot.currentPower);
#else
  jsonAddKey(out, first, "current_power_volt");
  out.print(0);
  jsonAddKey(out, first, "target_power_volt");
  out.print(0);
  jsonAddKey(out, first, "current_power_mode");
  out.print('"');
  out.print(0);
  out.print('"');
  jsonAddKey(out, first, "current_power_p");
  out.print(0);
#endif

#ifdef USE_WATER_PUMP
  jsonAddKey(out, first, "wp_spd");
  out.print(snapshot.waterPumpSpeed);
#endif
#ifdef USE_WATERSENSOR
  jsonAddKey(out, first, "WFflowRate");
  out.print(format_float(snapshot.waterFlowRate, 2));
  jsonAddKey(out, first, "WFtotalMl");
  out.print(snapshot.waterFlowTotalMl);
#endif
#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_1WIRE) || defined(USE_PRESSURE_MPX)
  jsonAddKey(out, first, "prvl");
  out.print(format_float(snapshot.pressure, 2));
#endif

  if (snapshot.hasAlcohol) {
    jsonAddKey(out, first, "alc");
    out.print(format_float(snapshot.alcohol, 2));
    jsonAddKey(out, first, "stm_alc");
    out.print(format_float(snapshot.steamAlcohol, 2));
  }
  if (snapshot.hasTimePrediction) {
    jsonAddKey(out, first, "TimeRemaining");
    out.print(String(snapshot.timeRemaining));
    jsonAddKey(out, first, "TotalTime");
    out.print(String(snapshot.totalTime));
  }

  jsonAddKey(out, first, "Status");
  out.print('"');
  jsonPrintEscaped(out, snapshot.status);
  out.print('"');
  jsonAddKey(out, first, "Lstatus");
  out.print('"');
  jsonPrintEscaped(out, snapshot.luaStatus);
  out.print('"');
  jsonAddKey(out, first, "heaterAlarmLatched");
  out.print(snapshot.heaterAlarmLatched ? 1 : 0);
  jsonAddKey(out, first, "latestMessageSequence");
  out.print(snapshot.latestMessageSequence);
}

void send_ajax_json(AsyncWebServerRequest *request) {
  const RuntimeAjaxQuery query = classifyRuntimeAjaxQuery(request);
  if (sendRuntimeAjaxQueryError(request, query.kind)) return;

  if (query.kind == RUNTIME_AJAX_QUERY_OPERATION) {
    const OperationId operationId = query.value;
    if (!pending_command_lock(pdMS_TO_TICKS(50))) {
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
    pending_command_unlock(true);

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

  if (!snapshot.hasRuntimeEvent) {
    out.print('}');
    request->send(response);
    return;
  }
  sendRuntimeEventResponse(
      request, response, snapshot.runtimeEvent, snapshot.eventText);
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
  SteamSensor.SetTemp = SamSetup.SetSteamTemp;
  PipeSensor.SetTemp = SamSetup.SetPipeTemp;
  WaterSensor.SetTemp = SamSetup.SetWaterTemp;
  TankSensor.SetTemp = SamSetup.SetTankTemp;
  ACPSensor.SetTemp = SamSetup.SetACPTemp;
  SteamSensor.Delay = SamSetup.SteamDelay;
  PipeSensor.Delay = SamSetup.PipeDelay;
  WaterSensor.Delay = SamSetup.WaterDelay;
  TankSensor.Delay = SamSetup.TankDelay;
  ACPSensor.Delay = SamSetup.ACPDelay;
  if (SamSetup.LogPeriod == 0) SamSetup.LogPeriod = 3;
  if (SamSetup.autospeed >= 100) SamSetup.autospeed = 0;
  apply_setup_sensor_fields(0);

  // Проверка через валидатор, а не только по верхней границе: SamSetup.Mode — знаковый int
  // из загруженного профиля, и отрицательное значение раньше проходило насквозь. Тогда
  // mode_ops_by_mode() не находит запись реестра и mode_dispatch_alarm() молча не вызывает
  // ни одного обработчика — надзор за авариями пропадает. Семантика прежняя (тихий сброс
  // в 0, а не отказ): это путь загрузки профиля, ронять его нельзя.
  if (!is_valid_samovar_mode(SamSetup.Mode)) SamSetup.Mode = 0;
  Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode;
  change_samovar_mode();

  if ((uint8_t)SamSetup.videourl[0] == 0xFF) SamSetup.videourl[0] = '\0';
#ifdef SAMOVAR_USE_BLYNK
  if (strlen(SamSetup.videourl) > 0) Blynk.setProperty(V20, "url", (String)SamSetup.videourl);
  Blynk.virtualWrite(V15, ipst);
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

  if (isnan(SamSetup.SetWaterTemp) || SamSetup.SetWaterTemp == 0) SamSetup.SetWaterTemp = TARGET_WATER_TEMP;
  if (isnan(SamSetup.SetACPTemp) || SamSetup.SetACPTemp == 0) SamSetup.SetACPTemp = 43;
  if (isnan(SamSetup.DistTemp) || SamSetup.DistTemp <= 0) SamSetup.DistTemp = DEFAULT_DIST_TEMP;
  if (isnan(SamSetup.DistTimeF)) {
    SamSetup.DistTimeF = 16;
  }
  if (isnan(SamSetup.MaxPressureValue)) {
    SamSetup.MaxPressureValue = 0;
  }


#ifdef USE_HEAD_LEVEL_SENSOR
  // bool-поле не проверяем через isnan()
#endif


  //  pump_regulator.Kp = SamSetup.Kp;
  //  pump_regulator.Ki = SamSetup.Ki;
  //  pump_regulator.Kd = SamSetup.Kd;

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
