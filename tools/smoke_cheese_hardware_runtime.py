#!/usr/bin/env python3
"""Compiled, source-derived hardware decisions of universal Cheese operations."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "cheese.h").read_text(encoding="utf-8")


def body(signature: str) -> str:
    return extract_function_body(SOURCE, signature, strip_comments=False)


def run(source: str, label: str, expect_success: bool = True) -> None:
    with tempfile.TemporaryDirectory(prefix="samovar-cheese-hw-") as tmp:
        path = Path(tmp)
        cpp = path / "test.cpp"
        binary = path / "test"
        cpp.write_text(source, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if compiled.returncode != 0:
            raise AssertionError(f"{label} compile failed\n{compiled.stderr}")
        completed = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        passed = completed.returncode == 0
        if passed != expect_success:
            raise AssertionError(f"{label} failed\n{completed.stdout}{completed.stderr}")


MIXER = r'''
#include <cmath>
#include <cstdint>
#include <iostream>
using std::isfinite;
struct WProgram { uint8_t capacity_num; float Speed; uint16_t Volume; };
struct Setup { bool rele2; } SamSetup = {true};
struct Runtime { uint8_t mixerDevice; bool mixerRunning; } cheeseRuntime = {};
bool mixer_status = false;
int relayWrites = 0; bool relayState = false; void digitalWrite(int, bool state) { ++relayWrites; relayState = state; }
#define RELE_CHANNEL2 2
bool i2cPresent = true; bool i2cOk = true; int i2cCalls = 0; uint16_t i2cSpeed = 0; bool i2cDirection = false;
bool i2c_stepper_mixer_present() { return i2cPresent; }
bool set_stepper_by_time(uint16_t speed, bool direction, uint16_t) { ++i2cCalls; i2cSpeed = speed; i2cDirection = direction; return i2cOk; }
inline bool cheese_mixer_start(const WProgram& row) { @START@ }
inline bool cheese_mixer_stop() { @STOP@ }
int failures = 0; void check(bool value, const char* text) { if (!value) { std::cerr << text << '\n'; ++failures; } }
int main() {
  WProgram relay = {1, 0.0f, 0}; cheeseRuntime.mixerDevice = 1;
  check(cheese_mixer_start(relay) && mixer_status && relayState, "relay mixer did not publish common state");
  check(cheese_mixer_stop() && !mixer_status && !relayState, "relay mixer stop did not publish common state");
  WProgram i2c = {2, -17.0f, 12}; cheeseRuntime.mixerDevice = 2;
  check(cheese_mixer_start(i2c) && mixer_status && i2cSpeed == 17 && i2cDirection, "I2C mixer direction or speed changed");
  i2cOk = false;
  check(!cheese_mixer_stop() && mixer_status, "failed I2C stop falsely changed common state");
  return failures;
}
'''


DOSER = r'''
#include <cmath>
#include <cstdint>
#include <climits>
#include <iostream>
using std::isfinite;
struct WProgram { float Temp; float Param; };
struct Setup { uint16_t StepperStepMl; } SamSetup = {4};
struct Runtime { bool doserStarted; } cheeseRuntime = {};
unsigned int TargetStepps = 0; bool StepperMoving = false;
int stopCalls = 0, startCalls = 0; void stopService() { ++stopCalls; } void startService() { ++startCalls; }
void stepper_safe_stop_reset() {} void stepper_safe_reverse(bool) {}
float motionSpeed = 0; int32_t motionTarget = 0;
void stepper_safe_set_motion(float speed, int32_t, int32_t target) { motionSpeed = speed; motionTarget = target; }
struct Stepper { void enable() {} } stepper;
#define STEPPER_REVERSE
inline bool cheese_local_doser_motion(const WProgram& row,
                                      uint32_t& targetSteps, float& speed) { @MOTION@ }
inline bool cheese_start_local_doser(const WProgram& row) { @DOSE@ }
int failures = 0; void check(bool value, const char* text) { if (!value) { std::cerr << text << '\n'; ++failures; } }
int main() {
  check(!cheese_start_local_doser({0.24f, 60.0f}), "fractional dose below one step was accepted");
  check(cheese_start_local_doser({2.5f, 60.0f}), "valid local dose was rejected");
  check(TargetStepps == 10 && motionTarget == 10 && motionSpeed == 4.0f && cheeseRuntime.doserStarted,
        "local dose ml-to-steps or rate conversion changed");
  check(!cheese_start_local_doser({2.5f, 0.0f}), "zero local dose speed was accepted");
  return failures;
}
'''


COOLING = r'''
#include <cstdint>
#include <iostream>
enum ActuatorCommandResult { ACTUATOR_COMMAND_APPLIED, ACTUATOR_COMMAND_FAILED };
bool valve = false; int valveCalls = 0; int secondWrites = 0; bool second = false; int pumpCalls = 0; float pumpDuty = -1;
ActuatorCommandResult beer_set_cooling_outputs(bool active) { valve = active; ++valveCalls; return ACTUATOR_COMMAND_APPLIED; }
ActuatorCommandResult set_pump_pwm(float duty) { ++pumpCalls; pumpDuty = duty; return ACTUATOR_COMMAND_APPLIED; }
ActuatorCommandResult open_valve(bool active, bool) { valve = active; ++valveCalls; return ACTUATOR_COMMAND_APPLIED; }
void digitalWrite(int, bool value) { ++secondWrites; second = value; }
#define WATER_PUMP_PIN 7
#define PWM_LOW_VALUE 40
#define LOW 0
inline bool cheese_set_cooling_outputs(bool active, bool highFlow) { @COOL@ }
int failures = 0; void check(bool value, const char* text) { if (!value) { std::cerr << text << '\n'; ++failures; } }
int main() {
  check(cheese_set_cooling_outputs(true, true) && valve, "full cooling flow was rejected");
#ifdef USE_WATER_PUMP
  check(cheese_set_cooling_outputs(true, false) && pumpDuty == 400, "pump near-target flow was not reduced");
  check(cheese_set_cooling_outputs(false, false) && !valve, "pump cooling did not stop");
#else
  check(cheese_set_cooling_outputs(true, false) && !second, "valve near-target flow did not close boost valve");
  check(cheese_set_cooling_outputs(true, true) && second, "valve full flow did not open boost valve");
  check(cheese_set_cooling_outputs(false, false) && !valve && !second, "valve cooling did not close both outputs");
#endif
  return failures;
}
'''


def main() -> int:
    try:
        mixer = MIXER.replace("@START@", body("inline bool cheese_mixer_start(const WProgram& row)"))
        mixer = mixer.replace("@STOP@", body("inline bool cheese_mixer_stop()"))
        run(mixer, "relay and I2C mixer")
        mixer_mutant = mixer.replace(
            "mixer_status = cheeseRuntime.mixerRunning;", "mixer_status = false;", 1
        )
        run(mixer_mutant, "relay/I2C mixer state mutation", False)
        motion_body = body("inline bool cheese_local_doser_motion(const WProgram& row,")
        dose_body = body("inline bool cheese_start_local_doser(const WProgram& row)")
        doser = DOSER.replace("@MOTION@", motion_body).replace("@DOSE@", dose_body)
        run(doser, "local dose")
        motion_mutant = motion_body.replace("if (targetSteps < 1) return false;", "if (false) return false;", 1)
        if motion_mutant == motion_body:
            raise AssertionError("local dose mutation anchor missing")
        run(DOSER.replace("@MOTION@", motion_mutant).replace("@DOSE@", dose_body),
            "local dose minimum-step mutation", False)
        cooling_body = body("inline bool cheese_set_cooling_outputs(bool active, bool highFlow)")
        run("#define USE_WATER_PUMP\n" + COOLING.replace("@COOL@", cooling_body), "PWM cooling")
        run("#define USE_WATER_VALVE 1\n" + COOLING.replace("@COOL@", cooling_body), "two-valve cooling")
        pump_mutant = cooling_body.replace(
            "set_pump_pwm(PWM_LOW_VALUE * 10)", "set_pump_pwm(0)", 1
        )
        valve_mutant = cooling_body.replace(
            "highFlow ? USE_WATER_VALVE : !USE_WATER_VALVE",
            "highFlow ? !USE_WATER_VALVE : !USE_WATER_VALVE", 1,
        )
        if pump_mutant == cooling_body or valve_mutant == cooling_body:
            raise AssertionError("cooling mutation anchor missing")
        run("#define USE_WATER_PUMP\n" + COOLING.replace("@COOL@", pump_mutant),
            "PWM cooling flow mutation", False)
        run("#define USE_WATER_VALVE 1\n" + COOLING.replace("@COOL@", valve_mutant),
            "two-valve cooling flow mutation", False)
    except (AssertionError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("OK: Cheese relay/I2C mixer, local D, and both cooling builds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
