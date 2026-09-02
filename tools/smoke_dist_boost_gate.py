#!/usr/bin/env python3
"""[T21-1] run_dist_program() должна гасить бустерный ТЭН при ПЕРВОМ переходе
между строками программы дистилляции - независимо от того, каким было Power
покидаемой строки.

До правки условие было `!distBoostGated && program[num - 1].Power != 0`.
Power == 0 в этой прошивке означает "не трогать регулятор" (сквозной режим,
см. apply_program_power_row() в power_regulator.h), а НЕ "мощность не задана".
Из-за лишнего операнда бустер не гас, если покидаемая строка имела Power == 0 -
BOOST продолжал греть до конца сессии.

Тест компилирует РЕАЛЬНОЕ тело run_dist_program() (distiller.h) в изолированном
харнессе (тот же набор моков, что и в smoke_dist_last_row_capacity.py) и
проверяет: при program[0].Power == 0 переход run_dist_program(1) обязан вызвать
heater_boost_output_off() ровно один раз. Откат правки (восстановление
`&& program[num - 1].Power != 0`) валит этот assert, так как условие снова
станет ложным для Power == 0.

[PKG-B, П4] Второй харнесс (BOIL_FRONT_HARNESS_TEMPLATE) проверяет новый гейт в
distiller_proc(): если SamSetup.UseST == false, BOOST обязан гаситься уже по
фронту начала кипения (boil_started && !distBoilStartedPrev), не дожидаясь
первого перехода строки программы - иначе однострочная программа или поздний
переход держат BOOST включённым весь процесс кипения вопреки настройке
пользователя. Извлекается РЕАЛЬНЫЙ блок `if (boil_started && ...) { ... }` из
distiller_proc() через extract_braced_block_after.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "void run_dist_program(uint8_t num)"
BOIL_FRONT_TOKEN = "if (boil_started && !distBoilStartedPrev)"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

#define SAMOVAR_USE_POWER 1

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };

struct String {
  std::string s;
  String() {}
  String(const char* value) : s(value) {}
  String(int value) : s(std::to_string(value)) {}
  String operator+(const String& other) const { String r; r.s = s + other.s; return r; }
};
static String operator+(const char* left, const String& right) {
  String r; r.s = std::string(left) + right.s; return r;
}

using ProgramType = char;
static const ProgramType PROGRAM_TYPE_NONE = 0;
struct WProgram { ProgramType WType = PROGRAM_TYPE_NONE; uint8_t capacity_num = 0; float Power = 0; };
static bool program_type_empty(ProgramType value) { return value == PROGRAM_TYPE_NONE; }

static const uint8_t PROGRAM_END = 8;

static WProgram program[PROGRAM_END];
static uint8_t ProgramLen = 0;
static uint8_t ProgramNum = 0;

struct TimePredictor {
  unsigned long startTime = 0;
  float initialAlcohol = 0;
  float initialSteamAlcohol = 0;
  float initialTemp = 0;
  unsigned long lastUpdateTime = 0;
  float remainingTime = 0;
  float rowPredictedTotalTime = 0;
  bool rowPredictionAvailable = false;
  bool baselineValid = false;
};
static TimePredictor timePredictor;

enum DistPredictionReason { DIST_PREDICTION_AWAITING_BOIL = 0, DIST_PREDICTION_COLLECTING };
static DistPredictionReason distRowPredictionReason = DIST_PREDICTION_AWAITING_BOIL;

struct Sensor { float avgTemp = 0; float StartProgTemp = 0; };
static Sensor TankSensor, SteamSensor, PipeSensor, WaterSensor;

static bool distBoostGated = false;

static unsigned long fakeMillis = 0;
static unsigned long millis() { return fakeMillis; }
static float get_alcohol(float t) { return 100.0f - t; }
static float get_steam_alcohol(float t) { return 100.0f - t; }

static void set_capacity(uint8_t) {}
static void apply_program_power_row(float) {}

// Заглушка НЕ static: единственный вызов лежит внутри вклеенного тела
// run_dist_program() ниже. Со static мутация (откат к
// `&& program[num - 1].Power != 0`), убирающая вызов при Power == 0,
// уводила бы диагностику в unused-function/-Werror вместо содержательного
// assert-а по boostCalls.
int boostCalls = 0;
void heater_boost_output_off() { boostCalls++; }

static int sendMsgCalls = 0;
static void SendMsg(const String&, MESSAGE_TYPE) { sendMsgCalls++; }

@RUN_DIST_PROGRAM_BODY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}

int main() {
  // Программа из двух строк; уходящая строка 0 имеет Power == 0 (сквозной режим -
  // "не трогать регулятор", а не "мощность не задана").
  program[0].WType = 'T'; program[0].capacity_num = 1; program[0].Power = 0.0f;
  program[1].WType = 'T'; program[1].capacity_num = 2; program[1].Power = 20.0f;
  ProgramLen = 2;
  ProgramNum = 0;
  distBoostGated = false;
  boostCalls = 0;

  run_dist_program(1);

  check(boostCalls == 1,
        "переход со строки с Power==0 обязан один раз погасить BOOST (heater_boost_output_off)");
  check(distBoostGated, "distBoostGated должен защёлкнуться после первого перехода");

  if (failures != 0) return 1;
  std::cout << "run_dist_program BOOST gate (Power==0 row) checks passed\n";
  return 0;
}
'''

BOIL_FRONT_HARNESS_TEMPLATE = r'''
#include <iostream>

struct Sensor { float avgTemp = 0; float StartProgTemp = 0; };
static Sensor TankSensor;

struct Setup { bool UseST = true; };
static Setup SamSetup;

static bool boil_started = false;
static bool distBoilStartedPrev = false;
static bool distBoostGated = false;

static int resetCalls = 0;
static void resetTimePredictor() { resetCalls++; }

static int boostCalls = 0;
static void heater_boost_output_off() { boostCalls++; }

static void run_boil_front_block() {
  if (boil_started && !distBoilStartedPrev) {
@BOIL_FRONT_BLOCK@
  }
  distBoilStartedPrev = boil_started;
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}

static void reset_state(bool useSt, bool boostGated, bool boilStarted, bool boilStartedPrev) {
  SamSetup.UseST = useSt;
  distBoostGated = boostGated;
  boil_started = boilStarted;
  distBoilStartedPrev = boilStartedPrev;
  resetCalls = 0;
  boostCalls = 0;
}

int main() {
  // Не фронт кипения (уже шёл boil_started на прошлом тике) - гейт не должен
  // сработать вовсе, независимо от UseST. Контроль, что мы не сломали исходное
  // условие фронта.
  reset_state(/*useSt=*/false, /*boostGated=*/false, /*boilStarted=*/true, /*boilStartedPrev=*/true);
  run_boil_front_block();
  check(resetCalls == 0, "не-фронт (boil уже шёл): resetTimePredictor не должен вызываться");
  check(boostCalls == 0, "не-фронт (boil уже шёл): BOOST не должен гаситься");

  // Фронт кипения, UseST == true (пользователь хочет держать BOOST при кипении):
  // старое поведение - гасим только переходом строки, здесь BOOST не трогаем.
  reset_state(/*useSt=*/true, /*boostGated=*/false, /*boilStarted=*/true, /*boilStartedPrev=*/false);
  run_boil_front_block();
  check(resetCalls == 1, "фронт кипения обязан вызвать resetTimePredictor ровно один раз");
  check(boostCalls == 0, "UseST == true: фронт кипения не должен гасить BOOST");
  check(!distBoostGated, "UseST == true: distBoostGated не должен взводиться по фронту");

  // Фронт кипения, UseST == false, BOOST ещё не погашен - новый гейт обязан
  // погасить его один раз прямо по фронту, не дожидаясь перехода строки.
  reset_state(/*useSt=*/false, /*boostGated=*/false, /*boilStarted=*/true, /*boilStartedPrev=*/false);
  run_boil_front_block();
  check(resetCalls == 1, "фронт кипения обязан вызвать resetTimePredictor ровно один раз");
  check(boostCalls == 1, "UseST == false: фронт кипения обязан один раз погасить BOOST");
  check(distBoostGated, "UseST == false: distBoostGated должен защёлкнуться по фронту");

  // Фронт кипения, UseST == false, но BOOST уже погашен переходом строки раньше -
  // повторно гасить не должны (защёлка distBoostGated).
  reset_state(/*useSt=*/false, /*boostGated=*/true, /*boilStarted=*/true, /*boilStartedPrev=*/false);
  run_boil_front_block();
  check(boostCalls == 0, "UseST == false, но уже погашен переходом строки: повторного гашения быть не должно");

  if (failures != 0) return 1;
  std::cout << "distiller_proc boiling-front BOOST gate checks passed\n";
  return 0;
}
'''


def build_harness(dist_source: str) -> str:
    body = extract_function_body(dist_source, SIGNATURE)
    return HARNESS_TEMPLATE.replace(
        "@RUN_DIST_PROGRAM_BODY@", "void run_dist_program(uint8_t num) {" + body + "}"
    )


def build_boil_front_harness(dist_source: str) -> str:
    block, _ = extract_braced_block_after(dist_source, BOIL_FRONT_TOKEN)
    return BOIL_FRONT_HARNESS_TEMPLATE.replace("@BOIL_FRONT_BLOCK@", block)


def compile_and_run(harness: str, name: str = "dist_boost_gate_test") -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-dist-boost-gate-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / f"{name}.cpp"
        binary = temp / name
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write("compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    dist_source = (ROOT / "distiller.h").read_text(encoding="utf-8")
    try:
        harness = build_harness(dist_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    result = compile_and_run(harness)
    if result != 0:
        return result

    try:
        boil_front_harness = build_boil_front_harness(dist_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    result = compile_and_run(boil_front_harness, name="dist_boil_front_gate_test")
    if result != 0:
        return result

    # [PKG-B, П4] Мутация: убираем условие UseST - гейт срабатывает всегда, даже
    # когда пользователь явно хочет держать BOOST включённым при кипении.
    mutant = boil_front_harness.replace(
        "if (!SamSetup.UseST && !distBoostGated) {",
        "if (!distBoostGated) {",
        1,
    )
    if mutant == boil_front_harness:
        print("FAIL: не удалось построить мутацию boiling-front BOOST gate", file=sys.stderr)
        return 1
    if compile_and_run(mutant, name="dist_boil_front_gate_mutant") == 0:
        print("FAIL: мутация boiling-front BOOST gate пережила тест", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
