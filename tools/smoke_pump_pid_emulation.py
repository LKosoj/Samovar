#!/usr/bin/env python3
"""Эмуляция насоса с настоящим GyverPID и кодом прошивки.

Тепловая модель условная: вода 20 °C, нелинейный поток у нижнего ШИМ,
теплоёмкость 2500 Дж/К, задержка потока 4 с и ступень тепла 600 -> 1200 Вт.
Это проверка алгоритма, а не подбор коэффициентов под физический насос.
"""
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import I18N_INCLUDE, extract_function_body

ROOT = Path(__file__).resolve().parents[1]
pwm = (ROOT / "pumppwm.h").read_text()
common = (ROOT / "mode_common.h").read_text()
selftest = (ROOT / "selftest.h").read_text()

HARNESS = I18N_INCLUDE + r'''
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <GyverPID.h>
#include "safety_transition.h"
#define USE_WATER_PUMP
uint32_t nowMs = 0;
struct Setup { float SetWaterTemp = 48; float StepperStepMl = 100; } SamSetup;
struct Sensor { float avgTemp = 20; } WaterSensor, ACPSensor;
bool PowerOn = true, valve_status = true, is_self_test = false;
bool pump_started = false, mode_switch_barrier_active = false;
int8_t wp_count = 0;
float water_pump_speed = 0;
GyverPID pump_regulator(6.5, 0.3, 30, 1023);
struct Pwm {
  uint32_t last = 0;
  int writes = 0;
  void write(uint32_t duty) { last = duty; writes++; }
} pump_pwm;
static void check(bool ok, const char* message) {
  if (!ok) { std::fprintf(stderr, "FAIL: %s\n", message); std::exit(1); }
}
ActuatorCommandResult set_pump_pwm(float duty) { @PWM@ }
inline float pump_pid_soften_factor(float pwm) { @FACTOR@ }
void set_pump_speed_pid(float temp, bool soften = true) { @PID@ }
bool mode_acp_above_boost_threshold(float threshold) { return ACPSensor.avgTemp > threshold; }
int warnings = 0;
void mode_warn_acp_hot_once(bool hot, float) { if (hot) warnings++; }
inline bool mode_water_rising_fast() { @RISE@ }
inline void mode_update_water_pump_pid(float acpBoostThreshold) { @UPDATE@ }

// Зависимости самотеста: время настоящее для алгоритма, аппаратура заменена состоянием.
static SafetyTransition selfTestTransition = {SAFETY_TRANSITION_IDLE, 0};
static bool selfTestCompleted = false;
static uint64_t selfTestOwnerGeneration = 0;
static uint32_t selfTestPumpTickMs = 0;
bool ownerValid = true;
bool mode_switch_in_progress() { return mode_switch_barrier_active; }
bool samovar_process_active() { return PowerOn; }
bool safety_owner_generation_acquire(uint64_t& generation) {
  if (!ownerValid) return false;
  generation = 1;
  return true;
}
bool safety_owner_generation_valid(uint64_t generation) { return ownerValid && generation == 1; }
void safety_owner_generation_release(uint64_t& generation) { generation = 0; }
bool heater_power_on() { return PowerOn; }
void set_power(bool on, bool) { PowerOn = on; }
void open_valve(bool on, bool) { valve_status = on; }
int capacity_num = 0;
void set_capacity(int n) { capacity_num = n; }
void next_capacity() { capacity_num++; }
bool serviceRunning = false;
void stopService() { serviceRunning = false; }
void startService() { serviceRunning = true; }
void reset_sensor_counter() {}
enum { NOTIFY_MSG, WARNING_MSG };
void SendMsg(const char*, int) {}
float get_speed_from_rate(float rate) { return rate * SamSetup.StepperStepMl; }
float TargetStepps = 0;
void stepper_safe_set_max_speed(float) {}
void stepper_safe_set_current(float) {}
void stepper_safe_set_target(float) {}
inline void finish_self_test_now(bool completed) { @FINISH@ }
inline bool abort_self_test_if_owner_lost() { @ABORT@ }
inline void start_self_test() { @START@ }
inline void tick_self_test() { @TICK@ }
inline void stop_self_test() { @STOP@ }

void reset(float setpoint, float temperature) {
  PowerOn = false;
  mode_water_rising_fast();
  PowerOn = true;
  valve_status = true;
  is_self_test = false;
  ownerValid = true;
  mode_switch_barrier_active = false;
  pump_started = false;
  wp_count = 0;
  water_pump_speed = 0;
  pump_pwm = Pwm{};
  SamSetup.SetWaterTemp = setpoint;
  WaterSensor.avgTemp = temperature;
  ACPSensor.avgTemp = 20;
  pump_regulator = GyverPID(6.5, 0.3, 30, 1023);
  pump_regulator.setDirection(REVERSE);
  pump_regulator.setLimits(PWM_LOW_VALUE * 10, 1023);
  safety_transition_cancel(selfTestTransition);
  selfTestOwnerGeneration = 0;
  nowMs = 0;
}
void control(float temp) {
  nowMs += 1000;
  WaterSensor.avgTemp = temp;
  mode_update_water_pump_pid(45);
  check(std::isfinite(water_pump_speed), "PWM must stay finite");
}
void constant_water() {
  for (float target : {48.0f, 55.0f}) {
    reset(target, 20);
    for (int i = 0; i < 120; i++) {
      control(20);
      check(pump_regulator.input == 20, "constant water must not become artificial temperature");
      if (i >= 12) check(water_pump_speed == PWM_LOW_VALUE * 10,
                        "cold water must not pulse after soft start");
    }
    std::printf("constant %.0f C target: PWM %.0f, no pulses\n", target, water_pump_speed);
  }
}
void thermal_step() {
  reset(48, 48);
  // Начальное состояние уже работающего насоса; интеграл соответствует исходному теплу.
  pump_started = true;
  wp_count = 10;
  pump_regulator.integral = water_pump_speed = 120;
  float temp = 48, flow = std::sqrt(120.0f / 1023 - 0.055f);
  float maxStepTemp = 0, minSteady = 100, maxSteady = 0;
  float initialPwm = 0, minPwm = 1023, maxPwm = 0;
  for (int i = 0; i < 3600; i++) {
    float noise = (i % 2 ? 0.05f : -0.05f);
    control(temp + noise);
    check(pump_regulator.input == WaterSensor.avgTemp,
          "sensor noise must not be amplified by input substitution");
    float nextFlow = std::sqrt(std::max(0.0f, water_pump_speed / 1023 - 0.055f));
    flow += (nextFlow - flow) / 4;
    temp += ((i < 1800 ? 600.0f : 1200.0f) - 120 * flow * (temp - 20)) / 2500;
    if (i >= 1600 && i < 1800) initialPwm += water_pump_speed / 200;
    if (i >= 1800) maxStepTemp = std::max(maxStepTemp, temp);
    if (i >= 3400) {
      minSteady = std::min(minSteady, temp); maxSteady = std::max(maxSteady, temp);
      minPwm = std::min(minPwm, water_pump_speed); maxPwm = std::max(maxPwm, water_pump_speed);
    }
  }
  std::printf("thermal 600->1200 W: peak %.2f C, final %.2f..%.2f C, PWM %.1f->%.1f\n",
              maxStepTemp, minSteady, maxSteady, initialPwm, water_pump_speed);
  std::printf("steady PWM with +/-0.05 C noise: %.1f..%.1f\n", minPwm, maxPwm);
  check(maxPwm - minPwm < 15, "small sensor noise must not cause large steady PWM pulses");
  check(minSteady > 47 && maxSteady < 49, "thermal step must settle around the water setpoint");
  check(water_pump_speed > initialPwm + 30, "increased heat must increase cooling");
}
void rapid_rise() {
  for (float target : {40.0f, 55.0f}) {
    reset(target, target - 2);
    pump_started = true;
    wp_count = 10;
    water_pump_speed = PWM_LOW_VALUE * 10;
    for (int i = 0; i <= 5; i++) control(target - 2 + i * 0.3f);
    check(pump_regulator.Kp == 6.5f && pump_regulator.Ki == 0.3f && pump_regulator.Kd == 30,
          "rapid water rise must restore full coefficients");
    control(target - 0.7f);
    check(pump_regulator.Kp == 6.5f && pump_regulator.Kd == 30,
          "single falling sample must keep full coefficients");
    for (int i = 0; i < 4; i++) control(target - 0.3f);
    check(pump_regulator.Kp == 6.5f && pump_regulator.Kd == 30,
          "slower water rise must keep full coefficients");
    for (int i = 0; i < 5; i++) control(target - 0.5f);
    check(pump_regulator.Kp < 6.5f && pump_regulator.Kd < 30,
          "falling water window must restore softened coefficients");
    ACPSensor.avgTemp = 65;
    control(target - 1);
    check(pump_regulator.input == target + 3 && pump_regulator.Kd == 30,
          "hot ACP must keep its full-coefficient substitute");
  }
}
void self_test(uint32_t startTime, bool manualStop, bool loseOwner) {
  reset(48, 20);
  PowerOn = false;
  nowMs = startTime;
  start_self_test();
  tick_self_test();
  check(is_self_test && serviceRunning && valve_status, "self-test must start its actuators");
  check(water_pump_speed == PWM_START_VALUE * 10, "self-test must start at configured start PWM");
  for (int i = 1; i <= 260; i++) {
    nowMs += 100;
    WaterSensor.avgTemp = (i % 2 ? 20 : 55);
    ACPSensor.avgTemp = (i % 2 ? 20 : 70);
    mode_update_water_pump_pid(45);
    tick_self_test();
    check(is_self_test, "self-test must remain active until its hold expires");
    float expected = i < 110 ? PWM_START_VALUE * 10 : (PWM_START_VALUE + 20) * 10;
    check(water_pump_speed == expected, "self-test must keep its PWM despite water/ACP changes");
  }
  check(warnings > 0, "ACP warning must continue during self-test");
  if (loseOwner) { ownerValid = false; tick_self_test(); }
  else if (manualStop) stop_self_test();
  else { nowMs += 2000; tick_self_test(); }
  check(!is_self_test && !pump_started && water_pump_speed == 0 && !valve_status && !serviceRunning,
        "self-test finish/stop/owner loss must stop its actuators");
  std::printf("self-test: start %d, target %d, stop 0 (%s)\n",
              PWM_START_VALUE * 10, (PWM_START_VALUE + 20) * 10,
              loseOwner ? "owner lost" : manualStop ? "manual" : "completed");
}
int main() {
  constant_water();
  thermal_step();
  rapid_rise();
  self_test(1000, false, false);
  self_test(UINT32_MAX - 2000u, true, false);
  self_test(1000, false, true);
}
'''

bodies = {
    "@PWM@": extract_function_body(pwm, "ActuatorCommandResult set_pump_pwm(float duty)"),
    "@FACTOR@": extract_function_body(pwm, "inline float pump_pid_soften_factor(float pwm)"),
    "@PID@": extract_function_body(pwm, "void set_pump_speed_pid(float temp, bool soften)"),
    "@RISE@": extract_function_body(common, "inline bool mode_water_rising_fast()"),
    "@UPDATE@": extract_function_body(common, "inline void mode_update_water_pump_pid(float acpBoostThreshold)"),
}
for token, signature in (
    ("@FINISH@", "inline void finish_self_test_now(bool completed)"),
    ("@ABORT@", "inline bool abort_self_test_if_owner_lost()"),
    ("@START@", "inline void start_self_test(void)"),
    ("@TICK@", "inline void tick_self_test(void)"),
    ("@STOP@", "inline void stop_self_test(void)"),
):
    bodies[token] = extract_function_body(selftest, signature)
harness = HARNESS
for token, body in bodies.items():
    harness = harness.replace(token, body)


def run(source, low, start):
    with tempfile.TemporaryDirectory(prefix="samovar-pump-emulation-") as directory:
        base = Path(directory)
        (base / "Arduino.h").write_text(
            "#pragma once\n#include <cstdint>\nextern uint32_t nowMs;\n"
            "inline uint32_t millis() { return nowMs; }\n"
            "#define constrain(v, lo, hi) ((v)<(lo)?(lo):((v)>(hi)?(hi):(v)))\n"
        )
        cpp = base / "test.cpp"
        cpp.write_text(source)
        built = subprocess.run([
            "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
            f"-DPWM_LOW_VALUE={low}", f"-DPWM_START_VALUE={start}",
            "-I" + directory, "-I" + str(ROOT), "-I" + str(ROOT / "libraries/GyverPID/src"),
            str(cpp), "-o", str(base / "test"),
        ], capture_output=True, text=True)
        if built.returncode:
            raise SystemExit(built.stderr)
        return subprocess.run([str(base / "test")], capture_output=True, text=True)


for low, start in ((6, 20), (10, 40)):
    result = run(harness, low, start)
    print(f"PWM_LOW_VALUE={low}, PWM_START_VALUE={start}\n{result.stdout}", end="")
    if result.returncode:
        raise SystemExit(result.stderr)

# Возврат старой подмены и удаление отдельных частей самотеста должны падать по assert.
for name, old, new, expected in (
    ("input substitution", "pump_regulator.input = temp;",
     "pump_regulator.input = SamSetup.SetWaterTemp + (temp - SamSetup.SetWaterTemp) * pump_pid_soften_factor(water_pump_speed);",
     "constant water must not become artificial temperature"),
    ("PID interferes with self-test", "!valve_status || is_self_test", "!valve_status",
     "self-test must keep its PWM"),
    ("self-test startup never finishes", "selfTestPumpTickMs) >= 1000", "selfTestPumpTickMs) >= 60000",
     "self-test must keep its PWM"),
    ("self-test startup runs each loop", "selfTestPumpTickMs) >= 1000", "selfTestPumpTickMs) >= 1",
     "self-test must keep its PWM"),
):
    if harness.count(old) != 1:
        raise SystemExit(f"FAIL: mutation token not unique: {name}")
    result = run(harness.replace(old, new), 6, 20)
    if result.returncode == 0 or expected not in result.stderr:
        raise SystemExit(f"FAIL: mutation {name} missed expected assert: {result.stderr}")
print("pump PID emulation and mutation checks passed")
