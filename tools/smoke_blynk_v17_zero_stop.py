#!/usr/bin/env python3
"""Поведенческая проверка BLYNK_WRITE(V17) (Blynk.ino): ноль во время отбора ставит
отбор на ручную паузу, и снять её можно кнопкой паузы (V13).

История. Ноль сначала уходил в set_pump_speed(1) - насос не останавливался, а полз
на минимальной скорости. Потом ноль стал звать stopService() напрямую: мотор
вставал, но без PauseOn, и отбор было нечем возобновить - pause_withdrawal()
выходит сразу при стоящем моторе и снятой паузе, а set_pump_speed() стоящий мотор
не запускает. Теперь ноль зовёт enter_manual_pause() - ту же паузу, что V13.

Харнесс собирает вместе НАСТОЯЩИЕ тела BLYNK_WRITE(V17) и BLYNK_WRITE(V13)
(Blynk.ino), pause_withdrawal() и enter_manual_pause() (logic.h), а разбор чисел -
настоящий control_numeric_input.h. Заглушки моделируют состояние: шаговый мотор
(крутится/стоит, скорость, шаги, цель), второй I2C-насос, set_pump_speed() (на
стоящем моторе только запоминает скорость, как и настоящая). resume_from_pause()
заглушён до pause_withdrawal(false) - остальное в нём (детектор, пиво, тип
ожидания) к V17 отношения не имеет.

Мутации (каждая обязана провалить конкретный assert, а не компиляцию):
  * ветка нуля вырезана целиком - ноль уходит в строгий парсер как ошибка;
  * enter_manual_pause() заменён на прежний stopService() - V13 не возобновляет;
  * снята проверка !PauseOn - повторный ноль на паузе открывает вторую пару событий;
  * снята проверка статуса - ноль вне отбора останавливает калибровку насоса.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import I18N_INCLUDE, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

ZERO_PAUSE_LINE = (
    "    if (!PauseOn && SamovarStatusInt == SAMOVAR_STATUS_RECT_WITHDRAWAL) enter_manual_pause();\n"
)

HARNESS_TEMPLATE = I18N_INCLUDE + r'''
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <algorithm>
using std::max;

#include "control_numeric_input.h"

static bool modeSwitchInProgressStub = false;
bool mode_switch_in_progress() { return modeSwitchInProgressStub; }

struct SetupEEPROM { uint16_t StepperStepMl = 1000; };
static SetupEEPROM SamSetup;

static const int16_t SAMOVAR_STATUS_IDLE = 0;
static const int16_t SAMOVAR_STATUS_RECT_WITHDRAWAL = 10;
static const int16_t SAMOVAR_STATUS_RECT_AUTOPAUSE = 15;
static const int16_t SAMOVAR_STATUS_PAUSED = 40;
static int16_t SamovarStatusInt = SAMOVAR_STATUS_IDLE;

static const int SAMOVAR_RECTIFICATION_MODE = 0;
static const int SAMOVAR_BEER_MODE = 4;
static int Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
static const int SAMOVAR_STARTVAL_BEER_START = 2000;
static int startval = 0;

static bool PauseOn = false;
static bool PowerOn = true;
static bool alarm_event = false;
static bool program_Wait = false;
static bool program_Pause = false;
static bool beerManualPause = false;
static bool rectManualPauseActive = false;
static uint16_t CurrrentStepperSpeed = 0;
static int32_t TargetStepps = 0;
static int32_t CurrrentStepps = 0;

// ---- Шаговый мотор: состояние, от которого зависят pause_withdrawal() и V13 ----
static bool stepperRunning = false;
static float stepperMaxSpeed = 0.0f;
static int32_t stepperCurrent = 0;
static int32_t stepperTarget = 0;
bool stepper_safe_get_state() { return stepperRunning; }
int32_t stepper_safe_get_target() { return stepperTarget; }
int32_t stepper_safe_get_current() { return stepperCurrent; }
float stepper_safe_get_speed() { return stepperRunning ? stepperMaxSpeed : 0.0f; }
void stepper_safe_set_max_speed(float speed) { stepperMaxSpeed = speed; }
void stepper_safe_set_current(int32_t current) { stepperCurrent = current; }
void stepper_safe_set_target(int32_t target) { stepperTarget = target; }
void stepper_safe_stop() { stepperRunning = false; }
static int stopServiceCalls = 0;
void stopService() { stopServiceCalls++; stepperRunning = false; }
void startService() { stepperRunning = stepperTarget > stepperCurrent; }

// ---- Второй (I2C) насос строки голов ----
static bool rectSecondPumpHeadsRow = false;
static bool rectSecondPumpRunning = false;
static bool secondPumpStopOk = true;
bool rect_pause_second_i2c_pump() {
  if (!rectSecondPumpRunning) return true;
  if (!secondPumpStopOk) return false;
  rectSecondPumpRunning = false;
  return true;
}
bool rect_resume_second_i2c_pump() {
  if (rectSecondPumpHeadsRow) rectSecondPumpRunning = true;
  return true;
}
static int rectFailCalls = 0;
void rect_fail_second_i2c_pump(const char*) { rectFailCalls++; }

enum MESSAGE_TYPE { ALARM_MSG, WARNING_MSG, NOTIFY_MSG };
template <typename T> void SendMsg(const T&, MESSAGE_TYPE) {}
enum UiWaitReason { UI_WAIT_MANUAL_RECT, UI_WAIT_MANUAL_BEER };
enum RuntimePairOutcome { RUNTIME_PAIR_RESUMED };
static int pairBeginCalls = 0;
static int pairEndCalls = 0;
void runtime_pair_begin(UiWaitReason, const char*, MESSAGE_TYPE) { pairBeginCalls++; }
void runtime_pair_end(UiWaitReason, RuntimePairOutcome, const char*, MESSAGE_TYPE) { pairEndCalls++; }
char current_program_type() { return 'B'; }

// set_pump_speed() (logic.h): на крутящемся моторе меняет его скорость, на стоящем -
// только запоминает её для возобновления, мотор не запускает.
enum UiControlSource { UI_CONTROL_SOURCE_UNKNOWN = 0, UI_CONTROL_SOURCE_MANUAL = 2 };
static int setPumpSpeedCalls = 0;
void set_pump_speed(float pumpspeed, bool, bool = true,
                    UiControlSource = UI_CONTROL_SOURCE_UNKNOWN) {
  setPumpSpeedCalls++;
  CurrrentStepperSpeed = (uint16_t)pumpspeed;
  if (stepperRunning) stepperMaxSpeed = pumpspeed;
}

static int reportErrorCalls = 0;
static uint8_t lastReportPin = 0;
void report_blynk_numeric_error(uint8_t virtualPin, NumericParseResult) {
  reportErrorCalls++;
  lastReportPin = virtualPin;
}

struct BlynkParamMock {
  const char* text;
  const char* asStr() const { return text; }
};

// ---- Настоящий код под тестом ----
void pause_withdrawal(bool Pause) {
@PAUSE_WITHDRAWAL@
}
void enter_manual_pause() {
@ENTER_MANUAL_PAUSE@
}
void resume_from_pause() { pause_withdrawal(false); program_Wait = false; }

static void run_v17(const char* input) {
  BlynkParamMock param{input};
@V17@
}
static void run_v13(const char* input) {
  BlynkParamMock param{input};
@V13@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  modeSwitchInProgressStub = false;
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  startval = 0;
  PauseOn = false;
  PowerOn = true;
  alarm_event = false;
  program_Wait = false;
  program_Pause = false;
  beerManualPause = false;
  rectManualPauseActive = false;
  CurrrentStepperSpeed = 0;
  TargetStepps = 0;
  CurrrentStepps = 0;
  stepperRunning = false;
  stepperMaxSpeed = 0.0f;
  stepperCurrent = 0;
  stepperTarget = 0;
  stopServiceCalls = 0;
  rectSecondPumpHeadsRow = false;
  rectSecondPumpRunning = false;
  secondPumpStopOk = true;
  rectFailCalls = 0;
  pairBeginCalls = 0;
  pairEndCalls = 0;
  setPumpSpeedCalls = 0;
  reportErrorCalls = 0;
  lastReportPin = 0;
}

static void start_withdrawal(uint16_t speed, int32_t current, int32_t target) {
  reset_fixture();
  SamovarStatusInt = SAMOVAR_STATUS_RECT_WITHDRAWAL;
  CurrrentStepperSpeed = speed;
  stepperMaxSpeed = speed;
  stepperCurrent = current;
  stepperTarget = target;
  stepperRunning = true;
}

// Ноль -> пауза -> снятие паузы кнопкой: мотор продолжает с той же скорости и шага.
static void zero_then_resume(uint16_t speed, int32_t current, int32_t target) {
  start_withdrawal(speed, current, target);
  run_v17("0");
  check(!stepperRunning, "0/withdrawal: мотор обязан остановиться");
  check(PauseOn, "0/withdrawal: ноль обязан поставить паузу (PauseOn)");
  check(rectManualPauseActive && pairBeginCalls == 1,
        "0/withdrawal: пауза обязана быть ручной (одна пара событий)");
  check(CurrrentStepperSpeed == speed, "0/withdrawal: скорость отбора не обнуляется");
  check(setPumpSpeedCalls == 0 && reportErrorCalls == 0,
        "0/withdrawal: ноль не идёт ни в set_pump_speed(), ни в ошибку разбора");

  // Статус ещё не пересчитан (WITHDRAWAL), а пауза уже стоит: повторный ноль - пусто.
  run_v17("0");
  check(pairBeginCalls == 1, "повторный 0 на паузе: вторая пара событий не открывается");
  SamovarStatusInt = SAMOVAR_STATUS_PAUSED;
  run_v17("0");
  check(pairBeginCalls == 1 && PauseOn, "0 на статусе PAUSED: ничего не меняется");

  run_v13("0");
  check(!PauseOn, "V13=0 после V17=0: пауза снимается");
  check(stepperRunning, "V13=0 после V17=0: отбор обязан возобновиться (мотор крутится)");
  check(stepperMaxSpeed == (float)speed, "V13=0 после V17=0: прежняя скорость мотора");
  check(stepperCurrent == current && stepperTarget == target,
        "V13=0 после V17=0: прежние пройденные шаги и цель");
  check(pairEndCalls == 1 && !rectManualPauseActive, "V13=0: ручная пауза закрыта");
}

int main() {
  zero_then_resume(42, 100, 500);
  zero_then_resume(77, 2000, 9000);

  // Скорость, заданная на паузе, применяется при возобновлении.
  start_withdrawal(42, 100, 500);
  run_v17("0");
  SamovarStatusInt = SAMOVAR_STATUS_PAUSED;
  run_v17("5");
  check(!stepperRunning, "5 на паузе: стоящий мотор не запускается");
  const uint16_t pausedSpeed = CurrrentStepperSpeed;
  check(pausedSpeed != 42 && pausedSpeed > 0, "5 на паузе: новая скорость запомнена");
  run_v13("0");
  check(stepperRunning && stepperMaxSpeed == (float)pausedSpeed,
        "V13=0: отбор продолжается со скоростью, заданной на паузе");

  // Головы со вторым насосом: ноль останавливает I2C-насос, кнопка паузы его запускает.
  reset_fixture();
  SamovarStatusInt = SAMOVAR_STATUS_RECT_WITHDRAWAL;
  rectSecondPumpHeadsRow = true;
  rectSecondPumpRunning = true;
  run_v17("0");
  check(PauseOn && !rectSecondPumpRunning, "0/heads: I2C-насос на паузе");
  check(rectFailCalls == 0, "0/heads: успешная остановка - не авария");
  run_v13("0");
  check(!PauseOn && rectSecondPumpRunning, "V13=0/heads: I2C-насос снова качает");
  check(!stepperRunning, "V13=0/heads: встроенный мотор на головах не запускается");

  reset_fixture();
  SamovarStatusInt = SAMOVAR_STATUS_RECT_WITHDRAWAL;
  rectSecondPumpHeadsRow = true;
  rectSecondPumpRunning = true;
  secondPumpStopOk = false;
  run_v17("0");
  check(rectFailCalls == 1, "0/heads: отказ остановки I2C-насоса обязан стать аварией");

  // Автопауза по датчику: пауза уже стоит, ручной она от нуля не становится.
  start_withdrawal(42, 100, 500);
  SamovarStatusInt = SAMOVAR_STATUS_RECT_AUTOPAUSE;
  stepperRunning = false;
  PauseOn = true;
  program_Wait = true;
  run_v17("0");
  check(pairBeginCalls == 0 && !rectManualPauseActive, "0/autopause: ничего не меняется");

  // Вне отбора тот же мотор крутит калибровка насоса - ноль её не трогает.
  reset_fixture();
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  stepperRunning = true;
  stepperTarget = 999999999;
  CurrrentStepperSpeed = 33;
  run_v17("0");
  check(stepperRunning && !PauseOn, "0/idle: калибровка насоса не останавливается");
  check(CurrrentStepperSpeed == 33 && reportErrorCalls == 0, "0/idle: ничего не меняется");

  reset_fixture();
  run_v17("abc");
  check(reportErrorCalls == 1 && lastReportPin == 17, "abc: одна ошибка разбора на пин 17");
  check(setPumpSpeedCalls == 0 && !PauseOn, "abc: без побочных эффектов");

  start_withdrawal(42, 100, 500);
  modeSwitchInProgressStub = true;
  run_v17("0");
  check(stepperRunning && !PauseOn, "mode_switch_in_progress(): обработчик выходит сразу");

  if (failures != 0) return 1;
  std::cout << "BLYNK_WRITE(V17) zero-pause behaviour checks passed\n";
  return 0;
}
'''


def build_harness(bodies: dict) -> str:
    harness = HARNESS_TEMPLATE
    for key, body in bodies.items():
        harness = harness.replace(f"@{key}@", body)
    return harness


def compile_and_run(harness: str, emit: bool) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-blynk-v17-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "blynk_v17_test.cpp"
        binary = temp / "blynk_v17_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-I", str(ROOT),
                "-I", str(ROOT / "libraries/I2CStepperProtocol/src"),
                str(source), "-o", str(binary),
            ],
            capture_output=True, text=True, check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return 2, ""
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if emit:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode, run_result.stderr


def main() -> int:
    blynk = (ROOT / "Blynk.ino").read_text(encoding="utf-8")
    logic = (ROOT / "logic.h").read_text(encoding="utf-8")
    try:
        bodies = {
            "V17": extract_function_body(blynk, "BLYNK_WRITE(V17)"),
            "V13": extract_function_body(blynk, "BLYNK_WRITE(V13)"),
            "PAUSE_WITHDRAWAL": extract_function_body(logic, "void pause_withdrawal(bool Pause)"),
            "ENTER_MANUAL_PAUSE": extract_function_body(logic, "void enter_manual_pause()"),
        }
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if bodies["V17"].count(ZERO_PAUSE_LINE) != 1:
        print("FAIL: BLYNK_WRITE(V17) zero-pause anchor not found", file=sys.stderr)
        return 1

    code, _ = compile_and_run(build_harness(bodies), True)
    if code != 0:
        return 1

    # Каждая мутация обязана упасть на своём assert-е (ожидаемый фрагмент текста).
    mutants = {
        "zero branch removed": (
            "  if (result.ok() && rate == 0.0f) {\n" + ZERO_PAUSE_LINE + "    return;\n  }\n",
            "",
            "0/withdrawal: ноль обязан поставить паузу",
        ),
        "old direct stopService": (
            "enter_manual_pause();\n", "stopService();\n",
            "V13=0 после V17=0: отбор обязан возобновиться",
        ),
        "PauseOn guard removed": (
            "if (!PauseOn && SamovarStatusInt", "if (SamovarStatusInt",
            "повторный 0 на паузе: вторая пара событий не открывается",
        ),
        "status guard removed": (
            "!PauseOn && SamovarStatusInt == SAMOVAR_STATUS_RECT_WITHDRAWAL",
            "!PauseOn",
            "0/idle: калибровка насоса не останавливается",
        ),
    }
    for name, (anchor, replacement, expected) in mutants.items():
        if bodies["V17"].count(anchor) != 1:
            print(f"FAIL: mutation anchor missing: {name}", file=sys.stderr)
            return 1
        mutated = dict(bodies, V17=bodies["V17"].replace(anchor, replacement, 1))
        code, stderr = compile_and_run(build_harness(mutated), False)
        if code == 2:
            print(f"FAIL: mutation '{name}' broke compilation instead of an assert", file=sys.stderr)
            return 1
        if code == 0 or expected not in stderr:
            print(f"FAIL: mutation '{name}' not caught by '{expected}'; stderr:\n{stderr}",
                  file=sys.stderr)
            return 1
    print("BLYNK_WRITE(V17) zero-pause smoke check passed (behaviour + mutation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
