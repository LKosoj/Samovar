#!/usr/bin/env python3
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens


ROOT = Path(__file__).resolve().parents[1]


def source_slice(source: str, start_token: str, end_token: str) -> str:
    start = source.find(start_token)
    end = source.find(end_token, start)
    if start < 0 or end < 0:
        raise ValueError(f"source slice not found: {start_token} .. {end_token}")
    return source[start:end]


def extract_last_function_body(source: str, signature: str) -> str:
    start = source.rfind(signature)
    if start < 0:
        raise ValueError(f"function not found: {signature}")
    return extract_function_body(source[start:], signature)


def build_harness() -> str:
    samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    web = (ROOT / "WebServer.ino").read_text(encoding="utf-8")
    api = (ROOT / "samovar_api.h").read_text(encoding="utf-8")

    profile_defs = source_slice(
        samovar, "enum ProfileOperationFlags", "ProfileOperationSlot active_profile_operation")
    mode_result = source_slice(api, "enum ModeSwitchResult", "enum PersistResult")
    persist_result = source_slice(api, "enum PersistResult", "enum ProfileLoadResult")

    bodies = {
        "@PHASE_LOAD_BODY@": extract_function_body(
            samovar, "static inline ProfileOperationPhase profile_operation_phase_load()"),
        "@PHASE_STORE_BODY@": extract_function_body(
            samovar, "static inline void profile_operation_phase_store("),
        "@RESET_SLOT_BODY@": extract_function_body(
            samovar, "static void reset_profile_operation_slot()"),
        "@IS_VALID_MODE_BODY@": extract_function_body(web, "bool is_valid_samovar_mode(long mode) {"),
        "@QUEUE_BODY@": extract_function_body(web, "static OperationError queue_profile_operation("),
        "@COMMIT_BODY@": extract_last_function_body(samovar, "static OperationError commit_profile_operation()"),
        "@SET_TERMINAL_BODY@": extract_function_body(samovar, "static void set_profile_operation_terminal("),
        "@PUBLISH_BODY@": extract_function_body(samovar, "static void publish_profile_operation_terminal()"),
        "@FORCE_COMPLETE_BODY@": extract_function_body(
            web, "static ModeSwitchResult force_complete_mode_switch_failed(const char* warning)"),
        "@SWITCH_BODY@": extract_function_body(web, "ModeSwitchResult switch_samovar_mode(SAMOVAR_MODE requestedMode)"),
        "@PROCESS_BODY@": extract_last_function_body(samovar, "static void process_profile_operation()"),
    }

    harness = r'''
#include <cmath>
#include <cstdint>
#include <cstring>
#include <deque>
#include <iostream>
#include <string>

#include "operation_store.h"
#include "safety_transition.h"

#define USE_LUA 1
#define pdMS_TO_TICKS(value) (value)
#define portENTER_CRITICAL(mux) do { (void)(mux); } while (0)
#define portEXIT_CRITICAL(mux) do { (void)(mux); } while (0)

using TickType_t = int;
using portMUX_TYPE = int;

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}

  String& operator=(const char* text) {
    value_ = text ? text : "";
    return *this;
  }
  String& operator+=(const char* text) {
    value_ += text ? text : "";
    return *this;
  }
  void replace(const char* from, const char* to) {
    const std::string needle = from ? from : "";
    const std::string replacement = to ? to : "";
    if (needle.empty()) return;
    size_t offset = 0;
    while ((offset = value_.find(needle, offset)) != std::string::npos) {
      value_.replace(offset, needle.size(), replacement);
      offset += replacement.size();
    }
  }
  const std::string& value() const { return value_; }

 private:
  std::string value_;
};

enum SAMOVAR_MODE {
  SAMOVAR_RECTIFICATION_MODE,
  SAMOVAR_DISTILLATION_MODE,
  SAMOVAR_BEER_MODE,
  SAMOVAR_BK_MODE,
  SAMOVAR_NBK_MODE,
  SAMOVAR_SUVID_MODE,
  SAMOVAR_LUA_MODE,
};

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };

struct SetupEEPROM {
  int value;
  int Mode;
};

struct ProgramDraft {
  int value;
};

enum ProgramUpdateAction : uint8_t {
  PROGRAM_UPDATE_NONE = 0,
  PROGRAM_UPDATE_REPLACE,
  PROGRAM_UPDATE_CLEAR,
};

@PROFILE_DEFS@
@MODE_RESULT@
@PERSIST_RESULT@

OperationStore operationStore{};
ProfileOperationSlot active_profile_operation{};
static_assert(sizeof(ProfileOperationPhase) == sizeof(uint8_t),
              "ProfileOperationPhase must remain byte-sized");
static_assert(std::is_trivially_copyable<ProfileOperationSlot>::value,
              "ProfileOperationSlot must remain trivially copyable");
static_assert(sizeof(ProfileOperationSlot) <= 1368,
              "ProfileOperationSlot exceeds firmware budget");

static inline ProfileOperationPhase profile_operation_phase_load() {
@PHASE_LOAD_BODY@
}

static inline void profile_operation_phase_store(ProfileOperationPhase phase) {
@PHASE_STORE_BODY@
}

static void reset_profile_operation_slot() {
@RESET_SLOT_BODY@
}

volatile bool mode_switch_barrier_active = false;
volatile SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
volatile SAMOVAR_MODE Samovar_CR_Mode = SAMOVAR_RECTIFICATION_MODE;
SetupEEPROM SamSetup{};
String SessionDescription;
String lua_type_script;
float BoilerVolume = 0.0f;
bool heatLossCalculated = true;
uint32_t heatStartMillis = 9;
portMUX_TYPE emergencyStopMux = 0;

static std::deque<bool> pendingLockResults;
static bool sessionActive = false;
static bool runtimeLockResult = true;
static PersistResult persistResult = PERSIST_OK;
static int persistCalls = 0;
static int programCommitCalls = 0;
static int programClearCalls = 0;
static int runtimeLockCalls = 0;
static int applyConfigCalls = 0;
static int sensorApplyCalls = 0;
static int resetCalls = 0;
static int luaLoadCalls = 0;
static int cleanupCalls = 0;
static int logCloseCalls = 0;
static int messageCalls = 0;
static int liveProgram = 0;
static bool luaStopResult = true;
static bool commandQueueIdle = true;
static bool commandDiscardResult = true;
static bool pendingDiscardResult = true;
static bool pendingCancelledValue = false;
static bool actuatorsIdleResult = true;
static bool modeQueuesIdleResult = true;
static bool luaModeOwnerIdleResult = true;
static bool logClosePendingResult = false;
static bool logCloseRequestResult = true;
static uint32_t fakeNow = 0;
static uint32_t cleanupDeadline = 1000;
static int forceHeaterOffCalls = 0;
static int notifyPowerWorkerCalls = 0;
static std::string lastWarningMessage;
static bool heaterPowerOnResult = false;
static bool powerTransitionActiveResult = false;
static bool nbkTransitionActiveResult = false;
static bool modeHeatingStartActiveResult = false;
static bool selfTestActiveResult = false;
static bool modeRuntimeOwnerIdleResult = true;

static bool pending_command_lock(TickType_t) {
  if (pendingLockResults.empty()) return true;
  const bool result = pendingLockResults.front();
  pendingLockResults.pop_front();
  return result;
}

static void pending_command_unlock(bool) {}

// Единственный вызов каждой лежит во вклеенном теле (WebServer.ino:173/174),
// поэтому со `static` мутация, убравшая вызов, роняла бы компилятор вместо
// assert-а - см. группу предикатов cleanupReady ниже.
bool mode_switch_in_progress() {
  return mode_switch_barrier_active;
}

bool program_update_session_active() {
  return sessionActive;
}

// Заглушки ниже намеренно НЕ static: единственный вызов каждой лежит во
// вклеенном теле commit_profile_operation (Samovar.ino:352-423), и со `static`
// мутация, убравшая вызов, роняла бы компилятор по unused-function вместо
// содержательного assert-а - тот же приём, что у force_heater_output_off_locked
// ниже и у предикатов cleanupReady. Держится это на поведенческих кейсах: без
// них снятие `static` меняет ложный улов на молчаливую слепую зону, что хуже.
bool runtime_state_lock(TickType_t) {
  runtimeLockCalls++;
  return runtimeLockResult;
}

static void runtime_state_unlock(bool) {}

PersistResult save_profile_nvs(const SetupEEPROM&) {
  persistCalls++;
  return persistResult;
}

static const char* persist_result_code(PersistResult) {
  return "fake_persist_error";
}

// Non-static: a mutation that deletes the (single) production call site must not
// turn this into an unused-function -Werror compile failure that masks the bug.
void force_heater_output_off_locked(bool) { forceHeaterOffCalls++; }
void notify_power_worker() { notifyPowerWorkerCalls++; }

static void SendMsg(const String& message, MESSAGE_TYPE) {
  messageCalls++;
  lastWarningMessage = message.value();
}

void program_commit(const ProgramDraft& draft) {
  programCommitCalls++;
  liveProgram = draft.value;
}

void program_clear() {
  programClearCalls++;
  liveProgram = 0;
}

void samovar_reset() { resetCalls++; }

void apply_setup_sensor_fields(uint8_t) { sensorApplyCalls++; }

void apply_config_runtime() { applyConfigCalls++; }

// Заглушка обязана зависеть от режима, как настоящая: get_lua_mode_name
// (lua.h:1888) выводит имя из Samovar_CR_Mode, а не из аргумента. С константой
// проверка «после смены режима подхватилось имя нового режима» была бы верна и
// тогда, когда имя не обновляют вовсе. Имена условные - пинится соответствие
// имени режиму, а не сами строки (в настоящих ещё и версии LUA_*).
String get_lua_mode_name(bool = true) {
  switch (Samovar_CR_Mode) {
    case SAMOVAR_DISTILLATION_MODE:
      return String("dist");
    case SAMOVAR_BEER_MODE:
      return String("beer");
    default:
      return String("rect");
  }
}

void load_lua_script() { luaLoadCalls++; }

static SafetyModeSwitchState modeSwitchState = {
    SAFETY_MODE_SWITCH_IDLE, 0, false};

struct ModeActuatorCleanupState {
  bool initialized;
  bool mixerStopped;
  bool pumpStopped;
  uint32_t deadline;
};

static ModeActuatorCleanupState modeActuatorCleanup{};

static bool tick_mode_actuator_cleanup(bool) {
  cleanupCalls++;
  if (!modeActuatorCleanup.initialized) {
    modeActuatorCleanup.initialized = true;
    modeActuatorCleanup.deadline = cleanupDeadline;
  }
  return actuatorsIdleResult;
}

bool request_data_log_close() {
  logCloseCalls++;
  return logCloseRequestResult;
}
static uint32_t millis() { return fakeNow; }
// Non-static: a mutation that removes the (single) call site inside
// switch_samovar_mode's cleanup-readiness computation must not turn these into
// an unused-function -Werror compile failure that masks the bug (see
// force_heater_output_off_locked/notify_power_worker above).
bool heater_power_on() { return heaterPowerOnResult; }
bool power_transition_active() { return powerTransitionActiveResult; }
bool nbk_transition_active() { return nbkTransitionActiveResult; }
bool mode_heating_start_active() { return modeHeatingStartActiveResult; }
bool self_test_active() { return selfTestActiveResult; }
bool mode_runtime_owner_idle() { return modeRuntimeOwnerIdleResult; }
// Тот же расчёт готовности, поэтому и то же правило: обе впервые вызываются
// только в фазе WAIT_CLEANUP (WebServer.ino:1860/1863), других вызывающих нет.
bool lua_mode_owner_idle() { return luaModeOwnerIdleResult; }
bool mode_control_queues_idle() { return modeQueuesIdleResult; }
// То же правило для предикатов фазы STOP_REQUESTED (WebServer.ino:1836-1841) и
// для признака незакрытого лога (1864): единственный вызов каждого лежит в
// switch_samovar_mode, поэтому со `static` мутация, убравшая вызов, роняла бы
// компилятор вместо assert-а. Держится это только на кейсах ниже: без них
// снятие `static` меняет ложный улов на молчаливую слепую зону, что хуже.
bool request_lua_mode_stop() { return luaStopResult; }
bool samovar_command_queue_idle(TickType_t) { return commandQueueIdle; }
bool discard_samovar_commands(TickType_t) { return commandDiscardResult; }
bool discard_pending_mode_control_commands(bool& cancelled) {
  cancelled = pendingCancelledValue;
  return pendingDiscardResult;
}
bool data_log_close_pending() { return logClosePendingResult; }
void stop_active_process_for_mode() { sessionActive = false; }

static OperationError commit_profile_operation();
static void set_profile_operation_terminal(OperationState, OperationError);
static void publish_profile_operation_terminal();
static void process_profile_operation();
ModeSwitchResult switch_samovar_mode(SAMOVAR_MODE requestedMode);

static bool is_valid_samovar_mode(long mode) {
@IS_VALID_MODE_BODY@
}

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
    OperationId& operationId) {
@QUEUE_BODY@
}

static OperationError commit_profile_operation() {
@COMMIT_BODY@
}

static void set_profile_operation_terminal(
    OperationState state,
    OperationError error) {
@SET_TERMINAL_BODY@
}

static void publish_profile_operation_terminal() {
@PUBLISH_BODY@
}

static ModeSwitchResult force_complete_mode_switch_failed(const char* warning) {
@FORCE_COMPLETE_BODY@
}

ModeSwitchResult switch_samovar_mode(SAMOVAR_MODE requestedMode) {
@SWITCH_BODY@
}

static void process_profile_operation() {
@PROCESS_BODY@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static bool profile_description_is_reset() {
  for (size_t index = 0;
       index < sizeof(active_profile_operation.description); index++) {
    if (active_profile_operation.description[index] != '\0') return false;
  }
  return true;
}

static bool profile_slot_is_reset() {
  return active_profile_operation.settings.value == 0 &&
         active_profile_operation.settings.Mode == 0 &&
         active_profile_operation.program.value == 0 &&
         profile_description_is_reset() &&
         active_profile_operation.id == 0 &&
         active_profile_operation.boilerVolume == 0.0f &&
         active_profile_operation.flags == 0 &&
         active_profile_operation.sensorResetMask == 0 &&
         active_profile_operation.sourceMode == 0 &&
         active_profile_operation.targetMode == 0 &&
         profile_operation_phase_load() == PROFILE_OPERATION_EMPTY &&
         active_profile_operation.terminalState == OPERATION_STATE_EMPTY &&
         active_profile_operation.terminalError == OPERATION_ERROR_NONE &&
         active_profile_operation.programAction == PROGRAM_UPDATE_NONE;
}

static void reset_fixture() {
  operationStore = {};
  reset_profile_operation_slot();
  mode_switch_barrier_active = false;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  Samovar_CR_Mode = SAMOVAR_RECTIFICATION_MODE;
  SamSetup = {10, SAMOVAR_RECTIFICATION_MODE};
  SessionDescription = "old";
  BoilerVolume = 1.0f;
  heatLossCalculated = true;
  heatStartMillis = 9;
  lua_type_script = "";
  pendingLockResults.clear();
  sessionActive = false;
  runtimeLockResult = true;
  persistResult = PERSIST_OK;
  persistCalls = 0;
  programCommitCalls = 0;
  programClearCalls = 0;
  runtimeLockCalls = 0;
  applyConfigCalls = 0;
  sensorApplyCalls = 0;
  resetCalls = 0;
  luaLoadCalls = 0;
  cleanupCalls = 0;
  logCloseCalls = 0;
  messageCalls = 0;
  liveProgram = 7;
  luaStopResult = true;
  commandQueueIdle = true;
  commandDiscardResult = true;
  pendingDiscardResult = true;
  pendingCancelledValue = false;
  actuatorsIdleResult = true;
  modeQueuesIdleResult = true;
  luaModeOwnerIdleResult = true;
  logClosePendingResult = false;
  logCloseRequestResult = true;
  fakeNow = 0;
  cleanupDeadline = 1000;
  forceHeaterOffCalls = 0;
  notifyPowerWorkerCalls = 0;
  lastWarningMessage.clear();
  heaterPowerOnResult = false;
  powerTransitionActiveResult = false;
  nbkTransitionActiveResult = false;
  modeHeatingStartActiveResult = false;
  selfTestActiveResult = false;
  modeRuntimeOwnerIdleResult = true;
  modeSwitchState = {SAFETY_MODE_SWITCH_IDLE, 0, false};
  modeActuatorCleanup = {};
}

static OperationRecord record_for(OperationId id) {
  OperationRecord record{};
  check(operation_store_copy_locked(operationStore, id, record) ==
            OPERATION_ERROR_NONE,
        "operation record missing");
  return record;
}

static OperationRecord* mutable_record_for(OperationId id) {
  for (size_t index = 0; index < OPERATION_STORE_CAPACITY; index++) {
    if (operationStore.records[index].id == id &&
        operationStore.records[index].state != OPERATION_STATE_EMPTY) {
      return &operationStore.records[index];
    }
  }
  return nullptr;
}

static OperationError queue_save(
    const SetupEEPROM& settings,
    OperationId& id,
    const ProgramDraft* draft = nullptr,
    bool requireProgramIdle = false,
    bool modeChange = false,
    SAMOVAR_MODE targetMode = SAMOVAR_RECTIFICATION_MODE) {
  return queue_profile_operation(
      OPERATION_KIND_SAVE,
      &settings,
      PROFILE_SENSOR_RESET_STEAM,
      draft,
      draft ? PROGRAM_UPDATE_REPLACE : PROGRAM_UPDATE_NONE,
      0,
      0.0f,
      nullptr,
      requireProgramIdle,
      modeChange,
      SAMOVAR_RECTIFICATION_MODE,
      targetMode,
      id);
}

static OperationError queue_program(
    OperationId& id,
    const ProgramDraft* draft,
    ProgramUpdateAction action,
    uint8_t metadataFlags = 0,
    float volume = 0.0f,
    const char* description = nullptr) {
  return queue_profile_operation(
      OPERATION_KIND_PROGRAM,
      nullptr,
      0,
      draft,
      action,
      metadataFlags,
      volume,
      description,
      true,
      false,
      SAMOVAR_RECTIFICATION_MODE,
      SAMOVAR_RECTIFICATION_MODE,
      id);
}

static OperationRecord run_to_terminal(OperationId id, int maxTicks = 12) {
  OperationRecord record = record_for(id);
  for (int tick = 0; tick < maxTicks &&
       record.state != OPERATION_STATE_SUCCEEDED &&
       record.state != OPERATION_STATE_FAILED; tick++) {
    process_profile_operation();
    record = record_for(id);
  }
  return record;
}

static void test_queue_failures_and_atomic_id() {
  reset_fixture();
  SetupEEPROM settings{20, SAMOVAR_RECTIFICATION_MODE};
  OperationId id = 91;
  pendingLockResults.push_back(false);
  check(queue_save(settings, id) == OPERATION_ERROR_LOCK_BUSY,
        "pending lock failure was not reported");
  check(id == 91 &&
            profile_operation_phase_load() == PROFILE_OPERATION_EMPTY,
        "lock failure published DTO or changed ID");

  reset_fixture();
  profile_operation_phase_store(PROFILE_OPERATION_RUNNING);
  check(queue_save(settings, id) == OPERATION_ERROR_LOCK_BUSY,
        "occupied slot was accepted");
  check(operationStore.nextId == 0, "occupied slot reserved an operation");

  reset_fixture();
  for (size_t index = 0; index < OPERATION_STORE_CAPACITY; index++) {
    OperationId reserved = 0;
    check(operation_store_reserve_locked(
              operationStore, OPERATION_KIND_SAVE, reserved) ==
              OPERATION_ERROR_NONE,
          "full-store setup failed");
  }
  check(queue_save(settings, id) == OPERATION_ERROR_STORE_FULL,
        "full active store was accepted");
  check(profile_operation_phase_load() == PROFILE_OPERATION_EMPTY,
        "STORE_FULL published DTO");

  reset_fixture();
  active_profile_operation.settings = {91, SAMOVAR_DISTILLATION_MODE};
  active_profile_operation.program = {92};
  memset(active_profile_operation.description, 'x',
         sizeof(active_profile_operation.description));
  active_profile_operation.id = 93;
  active_profile_operation.boilerVolume = 94.0f;
  active_profile_operation.flags = 0xff;
  active_profile_operation.sensorResetMask = 0xff;
  active_profile_operation.sourceMode = SAMOVAR_DISTILLATION_MODE;
  active_profile_operation.targetMode = SAMOVAR_BEER_MODE;
  active_profile_operation.terminalState = OPERATION_STATE_FAILED;
  active_profile_operation.terminalError = OPERATION_ERROR_INTERNAL;
  active_profile_operation.programAction = PROGRAM_UPDATE_CLEAR;
  profile_operation_phase_store(PROFILE_OPERATION_EMPTY);
  id = 0;
  check(queue_save(settings, id) == OPERATION_ERROR_NONE,
        "valid save queue failed");
  check(id == active_profile_operation.id && record_for(id).id == id &&
            active_profile_operation.settings.value == settings.value &&
            active_profile_operation.settings.Mode == settings.Mode &&
            active_profile_operation.program.value == 0 &&
            profile_description_is_reset() &&
            active_profile_operation.boilerVolume == 0.0f &&
            active_profile_operation.flags == PROFILE_OPERATION_HAS_SETTINGS &&
            active_profile_operation.sensorResetMask ==
                PROFILE_SENSOR_RESET_STEAM &&
            active_profile_operation.terminalState == OPERATION_STATE_EMPTY &&
            active_profile_operation.terminalError == OPERATION_ERROR_NONE &&
            active_profile_operation.programAction == PROGRAM_UPDATE_NONE &&
            profile_operation_phase_load() == PROFILE_OPERATION_QUEUED,
        "queue initialization retained stale slot payload");
}

static void test_invalid_combinations() {
  reset_fixture();
  SetupEEPROM settings{20, SAMOVAR_RECTIFICATION_MODE};
  ProgramDraft draft{30};
  OperationId id = 0;
  check(queue_profile_operation(
            OPERATION_KIND_SAVE, nullptr, 0, nullptr, PROGRAM_UPDATE_NONE,
            0, 0, nullptr, false, false,
            SAMOVAR_RECTIFICATION_MODE, SAMOVAR_RECTIFICATION_MODE, id) ==
            OPERATION_ERROR_INTERNAL,
        "SAVE without settings was accepted");
  check(queue_profile_operation(
            OPERATION_KIND_SAVE, &settings, 0, nullptr, PROGRAM_UPDATE_NONE,
            PROFILE_OPERATION_METADATA_VOLUME, 2, nullptr, false, false,
            SAMOVAR_RECTIFICATION_MODE, SAMOVAR_RECTIFICATION_MODE, id) ==
            OPERATION_ERROR_INTERNAL,
        "SAVE metadata was accepted");
  check(queue_profile_operation(
            OPERATION_KIND_PROGRAM, &settings, 0, &draft,
            PROGRAM_UPDATE_REPLACE, 0, 0, nullptr, true, false,
            SAMOVAR_RECTIFICATION_MODE, SAMOVAR_RECTIFICATION_MODE, id) ==
            OPERATION_ERROR_INTERNAL,
        "PROGRAM settings were accepted");
  check(queue_profile_operation(
            OPERATION_KIND_PROGRAM, nullptr, 1, &draft,
            PROGRAM_UPDATE_REPLACE, 0, 0, nullptr, true, false,
            SAMOVAR_RECTIFICATION_MODE, SAMOVAR_RECTIFICATION_MODE, id) ==
            OPERATION_ERROR_INTERNAL,
        "PROGRAM sensor reset was accepted");
  check(queue_profile_operation(
            OPERATION_KIND_PROGRAM, nullptr, 0, nullptr,
            PROGRAM_UPDATE_NONE, 0, 0, nullptr, true, false,
            SAMOVAR_RECTIFICATION_MODE, SAMOVAR_RECTIFICATION_MODE, id) ==
            OPERATION_ERROR_INTERNAL,
        "empty PROGRAM operation was accepted");
  check(operationStore.nextId == 0 &&
            profile_operation_phase_load() == PROFILE_OPERATION_EMPTY,
        "invalid combination mutated store or DTO");
}

static void test_idle_policy_and_races() {
  SetupEEPROM settings{20, SAMOVAR_RECTIFICATION_MODE};
  ProgramDraft draft{30};
  OperationId id = 0;

  reset_fixture();
  sessionActive = true;
  check(queue_save(settings, id) == OPERATION_ERROR_NONE,
        "settings-only save regressed under active session");
  check(run_to_terminal(id).state == OPERATION_STATE_SUCCEEDED,
        "settings-only active-session save did not complete");

  reset_fixture();
  sessionActive = true;
  check(queue_save(settings, id, &draft, true) == OPERATION_ERROR_CANCELLED,
        "explicit save program ignored active session");

  reset_fixture();
  sessionActive = true;
  settings.Mode = SAMOVAR_DISTILLATION_MODE;
  check(queue_save(
            settings, id, &draft, false, true,
            SAMOVAR_DISTILLATION_MODE) == OPERATION_ERROR_NONE,
        "mode default draft regressed under active session");
  // !sessionActive проверяется явно, хотя метка чека обещала это и раньше: до
  // этого assert стоял только на статусе, и останов активного процесса не был
  // проверен ничем. Единственный, кто его глушит, - stop_active_process_for_mode()
  // (WebServer.ino:1832); без этого терма его вызов можно удалить, и новый режим
  // молча стартует поверх работающего старого.
  check(run_to_terminal(id).state == OPERATION_STATE_SUCCEEDED && !sessionActive,
        "mode operation did not stop active session and complete");

  reset_fixture();
  check(queue_program(id, &draft, PROGRAM_UPDATE_REPLACE) ==
            OPERATION_ERROR_NONE,
        "program race setup queue failed");
  sessionActive = true;
  OperationRecord record = run_to_terminal(id);
  check(record.state == OPERATION_STATE_FAILED &&
            record.error == OPERATION_ERROR_CANCELLED &&
            programCommitCalls == 0,
        "active-session race did not cancel without side effects");

  reset_fixture();
  settings.Mode = SAMOVAR_DISTILLATION_MODE;
  check(queue_save(
            settings, id, &draft, false, true,
            SAMOVAR_DISTILLATION_MODE) == OPERATION_ERROR_NONE,
        "mode race setup queue failed");
  Samovar_Mode = SAMOVAR_BEER_MODE;
  record = run_to_terminal(id);
  check(record.state == OPERATION_STATE_FAILED &&
            record.error == OPERATION_ERROR_CANCELLED &&
            persistCalls == 0 && !mode_switch_barrier_active,
        "pre-cleanup mode race did not cancel and clear barrier");
}

static void test_save_program_metadata_and_two_saves() {
  reset_fixture();
  SetupEEPROM first{20, SAMOVAR_RECTIFICATION_MODE};
  SetupEEPROM second{30, SAMOVAR_RECTIFICATION_MODE};
  ProgramDraft draft{44};
  OperationId firstId = 0;
  OperationId secondId = 0;
  check(queue_save(first, firstId, &draft, true) == OPERATION_ERROR_NONE,
        "compound save queue failed");
  check(run_to_terminal(firstId).state == OPERATION_STATE_SUCCEEDED,
        "compound save did not succeed");
  check(SamSetup.value == 20 && liveProgram == 44 && persistCalls == 1 &&
            programCommitCalls == 1 && sensorApplyCalls == 1,
        "compound save owner commit mismatch");
  check(queue_save(second, secondId) == OPERATION_ERROR_NONE,
        "second save queue failed");
  check(secondId != firstId &&
            run_to_terminal(secondId).state == OPERATION_STATE_SUCCEEDED &&
            SamSetup.value == 30 && persistCalls == 2,
        "second save did not publish a distinct terminal result");

  reset_fixture();
  OperationId id = 0;
  check(queue_program(id, &draft, PROGRAM_UPDATE_REPLACE) ==
            OPERATION_ERROR_NONE &&
            run_to_terminal(id).state == OPERATION_STATE_SUCCEEDED &&
            liveProgram == 44,
        "standalone program replace failed");
  check(queue_program(id, nullptr, PROGRAM_UPDATE_CLEAR) ==
            OPERATION_ERROR_NONE &&
            run_to_terminal(id).state == OPERATION_STATE_SUCCEEDED &&
            liveProgram == 0 && programClearCalls == 1,
        "standalone program clear failed");
  check(queue_program(
            id, nullptr, PROGRAM_UPDATE_NONE,
            PROFILE_OPERATION_METADATA_VOLUME |
                PROFILE_OPERATION_METADATA_DESCRIPTION,
            9.5f, "new%description") == OPERATION_ERROR_NONE &&
            run_to_terminal(id).state == OPERATION_STATE_SUCCEEDED,
        "standalone metadata update failed");
  check(std::fabs(BoilerVolume - 9.5f) < 0.001f &&
            SessionDescription.value() == "new&#37;description",
        "metadata owner commit mismatch");
}

static void test_failures_preserve_owner_state() {
  SetupEEPROM settings{20, SAMOVAR_RECTIFICATION_MODE};
  ProgramDraft draft{44};
  OperationId id = 0;

  reset_fixture();
  persistResult = PERSIST_WRITE_FAILED;
  check(queue_save(settings, id, &draft, true) == OPERATION_ERROR_NONE,
        "persist-failure setup queue failed");
  OperationRecord record = run_to_terminal(id);
  check(record.state == OPERATION_STATE_FAILED &&
            record.error == OPERATION_ERROR_PROFILE_PERSIST_FAILED &&
            SamSetup.value == 10 && liveProgram == 7 && persistCalls == 1 &&
            programCommitCalls == 0,
        "persist failure exposed partial owner state");

  reset_fixture();
  runtimeLockResult = false;
  check(queue_program(
            id, &draft, PROGRAM_UPDATE_REPLACE,
            PROFILE_OPERATION_METADATA_DESCRIPTION, 0, "new") ==
            OPERATION_ERROR_NONE,
        "runtime-failure setup queue failed");
  record = run_to_terminal(id);
  check(record.state == OPERATION_STATE_FAILED &&
            record.error == OPERATION_ERROR_RUNTIME_BUSY &&
            liveProgram == 7 && SessionDescription.value() == "old" &&
            programCommitCalls == 0,
        "metadata lock failure exposed partial program/metadata state");

  reset_fixture();
  settings.Mode = SAMOVAR_DISTILLATION_MODE;
  pendingDiscardResult = false;
  // Дедлайн просрочен часами (fakeNow), а не обнулением cleanupDeadline: тогда
  // сброс modeActuatorCleanup виден по ОБОИМ полям сразу (initialized true->false,
  // deadline 1000->0). При cleanupDeadline = 0 проверка deadline была бы
  // тавтологией — она проходила бы и без сброса.
  fakeNow = 5000;
  check(queue_save(
            settings, id, &draft, false, true,
            SAMOVAR_DISTILLATION_MODE) == OPERATION_ERROR_NONE,
        "cleanup-failure setup queue failed");
  record = run_to_terminal(id);
  check(record.state == OPERATION_STATE_FAILED &&
            record.error == OPERATION_ERROR_MODE_SWITCH_FAILED &&
            persistCalls == 0 && SamSetup.value == 10 && liveProgram == 7 &&
            !mode_switch_barrier_active && forceHeaterOffCalls == 1 &&
            notifyPowerWorkerCalls == 1,
        "cleanup failure persisted/committed or left the barrier stuck");
  // R9: принудительное завершение обязано обнулить состояние доводки приводов.
  // Иначе initialized остаётся true, и tick_mode_actuator_cleanup() СЛЕДУЮЩЕЙ
  // смены режима (WebServer.ino: `if (!modeActuatorCleanup.initialized)`)
  // пропустит переинициализацию и унаследует протухший deadline — тот уже
  // просрочен, поэтому следующая смена режима принудительно провалится сразу,
  // не дав приводам ни одного тика на остановку.
  // Проверяются только поля, которые к этому моменту РЕАЛЬНО ненулевые
  // (заглушка tick_mode_actuator_cleanup выставляет ровно эти два); assert на
  // mixerStopped/pumpStopped был бы тавтологией — они false и без сброса.
  check(!modeActuatorCleanup.initialized && modeActuatorCleanup.deadline == 0,
        "forced mode-switch completion left stale modeActuatorCleanup state");

  reset_fixture();
  settings.Mode = SAMOVAR_DISTILLATION_MODE;
  persistResult = PERSIST_READ_FAILED;
  check(queue_save(
            settings, id, &draft, false, true,
            SAMOVAR_DISTILLATION_MODE) == OPERATION_ERROR_NONE,
        "mode-persist-failure setup queue failed");
  record = run_to_terminal(id);
  // NVS persist failing no longer traps the barrier: the mode switch is forced
  // to completion in RAM (settings/program/mode applied, RAM commit finished),
  // only the terminal error still reports that NVS did not durably persist it.
  check(record.state == OPERATION_STATE_FAILED &&
            record.error == OPERATION_ERROR_PROFILE_PERSIST_FAILED &&
            persistCalls == 1 && SamSetup.value == 20 && liveProgram == 44 &&
            programCommitCalls == 1 && applyConfigCalls == 1 &&
            luaLoadCalls == 1 && resetCalls == 1 &&
            Samovar_Mode == SAMOVAR_DISTILLATION_MODE &&
            !mode_switch_barrier_active && forceHeaterOffCalls == 1 &&
            notifyPowerWorkerCalls == 1,
        "mode persist failure blocked the RAM mode commit or left the barrier stuck");
}

static void test_mode_change_reloads_lua_script_of_new_mode() {
  // Целевых режима два, и это существенно: на одном режиме проверку ниже
  // устроил бы и хардкод `lua_type_script = "dist"` - имя совпало бы с
  // единственным прогоняемым. Второй режим отбирает у хардкода эту возможность:
  // одной константой оба ожидания разом не удовлетворить.
  const SAMOVAR_MODE targets[] = {SAMOVAR_DISTILLATION_MODE, SAMOVAR_BEER_MODE};
  for (SAMOVAR_MODE target : targets) {
    reset_fixture();
    // Исходное состояние - загружен скрипт ПРЕЖНЕГО режима: ровно то, что смена
    // режима обязана подменить. Иначе load_lua_script() перечитает скрипт
    // старого режима, и новый поедет на чужой логике.
    lua_type_script = get_lua_mode_name();
    const std::string previousScript = lua_type_script.value();
    SetupEEPROM settings{20, target};
    OperationId id = 0;
    check(queue_save(settings, id, nullptr, false, true, target) ==
              OPERATION_ERROR_NONE,
          "lua-mode-name setup queue failed");
    check(run_to_terminal(id).state == OPERATION_STATE_SUCCEEDED &&
              luaLoadCalls == 1,
          "lua-mode-name setup did not complete the mode commit");
    // Имя обязано быть взято ПОСЛЕ коммита режима в RAM (Samovar.ino:389 ставит
    // Samovar_CR_Mode, из которого get_lua_mode_name его и выводит): строкой
    // выше по тексту та же строка кода вернула бы имя прежнего режима.
    check(lua_type_script.value() != previousScript &&
              lua_type_script.value() == get_lua_mode_name().value(),
          "mode change did not refresh lua_type_script to the new mode script");
  }
}

static void test_mode_success_and_terminal_retry() {
  reset_fixture();
  SetupEEPROM settings{20, SAMOVAR_DISTILLATION_MODE};
  ProgramDraft draft{44};
  OperationId id = 0;
  check(queue_save(
            settings, id, &draft, false, true,
            SAMOVAR_DISTILLATION_MODE) == OPERATION_ERROR_NONE,
        "mode-success setup queue failed");
  OperationRecord record = run_to_terminal(id);
  check(record.state == OPERATION_STATE_SUCCEEDED &&
            persistCalls == 1 && programCommitCalls == 1 &&
            applyConfigCalls == 1 && luaLoadCalls == 1 && resetCalls == 1 &&
            Samovar_Mode == SAMOVAR_DISTILLATION_MODE &&
            !mode_switch_barrier_active && profile_slot_is_reset() &&
            forceHeaterOffCalls == 0 && notifyPowerWorkerCalls == 0,
        "mode success did not perform one complete owner commit");

  reset_fixture();
  settings = {30, SAMOVAR_RECTIFICATION_MODE};
  check(queue_save(settings, id, &draft, true) == OPERATION_ERROR_NONE,
        "terminal-retry setup queue failed");
  pendingLockResults.push_back(true);
  pendingLockResults.push_back(false);
  process_profile_operation();
  record = record_for(id);
  check(record.state == OPERATION_STATE_RUNNING && persistCalls == 1 &&
            programCommitCalls == 1 &&
            profile_operation_phase_load() ==
                PROFILE_OPERATION_TERMINAL_PENDING,
        "terminal lock busy did not retain terminal-pending state");
  process_profile_operation();
  record = record_for(id);
  check(record.state == OPERATION_STATE_SUCCEEDED && persistCalls == 1 &&
            programCommitCalls == 1 && profile_slot_is_reset(),
        "terminal retry repeated operation side effects");
}

static void test_transition_failures_are_fail_closed() {
  SetupEEPROM settings{20, SAMOVAR_RECTIFICATION_MODE};
  SetupEEPROM modeSettings{20, SAMOVAR_DISTILLATION_MODE};
  OperationId id = 0;

  reset_fixture();
  check(queue_save(
            modeSettings, id, nullptr, false, true,
            SAMOVAR_DISTILLATION_MODE) == OPERATION_ERROR_NONE,
        "mark-running recovery setup queue failed");
  OperationRecord* record = mutable_record_for(id);
  check(record != nullptr, "mark-running recovery record missing in setup");
  if (record) record->state = OPERATION_STATE_RUNNING;
  check(mode_switch_barrier_active,
        "mode barrier was not raised before mark-running recovery");
  process_profile_operation();
  OperationRecord recovered = record_for(id);
  check(recovered.state == OPERATION_STATE_FAILED &&
            recovered.error == OPERATION_ERROR_INTERNAL &&
            profile_slot_is_reset() &&
            !mode_switch_barrier_active && persistCalls == 0 &&
            cleanupCalls == 0 && resetCalls == 0,
        "mark-running recovery retained the barrier or started side effects");

  reset_fixture();
  check(queue_save(
            modeSettings, id, nullptr, false, true,
            SAMOVAR_DISTILLATION_MODE) == OPERATION_ERROR_NONE,
        "missing-record setup queue failed");
  record = mutable_record_for(id);
  if (record) *record = {};
  process_profile_operation();
  check(profile_operation_phase_load() == PROFILE_OPERATION_FAILED_CLOSED &&
            mode_switch_barrier_active && persistCalls == 0 &&
            cleanupCalls == 0 && messageCalls == 1,
        "missing record did not retain the safe fail-closed barrier");
  process_profile_operation();
  check(persistCalls == 0 && messageCalls == 1,
        "fail-closed missing record retried work or diagnostics");

  reset_fixture();
  check(queue_save(settings, id) == OPERATION_ERROR_NONE,
        "terminal-invalid setup queue failed");
  pendingLockResults.push_back(true);
  pendingLockResults.push_back(false);
  process_profile_operation();
  record = mutable_record_for(id);
  check(record != nullptr &&
            profile_operation_phase_load() ==
                PROFILE_OPERATION_TERMINAL_PENDING,
        "terminal-invalid setup did not retain terminal pending");
  if (record) record->state = OPERATION_STATE_SUCCEEDED;
  process_profile_operation();
  check(profile_operation_phase_load() == PROFILE_OPERATION_FAILED_CLOSED &&
            persistCalls == 1 && messageCalls == 1,
        "invalid terminal transition did not become visible fail-closed state");
  process_profile_operation();
  check(persistCalls == 1 && messageCalls == 1,
        "invalid terminal transition repeated side effects or diagnostics");
}

// R11: WAIT_CLEANUP's deadline-expiry force-completion must be gated by the
// SAME safety_mode_switch_cleanup_ready(...) result the bottom check uses, not
// a separate hand-rolled list of terms. Before this fix six of its eleven
// terms (heaterPowerOn/powerTransitionActive/nbkTransitionActive/
// modeHeatingActive/selfTestActive/ownerIdle) were absent from the deadline
// exit condition, so a switch stuck on exactly one of them never force-failed
// and the barrier hung forever. Each case below reaches WAIT_CLEANUP with
// every term healthy except exactly one, expires the deadline, and requires
// the switch to force-fail anyway, naming the correct blocker.
struct ModeSwitchBlockerCase {
  const char* name;
  bool heaterPowerOn;
  bool powerTransitionActive;
  bool nbkTransitionActive;
  bool modeHeatingActive;
  bool selfTestActive;
  bool ownerIdle;
  bool actuatorsIdle;
  bool luaIdle;
  bool queuesIdle;
  bool logClosePending;
  const char* expectedWarning;
};

static void test_mode_switch_force_completion_names_single_blocker() {
  const ModeSwitchBlockerCase cases[] = {
      {"heaterPowerOn", true, false, false, false, false, true, true, true, true, false,
       "Смена режима завершена принудительно: не подтвердился нагрев"},
      {"powerTransitionActive", false, true, false, false, false, true, true, true, true, false,
       "Смена режима завершена принудительно: не подтвердился переход мощности"},
      {"nbkTransitionActive", false, false, true, false, false, true, true, true, true, false,
       "Смена режима завершена принудительно: не подтвердился переход НБК"},
      {"modeHeatingActive", false, false, false, true, false, true, true, true, true, false,
       "Смена режима завершена принудительно: не подтвердился старт нагрева"},
      {"selfTestActive", false, false, false, false, true, true, true, true, true, false,
       "Смена режима завершена принудительно: не подтвердился самотест"},
      {"ownerIdle", false, false, false, false, false, false, true, true, true, false,
       "Смена режима завершена принудительно: не подтвердился владелец режима"},
      {"actuatorsIdle", false, false, false, false, false, true, false, true, true, false,
       "Смена режима завершена принудительно: не подтвердился привод"},
      // luaIdle/queuesIdle входили ещё в дофиксовый выход по дедлайну, но
      // проверены не были: lua_mode_owner_idle() был захардкожен в true, а
      // modeQueuesIdleResult никто не ронял. Без этих двух кейсов терм можно
      // молча выкинуть из safety_mode_switch_cleanup_ready(), и smoke остаётся
      // зелёным - ровно та дыра, ради которой R11 свёл готовность в один расчёт.
      // В фазе STOP_REQUESTED готовность считают другие предикаты
      // (request_lua_mode_stop/samovar_command_queue_idle), поэтому уронить эти
      // два терма можно, не мешая дойти до WAIT_CLEANUP.
      {"luaIdle", false, false, false, false, false, true, true, false, true, false,
       "Смена режима завершена принудительно: не подтвердился Lua"},
      {"queuesIdle", false, false, false, false, false, true, true, true, false, false,
       "Смена режима завершена принудительно: не подтвердился очередь"},
      // logClosePending проверяется здесь же, хотя в цепочке стоит первым: лог
      // закрывается асинхронно, и «закрытие запрошено, но ещё не доехало» - это
      // ровно тот случай, когда барьер обязан сдаться по дедлайну, а не ждать
      // вечно. Кейс держится на том, что выход по дедлайну (WebServer.ino:1887)
      // стоит РАНЬШЕ запроса закрытия лога (1913).
      {"logClosePending", false, false, false, false, false, true, true, true, true, true,
       "Смена режима завершена принудительно: не подтвердился лог"},
  };

  for (const ModeSwitchBlockerCase& blockerCase : cases) {
    reset_fixture();
    heaterPowerOnResult = blockerCase.heaterPowerOn;
    powerTransitionActiveResult = blockerCase.powerTransitionActive;
    nbkTransitionActiveResult = blockerCase.nbkTransitionActive;
    modeHeatingStartActiveResult = blockerCase.modeHeatingActive;
    selfTestActiveResult = blockerCase.selfTestActive;
    modeRuntimeOwnerIdleResult = blockerCase.ownerIdle;
    actuatorsIdleResult = blockerCase.actuatorsIdle;
    luaModeOwnerIdleResult = blockerCase.luaIdle;
    modeQueuesIdleResult = blockerCase.queuesIdle;
    logClosePendingResult = blockerCase.logClosePending;

    SetupEEPROM settings{20, SAMOVAR_DISTILLATION_MODE};
    OperationId id = 0;
    const std::string label = std::string("blocker case ") + blockerCase.name;
    check(queue_save(
              settings, id, nullptr, false, true,
              SAMOVAR_DISTILLATION_MODE) == OPERATION_ERROR_NONE,
          (label + ": setup queue failed").c_str());

    // Tick 1: STOP_REQUESTED phase (everything healthy) -> WAIT_CLEANUP.
    process_profile_operation();
    check(record_for(id).state == OPERATION_STATE_RUNNING,
          (label + ": did not reach WAIT_CLEANUP cleanly").c_str());

    // Tick 2: WAIT_CLEANUP, deadline not yet expired -> requests log close.
    process_profile_operation();
    check(record_for(id).state == OPERATION_STATE_RUNNING &&
              modeSwitchState.logCloseRequested,
          (label + ": resolved before the log close was requested").c_str());

    // Now expire the deadline while the single blocker stays active.
    fakeNow = cleanupDeadline + 1;

    // Tick 3: deadline expired, cleanup still not ready -> forced completion.
    process_profile_operation();
    const OperationRecord record = record_for(id);
    check(record.state == OPERATION_STATE_FAILED &&
              record.error == OPERATION_ERROR_MODE_SWITCH_FAILED,
          (label + ": did not force-complete the stuck switch").c_str());
    check(!mode_switch_barrier_active,
          (label + ": left the barrier stuck").c_str());
    check(forceHeaterOffCalls == 1 && notifyPowerWorkerCalls == 1,
          (label + ": did not cut heater output or notify the power worker")
              .c_str());
    check(!modeActuatorCleanup.initialized && modeActuatorCleanup.deadline == 0,
          (label + ": left stale modeActuatorCleanup state").c_str());
    check(lastWarningMessage == blockerCase.expectedWarning,
          (label + ": warning text did not name this blocker").c_str());
  }
}

// Фаза STOP_REQUESTED: своя цепочка принудительного завершения
// (WebServer.ino:1842-1850), до расчёта cleanupReady эти блокеры не доходят.
// Проверять один терминальный статус тут МАЛО и это не педантизм: под мутацией,
// выкидывающей блокер, смена режима спокойно доезжает до WAIT_CLEANUP и валится
// уже ТАМ по дедлайну лога - статус тот же самый MODE_SWITCH_FAILED. Именно так
// тест на строке ~766 и проходит под мутацией: он ждёт отказ, получает отказ, но
// по другой причине. Отличает причины только текст предупреждения, поэтому он
// здесь и есть предмет проверки.
struct StopPhaseBlockerCase {
  const char* name;
  bool luaStop;
  bool queueDiscarded;
  bool pendingDiscarded;
  const char* expectedWarning;
};

static void test_stop_phase_force_completion_names_single_blocker() {
  const StopPhaseBlockerCase cases[] = {
      {"luaStop", false, true, true,
       "Смена режима завершена принудительно: не подтвердился Lua"},
      {"queueDiscarded", true, false, true,
       "Смена режима завершена принудительно: не подтвердился очередь"},
      {"pendingDiscarded", true, true, false,
       "Смена режима завершена принудительно: не подтвердился очередь"},
  };

  for (const StopPhaseBlockerCase& blockerCase : cases) {
    reset_fixture();
    luaStopResult = blockerCase.luaStop;
    commandDiscardResult = blockerCase.queueDiscarded;
    pendingDiscardResult = blockerCase.pendingDiscarded;

    SetupEEPROM settings{20, SAMOVAR_DISTILLATION_MODE};
    OperationId id = 0;
    const std::string label = std::string("stop-phase case ") + blockerCase.name;
    check(queue_save(
              settings, id, nullptr, false, true,
              SAMOVAR_DISTILLATION_MODE) == OPERATION_ERROR_NONE,
          (label + ": setup queue failed").c_str());

    // Тик 1: дедлайн не вышел - блокер обязан ДЕРЖАТЬ смену, а не валить её.
    process_profile_operation();
    check(record_for(id).state == OPERATION_STATE_RUNNING &&
              modeSwitchState.phase == SAFETY_MODE_SWITCH_STOP_REQUESTED,
          (label + ": resolved before the deadline expired").c_str());

    fakeNow = cleanupDeadline + 1;

    // Тик 2: дедлайн вышел, блокер держится -> принудительное завершение.
    process_profile_operation();
    const OperationRecord record = record_for(id);
    check(record.state == OPERATION_STATE_FAILED &&
              record.error == OPERATION_ERROR_MODE_SWITCH_FAILED,
          (label + ": did not force-complete the stuck switch").c_str());
    check(!mode_switch_barrier_active,
          (label + ": left the barrier stuck").c_str());
    check(lastWarningMessage == blockerCase.expectedWarning,
          (label + ": warning text did not name this blocker").c_str());
  }
}

// queueWasIdle - единственный из предикатов фазы, который на ИСХОД смены режима
// не влияет вовсе: он решает лишь, узнает ли пользователь, что его отложенные
// команды выкинули. Поэтому предмет проверки тут - факт отправки сообщения;
// assert на статус операции был бы тавтологией (он одинаков в обоих случаях).
static void test_stop_phase_reports_discarded_pending_commands() {
  reset_fixture();
  commandQueueIdle = false;

  SetupEEPROM settings{20, SAMOVAR_DISTILLATION_MODE};
  OperationId id = 0;
  check(queue_save(
            settings, id, nullptr, false, true,
            SAMOVAR_DISTILLATION_MODE) == OPERATION_ERROR_NONE,
        "busy-queue setup queue failed");

  process_profile_operation();
  check(modeSwitchState.phase == SAFETY_MODE_SWITCH_WAIT_CLEANUP,
        "busy queue blocked the mode switch instead of only warning about it");
  check(lastWarningMessage ==
            "Отложенные управляющие команды отменены сменой режима",
        "did not tell the user their queued commands were discarded");
}

// Барьер смены режима обязан отбивать постановку новых операций (WebServer.ino:173).
// Иначе профиль применится в середине смены режима - ровно тогда, когда старый
// режим уже остановлен, а новый ещё не применён. Значение барьера проверяют
// многие тесты, но то, что он ОТБИВАЕТ постановку, не проверял ни один.
static void test_queue_rejected_while_mode_switch_barrier_is_up() {
  reset_fixture();
  mode_switch_barrier_active = true;

  SetupEEPROM settings{20, SAMOVAR_RECTIFICATION_MODE};
  OperationId id = 0;
  check(queue_save(settings, id) == OPERATION_ERROR_CANCELLED,
        "queued a profile operation while the mode-switch barrier was up");
}

// Отказ запроса на закрытие лога (WebServer.ino:1914) не должен ни зависать
// барьером, ни проскакивать: пока закрытие не подтверждено, готовность не
// наступает, а по дедлайну смена обязана завершиться принудительно с указанием
// лога как причины. Без этого кейса request_data_log_close() можно захардкодить
// в true, и ни один тест не заметит.
static void test_log_close_request_failure_forces_completion() {
  reset_fixture();
  logCloseRequestResult = false;

  SetupEEPROM settings{20, SAMOVAR_DISTILLATION_MODE};
  OperationId id = 0;
  check(queue_save(
            settings, id, nullptr, false, true,
            SAMOVAR_DISTILLATION_MODE) == OPERATION_ERROR_NONE,
        "log-close-failure setup queue failed");

  process_profile_operation();  // Тик 1: STOP_REQUESTED -> WAIT_CLEANUP.
  process_profile_operation();  // Тик 2: запрос закрытия лога проваливается.
  check(!modeSwitchState.logCloseRequested && logCloseCalls > 0,
        "marked the log close as requested even though the request failed");

  fakeNow = cleanupDeadline + 1;
  process_profile_operation();  // Тик 3: дедлайн вышел -> принудительно.
  const OperationRecord record = record_for(id);
  check(record.state == OPERATION_STATE_FAILED &&
            record.error == OPERATION_ERROR_MODE_SWITCH_FAILED,
        "a failing log close did not force-complete the stuck switch");
  check(lastWarningMessage ==
            "Смена режима завершена принудительно: не подтвердился лог",
        "forced completion did not name the log as the blocker");
}

int main() {
  test_queue_failures_and_atomic_id();
  test_invalid_combinations();
  test_idle_policy_and_races();
  test_save_program_metadata_and_two_saves();
  test_failures_preserve_owner_state();
  test_mode_change_reloads_lua_script_of_new_mode();
  test_mode_success_and_terminal_retry();
  test_transition_failures_are_fail_closed();
  test_mode_switch_force_completion_names_single_blocker();
  test_stop_phase_force_completion_names_single_blocker();
  test_stop_phase_reports_discarded_pending_commands();
  test_queue_rejected_while_mode_switch_barrier_is_up();
  test_log_close_request_failure_forces_completion();
  if (failures != 0) return 1;
  std::cout << "profile operation behavioral checks passed\n";
  return 0;
}
'''
    harness = harness.replace("@PROFILE_DEFS@", profile_defs)
    harness = harness.replace("@MODE_RESULT@", mode_result)
    harness = harness.replace("@PERSIST_RESULT@", persist_result)
    for marker, body in bodies.items():
        harness = harness.replace(marker, body)
    return harness


def static_checks() -> list[str]:
    errors: list[str] = []
    samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    web = (ROOT / "WebServer.ino").read_text(encoding="utf-8")
    api = (ROOT / "samovar_api.h").read_text(encoding="utf-8")
    selftest = (ROOT / "selftest.h").read_text(encoding="utf-8")

    old_symbols = (
        "pending_setup_save_buf",
        "pending_save_profile_flag",
        "pending_program_update",
        "pending_program_metadata",
        "pending_switch_mode_flag",
        "pending_switch_mode_value",
        "queue_pending_setup_save",
        "queue_pending_program",
    )
    production = samovar + web + api + selftest
    for symbol in old_symbols:
        if symbol in production:
            errors.append(f"obsolete split-operation symbol remains: {symbol}")

    if samovar.count("ProfileOperationSlot active_profile_operation{};") != 1:
        errors.append("single fixed active ProfileOperationSlot is missing")
    if "sizeof(ProfileOperationSlot) <= 1368" not in samovar:
        errors.append("ProfileOperationSlot RAM replacement budget is missing")
    if "sizeof(ProfileOperationPhase) == sizeof(uint8_t)" not in samovar:
        errors.append("ProfileOperationPhase byte-size contract is missing")
    phase_load = extract_function_body(
        samovar, "static inline ProfileOperationPhase profile_operation_phase_load()")
    if "__atomic_load_n" not in phase_load or "__ATOMIC_ACQUIRE" not in phase_load:
        errors.append("profile phase load is not acquire-atomic")
    phase_store = extract_function_body(
        samovar, "static inline void profile_operation_phase_store(")
    if "__atomic_store_n" not in phase_store or "__ATOMIC_RELEASE" not in phase_store:
        errors.append("profile phase store is not release-atomic")
    if samovar.count("active_profile_operation.phase") != 2:
        errors.append("Samovar.ino bypasses the profile phase atomic accessors")
    if "active_profile_operation.phase" in web:
        errors.append("WebServer.ino bypasses the profile phase atomic accessors")
    if re.search(r"\bactive_profile_operation\s*=", production):
        errors.append("production clears ProfileOperationSlot through aggregate assignment")
    reset_slot = extract_function_body(
        samovar, "static void reset_profile_operation_slot()")
    require_ordered_tokens(
        "profile slot reset preserves atomic phase publication",
        reset_slot,
        [
            "active_profile_operation.settings = SetupEEPROM{};",
            "active_profile_operation.program = ProgramDraft{};",
            "memset(active_profile_operation.description, 0,",
            "active_profile_operation.id = 0;",
            "active_profile_operation.boilerVolume = 0.0f;",
            "active_profile_operation.flags = 0;",
            "active_profile_operation.sensorResetMask = 0;",
            "active_profile_operation.sourceMode = 0;",
            "active_profile_operation.targetMode = 0;",
            "active_profile_operation.terminalState = OPERATION_STATE_EMPTY;",
            "active_profile_operation.terminalError = OPERATION_ERROR_NONE;",
            "active_profile_operation.programAction = PROGRAM_UPDATE_NONE;",
            "profile_operation_phase_store(PROFILE_OPERATION_EMPTY);",
        ],
        errors,
    )
    if not reset_slot.rstrip().endswith(
            "profile_operation_phase_store(PROFILE_OPERATION_EMPTY);"):
        errors.append("profile slot reset does not publish EMPTY last")
    if "active_profile_operation.phase" in reset_slot or \
            "sizeof(active_profile_operation)" in reset_slot or \
            "memset(&active_profile_operation" in reset_slot:
        errors.append("profile slot reset writes phase or clears the whole struct")
    if re.search(r"memset\s*\(\s*&?active_profile_operation\s*,", production):
        errors.append("production clears the whole ProfileOperationSlot with memset")
    queue = extract_function_body(web, "static OperationError queue_profile_operation(")
    if "profile_operation_phase_store(PROFILE_OPERATION_QUEUED)" not in queue:
        errors.append("queue publication does not use the release phase store")
    if "__sync_synchronize" in queue:
        errors.append("queue publication retains the obsolete full fence")
    if queue.count("reset_profile_operation_slot();") != 1:
        errors.append("profile queue does not reset the slot exactly once")
    require_ordered_tokens(
        "profile queue resets, fills, then publishes",
        queue,
        [
            "reset_profile_operation_slot();",
            "if (settings)",
            "active_profile_operation.id = reservedId;",
            "profile_operation_phase_store(PROFILE_OPERATION_QUEUED);",
        ],
        errors,
    )
    if samovar.count("process_profile_operation();") != 2:
        errors.append("process_profile_operation must have one prototype and one loop call")
    process = extract_last_function_body(samovar, "static void process_profile_operation()")
    if "ProfileOperationSlot" in process:
        errors.append("process_profile_operation copies the full DTO")
    publish = extract_function_body(samovar, "static void publish_profile_operation_terminal()")
    if publish.count("reset_profile_operation_slot();") != 1:
        errors.append("terminal publisher does not reset the slot exactly once")
    require_ordered_tokens(
        "terminal publisher resets only after a successful finish",
        publish,
        [
            "if (finishError == OPERATION_ERROR_NONE)",
            "reset_profile_operation_slot();",
            "} else {",
        ],
        errors,
    )
    for forbidden in ("save_profile_nvs", "program_commit", "switch_samovar_mode"):
        if forbidden in publish:
            errors.append(f"terminal publisher repeats side effect: {forbidden}")
    if process.count("reset_profile_operation_slot();") != 1:
        errors.append("mark-running recovery does not reset the slot exactly once")
    require_ordered_tokens(
        "mark-running recovery clears the barrier before the slot",
        process,
        [
            "if (finishError == OPERATION_ERROR_NONE)",
            "mode_switch_barrier_active = false;",
            "reset_profile_operation_slot();",
            "} else {",
        ],
        errors,
    )
    if samovar.count("reset_profile_operation_slot();") != 2 or \
            web.count("reset_profile_operation_slot();") != 1:
        errors.append("profile slot reset helper has an unexpected production owner")

    switch = extract_function_body(
        web, "ModeSwitchResult switch_samovar_mode(SAMOVAR_MODE requestedMode)")
    if switch.count("commit_profile_operation()") != 1:
        errors.append("mode FSM does not have exactly one final owner commit")
    for forbidden in (
        "prepare_default_program_for_mode",
        "save_profile_nvs",
        "program_commit(",
        "program_clear(",
    ):
        if forbidden in switch:
            errors.append(f"mode FSM retains obsolete duplicate path: {forbidden}")

    handle_save = extract_function_body(web, "void handleSave(AsyncWebServerRequest *request)")
    prepare_index = handle_save.find("prepare_default_program_for_mode")
    queue_index = handle_save.find("queue_profile_operation")
    if prepare_index < 0 or queue_index < 0 or prepare_index > queue_index:
        errors.append("default mode program is not validated before queue publication")
    if "beginResponse(301" in handle_save or "send_save_operation_accepted" not in handle_save:
        errors.append("/save retains redirect or lacks operation acceptance")
    if "wProgramCount == 1" not in handle_save:
        errors.append("/save does not preserve explicit-program idle policy")

    web_program = extract_function_body(
        web, "void web_program(AsyncWebServerRequest *request)")
    if "send_program_operation_accepted" not in web_program:
        errors.append("mutating /program lacks six-field operation response")
    if "send_program_json_response" not in web_program:
        errors.append("/program lost legacy three-field read/reject response")
    reserve_owners = (
        "queue_profile_operation",
        "queue_pending_i2cstepper",
        "queue_pending_i2cpump",
        "queue_pending_i2ccal",
        "queue_pending_local_cal",
    )
    reserve_count = 0
    for owner in reserve_owners:
        owner_body = extract_function_body(
            web, f"static OperationError {owner}(")
        owner_count = owner_body.count("operation_store_reserve_locked(")
        if owner_count != 1:
            errors.append(f"{owner} does not own exactly one reserve callsite")
        reserve_count += owner_count
    if web.count("operation_store_reserve_locked(") != reserve_count or \
            reserve_count != 5:
        errors.append("operation reserve callsite is outside the accepted owner inventory")
    if "operation_store_mark_running_locked(" in web or \
            "operation_store_finish_locked(" in web:
        errors.append("WebServer.ino owns mark-running or finish transition")

    transition_owners = {
        "process_profile_operation": process,
        "publish_profile_operation_terminal": publish,
        "process_pending_i2c_operations": extract_function_body(
            samovar, "static void process_pending_i2c_operations()"),
        "cancel_queued_i2c_operations_locked": extract_function_body(
            samovar, "static bool cancel_queued_i2c_operations_locked("),
    }
    expected_transitions = {
        "process_profile_operation": (1, 1),
        "publish_profile_operation_terminal": (0, 1),
        "process_pending_i2c_operations": (1, 1),
        "cancel_queued_i2c_operations_locked": (0, 1),
    }
    mark_count = 0
    finish_count = 0
    for owner, owner_body in transition_owners.items():
        actual = (
            owner_body.count("operation_store_mark_running_locked("),
            owner_body.count("operation_store_finish_locked("),
        )
        if actual != expected_transitions[owner]:
            errors.append(f"{owner} transition ownership mismatch: {actual}")
        mark_count += actual[0]
        finish_count += actual[1]
    if samovar.count("operation_store_mark_running_locked(") != mark_count or \
            mark_count != 2 or \
            samovar.count("operation_store_finish_locked(") != finish_count or \
            finish_count != 4:
        errors.append("Samovar.ino transition callsite is outside A-12/A-02 owners")
    if "operation_store_reserve_locked(" in samovar or \
            "operation_store_mark_running_locked(" in api or \
            "operation_store_finish_locked(" in api:
        errors.append("reserve/transition callsite leaked into Samovar.ino or samovar_api.h")
    return errors


def main() -> int:
    errors = static_checks()
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-profile-operation-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "profile_operation_test.cpp"
        binary = temp / "profile_operation_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(ROOT),
                str(source),
                "-o",
                str(binary),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if compile_result.returncode != 0:
            print(compile_result.stdout, end="")
            return compile_result.returncode
        run_result = subprocess.run(
            [str(binary)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        print(run_result.stdout, end="")
        if run_result.returncode != 0:
            return run_result.returncode

    print("smoke_profile_operation: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
