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
# Насос охлаждения всегда на обычном PID: адаптивная модель "обороты задают скорость
# остывания" для проточного охладителя неверна и раскачивала насос.
require(pump, "pump_regulator.getResultNow()", errors)
for name, text in (("pumppwm.h", pump), ("mode_common.h", mode_common),
                   ("adaptive_pid.h", adaptive_source)):
    if "adaptive_pump" in text or "AdaptivePump" in text or "USE_ADAPTIVE_PID" in text:
        errors.append(f"{name} must not route the cooling pump through adaptive PID")

# Выученный горизонт берётся из профиля при сбросе и сохраняется после подстройки.
# Без регулятора разгон - полная мощность, замер выбега должен отсчитывать сброс от неё.
require(beer, "heater_enable_outputs(SAFETY_HEATER_OUTPUT_MAIN | SAFETY_HEATER_OUTPUT_BOOST);\n"
              "    // Разгон без регулятора - полная мощность: замер выбега отсчитывает сброс от неё.\n"
              "    adaptiveHeaterState.lastOutput = 1.0f;", errors)
require(beer, "adaptive_heater_reset(adaptiveHeaterState, SamSetup.HeaterHorizon);", errors)
require(beer, "if (adaptiveHeaterState.horizonLearned) {\n"
              "    adaptiveHeaterState.horizonLearned = false;\n"
              "    persist_heater_horizon(adaptiveHeaterState.predictionHorizonSeconds);", errors)
samovar_source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
try:
    horizon_persist_body = extract_function_body(
        samovar_source, "void persist_heater_horizon(float horizonSeconds) {")
except ValueError as exc:
    errors.append(str(exc))
    horizon_persist_body = ""

HORIZON_PERSIST_HARNESS = r'''
#include <cstdio>
#include <cstdlib>

enum PersistResult { PERSIST_OK, PERSIST_WRITE_FAILED };
struct SetupEEPROM { float untouched; float HeaterHorizon; };
SetupEEPROM SamSetup{};
int configMux = 0;
#define portENTER_CRITICAL(lock) ((void)(lock))
#define portEXIT_CRITICAL(lock) ((void)(lock))

static PersistResult nextResult = PERSIST_OK;
static int saveCalls = 0;
static SetupEEPROM saved{};
PersistResult save_profile_nvs(const SetupEEPROM& candidate) {
  saveCalls++;
  saved = candidate;
  return nextResult;
}

void persist_heater_horizon(float horizonSeconds) {
@BODY@
}

static void check(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL: %s\n", message);
    std::exit(1);
  }
}

int main() {
  SamSetup = {42.0f, 0.0f};
  persist_heater_horizon(310.0f);
  check(saveCalls == 1 && saved.HeaterHorizon == 310.0f && saved.untouched == 42.0f,
        "learned horizon must be written into the whole profile");
  check(SamSetup.HeaterHorizon == 310.0f, "saved horizon must be applied to SamSetup");
  persist_heater_horizon(310.0f);
  check(saveCalls == 1, "unchanged horizon must not rewrite NVS");
  nextResult = PERSIST_WRITE_FAILED;
  persist_heater_horizon(420.0f);
  check(saveCalls == 2 && SamSetup.HeaterHorizon == 310.0f,
        "failed horizon write must not change SamSetup");
  return 0;
}
'''.replace("@BODY@", horizon_persist_body)

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

// Подход снизу (с target-2) со скоростью ratePerMin до вершины target+overshoot.
static uint32_t drive_to_peak(AdaptiveHeaterState& state, float target, float overshoot,
                              float ratePerMin, uint32_t ms) {
  float temp = target - 2.0f;
  state.lastCommandApplied = true;
  while (temp < target + overshoot) {
    adaptive_heater_step(state, target, target, temp, 4.0f, ms);
    temp += ratePerMin / 60.0f;
    ms += 1000U;
  }
  return ms;
}

// Замер выбега: 3 минуты полной мощности (fullOutput) с ростом ratePerMin, сброс через
// половину (держится halfHoldS секунд на 0.3), затем мощность 0 и выбег на coastDeg по
// экспоненте с начальной скоростью ratePerMin. returnAfterS - мощность возвращается
// на 0.6 через столько секунд выбега; fall - после вершины спад на 0.3 °C, иначе полка.
struct CoastRun {
  float ratePerMin;
  float coastDeg;
  float fullOutput;
  uint32_t halfHoldS;
  uint32_t returnAfterS;
  uint32_t gapAtS;
  uint32_t resetAtS;
  bool fall;
};

static CoastRun coast_run(float ratePerMin, float coastDeg) {
  return {ratePerMin, coastDeg, 1.0f, 0U, 0U, 0U, 0U, true};
}

static void coast_sample(AdaptiveHeaterState& state, float output, float temp, uint32_t& ms) {
  state.lastCommandApplied = true;
  state.lastOutput = output;
  adaptive_heater_track_coast(state, temp, ms);
  ms += 1000U;
}

static float learned_coast(float horizon, const CoastRun& run) {
  AdaptiveHeaterState state{};
  adaptive_heater_reset(state, horizon);
  uint32_t ms = 1000000U;
  float temp = 60.0f;
  for (int second = 0; second < 180; ++second) {
    coast_sample(state, run.fullOutput, temp, ms);
    temp += run.ratePerMin / 60.0f;
  }
  coast_sample(state, 0.4f, temp, ms);
  for (uint32_t second = 0; second < run.halfHoldS; ++second) {
    temp += run.ratePerMin / 60.0f;
    coast_sample(state, 0.3f, temp, ms);
  }
  const float start = temp;
  const float tau = 60.0f * run.coastDeg / run.ratePerMin;
  const uint32_t topS = static_cast<uint32_t>(8.0f * tau);
  for (uint32_t second = 1; second <= topS + 400U; ++second) {
    if (second == run.gapAtS) ms += 10000U;
    if (second == run.resetAtS) adaptive_heater_reset(state, state.predictionHorizonSeconds);
    temp = second < topS ? start + run.coastDeg * (1.0f - std::exp(-(second / tau)))
                         : start + run.coastDeg;
    if (second >= topS && run.fall) temp -= (second - topS) * 0.01f;
    const bool returned = run.returnAfterS != 0U && second >= run.returnAfterS;
    coast_sample(state, returned ? 0.6f : 0.0f, temp, ms);
    if (returned || (run.fall && second >= topS + 30U)) break;
  }
  return state.horizonLearned ? state.predictionHorizonSeconds : -1.0f;
}

int main() {
  AdaptiveHeaterState heater{};
  adaptive_heater_reset(heater, 0.0f);
  AdaptiveHeaterResult heat = adaptive_heater_step(heater, 70.0f, 70.0f, 20.0f, 4.0f, 0);
  check(heat.boost && heat.duty > 0.99f,
        "far heater target must request full power and boost");
  heater.lastCommandApplied = true;
  heat = adaptive_heater_step(heater, 70.0f, 70.0f, 66.0f, 4.0f, 1000);
  check(!heat.boost, "heater boost must stop at four degrees before target");
  heat = adaptive_heater_step(heater, 71.0f, 70.0f, 64.0f, 4.0f, 2000);
  check(!heat.boost, "heater boost must not restart inside the same stage");
  adaptive_heater_reset(heater, 0.0f);
  heat = adaptive_heater_step(heater, 70.0f, 70.0f, 64.0f, 4.0f, 3000);
  check(heat.boost, "new heater stage must allow boost again");

  AdaptiveHeaterState rampHeater{};
  adaptive_heater_reset(rampHeater, 0.0f);
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
  adaptive_heater_reset(flatHeater, 0.0f);
  adaptive_heater_step(flatHeater, 70.0f, 70.0f, 68.0f, 4.0f, 0);
  flatHeater.lastCommandApplied = true;
  const float flatDuty = adaptive_heater_step(flatHeater, 70.0f, 70.0f, 68.0f, 4.0f, 1000).duty;
  AdaptiveHeaterState risingHeater{};
  adaptive_heater_reset(risingHeater, 0.0f);
  adaptive_heater_step(risingHeater, 70.0f, 70.0f, 67.0f, 4.0f, 0);
  risingHeater.lastCommandApplied = true;
  const float risingDuty = adaptive_heater_step(risingHeater, 70.0f, 70.0f, 68.0f, 4.0f, 1000).duty;
  check(risingDuty < flatDuty,
        "heater prediction must reduce power while temperature is rising");

  AdaptiveHeaterState learnedHeater{};
  adaptive_heater_reset(learnedHeater, 0.0f);
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
  adaptive_heater_reset(boostLearningHeater, 0.0f);
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
  adaptive_heater_reset(failedHeater, 0.0f);
  adaptive_heater_step(failedHeater, 70.0f, 70.0f, 68.0f, 4.0f, 0);
  failedHeater.lastCommandApplied = true;
  adaptive_heater_step(failedHeater, 70.0f, 70.0f, 68.2f, 4.0f, 16000);
  failedHeater.powerForOneDegreePerMinute = 1.0f;
  failedHeater.lastCommandApplied = false;
  adaptive_heater_step(failedHeater, 70.0f, 70.0f, 68.3f, 4.0f, 17000);
  check(std::fabs(failedHeater.powerForOneDegreePerMinute - 1.0f) < 0.0001f,
        "failed heater command must block learning of its response");

  AdaptiveHeaterState pausedHeater{};
  adaptive_heater_reset(pausedHeater, 0.0f);
  adaptive_heater_step(pausedHeater, 70.0f, 70.0f, 68.0f, 4.0f, 0);
  pausedHeater.lastCommandApplied = true;
  pausedHeater.integral = 0.2f;
  adaptive_heater_step(pausedHeater, 68.2f, 70.0f, 68.0f, 4.0f, 600000);
  check(std::fabs(pausedHeater.integral - 0.2f) < 0.0001f,
        "long heater pause must not integrate inactive time");
  check(!pausedHeater.boostAllowed,
        "long pause and moving setpoint must preserve the boost latch");

  // Горизонт предсказания учится по выбегу котла после снятия мощности (01.10.2026).
  AdaptiveHeaterState horizonHeater{};
  adaptive_heater_reset(horizonHeater, 0.0f);
  check(std::fabs(horizonHeater.predictionHorizonSeconds - 60.0f) < 0.001f,
        "unlearned horizon must start from sixty seconds");
  adaptive_heater_reset(horizonHeater, 200.0f);
  check(std::fabs(horizonHeater.predictionHorizonSeconds - 200.0f) < 0.001f,
        "stored horizon must be restored on reset");
  adaptive_heater_reset(horizonHeater, 5000.0f);
  check(std::fabs(horizonHeater.predictionHorizonSeconds - 900.0f) < 0.001f,
        "stored horizon must be capped at nine hundred seconds");

  // Горизонт = 1.2 * выбег: подъём после снятия мощности / скорость в середине сброса.
  check(std::fabs(learned_coast(100.0f, coast_run(0.5f, 2.0f)) - 288.0f) < 3.0f,
        "measured horizon must equal 1.2 coast time at start rate");
  CoastRun plateauRun = coast_run(0.25f, 2.0f);
  plateauRun.fall = false;
  check(std::fabs(learned_coast(200.0f, plateauRun) - 576.0f) < 6.0f,
        "coast ending on a five minute plateau must be measured at slow rate");
  check(std::fabs(learned_coast(60.0f, coast_run(0.25f, 3.0f)) - 180.0f) < 0.5f,
        "single coast must lengthen the horizon at most threefold");
  check(std::fabs(learned_coast(600.0f, coast_run(0.5f, 0.5f)) - 200.0f) < 0.5f,
        "single coast must shorten the horizon at most threefold");
  check(learned_coast(290.0f, coast_run(0.5f, 2.0f)) < 0.0f,
        "horizon change under five percent must not be saved");

  CoastRun returnedRun = coast_run(0.5f, 4.0f);
  returnedRun.returnAfterS = 120U;
  check(std::fabs(learned_coast(600.0f, returnedRun) - 480.0f) < 0.5f,
        "power returned on the rise must shorten the horizon by at most a fifth");
  check(learned_coast(60.0f, returnedRun) < 0.0f,
        "power returned on the rise must not lengthen the horizon");
  returnedRun.returnAfterS = 20U;
  check(learned_coast(600.0f, returnedRun) < 0.0f,
        "power returned within a minute is jitter, not a coast");

  CoastRun slowDropRun = coast_run(0.5f, 2.0f);
  slowDropRun.halfHoldS = 360U;
  check(learned_coast(100.0f, slowDropRun) < 0.0f,
        "power drop slower than five minutes must not be measured");
  CoastRun partialRun = coast_run(0.5f, 2.0f);
  partialRun.fullOutput = 0.8f;
  check(learned_coast(100.0f, partialRun) < 0.0f,
        "coast without full power before the drop must not be measured");

  CoastRun rowChangeRun = coast_run(0.5f, 2.0f);
  rowChangeRun.resetAtS = 30U;
  check(std::fabs(learned_coast(100.0f, rowChangeRun) - 288.0f) < 3.0f,
        "coast continuing after a row change must still be learned");
  CoastRun gapRun = coast_run(0.5f, 2.0f);
  gapRun.gapAtS = 30U;
  check(learned_coast(100.0f, gapRun) < 0.0f,
        "coast interrupted by a heater pause must not be learned");

  AdaptiveHeaterState shortHorizon{};
  adaptive_heater_reset(shortHorizon, 15.0f);
  AdaptiveHeaterState longHorizon{};
  adaptive_heater_reset(longHorizon, 600.0f);
  const uint32_t shortMs = drive_to_peak(shortHorizon, 70.0f, -1.0f, 0.5f, 0);
  const uint32_t longMs = drive_to_peak(longHorizon, 70.0f, -1.0f, 0.5f, 0);
  check(adaptive_heater_step(longHorizon, 70.0f, 70.0f, 69.0f, 4.0f, longMs).duty <
        adaptive_heater_step(shortHorizon, 70.0f, 70.0f, 69.0f, 4.0f, shortMs).duty,
        "longer prediction horizon must cut power earlier on the same approach");

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
            "millis wrap compared without signed delta",
            adaptive_source.replace(
                "return static_cast<int32_t>(nowMs - deadlineMs) >= 0;",
                "return nowMs >= deadlineMs;",
                1,
            ),
            "learning deadline must remain pending across millis wrap",
        ),
    )
    mutations += (
        (
            "coast dropped on row change",
            adaptive_source.replace("  state.coast = coast;\n", "  (void)coast;\n", 1),
            "coast continuing after a row change must still be learned",
        ),
        (
            "heater pause ignored by coast",
            adaptive_source.replace(
                "nowMs - coast.lastMs > 5000U", "nowMs - coast.lastMs > 50000U", 1),
            "coast interrupted by a heater pause must not be learned",
        ),
        (
            "prediction on fixed reaction delay",
            adaptive_source.replace(
                "state.filteredRate * state.predictionHorizonSeconds / 60.0f",
                "state.filteredRate * state.reactionDelaySeconds / 60.0f", 1),
            "longer prediction horizon must cut power earlier on the same approach",
        ),
        (
            "coast margin removed",
            adaptive_source.replace("1.2f * 60.0f * (coast.peak", "60.0f * (coast.peak", 1),
            "measured horizon must equal 1.2 coast time at start rate",
        ),
        (
            "plateau never ends coast",
            adaptive_source.replace(
                " || nowMs - coast.peakMs >= 5UL * 60000UL;", ";", 1),
            "coast ending on a five minute plateau must be measured at slow rate",
        ),
        (
            "threefold limit removed",
            adaptive_source.replace(
                "adaptive_pid_clamp(measured, current / 3.0f, current * 3.0f)",
                "adaptive_pid_clamp(measured, ADAPTIVE_HEATER_HORIZON_MIN_S, "
                "ADAPTIVE_HEATER_HORIZON_MAX_S)", 1),
            "single coast must lengthen the horizon at most threefold",
        ),
        (
            "small change saved",
            adaptive_source.replace(
                "if (fabsf(horizon - current) < 0.05f * current) return;",
                "if (horizon == current) return;", 1),
            "horizon change under five percent must not be saved",
        ),
        (
            "returned power shortens without limit",
            adaptive_source.replace(
                "    if (measured < 0.8f * current) measured = 0.8f * current;\n", "", 1),
            "power returned on the rise must shorten the horizon by at most a fifth",
        ),
        (
            "returned power lengthens horizon",
            adaptive_source.replace(
                "nowMs - coast.startMs < 60000U || measured > current",
                "nowMs - coast.startMs < 60000U", 1),
            "power returned on the rise must not lengthen the horizon",
        ),
        (
            "jitter measured as coast",
            adaptive_source.replace(
                "nowMs - coast.startMs < 60000U || measured > current",
                "measured > current", 1),
            "power returned within a minute is jitter, not a coast",
        ),
        (
            "slow drop measured",
            adaptive_source.replace(
                "nowMs - coast.startMs > 5UL * 60000UL", "nowMs - coast.startMs > 50UL * 60000UL", 1),
            "power drop slower than five minutes must not be measured",
        ),
        (
            "partial power arms coast",
            adaptive_source.replace("if (output >= 0.9f &&", "if (output >= 0.7f &&", 1),
            "coast without full power before the drop must not be measured",
        ),
    )
    for name, mutated_header, expected_failure in mutations:
        built, ran = run_adaptive_harness(mutated_header)
        if built.returncode != 0:
            errors.append(f"mutation {name} did not compile:\n{built.stderr}")
        elif ran is None or ran.returncode == 0 or expected_failure not in ran.stderr:
            errors.append(f"mutation {name} was not rejected by {expected_failure}")

    built, ran = run_regulator_harness(HORIZON_PERSIST_HARNESS)
    if built.returncode != 0:
        errors.append("heater horizon persist harness compile failed:\n" + built.stderr)
    elif ran is None or ran.returncode != 0:
        errors.append("heater horizon persist harness failed:\n" + (ran.stderr if ran else "not run"))

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
