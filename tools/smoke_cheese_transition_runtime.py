#!/usr/bin/env python3
"""Source-derived Cheese error and safe-stage-transition checks."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "cheese.h").read_text(encoding="utf-8")


def body(signature: str) -> str:
    return extract_function_body(SOURCE, signature, strip_comments=False)


ERROR_HARNESS = r'''
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
class String {
 public:
  String(const char* value = "") : value_(value) {}
  String(unsigned int value) : value_(std::to_string(value)) {}
  String(int value) : value_(std::to_string(value)) {}
  const std::string& value() const { return value_; }
 private:
  std::string value_;
};
String operator+(const char* left, const String& right) { return String((std::string(left) + right.value()).c_str()); }
String operator+(const String& left, const char* right) { return String((left.value() + right).c_str()); }
String operator+(const String& left, const String& right) { return String((left.value() + right.value()).c_str()); }
enum MessageType { ALARM_MSG };
uint8_t ProgramNum = 0;
bool cheesePairErrorPending = false;
String message;
int finishCalls = 0;
void SendMsg(const String& value, MessageType) { message = value; }
void cheese_finish() { ++finishCalls; }
inline void cheese_abort(const String& reason) { @ABORT@ }
int main() {
  cheese_abort("Ошибка охлаждения");
  if (message.value() != "Строка 1: Ошибка охлаждения" || finishCalls != 1) return 1;
  ProgramNum = 7; message = ""; cheese_abort("Нет pH");
  return message.value() == "Строка 8: Нет pH" && finishCalls == 2 ? 0 : 1;
}
'''


TRANSITION_HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>
using std::isfinite;
#define USE_WATER_PUMP
#define PWM_LOW_VALUE 40
class String {
 public:
  String(const char* value = "") : value_(value) {}
  String(unsigned int value) : value_(std::to_string(value)) {}
  const std::string& value() const { return value_; }
 private:
  std::string value_;
};
String operator+(const char* left, const String& right) { return String((std::string(left) + right.value()).c_str()); }
String operator+(const String& left, const char* right) { return String((left.value() + right).c_str()); }
struct WProgram { char WType; float Temp; float Time; uint8_t capacity_num; float Speed; uint16_t Volume; float Power; uint8_t TempSensor; float Param; };
uint32_t program_load_cheese_doser_steps(const WProgram& row) { uint32_t steps = 0; std::memcpy(&steps, &row.Param, sizeof(steps)); return steps; }
#define CHEESE_DOSER_STEP_SPEED 3200
struct Setup { bool rele2; bool rele4; uint16_t StepperStepMl; } SamSetup = {true, true, 4};
struct Runtime { uint8_t mixerDevice; bool mixerRunning; bool mixerOneShotComplete; uint32_t mixerDeadlineMs; bool mixerReversed; bool doserStarted; bool doserCompleted; bool i2cDoserStarted; bool drainOpen; uint32_t enteredMs; uint32_t lastTickMs; float heatStartSetpoint; } cheeseRuntime = {};
enum ActuatorCommandResult { ACTUATOR_COMMAND_APPLIED, ACTUATOR_COMMAND_FAILED };
static const int RELE_CHANNEL2 = 2, RELE_CHANNEL4 = 4;
static const int SAMOVAR_STARTVAL_CHEESE_START = 42;
static const int NOTIFY_MSG = 1;
static const int SAMOVAR_CHEESE_MODE = 7;
enum UiWaitReason { UI_WAIT_CHEESE_OPERATOR, UI_WAIT_CHEESE_DOSE };
enum RuntimePairOutcome { RUNTIME_PAIR_ROW_CHANGE };
static void runtime_pair_begin(UiWaitReason, const char*, int) {}
static void runtime_pair_close_mode(int, RuntimePairOutcome, const char*, int) {}
static const uint8_t PROGRAM_END = 20;
WProgram program[3] = {};
uint8_t ProgramNum = 0;
uint32_t begintime = 0, beerMixerPauseSinceMs = 0, fakeMs = 100;
int alarm_c_min = 0, alarm_c_low_min = 0, currentstepcnt = 0, startval = 0;
bool i2cStepperMixerManualHold = false;
uint16_t i2cStepperMixerRpmOverride = 0;
uint8_t i2cStepperMixerDirOverride = 0;
bool msgfl = false, mixer_status = false, StepperMoving = false, relay2 = false, relay4 = false, cooling = false;
unsigned int TargetStepps = 0;
std::vector<std::string> trace;
uint32_t millis() { return fakeMs; }
void digitalWrite(int pin, bool value) {
  if (pin == RELE_CHANNEL2) { relay2 = value; trace.push_back(value ? "mixer-on" : "mixer-off"); }
  if (pin == RELE_CHANNEL4) { relay4 = value; trace.push_back(value ? "drain-on" : "drain-off"); }
}
ActuatorCommandResult beer_set_cooling_outputs(bool active) { cooling = active; trace.push_back(active ? "cooling-on" : "cooling-off"); return ACTUATOR_COMMAND_APPLIED; }
ActuatorCommandResult set_pump_pwm(float) { return ACTUATOR_COMMAND_APPLIED; }
void setHeaterPosition(bool) { trace.push_back("heater-off"); }
void stopService() { trace.push_back("doser-service-stop"); }
void startService() { trace.push_back("doser-service-start"); }
void stepper_safe_stop_reset() { if (StepperMoving) trace.push_back("doser-off"); }
void stepper_safe_reverse(bool) {}
void stepper_safe_set_motion(float, int32_t, int32_t) { trace.push_back("doser-on"); }
struct Stepper { void enable() {} } stepper;
#define STEPPER_REVERSE
bool i2c_stepper_mixer_present() { return true; }
bool set_stepper_by_time(uint16_t, bool, uint16_t) { return true; }
// I2C-насос: качает, пока его не остановили; отказ остановки оставляет его работать.
#define I2CSTEPPER_V3_MAX_SPEED_STEPS_PER_SEC 20000
float i2cStepperPumpRateOverride = 0.0f; uint8_t i2cStepperPumpDirOverride = 0;
bool i2cPumpRunning = false, i2cPumpStopOk = true; int i2cPumpStops = 0;
uint32_t i2c_get_step_by_liquid_volume(float ml) { return static_cast<uint32_t>(ml * 400.0f); }
float i2c_get_speed_from_rate(float litersPerHour) { return litersPerHour * 1000.0f * 400.0f / 3600.0f; }
bool start_second_i2c_pump_steps(float, uint32_t) { i2cPumpRunning = true; trace.push_back("i2c-pump-on"); return true; }
bool stop_second_i2c_pump() { ++i2cPumpStops; if (i2cPumpStopOk) { i2cPumpRunning = false; trace.push_back("i2c-pump-off"); } return i2cPumpStopOk; }
void request_emergency_stop(const String&) { trace.push_back("emergency"); }
const char* cheese_stage_name(char) { return "stage"; }
void SendMsg(const String&, int) {}
inline void cheese_set_drain(bool open) { @DRAIN@ }
inline bool cheese_mixer_is_i2c(uint8_t device) { @IS_I2C@ }
inline bool cheese_mixer_start(const WProgram& row) { @MIXER_START@ }
inline bool cheese_mixer_stop() { @MIXER_STOP@ }
inline bool cheese_configure_mixer(const WProgram& row, uint32_t nowMs) { @MIXER_CONFIGURE@ }
inline bool cheese_set_cooling_outputs(bool active, bool highFlow) { @COOLING@ }
inline bool cheese_local_doser_motion(const WProgram& row,
                                      uint32_t& targetSteps, float& speed) { @LOCAL_MOTION@ }
inline bool cheese_start_local_doser(const WProgram& row) { @LOCAL_DOSE@ }
inline bool cheese_i2c_doser_motion(const WProgram& row,
                                    uint32_t& targetSteps, float& rateLitersPerHour) { @I2C_MOTION@ }
inline bool cheese_start_i2c_doser(const WProgram& row) { @I2C_DOSE@ }
inline bool cheese_apply_safe_outputs(bool closeDrain) { @SAFE@ }
inline bool cheese_prepare_stage(uint8_t targetProgram) { @PREPARE@ }
static int index_of(const char* event) { for (size_t i = 0; i < trace.size(); ++i) if (trace[i] == event) return static_cast<int>(i); return -1; }
static bool previous_outputs_off_before_new_outputs() {
  const int coolingOff = index_of("cooling-off"), mixerOff = index_of("mixer-off"), doserOff = index_of("doser-off");
  const int mixerOn = index_of("mixer-on"), doserOn = index_of("doser-on");
  return coolingOff >= 0 && mixerOff >= 0 && doserOff >= 0 && mixerOn >= 0 && doserOn >= 0 && coolingOff < mixerOn && mixerOff < mixerOn && doserOff < doserOn;
}
int main() {
  program[0] = {'S', 0, 0, 0, 0, 0, 0, 0, 0};
  program[1] = {'W', 0, 0, 0, 0, 0, 0, 0, 0};
  if (!cheese_prepare_stage(0) || !relay4 || !cheeseRuntime.drainOpen) return 1;
  trace.clear();
  if (!cheese_prepare_stage(1) || relay4 || cheeseRuntime.drainOpen) return 2;
  program[1] = {'D', 2.5f, 1, 1, 0, 0, 0, 2, 60};
  ProgramNum = 0; cooling = true; relay2 = true; mixer_status = true; cheeseRuntime.mixerDevice = 1; cheeseRuntime.mixerRunning = true; StepperMoving = true; TargetStepps = 12; cheeseRuntime.doserStarted = true;
  trace.clear();
  if (!cheese_prepare_stage(1)) return 3;
  if (cooling || !relay2 || !StepperMoving || !cheeseRuntime.doserStarted || !previous_outputs_off_before_new_outputs()) return 4;
  if (i2cPumpStops != 0) return 5;  // чужой I2C-насос строка без I2C-дозы не трогает
  program[1] = {'D', 2.5f, 1, 0, 0, 0, 0, 4, 30};
  program[2] = {'W', 0, 1, 0, 0, 0, 0, 0, 1};
  trace.clear();
  if (!cheese_prepare_stage(1) || !i2cPumpRunning || !cheeseRuntime.i2cDoserStarted || index_of("doser-on") >= 0) return 6;
  trace.clear();
  if (!cheese_prepare_stage(2) || i2cPumpRunning || i2cPumpStops != 1 || cheeseRuntime.i2cDoserStarted) return 7;
  if (!cheese_prepare_stage(1) || !i2cPumpRunning) return 8;
  i2cPumpStopOk = false; trace.clear();
  if (cheese_prepare_stage(2) || index_of("emergency") < 0 || !i2cPumpRunning) return 9;
  return 0;
}
'''


def run(cpp: str, label: str, expected_success: bool) -> bool:
    with tempfile.TemporaryDirectory(prefix="samovar-cheese-transition-") as temp:
        path = Path(temp)
        source, binary = path / "test.cpp", path / "test"
        source.write_text(cpp, encoding="utf-8")
        compiled = subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)], capture_output=True, text=True, check=False)
        if compiled.returncode:
            print(f"FAIL: {label} compile\n{compiled.stderr}", file=sys.stderr)
            return False
        completed = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if (completed.returncode == 0) != expected_success:
            print(f"FAIL: {label}\n{completed.stdout}{completed.stderr}", file=sys.stderr)
            return False
    return True


def main() -> int:
    try:
        abort = body("inline void cheese_abort(const String& reason)")
        pieces = {
            "@DRAIN@": body("inline void cheese_set_drain(bool open)"),
            "@IS_I2C@": body("inline bool cheese_mixer_is_i2c(uint8_t device)"),
            "@I2C_MOTION@": body("inline bool cheese_i2c_doser_motion(const WProgram& row,"),
            "@I2C_DOSE@": body("inline bool cheese_start_i2c_doser(const WProgram& row)"),
            "@MIXER_START@": body("inline bool cheese_mixer_start(const WProgram& row)"),
            "@MIXER_STOP@": body("inline bool cheese_mixer_stop()"),
            "@MIXER_CONFIGURE@": body("inline bool cheese_configure_mixer(const WProgram& row, uint32_t nowMs)"),
            "@COOLING@": body("inline bool cheese_set_cooling_outputs(bool active, bool highFlow)"),
            "@LOCAL_MOTION@": body("inline bool cheese_local_doser_motion(const WProgram& row,"),
            "@LOCAL_DOSE@": body("inline bool cheese_start_local_doser(const WProgram& row)"),
            "@SAFE@": body("inline bool cheese_apply_safe_outputs(bool closeDrain)"),
            "@PREPARE@": body("inline bool cheese_prepare_stage(uint8_t targetProgram)"),
        }
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    error = ERROR_HARNESS.replace("@ABORT@", abort)
    if not run(error, "Cheese error message", True):
        return 1
    abort_mutant = abort.replace("ProgramNum + 1", "ProgramNum", 1)
    if abort_mutant == abort or not run(ERROR_HARNESS.replace("@ABORT@", abort_mutant), "Cheese error line mutation", False):
        return 1
    transition = TRANSITION_HARNESS
    for marker, value in pieces.items():
        transition = transition.replace(marker, value)
    if not run(transition, "Cheese safe transition", True):
        return 1
    prepare_mutant = pieces["@PREPARE@"].replace("if (!cheese_apply_safe_outputs(true)) return false;", "if (false) return false;", 1)
    if prepare_mutant == pieces["@PREPARE@"]:
        print("FAIL: safe transition mutation anchor missing", file=sys.stderr)
        return 1
    transition_mutant = transition.replace(pieces["@PREPARE@"], prepare_mutant, 1)
    if not run(transition_mutant, "Cheese safe transition mutation", False):
        return 1
    for marker, old, new, label in (
        ("@SAFE@", "cheeseRuntime.i2cDoserStarted && !stop_second_i2c_pump()", "false", "I2C pump left running"),
        ("@SAFE@", "cheeseRuntime.i2cDoserStarted && !stop_second_i2c_pump()", "!stop_second_i2c_pump()",
         "foreign I2C pump stopped"),
        ("@PREPARE@", "row.TempSensor == 4 && !cheese_start_i2c_doser(row)", "false", "I2C pump dose not started"),
    ):
        mutant = pieces[marker].replace(old, new, 1)
        if mutant == pieces[marker]:
            print(f"FAIL: {label} mutation anchor missing", file=sys.stderr)
            return 1
        if not run(transition.replace(pieces[marker], mutant, 1), f"mutation: {label}", False):
            return 1
    print("OK: Cheese errors identify the line and real stage transitions clear outputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
