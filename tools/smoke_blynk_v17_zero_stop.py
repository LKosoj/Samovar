#!/usr/bin/env python3
"""Поведенческая проверка BLYNK_WRITE(V17) (Blynk.ino): ноль обязан штатно
останавливать отбор.

До правки нулевой вход шёл через get_speed_from_rate(0), которая зажимает
результат СНИЗУ до 1 (минимальная скорость мотора), а затем через
set_pump_speed(1, true) - эта функция внутри себя зовёт stopService() и тут же
startService(), так что насос не останавливался, а полз на минимальной
скорости. Правка обрабатывает rate==0 ДО строгого парсера и зовёт
stopService() напрямую, без пересчёта скорости.

После код-ревью ветка rate==0 дополнительно проверяет тот же статус, что и
set_pump_speed() (logic.h): тот же шаговый двигатель используют калибровка
насоса, HopStepperStep() и самотест, и V17=0 вне отбора не должен обрывать
их работу. После остановки CurrrentStepperSpeed и ActualVolumePerHour
обнуляются - как и в остальных точках остановки отбора (WebServer.ino,
alarm.h, I2CStepper.h, pause_withdrawal в logic.h) - иначе телеметрия V9 и
расчёт флегмового числа продолжают считать по старой скорости.

Тест вытаскивает РЕАЛЬНОЕ тело BLYNK_WRITE(V17) из Blynk.ino (extract_function_body)
и компилирует его g++-харнессом. Разбор числа - настоящие parse_finite_float/
parse_control_rate_steps из control_numeric_input.h (включены как есть, не
переписаны); мокаются только истинно внешние побочные эффекты: stopService(),
set_pump_speed(), report_blynk_numeric_error(), mode_switch_in_progress(), а
также SamovarStatusInt/CurrrentStepperSpeed/ActualVolumePerHour.

Мутационная проверка: удаляет из извлечённого тела ветку "rate==0 -> статус +
stopService() + обнуление" целиком (та самая правка) - без неё сценарий "0"
обязан начать проваливаться (stopService() не позовётся, вместо этого
сработает строгий парсер и report_blynk_numeric_error). Если мутация не
ловится - тест сам ничего не проверяет и обманывает.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "BLYNK_WRITE(V17)"

# Ветка фикса: ноль обрабатывается ДО строгого парсера, но только в статусе,
# который проверяет и set_pump_speed() (logic.h) - вне отбора это no-op.
# Используется и как якорь для мутации (её отсутствие в теле - ошибка теста),
# и как сама мутация (её вырезание должно завалить сценарий "0").
ZERO_STOP_BRANCH = (
    "  if (result.ok() && rate == 0.0f) {\n"
    "    if (SamovarStatusInt == SAMOVAR_STATUS_RECT_WITHDRAWAL || SamovarStatusInt == SAMOVAR_STATUS_RECT_AUTOPAUSE || SamovarStatusInt == SAMOVAR_STATUS_PAUSED) {\n"
    "      stopService();\n"
    "      CurrrentStepperSpeed = 0;\n"
    "      ActualVolumePerHour = 0;\n"
    "    }\n"
    "    return;\n"
    "  }\n"
)

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

#include "control_numeric_input.h"

// ---- Моки истинно внешних зависимостей (не-static) ----
static bool modeSwitchInProgressStub = false;
bool mode_switch_in_progress() { return modeSwitchInProgressStub; }

struct SetupEEPROM {
  uint16_t StepperStepMl = 1000;
};
static SetupEEPROM SamSetup;

// ---- Статус отбора (тот же предикат, что и set_pump_speed() в logic.h) ----
static const int16_t SAMOVAR_STATUS_IDLE = 0;
static const int16_t SAMOVAR_STATUS_RECT_WITHDRAWAL = 10;
static const int16_t SAMOVAR_STATUS_RECT_AUTOPAUSE = 15;
static const int16_t SAMOVAR_STATUS_PAUSED = 40;
static const int16_t SAMOVAR_STATUS_RECT_ACCEL = 50;
static int16_t SamovarStatusInt = SAMOVAR_STATUS_IDLE;

// ---- Скорость/производительность, которые обязана обнулять остановка ----
static uint16_t CurrrentStepperSpeed = 0;
static float ActualVolumePerHour = 0.0f;

static int stopServiceCalls = 0;
void stopService() { stopServiceCalls++; }

static int setPumpSpeedCalls = 0;
static float lastPumpSpeed = -1.0f;
static bool lastContinueProcess = false;
void set_pump_speed(float pumpspeed, bool continue_process, bool updateBase = true) {
  (void)updateBase;
  setPumpSpeedCalls++;
  lastPumpSpeed = pumpspeed;
  lastContinueProcess = continue_process;
}

static int reportErrorCalls = 0;
static uint8_t lastReportPin = 0;
static NumericParseError lastReportError = NUMERIC_PARSE_OK;
void report_blynk_numeric_error(uint8_t virtualPin, NumericParseResult result) {
  reportErrorCalls++;
  lastReportPin = virtualPin;
  lastReportError = result.error;
}

struct BlynkParamMock {
  const char* text;
  const char* asStr() const { return text; }
};

// ---- Реальное тело BLYNK_WRITE(V17) (Blynk.ino) под тестом ----
static void run_v17_handler(const char* input) {
  BlynkParamMock param{input};
@BODY@
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
  stopServiceCalls = 0;
  setPumpSpeedCalls = 0;
  lastPumpSpeed = -1.0f;
  lastContinueProcess = false;
  reportErrorCalls = 0;
  lastReportPin = 0;
  lastReportError = NUMERIC_PARSE_OK;
  SamSetup.StepperStepMl = 1000;
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  // Ненулевые метки - чтобы "не тронуто" и "обнулено" различались в проверках.
  CurrrentStepperSpeed = 42;
  ActualVolumePerHour = 99.0f;
}

int main() {
  // Сценарий 1а: "0" при статусе отбора (RECT_WITHDRAWAL) - штатная остановка
  // БЕЗ пересчёта скорости, со сбросом CurrrentStepperSpeed/ActualVolumePerHour
  // (главная проверка правки + [Ревью] замечание 2).
  reset_fixture();
  SamovarStatusInt = SAMOVAR_STATUS_RECT_WITHDRAWAL;
  run_v17_handler("0");
  check(stopServiceCalls == 1, "0/withdrawal: stopService() должен быть вызван ровно один раз");
  check(setPumpSpeedCalls == 0, "0/withdrawal: set_pump_speed() не должен вызываться при нулевом входе");
  check(reportErrorCalls == 0, "0/withdrawal: нулевой вход валиден, ошибка не репортится");
  check(CurrrentStepperSpeed == 0, "0/withdrawal: CurrrentStepperSpeed должен быть обнулён");
  check(ActualVolumePerHour == 0.0f, "0/withdrawal: ActualVolumePerHour должен быть обнулён");

  // Сценарий 1б: "0" вне отбора (IDLE/разгон) - обработчик не должен трогать
  // посторонний шаговый (калибровку насоса, HopStepperStep(), самотест) -
  // [Ревью] замечание 1. Ничего не вызывается, ничего не меняется.
  reset_fixture();
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  run_v17_handler("0");
  check(stopServiceCalls == 0, "0/idle: stopService() не должен вызываться вне отбора");
  check(setPumpSpeedCalls == 0, "0/idle: set_pump_speed() не должен вызываться при нулевом входе");
  check(reportErrorCalls == 0, "0/idle: нулевой вход валиден, ошибка не репортится");
  check(CurrrentStepperSpeed == 42, "0/idle: CurrrentStepperSpeed не должен меняться");
  check(ActualVolumePerHour == 99.0f, "0/idle: ActualVolumePerHour не должен меняться");

  reset_fixture();
  SamovarStatusInt = SAMOVAR_STATUS_RECT_ACCEL;
  run_v17_handler("0");
  check(stopServiceCalls == 0, "0/accel: stopService() не должен вызываться во время разгона");
  check(CurrrentStepperSpeed == 42, "0/accel: CurrrentStepperSpeed не должен меняться");
  check(ActualVolumePerHour == 99.0f, "0/accel: ActualVolumePerHour не должен меняться");

  // Сценарии 2 и 3: "5" и "10" - разные ненулевые расходы обязаны давать
  // РАЗНЫЕ скорости насоса (ловит мутацию "всегда одна и та же скорость").
  reset_fixture();
  run_v17_handler("5");
  check(stopServiceCalls == 0, "5: stopService() не должен вызываться при ненулевом входе");
  check(setPumpSpeedCalls == 1, "5: set_pump_speed() должен быть вызван ровно один раз");
  check(lastContinueProcess == true, "5: continue_process должен быть true");
  check(lastPumpSpeed > 0.0f, "5: скорость должна быть положительной");
  float speedFor5 = lastPumpSpeed;

  reset_fixture();
  run_v17_handler("10");
  check(setPumpSpeedCalls == 1, "10: set_pump_speed() должен быть вызван ровно один раз");
  check(lastPumpSpeed > 0.0f, "10: скорость должна быть положительной");
  float speedFor10 = lastPumpSpeed;
  check(speedFor5 != speedFor10, "5 л/ч и 10 л/ч должны давать РАЗНУЮ скорость насоса");

  // Сценарий 4: невалидная строка - штатная ошибка разбора, без побочных
  // эффектов (ни stopService, ни set_pump_speed).
  reset_fixture();
  run_v17_handler("abc");
  check(reportErrorCalls == 1, "abc: должна быть ровно одна ошибка разбора");
  check(lastReportPin == 17, "abc: ошибка должна репортиться на пин 17");
  check(lastReportError != NUMERIC_PARSE_OK, "abc: код ошибки не должен быть NUMERIC_PARSE_OK");
  check(stopServiceCalls == 0, "abc: stopService() не должен вызываться при ошибке разбора");
  check(setPumpSpeedCalls == 0, "abc: set_pump_speed() не должен вызываться при ошибке разбора");

  // Сценарий 5: mode_switch_in_progress() - обработчик обязан выйти сразу,
  // не трогая ни один внешний вызов.
  reset_fixture();
  modeSwitchInProgressStub = true;
  run_v17_handler("5");
  check(stopServiceCalls == 0 && setPumpSpeedCalls == 0 && reportErrorCalls == 0,
        "mode_switch_in_progress(): обработчик не должен вызывать побочные эффекты");

  if (failures != 0) return 1;
  std::cout << "BLYNK_WRITE(V17) zero-stop behaviour checks passed\n";
  return 0;
}
'''


def build_harness(body: str) -> str:
    return HARNESS_TEMPLATE.replace("@BODY@", body)


def compile_and_run(harness: str, emit: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-blynk-v17-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "blynk_v17_test.cpp"
        binary = temp / "blynk_v17_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-I", str(ROOT),
                str(source), "-o", str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            if emit:
                sys.stderr.write(compile_result.stdout)
                sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if emit:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    source = (ROOT / "Blynk.ino").read_text(encoding="utf-8")
    try:
        body = extract_function_body(source, SIGNATURE)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if ZERO_STOP_BRANCH not in body:
        print("FAIL: BLYNK_WRITE(V17) zero-stop anchor not found - has the fix been reworded?",
              file=sys.stderr)
        return 1

    if compile_and_run(build_harness(body), True) != 0:
        return 1

    # Мутация: вырезаем ветку "rate==0 -> stopService()" целиком - имитация
    # регресса к поведению до правки (ноль снова уходит в строгий парсер).
    mutated = body.replace(ZERO_STOP_BRANCH, "", 1)
    if mutated == body:
        print("FAIL: zero-stop mutation anchor missing", file=sys.stderr)
        return 1
    if compile_and_run(build_harness(mutated), False) == 0:
        print("FAIL: zero-stop mutation survived (test does not actually check the fix)",
              file=sys.stderr)
        return 1

    print("BLYNK_WRITE(V17) zero-stop smoke check passed (behaviour + mutation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
