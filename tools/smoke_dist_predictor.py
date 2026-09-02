#!/usr/bin/env python3
"""Проверяет process forecast до DistTemp и интеграцию boil/session baseline."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cmath>
#include <iostream>

static constexpr float MIN_TEMP_RATE = 0.01f;

@HELPER@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void check_close(float actual, float expected, const char* message) {
  check(std::fabs(actual - expected) < 0.001f, message);
}

int main() {
  float remaining = -1.0f;
  check(calculate_dist_process_remaining(90.0f, 98.0f, 86.0f, 20.0f, remaining),
        "рост после кипения должен дать прогноз до DistTemp");
  check_close(remaining, 40.0f,
              "прогноз должен использовать долгосрочную скорость процесса");

  remaining = -1.0f;
  check(!calculate_dist_process_remaining(90.0f, 98.0f, 90.0f, 20.0f, remaining),
        "нулевая скорость не должна публиковать ложный нулевой прогноз");

  remaining = -1.0f;
  check(calculate_dist_process_remaining(98.0f, 98.0f, 90.0f, 20.0f, remaining),
        "достижение DistTemp является валидным завершённым прогнозом");
  check_close(remaining, 0.0f, "на DistTemp остаток должен быть нулём");

  if (failures != 0) return 1;
  std::cout << "distillation process predictor checks passed\n";
  return 0;
}
'''

WRAP_HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

@TIME_PREDICTOR@
@PREDICTION_REASON@

using ProgramType = char;
static const ProgramType PROGRAM_TYPE_NONE = 0;
struct WProgram { ProgramType WType; float Speed; };
static WProgram program[1] = {};
static uint8_t ProgramNum = 0;
static uint8_t ProgramLen = 1;
static bool program_type_empty(ProgramType value) { return value == PROGRAM_TYPE_NONE; }

struct Sensor { float avgTemp; float StartProgTemp; };
struct Setup { float DistTemp; };
static Sensor TankSensor = {};
static Setup SamSetup = {};
static TimePredictor timePredictor = {};
static DistPredictionReason distRowPredictionReason = DIST_PREDICTION_AWAITING_BOIL;
static DistPredictionReason distProcessPredictionReason = DIST_PREDICTION_AWAITING_BOIL;
static bool sessionTimerValid = false;
static unsigned long sessionStartTime = 0;
static bool distBoilStartedPrev = true;
static int startval = 7;
static const int SAMOVAR_STARTVAL_IDLE = 0;
static unsigned long fakeMillis = 0;
static unsigned long millis() { return fakeMillis; }
static constexpr float MIN_TEMP_RATE = 0.01f;
static constexpr float MIN_ALC_RATE = 0.001f;
static constexpr unsigned long PREDICTOR_UPDATE_MS = 30000UL;
static float get_alcohol(float value) { return 100.0f - value; }
static float get_steam_alcohol(float value) { return 100.0f - value; }
static float max(float left, float right) { return left > right ? left : right; }

class String {
 public:
  String(const char* value) : value_(value) {}
  String(int value) : value_(std::to_string(value)) {}
  String& operator+=(const String& other) { value_ += other.value_; return *this; }
  const std::string& text() const { return value_; }
 private:
  std::string value_;
};
static String operator+(const char* left, const String& right) {
  String combined(left);
  combined += right;
  return combined;
}
static String operator+(const String& left, const char* right) {
  String combined = left;
  combined += String(right);
  return combined;
}
static String lastStopMessage("");
static void stop_process(const String& message) { lastStopMessage = message; }

@PROCESS_HELPER@
@UPDATE@
@FINISH@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void check_close(float actual, float expected, const char* message) {
  check(std::fabs(actual - expected) < 1.0f, message);
}

static void configure_predictor_before_wrap() {
  const unsigned long beforeWrap = std::numeric_limits<unsigned long>::max() - 30000UL;
  program[0] = {'T', 98.0f};
  ProgramNum = 0;
  ProgramLen = 1;
  TankSensor.avgTemp = 81.0f;
  SamSetup.DistTemp = 98.0f;
  timePredictor = {};
  timePredictor.baselineValid = true;
  timePredictor.initialTemp = 80.0f;
  timePredictor.processInitialTemp = 80.0f;
  timePredictor.startTime = beforeWrap;
  timePredictor.processStartTime = beforeWrap;
  timePredictor.lastUpdateTime = beforeWrap;
  sessionTimerValid = true;
  sessionStartTime = beforeWrap;
  fakeMillis = 10000UL;
}

// [PKG-B, П7] Строка типа 'T' на очень медленном нагреве (0.03 °C/мин - типично
// для DS18B20 с шагом квантования 0.0625 °C сразу после закипания). Скорость
// обязана считаться как среднее с начала СТРОКИ (currentTemp/initialTemp за
// currentTime/startTime), а не по последнему 30-секундному окну (PREDICTOR_UPDATE_MS) -
// короткое окно то не видит изменения совсем, то ловит один квант целиком и
// завышает скорость в разы.
static void configure_slow_t_row() {
  program[0] = {'T', 98.0f};
  ProgramNum = 0;
  ProgramLen = 1;
  TankSensor.avgTemp = 80.06f;
  SamSetup.DistTemp = 100.0f;
  timePredictor = {};
  timePredictor.baselineValid = true;
  timePredictor.initialTemp = 80.0f;
  timePredictor.processInitialTemp = 80.0f;
  timePredictor.startTime = 0UL;
  timePredictor.processStartTime = 0UL;
  timePredictor.lastUpdateTime = 90000UL;
  sessionTimerValid = true;
  sessionStartTime = 0UL;
  fakeMillis = 120000UL;
}

int main() {
  configure_predictor_before_wrap();
  updateTimePredictor();
  check(timePredictor.rowPredictionAvailable,
        "row predictor must advance when its update interval crosses unsigned long wrap");
  check(timePredictor.processPredictionAvailable,
        "process predictor must remain available when process elapsed crosses wrap");
  check(timePredictor.predictedTotalTime > timePredictor.processRemainingTime,
        "session predicted total must include elapsed time across wrap");

  configure_slow_t_row();
  updateTimePredictor();
  check(timePredictor.rowPredictionAvailable,
        "slow T-row: медленный нагрев (0.03 C/мин с начала строки) должен дать доступный прогноз");
  check_close(timePredictor.remainingTime, 598.0f,
        "slow T-row: остаток обязан считаться по средней скорости с начала строки, а не по короткому 30-секундному окну");

  const unsigned long finishBeforeWrap = std::numeric_limits<unsigned long>::max() - 120000UL;
  sessionTimerValid = true;
  sessionStartTime = finishBeforeWrap;
  ProgramNum = 9;
  startval = 7;
  distBoilStartedPrev = true;
  fakeMillis = 60000UL;
  lastStopMessage = String("");
  distiller_finish();
  check(lastStopMessage.text().find("3 мин.") != std::string::npos,
        "session finish message must report elapsed minutes across unsigned long wrap");
  check(!sessionTimerValid && sessionStartTime == 0 && !distBoilStartedPrev,
        "finish must clear the valid session timer after reporting it");
  check(ProgramNum == 0 && startval == SAMOVAR_STARTVAL_IDLE,
        "finish must retain the normal session cleanup after wrap");

  if (failures != 0) return 1;
  std::cout << "distillation session/predictor wrap checks passed\n";
  return 0;
}
'''


def main() -> int:
    raw = (ROOT / "distiller.h").read_text(encoding="utf-8")
    source = strip_cpp_comments(raw)
    helper_body = extract_function_body(
        raw, "inline bool calculate_dist_process_remaining"
    )
    proc_body = extract_function_body(raw, "void distiller_proc()")
    run_body = extract_function_body(raw, "void run_dist_program(uint8_t num)")
    update_body = extract_function_body(raw, "void updateTimePredictor()")
    finish_body = extract_function_body(raw, "void distiller_finish()")

    errors: list[str] = []
    require_ordered_tokens(
        "boiling front resets the predictor baseline",
        proc_body,
        [
            "if (boil_started && !distBoilStartedPrev)",
            "TankSensor.StartProgTemp = TankSensor.avgTemp;",
            "resetTimePredictor();",
            "distBoilStartedPrev = boil_started;",
        ],
        errors,
    )
    if "resetTimePredictor();" in run_body:
        errors.append("переход строки всё ещё сбрасывает process baseline")
    for token in [
        "timePredictor.startTime = millis();",
        "timePredictor.rowPredictionAvailable = false;",
    ]:
        if token not in run_body:
            errors.append(f"run_dist_program missing row-only reset: {token}")
    for token in [
        "ProgramNum < ProgramLen",
        "calculate_dist_process_remaining(",
        "timePredictor.processRemainingTime",
    ]:
        if token not in update_body:
            errors.append(f"updateTimePredictor missing process contract: {token}")
    for token in [
        "if (sessionTimerValid)",
        "sessionTimerValid = false;",
        "sessionStartTime = 0;",
    ]:
        if token not in finish_body:
            errors.append(f"distiller_finish missing timer guard/reset: {token}")
    if "timePredictor.initialAlcohol = get_alcohol" in source.split(
        "void resetTimePredictor()", 1
    )[1].split("void updateTimePredictor()", 1)[0] and \
            "boil_started ?" not in extract_function_body(raw, "void resetTimePredictor()"):
        errors.append("resetTimePredictor initializes alcohol before boil")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    helper = (
        "bool calculate_dist_process_remaining("
        "float currentTemp, float targetTemp, float initialTemp, "
        "float elapsedMinutes, float& remainingMinutes) {"
        + helper_body
        + "}"
    )
    harness = HARNESS.replace("@HELPER@", helper)
    with tempfile.TemporaryDirectory(prefix="samovar-dist-predictor-") as temp_dir:
        temp = Path(temp_dir)
        def compile_and_run(name: str, source: str) -> subprocess.CompletedProcess[str]:
            source_path = temp / f"{name}.cpp"
            binary_path = temp / name
            source_path.write_text(source, encoding="utf-8")
            result = subprocess.run(
                [
                    "g++",
                    "-std=c++11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    str(source_path),
                    "-o",
                    str(binary_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return result
            return subprocess.run(
                [str(binary_path)], capture_output=True, text=True, check=False
            )

        result = compile_and_run("dist_predictor", harness)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if result.returncode != 0:
            return result.returncode

        mutant = harness.replace(
            "remainingMinutes = delta / rate;",
            "remainingMinutes = delta;",
            1,
        )
        if mutant == harness:
            print("FAIL: не удалось построить мутацию process forecast", file=sys.stderr)
            return 1
        if compile_and_run("dist_predictor_mutant", mutant).returncode == 0:
            print("FAIL: мутация process forecast пережила тест", file=sys.stderr)
            return 1

        def definition(token: str) -> str:
            start = raw.find(token)
            if start < 0:
                raise ValueError(f"missing definition: {token}")
            end = raw.find("};", start)
            if end < 0:
                raise ValueError(f"unterminated definition: {token}")
            return raw[start:end + 2]

        wrap_harness = (
            WRAP_HARNESS.replace("@TIME_PREDICTOR@", definition("struct TimePredictor"))
            .replace("@PREDICTION_REASON@", definition("enum DistPredictionReason"))
            .replace("@PROCESS_HELPER@", helper)
            .replace("@UPDATE@", "void updateTimePredictor() {" + update_body + "}")
            .replace("@FINISH@", "void distiller_finish() {" + finish_body + "}")
        )
        result = compile_and_run("dist_predictor_wrap", wrap_harness)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if result.returncode != 0:
            return result.returncode

        # [PKG-B, П7] Возврат к короткому 30-секундному окну (dtMin) вместо среднего
        # с начала строки. При очень медленном нагреве это завышает скорость в разы
        # (см. configure_slow_t_row) и должно завалить check_close на remainingTime.
        mutant = wrap_harness.replace(
            "(currentTemp - timePredictor.initialTemp) / "
            "((currentTime - timePredictor.startTime) / 60000.0f)",
            "(currentTemp - timePredictor.initialTemp) / dtMin",
            1,
        )
        if mutant == wrap_harness:
            print("FAIL: unable to build slow T-row rate mutation", file=sys.stderr)
            return 1
        if compile_and_run("dist_predictor_slow_t_row_mutant", mutant).returncode == 0:
            print("FAIL: slow T-row rate mutation survived", file=sys.stderr)
            return 1

        mutant = wrap_harness.replace(
            "unsigned long dtMs = currentTime - timePredictor.lastUpdateTime;",
            "unsigned long dtMs = currentTime >= timePredictor.lastUpdateTime ? currentTime - timePredictor.lastUpdateTime : 0UL;",
            1,
        )
        if mutant == wrap_harness:
            print("FAIL: unable to build predictor wrap mutation", file=sys.stderr)
            return 1
        if compile_and_run("dist_predictor_wrap_mutant", mutant).returncode == 0:
            print("FAIL: predictor wrap mutation survived", file=sys.stderr)
            return 1

        mutant = wrap_harness.replace(
            "(currentTime - sessionStartTime) / 60000.0f",
            "(currentTime >= sessionStartTime ? currentTime - sessionStartTime : 0UL) / 60000.0f",
            1,
        )
        if mutant == wrap_harness:
            print("FAIL: unable to build session predictor wrap mutation", file=sys.stderr)
            return 1
        if compile_and_run("dist_session_predictor_wrap_mutant", mutant).returncode == 0:
            print("FAIL: session predictor wrap mutation survived", file=sys.stderr)
            return 1

        mutant = wrap_harness.replace(
            "(millis() - sessionStartTime) / 60000",
            "(millis() >= sessionStartTime ? millis() - sessionStartTime : 0UL) / 60000",
            1,
        )
        if mutant == wrap_harness:
            print("FAIL: unable to build finish wrap mutation", file=sys.stderr)
            return 1
        if compile_and_run("dist_finish_wrap_mutant", mutant).returncode == 0:
            print("FAIL: session finish wrap mutation survived", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
