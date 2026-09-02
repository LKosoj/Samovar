#!/usr/bin/env python3
"""Trace-driven BK: cold start → cooling → boil evidence → work → finish."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cstdint>
#include <iostream>

#define portTICK_PERIOD_MS 1
static void vTaskDelay(int) {}

class String {
 public:
  String(const char* value) : value_(value) {}
  const char* c_str() const { return value_; }
 private:
  const char* value_;
};

enum BoilingEvidence : uint8_t {
  BOILING_EVIDENCE_NONE = 0,
  BOILING_EVIDENCE_STEAM,
  BOILING_EVIDENCE_PIPE,
  BOILING_EVIDENCE_TANK_AND_WATER,
  BOILING_EVIDENCE_TANK,
  BOILING_EVIDENCE_WATER,
};
static BoilingEvidence boiling_evidence = BOILING_EVIDENCE_NONE;

@RECORD@

struct Sensor {
  float avgTemp = 0;
};
struct Setup {
  float DistTemp = 98;
  float SetWaterTemp = 25;
  float rele4 = 0;
};

static Sensor TankSensor;
static Sensor SteamSensor;
static Sensor PipeSensor;
static Setup SamSetup;
static int SamovarStatusInt = 4000;
static const int SAMOVAR_STATUS_BK = 4000;
static bool PowerOn = false;
static bool valve_status = false;
static bool boilingFixture = false;
static int checkBoilingCalls = 0;
static int finishCalls = 0;
static int workModeCalls = 0;
static int openValveCalls = 0;
static const int POWER_SPEED_MODE = 1;
static const int POWER_WORK_MODE = 2;
static int powerMode = POWER_SPEED_MODE;
// [A1 п.1] Глобальная переменная BK.h - extract_function_body её не извлекает
// (она вне тела функций), харнесс заводит свою копию сам.
static bool bk_work_power_pending = false;
static const float CHANGE_POWER_MODE_STEAM_TEMP = 39.0f;
static const float DELTA_T_CLOSE_VALVE = 2.0f;
static const int MODE_HEATING_START_SUCCEEDED = 1;
static const int SAFETY_HEATER_OUTPUT_BOOST = 2;

static bool sensor_valid(const Sensor&) { return true; }
static bool process_sensor_failed(const char*, const char*) { return false; }
static bool mode_heating_start_pending(int) { return false; }
static int mode_run_heating_start(
    int, const char*, const char*, const String&, const char*, bool) {
  PowerOn = true;
  return MODE_HEATING_START_SUCCEEDED;
}
static bool mode_should_open_cooling(bool, bool, bool) {
  return PowerOn && !valve_status;
}
static bool mode_should_close_cooling(float, bool) { return false; }
static void open_valve(bool value, bool) {
  valve_status = value;
  openValveCalls++;
}
static bool check_boiling() {
  checkBoilingCalls++;
  if (!boilingFixture) return false;
  record_boiling_evidence(BOILING_EVIDENCE_TANK_AND_WATER);
  return true;
}
// [A1 п.1] Не static: после правки эта функция в извлечённых телах bk_proc()/
// check_alarm_bk() больше нигде не вызывается (заменена на bk_work_power_pending) -
// static-версия упала бы на -Werror=unused-function. Нужна только для того, чтобы
// компилировалась мутация ниже, которая возвращает вызов в текст.
bool current_power_mode_is(int mode) { return powerMode == mode; }
static void set_current_power_mode_value(int mode) {
  powerMode = mode;
  workModeCalls++;
}
static void digitalWrite(int, bool) {}
static const int RELE_CHANNEL4 = 4;
static void heater_boost_output_off() { digitalWrite(RELE_CHANNEL4, !SamSetup.rele4); }
static void mode_clear_alarm_pause_if_expired() {}
static bool mode_check_powered_cooling_sensors(const char*) { return true; }
static void mode_stop_cooling_pump_if_started() {}
static void mode_request_overheat_emergency_if_needed() {}
static void mode_request_water_flow_emergency_if_needed() {}
static void mode_handle_water_pre_alarm_if_due() {}
static void bk_finish() { finishCalls++; }

// [A1 п.2] Датчик куба всегда валиден (sensor_valid выше) - ветка мягкого отказа
// в bk_proc() синтаксически присутствует во вклеенном теле, но недостижима при
// runtime в этом харнессе (её поведение проверяет smoke_bk_start_refusal.py).
// Стабы нужны только для компиляции.
static int cancelProcessStartCalls = 0;
static void mode_cancel_process_start(const String&) { cancelProcessStartCalls++; }
static bool heater_safety_latched() { return false; }

// [A1 п.6] bk_proc() теперь безусловно зовёт хелпер плато из distiller.h - без
// заглушки вклеенное тело не скомпилируется (was not declared in this scope).
static bool plateauFinishDueStub = false;
static bool dist_plateau_finish_due() { return plateauFinishDueStub; }

// [A1 п.1, опционально] Управляемая заглушка (два значения) для ветки пред-аварии
// по воде в check_alarm_bk() - позволяет исполняемо проверить, что BKPower
// применяется по пред-аварии, если кипение ещё не подтверждено.
static bool waterPreAlarmDueStub = false;
static bool mode_water_pre_alarm_due() { return waterPreAlarmDueStub; }

// [9b] bk_apply_work_power()/bk_proc() теперь безусловно ссылаются на программу
// БК (переход по строкам, run_bk_program(0) после первого включения нагрева) -
// без этих заглушек вклеенные тела не скомпилируются. USE_WATER_PUMP в этом
// харнессе не определён, поэтому apply_program_power_row(program[0].Power) в
// bk_apply_work_power() компилируется в ветку #else (набор стабов ниже её не
// касается).
using ProgramType = char;
static const ProgramType PROGRAM_TYPE_NONE = 0;
struct WProgram { ProgramType WType = PROGRAM_TYPE_NONE; float Speed = 0; float Power = 0; int capacity_num = 0; };
static const uint8_t PROGRAM_END = 8;
static WProgram program[PROGRAM_END];
static uint8_t ProgramNum = 0;
static uint8_t ProgramLen = 0;
static bool program_type_empty(ProgramType value) { return value == PROGRAM_TYPE_NONE; }
// Управляемая заглушка (минимум два значения) - переход по строке программы БК
// не входит в сценарии этого файла (это область smoke_bk_program_run.py), но
// должна быть управляемой, а не жёстко false, иначе мутационные проверки самого
// program_threshold_row_done в другом тесте не спутать с этим стабом.
static bool rowThresholdDoneStub = false;
static bool program_threshold_row_done(const WProgram&) { return rowThresholdDoneStub; }
static int runBkProgramCalls = 0;
static uint8_t runBkProgramLastArg = 255;
static void run_bk_program(uint8_t num) {
  runBkProgramCalls++;
  runBkProgramLastArg = num;
}

@BK_APPLY_WORK_POWER@
@BK_PROC@
@BK_ALARM@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  TankSensor.avgTemp = 25.0f;
  bk_proc();
  check(PowerOn, "cold start должен включить нагрев через общий start helper");
  check(finishCalls == 0, "cold start не должен завершить BK");

  checkBoilingCalls = 0;
  check_alarm_bk();
  check(valve_status && openValveCalls == 1,
        "alarm tick должен открыть охлаждение при запросе");
  check(checkBoilingCalls == 1,
        "детектор кипения должен вызываться ровно один раз за tick");
  check(workModeCalls == 0, "до кипения рабочая мощность не включается");

  boilingFixture = true;
  checkBoilingCalls = 0;
  check_alarm_bk();
  check(checkBoilingCalls == 1,
        "boiling tick не должен опрашивать детектор дважды");
  check(powerMode == POWER_WORK_MODE && workModeCalls == 1,
        "подтверждение кипения должно включить рабочий режим");
  check(boiling_evidence == BOILING_EVIDENCE_TANK_AND_WATER,
        "источник подтверждения должен сохраниться");

  record_boiling_evidence(BOILING_EVIDENCE_PIPE);
  check(boiling_evidence == BOILING_EVIDENCE_TANK_AND_WATER,
        "первый источник кипения должен быть sticky");

  TankSensor.avgTemp = SamSetup.DistTemp;
  bk_proc();
  check(finishCalls == 1, "достижение DistTemp должно завершить BK");

  // [A1 п.1] Регулятор уже не в SPEED (например, ушёл туда по пред-аварии воды
  // ДО этого тика через другой путь) - переход на BKPower не должен теряться,
  // пока bk_work_power_pending ещё взведён.
  bk_work_power_pending = true;
  powerMode = POWER_WORK_MODE;
  boilingFixture = true;
  checkBoilingCalls = 0;
  workModeCalls = 0;
  check_alarm_bk();
  check(workModeCalls == 1,
        "BKPower должен примениться по взведённому флагу, даже если регулятор уже покинул SPEED");
  check_alarm_bk();
  check(workModeCalls == 1,
        "повторный тик не должен повторно применять BKPower - флаг снимается после применения");

  // [A1 п.1, опционально] Ветка пред-аварии по воде: если кипение ещё не
  // подтверждено (флаг взведён заново), а вода уже перегрелась - BKPower должен
  // примениться синхронно ДО общего хелпера, а не потеряться навсегда.
  bk_work_power_pending = true;
  boilingFixture = false;
  waterPreAlarmDueStub = true;
  workModeCalls = 0;
  check_alarm_bk();
  check(workModeCalls == 1,
        "пред-авария по воде должна применить BKPower, пока переход ещё не случился");
  waterPreAlarmDueStub = false;
  check_alarm_bk();
  check(workModeCalls == 1,
        "после применения по пред-аварии флаг снят - повторный тик не должен применять BKPower повторно");

  if (failures != 0) return 1;
  std::cout << "BK full route passed\n";
  return 0;
}
'''


def main() -> int:
    logic = (ROOT / "logic.h").read_text(encoding="utf-8")
    bk = (ROOT / "BK.h").read_text(encoding="utf-8")
    samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    bk_ui = (ROOT / "data_raw/bk.htm").read_text(encoding="utf-8")
    record_body = extract_function_body(
        logic, "inline void record_boiling_evidence"
    )
    proc_body = extract_function_body(bk, "void bk_proc()")
    alarm_body = extract_function_body(bk, "void check_alarm_bk()")
    apply_work_power_body = extract_function_body(bk, "static void bk_apply_work_power()")
    if strip_cpp_comments(alarm_body).count("check_boiling()") != 1:
        print("FAIL: BK alarm должен вызывать check_boiling ровно один раз", file=sys.stderr)
        return 1
    for token in [
        "BOILING_EVIDENCE_STEAM",
        "BOILING_EVIDENCE_PIPE",
        "record_boiling_evidence(evidence);",
        "evidence = BOILING_EVIDENCE_TANK_AND_WATER;",
        "evidence = BOILING_EVIDENCE_TANK;",
        "evidence = BOILING_EVIDENCE_WATER;",
    ]:
        if token not in logic + bk:
            print(f"FAIL: отсутствует источник кипения: {token}", file=sys.stderr)
            return 1
    if "BoilingPrecisionSensorConfigured" not in samovar or \
            "используется менее точный алгоритм куб/вода" not in bk_ui:
        print(
            "FAIL: UI не объясняет менее точный алгоритм без датчиков пара/царги",
            file=sys.stderr,
        )
        return 1

    harness = (
        HARNESS.replace(
            "@RECORD@",
            "void record_boiling_evidence(BoilingEvidence evidence) {"
            + record_body
            + "}",
        )
        .replace(
            "@BK_APPLY_WORK_POWER@",
            "void bk_apply_work_power() {" + apply_work_power_body + "}",
        )
        .replace("@BK_PROC@", "void bk_proc() {" + proc_body + "}")
        .replace("@BK_ALARM@", "void check_alarm_bk() {" + alarm_body + "}")
    )
    with tempfile.TemporaryDirectory(prefix="samovar-bk-route-") as temp_dir:
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

        result = compile_and_run("bk_route", harness)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if result.returncode != 0:
            return result.returncode

        mutant = harness.replace(
            "if (boiling_evidence == BOILING_EVIDENCE_NONE) boiling_evidence = evidence;",
            "(void)evidence;",
            1,
        )
        if mutant == harness:
            print("FAIL: не удалось построить мутацию sticky evidence", file=sys.stderr)
            return 1
        mutant_result = compile_and_run("bk_route_mutant", mutant)
        if mutant_result.returncode == 0:
            print("FAIL: мутация sticky evidence пережила BK route", file=sys.stderr)
            return 1

        # [A1 п.1] Откат к current_power_mode_is(POWER_SPEED_MODE) - переход на
        # BKPower снова теряется навсегда, как только регулятор синхронно покинул
        # SPEED ДО подтверждения кипения (см. новый сценарий в main()).
        power_mode_mutant = harness.replace(
            "bk_work_power_pending && (boilingNow",
            "current_power_mode_is(POWER_SPEED_MODE) && (boilingNow",
            1,
        )
        if power_mode_mutant == harness:
            print("FAIL: не удалось построить мутацию bk_work_power_pending (boiling)", file=sys.stderr)
            return 1
        power_mode_mutant_result = compile_and_run("bk_route_power_mode_mutant", power_mode_mutant)
        if power_mode_mutant_result.returncode == 0:
            print(
                "FAIL: мутация current_power_mode_is(POWER_SPEED_MODE) (boiling) пережила BK route",
                file=sys.stderr,
            )
            return 1

        # [A1 п.1, опционально] Пред-алармная ветка: если флаг игнорируется, переход
        # на BKPower при пред-аварии по воде (кипение ещё не подтверждено) молча
        # пропадает.
        pre_alarm_mutant = harness.replace(
            "bk_work_power_pending && mode_water_pre_alarm_due()",
            "false && mode_water_pre_alarm_due()",
            1,
        )
        if pre_alarm_mutant == harness:
            print("FAIL: не удалось построить мутацию bk_work_power_pending (пред-авария)", file=sys.stderr)
            return 1
        pre_alarm_mutant_result = compile_and_run("bk_route_pre_alarm_mutant", pre_alarm_mutant)
        if pre_alarm_mutant_result.returncode == 0:
            print(
                "FAIL: мутация bk_work_power_pending (пред-авария по воде) пережила BK route",
                file=sys.stderr,
            )
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
