#!/usr/bin/env python3
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]


def require(source: str, token: str, errors: list[str]) -> None:
    if token not in source:
        errors.append(f"missing token: {token}")


errors: list[str] = []
config = (ROOT / "Samovar_ini.h").read_text(encoding="utf-8")
beer = (ROOT / "beer.h").read_text(encoding="utf-8")
pump = (ROOT / "pumppwm.h").read_text(encoding="utf-8")
mode_common = (ROOT / "mode_common.h").read_text(encoding="utf-8")
adaptive_source = (ROOT / "adaptive_pid.h").read_text(encoding="utf-8")

require(config, "#define USE_ADAPTIVE_PID 1", errors)
require(beer, "adaptiveHeaterState, setpoint, boostTarget, temp,\n      ACCELERATION_HEATER_DELTA, nowMs", errors)
require(beer, "set_heater_regulator(adaptiveResult.duty, SamSetup.BVolt, &generation)", errors)
require((ROOT / "cheese.h").read_text(encoding="utf-8"),
        "set_heater_state(target, sensor->avgTemp, row.Temp);", errors)
require(beer, "heaterPID.Compute();", errors)
require(pump, "adaptive_pump_step(", errors)
require(pump, "pump_regulator.getResultNow()", errors)
require(mode_common, "SamSetup.SetWaterTemp + 3, WaterSensor.avgTemp, false", errors)

try:
    regulator_body = extract_function_body(
        beer,
        "inline ActuatorCommandResult set_heater_regulator(\n"
        "    double dutyCycle, float maximumTarget, uint64_t* generation)",
    )
except ValueError as exc:
    errors.append(str(exc))
    regulator_body = ""

HARNESS = r'''
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include "adaptive_pid.h"

static void check(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL: %s\n", message);
    std::exit(1);
  }
}

int main() {
  AdaptiveHeaterState heater{};
  adaptive_heater_reset(heater);
  AdaptiveHeaterResult heat = adaptive_heater_step(heater, 70.0f, 70.0f, 20.0f, 4.0f, 0);
  check(heat.boost && heat.duty > 0.99f,
        "far heater target must request full power and boost");
  heater.lastCommandApplied = true;
  heat = adaptive_heater_step(heater, 70.0f, 70.0f, 66.0f, 4.0f, 1000);
  check(!heat.boost, "heater boost must stop at four degrees before target");
  heat = adaptive_heater_step(heater, 71.0f, 70.0f, 64.0f, 4.0f, 2000);
  check(!heat.boost, "heater boost must not restart inside the same stage");
  adaptive_heater_reset(heater);
  heat = adaptive_heater_step(heater, 70.0f, 70.0f, 64.0f, 4.0f, 3000);
  check(heat.boost, "new heater stage must allow boost again");

  AdaptiveHeaterState rampHeater{};
  adaptive_heater_reset(rampHeater);
  heat = adaptive_heater_step(rampHeater, 20.0f, 70.0f, 20.0f, 4.0f, 0);
  check(heat.boost,
        "cheese ramp must compare boost cutoff with the final row target");
  rampHeater.lastCommandApplied = true;
  heat = adaptive_heater_step(rampHeater, 65.0f, 70.0f, 66.0f, 4.0f, 1000);
  check(!heat.boost, "cheese ramp boost must stop four degrees before final target");
  heat = adaptive_heater_step(rampHeater, 66.0f, 70.0f, 64.0f, 4.0f, 2000);
  check(!heat.boost,
        "cheese ramp boost must not restart after falling behind the ramp");

  AdaptiveHeaterState flatHeater{};
  adaptive_heater_reset(flatHeater);
  adaptive_heater_step(flatHeater, 70.0f, 70.0f, 68.0f, 4.0f, 0);
  flatHeater.lastCommandApplied = true;
  const float flatDuty = adaptive_heater_step(flatHeater, 70.0f, 70.0f, 68.0f, 4.0f, 1000).duty;
  AdaptiveHeaterState risingHeater{};
  adaptive_heater_reset(risingHeater);
  adaptive_heater_step(risingHeater, 70.0f, 70.0f, 67.0f, 4.0f, 0);
  risingHeater.lastCommandApplied = true;
  const float risingDuty = adaptive_heater_step(risingHeater, 70.0f, 70.0f, 68.0f, 4.0f, 1000).duty;
  check(risingDuty < flatDuty,
        "heater prediction must reduce power while temperature is rising");

  AdaptiveHeaterState learnedHeater{};
  adaptive_heater_reset(learnedHeater);
  adaptive_heater_step(learnedHeater, 70.0f, 70.0f, 68.0f, 4.0f, 0);
  learnedHeater.lastCommandApplied = true;
  for (int second = 1; second <= 16; ++second) {
    adaptive_heater_step(
        learnedHeater, 70.0f + second * 0.01f, 70.0f,
        68.0f + second * 0.01f,
        4.0f, static_cast<uint32_t>(second) * 1000U);
  }
  check(std::fabs(learnedHeater.powerForOneDegreePerMinute - 1.0f) > 0.0001f,
        "heater must learn observed power per heating rate");

  AdaptiveHeaterState boostLearningHeater{};
  adaptive_heater_reset(boostLearningHeater);
  adaptive_heater_step(boostLearningHeater, 80.0f, 80.0f, 60.0f, 4.0f, 0);
  boostLearningHeater.lastCommandApplied = true;
  boostLearningHeater.learningBlockedUntilMs = 0;
  adaptive_heater_step(boostLearningHeater, 80.0f, 80.0f, 60.1f, 4.0f, 1000);
  check(std::fabs(boostLearningHeater.powerForOneDegreePerMinute - 1.0f) < 0.0001f,
        "heater must not learn while boost is active");
  adaptive_heater_step(boostLearningHeater, 80.0f, 80.0f, 76.0f, 4.0f, 2000);
  for (int second = 3; second <= 16; ++second) {
    adaptive_heater_step(
        boostLearningHeater, 80.0f, 80.0f,
        76.0f + (second - 2) * 0.05f, 4.0f,
        static_cast<uint32_t>(second) * 1000U);
  }
  check(std::fabs(boostLearningHeater.powerForOneDegreePerMinute - 1.0f) < 0.0001f,
        "heater must block learning for fourteen seconds after boost stops");

  AdaptiveHeaterState failedHeater{};
  adaptive_heater_reset(failedHeater);
  adaptive_heater_step(failedHeater, 70.0f, 70.0f, 68.0f, 4.0f, 0);
  failedHeater.lastCommandApplied = true;
  adaptive_heater_step(failedHeater, 70.0f, 70.0f, 68.2f, 4.0f, 16000);
  failedHeater.powerForOneDegreePerMinute = 1.0f;
  failedHeater.lastCommandApplied = false;
  adaptive_heater_step(failedHeater, 70.0f, 70.0f, 68.3f, 4.0f, 17000);
  check(std::fabs(failedHeater.powerForOneDegreePerMinute - 1.0f) < 0.0001f,
        "failed heater command must block learning of its response");

  AdaptiveHeaterState pausedHeater{};
  adaptive_heater_reset(pausedHeater);
  adaptive_heater_step(pausedHeater, 70.0f, 70.0f, 68.0f, 4.0f, 0);
  pausedHeater.lastCommandApplied = true;
  pausedHeater.integral = 0.2f;
  adaptive_heater_step(pausedHeater, 68.2f, 70.0f, 68.0f, 4.0f, 600000);
  check(std::fabs(pausedHeater.integral - 0.2f) < 0.0001f,
        "long heater pause must not integrate inactive time");
  check(!pausedHeater.boostAllowed,
        "long pause and moving setpoint must preserve the boost latch");

  AdaptivePumpState coolPump{};
  adaptive_pump_reset(coolPump, 0.1f);
  const float hotDuty = adaptive_pump_step(
      coolPump, 48.0f, 55.0f, 55.0f, 0.1f, 0, false);
  check(hotDuty > 0.1f, "hot cooling water must increase pump duty");

  AdaptivePumpState coldPump{};
  adaptive_pump_reset(coldPump, 0.1f);
  const float coldDuty = adaptive_pump_step(
      coldPump, 48.0f, 45.0f, 45.0f, 0.1f, 0, false);
  check(std::fabs(coldDuty - 0.1f) < 0.0001f,
        "pump output must respect configured minimum duty");

  AdaptivePumpState flatPump{};
  adaptive_pump_reset(flatPump, 0.1f);
  adaptive_pump_step(flatPump, 48.0f, 49.0f, 49.0f, 0.1f, 0, false);
  const float flatPumpDuty = adaptive_pump_step(
      flatPump, 48.0f, 50.0f, 49.0f, 0.1f, 1000, false);
  AdaptivePumpState risingPump{};
  adaptive_pump_reset(risingPump, 0.1f);
  adaptive_pump_step(risingPump, 48.0f, 49.0f, 49.0f, 0.1f, 0, false);
  const float risingPumpDuty = adaptive_pump_step(
      risingPump, 48.0f, 50.0f, 50.0f, 0.1f, 1000, false);
  check(risingPumpDuty > flatPumpDuty,
        "pump prediction must react more strongly to rising water temperature");

  AdaptivePumpState learningPump{};
  adaptive_pump_reset(learningPump, 0.1f);
  adaptive_pump_step(learningPump, 48.0f, 55.0f, 55.0f, 0.1f, 0, false);
  adaptive_pump_note_command(learningPump, 0, false);
  for (int second = 1; second <= 9; ++second) {
    adaptive_pump_step(
        learningPump, 48.0f, 55.0f - second * 0.05f,
        55.0f - second * 0.05f, 0.1f,
        static_cast<uint32_t>(second) * 1000U, true);
    adaptive_pump_note_command(
        learningPump, static_cast<uint32_t>(second) * 1000U, true);
  }
  check(std::fabs(learningPump.dutyForOneDegreePerMinute - 0.35f) > 0.0001f,
        "pump must learn when stable operation allows learning");

  AdaptivePumpState blockedLearningPump{};
  adaptive_pump_reset(blockedLearningPump, 0.1f);
  adaptive_pump_step(blockedLearningPump, 48.0f, 55.0f, 55.0f, 0.1f, 0, false);
  adaptive_pump_note_command(blockedLearningPump, 0, false);
  for (int second = 1; second <= 7; ++second) {
    adaptive_pump_step(
        blockedLearningPump, 48.0f, 55.0f - second * 0.05f,
        55.0f - second * 0.05f, 0.1f,
        static_cast<uint32_t>(second) * 1000U, true);
    adaptive_pump_note_command(
        blockedLearningPump, static_cast<uint32_t>(second) * 1000U, true);
  }
  check(std::fabs(blockedLearningPump.dutyForOneDegreePerMinute - 0.35f) < 0.0001f,
        "pump must block delayed startup or ACP response for eight seconds");

  AdaptivePumpState afterOverridePump{};
  adaptive_pump_reset(afterOverridePump, 0.1f);
  adaptive_pump_step(afterOverridePump, 48.0f, 55.0f, 55.0f, 0.1f, 0, true);
  adaptive_pump_note_command(afterOverridePump, 0, false);
  adaptive_pump_step(afterOverridePump, 48.0f, 54.95f, 54.95f, 0.1f, 1000, true);
  adaptive_pump_note_command(afterOverridePump, 1000, true);
  check(std::fabs(afterOverridePump.dutyForOneDegreePerMinute - 0.35f) < 0.0001f,
        "failed pump command must block learning of its delayed response");

  AdaptivePumpState pausedPump{};
  adaptive_pump_reset(pausedPump, 0.1f);
  adaptive_pump_step(pausedPump, 48.0f, 49.0f, 49.0f, 0.1f, 0, false);
  pausedPump.integral = 0.2f;
  adaptive_pump_step(pausedPump, 48.0f, 49.0f, 49.0f, 0.1f, 600000, true);
  check(std::fabs(pausedPump.integral - 0.2f) < 0.0001f,
        "long pump pause must not integrate inactive time");
  check(std::fabs(pausedPump.filteredRate) < 0.0001f,
        "long pump pause must discard the stale cooling rate");

  const uint32_t nearWrap = 0xFFFFFFFFU - 1000U;
  const uint32_t wrappedDeadline = nearWrap + 8000U;
  check(!adaptive_pid_deadline_reached(nearWrap, wrappedDeadline),
        "learning deadline must remain pending across millis wrap");
  check(adaptive_pid_deadline_reached(nearWrap + 8000U, wrappedDeadline),
        "learning deadline must expire across millis wrap");
  return 0;
}
'''

REGULATOR_HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

enum ActuatorCommandResult {
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_FAILED
};

struct SetupStub { float StbVoltage; } SamSetup = {100.0f};
static float capturedTarget = -1.0f;

template <typename T>
T constrain(T value, T low, T high) {
  return value < low ? low : (value > high ? high : value);
}

void setHeaterPosition(bool) {}
void set_heater_state_flag(bool) {}
bool current_power_mode_is(int) { return false; }
void check_power_error() {}
ActuatorCommandResult set_current_power(float target, uint64_t* generation) {
  capturedTarget = target;
  if (generation != nullptr) *generation = 17;
  return ACTUATOR_COMMAND_APPLIED;
}

const int POWER_SLEEP_MODE = 0;

inline ActuatorCommandResult set_heater_regulator(
    double dutyCycle, float maximumTarget, uint64_t* generation) {
@REGULATOR_BODY@
}

int main() {
  uint64_t generation = 0;
  const ActuatorCommandResult result = set_heater_regulator(0.25, 230.0f, &generation);
#ifdef SAMOVAR_USE_SEM_AVR
  const float expected = 57.5f;
#else
  const float expected = 115.0f;
#endif
  if (result != ACTUATOR_COMMAND_APPLIED || generation != 17 ||
      std::fabs(capturedTarget - expected) > 0.001f) {
    std::fprintf(stderr, "FAIL: adaptive heater must scale from BVolt: target=%f\n",
                 capturedTarget);
    return 1;
  }
  return 0;
}
'''.replace("@REGULATOR_BODY@", regulator_body)


def run_adaptive_harness(header_source: str | None = None) -> tuple[subprocess.CompletedProcess, subprocess.CompletedProcess | None]:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        source = temp_path / "adaptive_pid_test.cpp"
        binary = temp_path / "adaptive_pid_test"
        source.write_text(HARNESS, encoding="utf-8")
        include_paths = ["-I", str(ROOT)]
        if header_source is not None:
            (temp_path / "adaptive_pid.h").write_text(header_source, encoding="utf-8")
            include_paths = ["-I", str(temp_path), "-I", str(ROOT)]
        built = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
             *include_paths, str(source), "-o", str(binary)],
            text=True, capture_output=True,
        )
        if built.returncode != 0:
            return built, None
        return built, subprocess.run([str(binary)], text=True, capture_output=True)


def run_regulator_harness(source_text: str, sem_enabled: bool = False) -> tuple[subprocess.CompletedProcess, subprocess.CompletedProcess | None]:
    with tempfile.TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / "heater_regulator_test.cpp"
        binary = Path(temp_dir) / "heater_regulator_test"
        source.write_text(source_text, encoding="utf-8")
        command = [
            "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
            str(source), "-o", str(binary),
        ]
        if sem_enabled:
            command.insert(1, "-DSAMOVAR_USE_SEM_AVR")
        built = subprocess.run(command, text=True, capture_output=True)
        if built.returncode != 0:
            return built, None
        return built, subprocess.run([str(binary)], text=True, capture_output=True)

if not errors:
    built, ran = run_adaptive_harness()
    if built.returncode != 0:
        errors.append("adaptive PID harness compile failed:\n" + built.stderr)
    elif ran is None or ran.returncode != 0:
        errors.append("adaptive PID harness failed:\n" + (ran.stderr if ran else "not run"))

    boost_learning_mutation = adaptive_source.replace(
        "if (!state.lastCommandApplied || state.boostActive) {",
        "if (!state.lastCommandApplied) {",
        1,
    ).replace(
        "if (state.lastCommandApplied && !state.boostActive &&",
        "if (state.lastCommandApplied &&",
        1,
    )
    failed_heater_mutation = adaptive_source.replace(
        "if (!state.lastCommandApplied || state.boostActive) {",
        "if (state.boostActive) {",
        1,
    ).replace(
        "if (state.lastCommandApplied && !state.boostActive &&",
        "if (!state.boostActive &&",
        1,
    )
    pump_gap_prefix, pump_gap_suffix = adaptive_source.rsplit(
        "if (elapsedMs > 5000U) {", 1)
    pump_gap_mutation = pump_gap_prefix + "if (false) {" + pump_gap_suffix
    mutations = (
        (
            "boost target replaced by moving setpoint",
            adaptive_source.replace(
                "const float actualError = boostTarget - temp;",
                "(void)boostTarget;\n  const float actualError = setpoint - temp;",
                1,
            ),
            "cheese ramp must compare boost cutoff with the final row target",
        ),
        (
            "long gap integrated",
            adaptive_source.replace("if (elapsedMs > 5000U) {", "if (false) {", 1),
            "long heater pause must not integrate inactive time",
        ),
        (
            "boost response learned",
            boost_learning_mutation,
            "heater must not learn while boost is active",
        ),
        (
            "boost cooldown removed",
            adaptive_source.replace(
                "if (!state.lastCommandApplied || state.boostActive) {",
                "if (!state.lastCommandApplied) {",
                1,
            ),
            "heater must block learning for fourteen seconds after boost stops",
        ),
        (
            "failed heater command learned",
            failed_heater_mutation,
            "failed heater command must block learning of its response",
        ),
        (
            "pump reaction delay ignored",
            adaptive_source.replace(
                "if (learningAllowed && state.lastCommandLearnable &&\n"
                "        adaptive_pid_deadline_reached(nowMs, state.learningBlockedUntilMs) &&",
                "if (learningAllowed && state.lastCommandLearnable &&",
                1,
            ),
            "pump must block delayed startup or ACP response for eight seconds",
        ),
        (
            "long pump gap integrated",
            pump_gap_mutation,
            "long pump pause must not integrate inactive time",
        ),
        (
            "millis wrap compared without signed delta",
            adaptive_source.replace(
                "return static_cast<int32_t>(nowMs - deadlineMs) >= 0;",
                "return nowMs >= deadlineMs;",
                1,
            ),
            "learning deadline must remain pending across millis wrap",
        ),
    )
    for name, mutated_header, expected_failure in mutations:
        built, ran = run_adaptive_harness(mutated_header)
        if built.returncode != 0:
            errors.append(f"mutation {name} did not compile:\n{built.stderr}")
        elif ran is None or ran.returncode == 0 or expected_failure not in ran.stderr:
            errors.append(f"mutation {name} was not rejected by {expected_failure}")

    for sem_enabled in (False, True):
        built, ran = run_regulator_harness(REGULATOR_HARNESS, sem_enabled)
        if built.returncode != 0:
            errors.append("heater regulator harness compile failed:\n" + built.stderr)
        elif ran is None or ran.returncode != 0:
            errors.append("heater regulator harness failed:\n" + (ran.stderr if ran else "not run"))

    regulator_mutation = REGULATOR_HARNESS.replace(
        "maximumTarget * sqrtf", "SamSetup.StbVoltage * sqrtf", 1)
    built, ran = run_regulator_harness(regulator_mutation)
    if built.returncode != 0:
        errors.append("regulator scale mutation did not compile:\n" + built.stderr)
    elif ran is None or ran.returncode == 0 or "must scale from BVolt" not in ran.stderr:
        errors.append("regulator scale mutation was not rejected")

if errors:
    print("adaptive PID smoke failed:")
    for error in errors:
        print(f" - {error}")
    raise SystemExit(1)

print("adaptive PID smoke passed")
