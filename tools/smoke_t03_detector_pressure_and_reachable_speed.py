#!/usr/bin/env python3
"""[T03/F04,F05] Единая шкала температуры и фактическая команда детектора."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
TEMPERATURE_SIGNATURE = "inline float detector_temperature_for_history(float rawTemperature)"
APPLY_SIGNATURE = "inline bool apply_detector_speed_correction(float baseSpeedRate)"
RATE_SIGNATURE = "float get_liquid_rate_by_step(int StepperSpeed)"
SPEED_SIGNATURE = "float get_speed_from_rate(float volume_per_hour)"

HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <iostream>

using std::round;

struct SetupEEPROM {
  bool UsePreccureCorrect = false;
  uint16_t StepperStepMl = 100;
} SamSetup;

struct ImpurityDetector {
  float correctionFactor = 1.0f;
} impurityDetector;

static float bme_pressure = 0;
static const float DETECTOR_PRESSURE_TEMP_COEF = 0.037f;
static float ActualVolumePerHour = 0;
static uint16_t CurrrentStepperSpeed = 0;
static int setPumpSpeedCalls = 0;
static uint8_t ProgramNum = 0;
static char programType = 'B';

static char program_type_at(uint8_t) { return programType; }

static float get_liquid_volume_by_step(float stepCount);
enum UiControlSource { UI_CONTROL_SOURCE_UNKNOWN = 0, UI_CONTROL_SOURCE_DETECTOR = 7 };
static void set_pump_speed(float stepSpeed, bool, bool, UiControlSource) {
  setPumpSpeedCalls++;
  CurrrentStepperSpeed = (uint16_t)stepSpeed;
  ActualVolumePerHour = get_liquid_volume_by_step(CurrrentStepperSpeed) * 3.6f;
}

static float get_liquid_volume_by_step(float stepCount) {
  return SamSetup.StepperStepMl > 0 ? stepCount / SamSetup.StepperStepMl : 0;
}

@RATE_FUNCTION@
@SPEED_FUNCTION@
@TEMPERATURE_FUNCTION@
@APPLY_FUNCTION@

static int failures = 0;
static void check(bool value, const char* message) {
  if (!value) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
static bool near(float left, float right, float epsilon = 0.002f) {
  return left > right - epsilon && left < right + epsilon;
}

static void test_pressure_scale_is_shared() {
  SamSetup.UsePreccureCorrect = false;
  bme_pressure = 750;
  float at750 = detector_temperature_for_history(89.63f);
  bme_pressure = 770;
  float at770 = detector_temperature_for_history(90.37f);
  check(near(at750, 90.0f) && near(at770, 90.0f),
        "выключенная коррекция должна привести оба давления к одной шкале истории");

  SamSetup.UsePreccureCorrect = true;
  bme_pressure = 750;
  at750 = detector_temperature_for_history(90.0f);
  bme_pressure = 770;
  at770 = detector_temperature_for_history(90.0f);
  check(near(at750, 90.0f) && near(at770, 90.0f),
        "включённая коррекция измерительного тракта не должна применяться второй раз");
}

static void test_reachable_rate_uses_each_calibration() {
  SamSetup.StepperStepMl = 100;
  check(near(get_liquid_rate_by_step(65535), 2359.26f),
        "локальный привод с калибровкой 100 должен возвращать достижимую скорость");
  SamSetup.StepperStepMl = 250;
  check(near(get_liquid_rate_by_step(65535), 943.704f),
        "другая калибровка должна давать другую достижимую скорость");
}

static void test_detector_changes_only_a_real_command() {
  programType = 'B';
  SamSetup.StepperStepMl = 100;
  impurityDetector.correctionFactor = 0.9f;
  CurrrentStepperSpeed = (uint16_t)get_speed_from_rate(1.0f);
  setPumpSpeedCalls = 0;
  check(apply_detector_speed_correction(get_liquid_rate_by_step(CurrrentStepperSpeed)),
        "снижение от достижимой базы должно изменить команду");
  check(CurrrentStepperSpeed < (uint16_t)get_speed_from_rate(1.0f) && setPumpSpeedCalls == 1,
        "детектор должен передать одну реально уменьшенную команду");

  const float appliedBase = get_liquid_rate_by_step((uint16_t)get_speed_from_rate(1.0f));
  CurrrentStepperSpeed = (uint16_t)(get_speed_from_rate(appliedBase) * impurityDetector.correctionFactor);
  setPumpSpeedCalls = 0;
  ActualVolumePerHour = 0.83f;
  check(!apply_detector_speed_correction(appliedBase),
        "коэффициент без изменения целой команды не считается снижением");
  check(setPumpSpeedCalls == 0,
        "равную текущей команду нельзя повторно устанавливать или о ней сообщать");
  check(near(ActualVolumePerHour, 0.83f),
        "no-op не должен подменять фактический расход базовой скоростью");
}

static void test_tails_do_not_command_the_drive() {
  programType = 'T';
  impurityDetector.correctionFactor = 0.9f;
  CurrrentStepperSpeed = (uint16_t)get_speed_from_rate(1.0f);
  setPumpSpeedCalls = 0;

  check(!apply_detector_speed_correction(1.0f),
        "на хвостах helper не должен менять команду привода");
  check(setPumpSpeedCalls == 0,
        "на хвостах helper не должен вызывать set_pump_speed");

  CurrrentStepperSpeed = (uint16_t)get_speed_from_rate(0.5f);
  check(!apply_detector_speed_correction(0.5f),
        "на хвостах helper не должен менять вторую команду другой скорости");
  check(setPumpSpeedCalls == 0,
        "на хвостах helper не должен вызывать set_pump_speed и на второй скорости");
}

int main() {
  test_pressure_scale_is_shared();
  test_reachable_rate_uses_each_calibration();
  test_detector_changes_only_a_real_command();
  test_tails_do_not_command_the_drive();
  return failures == 0 ? 0 : 1;
}
'''


def extract_functions(detector_source: str, logic_source: str) -> dict[str, str]:
    return {
        "temperature": extract_function_body(detector_source, TEMPERATURE_SIGNATURE),
        "apply": extract_function_body(detector_source, APPLY_SIGNATURE),
        "rate": extract_function_body(logic_source, RATE_SIGNATURE),
        "speed": extract_function_body(logic_source, SPEED_SIGNATURE),
    }


def build_harness(functions: dict[str, str]) -> str:
    return (HARNESS
            .replace("@RATE_FUNCTION@", RATE_SIGNATURE + " {" + functions["rate"] + "}")
            .replace("@SPEED_FUNCTION@", SPEED_SIGNATURE + " {" + functions["speed"] + "}")
            .replace("@TEMPERATURE_FUNCTION@", TEMPERATURE_SIGNATURE + " {" + functions["temperature"] + "}")
            .replace("@APPLY_FUNCTION@", APPLY_SIGNATURE + " {" + functions["apply"] + "}"))


def compile_and_run(harness: str, name: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="samovar-t03-detector-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / f"{name}.cpp"
        binary = temp / name
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if compiled.returncode != 0:
            return compiled
        return subprocess.run([str(binary)], capture_output=True, text=True, check=False)


def require_mutant_fails(functions: dict[str, str], key: str, anchor: str, replacement: str, message: str) -> None:
    if functions[key].count(anchor) != 1:
        raise AssertionError(f"мутационный якорь отсутствует: {anchor}")
    mutated = dict(functions)
    mutated[key] = mutated[key].replace(anchor, replacement, 1)
    result = compile_and_run(build_harness(mutated), "mutant")
    output = result.stdout + result.stderr
    if result.returncode == 0 or message not in output:
        raise AssertionError(f"мутант пережил проверку {message}: {output}")


def require_run_program_uses_applied_rate(logic_source: str) -> None:
    body = extract_function_body(logic_source, "void run_program(uint8_t num)")
    required = [
        "const float appliedVolumePerHour = rectSecondPumpHeadsRow",
        ": get_liquid_rate_by_step(CurrrentStepperSpeed);",
        "CurrentBaseSpeedRate = appliedVolumePerHour;",
        "ActualVolumePerHour = appliedVolumePerHour;",
    ]
    for token in required:
        if token not in body:
            raise AssertionError(f"run_program не использует достижимую скорость: {token}")


def require_process_uses_shared_temperature(detector_source: str) -> None:
    body = extract_function_body(detector_source, "void process_impurity_detector()")
    if body.count("detector_temperature_for_history(") != 2:
        raise AssertionError("активный отбор и собственная пауза должны использовать общую шкалу температуры")


def require_detector_message_guard(detector_source: str) -> None:
    body = extract_function_body(detector_source, "void process_impurity_detector()")
    guard = ('if (speedApplied) {\n'
             '            SendMsg("Детектор: Снижение скорости')
    if body.count(guard) != 1:
        raise AssertionError("сообщение о снижении должно быть только под guard фактической команды")
    if "скорость уже на минимуме" in body:
        raise AssertionError("при неизменной команде детектор не должен посылать отдельное сообщение")


def main() -> int:
    if shutil.which("g++") is None:
        print("FAIL: для T03 нужен g++", file=sys.stderr)
        return 1
    detector_source = (ROOT / "impurity_detector.h").read_text(encoding="utf-8")
    logic_source = (ROOT / "logic.h").read_text(encoding="utf-8")
    try:
        functions = extract_functions(detector_source, logic_source)
        require_run_program_uses_applied_rate(logic_source)
        require_process_uses_shared_temperature(detector_source)
        require_detector_message_guard(detector_source)
        result = compile_and_run(build_harness(functions), "t03")
        if result.returncode != 0:
            print(result.stdout + result.stderr, file=sys.stderr)
            return 1
        require_mutant_fails(
            functions, "temperature", "!SamSetup.UsePreccureCorrect", "false",
            "выключенная коррекция должна привести оба давления к одной шкале истории",
        )
        require_mutant_fails(
            functions,
            "apply",
            "(uint16_t)targetStepSpeed == CurrrentStepperSpeed",
            "(uint16_t)targetStepSpeed == 0",
            "равную текущей команду нельзя повторно устанавливать или о ней сообщать",
        )
        require_mutant_fails(
            functions,
            "apply",
            "if (program_type_at(ProgramNum) == 'T') return false;",
            "if (program_type_at(ProgramNum) == 'Z') return false;",
            "на хвостах helper не должен менять команду привода",
        )
        message_mutant = detector_source.replace("if (speedApplied) {", "if (true) {", 1)
        try:
            require_detector_message_guard(message_mutant)
        except AssertionError:
            pass
        else:
            raise AssertionError("мутант с безусловным сообщением пережил проверку guard")
        rate_mutant = logic_source.replace(
            "CurrentBaseSpeedRate = appliedVolumePerHour;", "CurrentBaseSpeedRate = program[num].Speed;", 1
        )
        try:
            require_run_program_uses_applied_rate(rate_mutant)
        except AssertionError:
            pass
        else:
            raise AssertionError("мутант с сырой базовой скоростью пережил проверку")
    except (AssertionError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("T03: давление и достижимая команда детектора проверены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
