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
struct Setup { bool rele2; bool rele4; uint16_t StepperStepMl; } SamSetup = {true, true, 4};
struct Runtime { uint8_t mixerDevice; bool mixerRunning; bool mixerOneShotComplete; uint32_t mixerDeadlineMs; bool doserStarted; bool doserCompleted; bool drainOpen; uint32_t enteredMs; uint32_t lastTickMs; float heatStartSetpoint; } cheeseRuntime = {};
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
void request_emergency_stop(const String&) { trace.push_back("emergency"); }
const char* cheese_stage_name(char) { return "stage"; }
void SendMsg(const String&, int) {}
inline void cheese_set_drain(bool open) { @DRAIN@ }
inline bool cheese_mixer_start(const WProgram& row) { @MIXER_START@ }
inline bool cheese_mixer_stop() { @MIXER_STOP@ }
inline bool cheese_configure_mixer(const WProgram& row, uint32_t nowMs) { @MIXER_CONFIGURE@ }
inline bool cheese_set_cooling_outputs(bool active, bool highFlow) { @COOLING@ }
inline bool cheese_local_doser_motion(const WProgram& row,
                                      uint32_t& targetSteps, float& speed) { @LOCAL_MOTION@ }
inline bool cheese_start_local_doser(const WProgram& row) { @LOCAL_DOSE@ }
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
    print("OK: Cheese errors identify the line and real stage transitions clear outputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
