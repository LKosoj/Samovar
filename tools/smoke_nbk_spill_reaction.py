#!/usr/bin/env python3
"""Поведенческая проверка [Пролив] (план nbk-2026-09-03-B, T3): быстрая
реакция handle_nbk_stage_work() на пролив браги. Отдельный, более строгий
порог `Тн − NBK_SPILL_DT_MULT * dT + dD` (по умолчанию множитель 3) стоит
ПЕРВОЙ веткой перед обычной просадкой `Тн − dT + dD` - при проливе По
снижается сразу на целый шаг dП (а не на dП/10, как при обычной просадке),
и уходит отдельное предупреждение WARNING_MSG вместо обычного NOTIFY_MSG.

Харнесс вытаскивает РЕАЛЬНОЕ тело "если пауза на инерцию вышла" из
handle_nbk_stage_work() через extract_braced_block_after - тот же якорь и тот
же приём, что и в smoke_nbk_po_floor.py/smoke_nbk_pressure_ceiling.py (блок
C) - актуаторная часть (По/candidateP/candidateM) и блок сообщений [П11]
находятся в одном extracted-теле, поэтому пинятся вместе, одним тиком.

Плюс 3 мутации (каждая обязана провалить харнесс):
  - переставить местами ветку пролива и ветку обычной просадки (текстово) -
    пролив становится недостижим, обычная ветка перехватывает его случаи.
  - NBK_SPILL_DT_MULT 3 -> 1 - порог пролива схлопывается с обычным порогом.
  - шаг снижения По в ветке пролива dП -> dП/10 - пролив перестаёт отличаться
    от обычной просадки по величине коррекции.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]

ANCHOR = "if (safety_deadline_expired(millis(), nbk_work_next_time))  {"

# [Мутация 1] Полный текст веток "пролив" + "обычная просадка" (актуаторная
# часть, до третьей ветки pressureHigh) - swap меняет порядок if/else-if,
# делая пролив недостижимым (обычная ветка шире и проверяется первой).
SPILL_BRANCH = (
    "if (nbk_Tb < nbk_Tn - NBK_SPILL_DT_MULT * nbk_dT + nbk_dD) { // [Пролив] "
    "Тб рухнула намного ниже Тн — снижаем подачу сразу на целый шаг dП, а не на dП/10\n"
    "      nbk_Po -= nbk_dP;\n"
    "      if (nbk_Po < 0) nbk_Po = 0;\n"
    "      candidateP = nbk_Po;\n"
    "      candidateM = nbk_Mo;\n"
    "      nbk_high_temp_ticks = 0;\n"
    "      nbk_high_pressure_ticks = 0; // [Ревью итог 03.09] счётчик «подряд» — любая другая ветка обнуляет\n"
    "    }"
)
NORMAL_BRANCH = (
    "else if ((nbk_Tb < nbk_Tn - nbk_dT + nbk_dD) || (nbk_Tp < nbk_Tp_lim)) {\n"
    "      nbk_Po -= nbk_dP / 10.0;\n"
    "      if (nbk_Po < 0) nbk_Po = 0; // По — подача не может быть отрицательной (по аналогии с 497-498)\n"
    "      candidateP = nbk_Po;\n"
    "      candidateM = nbk_Mo;\n"
    "      nbk_high_temp_ticks = 0; // счётчики «подряд»: просадка прерывает серию перегрева\n"
    "      nbk_high_pressure_ticks = 0; // [Ревью итог 03.09] подача уже снижена — давление ниже потолка не «подряд»\n"
    "    }"
)
TAIL = "else if (pressureHigh)"
ORIGINAL_ORDER_ANCHOR = SPILL_BRANCH + " " + NORMAL_BRANCH + " " + TAIL
_SWAPPED_NORMAL = NORMAL_BRANCH.replace("else if", "if", 1)
_SWAPPED_SPILL = SPILL_BRANCH.replace(
    "if (nbk_Tb < nbk_Tn - NBK_SPILL_DT_MULT", "else if (nbk_Tb < nbk_Tn - NBK_SPILL_DT_MULT", 1
)
SWAPPED_ORDER = _SWAPPED_NORMAL + " " + _SWAPPED_SPILL + " " + TAIL

# [Мутация 2] Значение множителя в самом #define.
SPILL_DEFINE_ANCHOR = "#define NBK_SPILL_DT_MULT 3 // [Пролив] порог пролива: Тн − 3·dT"

# [Мутация 3] Шаг снижения По именно в ветке пролива (актуаторная часть,
# единственное вхождение "nbk_Po -= nbk_dP;" во всём файле - без "/ 10.0").
SPILL_STEP_ANCHOR = "      nbk_Po -= nbk_dP;\n"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum NbkActuatorDeadlineTarget { NBK_ACTUATOR_NO_DEADLINE, NBK_ACTUATOR_OPTIMIZATION_DEADLINE, NBK_ACTUATOR_WORK_DEADLINE };

// [П11] сообщения о коррекции склеиваются через "..." + String(...) + "...".
class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(float value, int) : value_(std::to_string(value)) {}
  String& operator+=(const char* text) { value_ += (text ? text : ""); return *this; }
  String& operator+=(const String& other) { value_ += other.value_; return *this; }
  void reserve(size_t) {}
  bool contains(const char* needle) const { return value_.find(needle) != std::string::npos; }
 private:
  std::string value_;
};

// [Пролив] предмет этого теста.
@SPILL_MULT_DEFINE@

// [T2/П10] высокотемпературная ветка (не предмет этого теста, но должна компилироваться).
#define NBK_HIGH_TB_HOLD_TICKS 3
uint8_t nbk_high_temp_ticks = 0;
float nbk_Po_ceiling = 1000.0f;

// [T1-2026-09-03] ветка по давлению (не предмет этого теста, но должна
// компилироваться) - предикат всегда false, поведение теста не меняется.
uint8_t nbk_high_pressure_ticks = 0;
float pressure_value = 0;
float nbk_pressure_ceiling = 0;
bool nbk_pressure_above_ceiling() { return false; }

float nbk_Tb = 0;
float nbk_Tn = 98.5f;
float nbk_dT = 0.5f;
float nbk_dD = 0;
float nbk_Tp = 100.0f;
float nbk_Tp_lim = 81.0f;
float nbk_P = 0;
float nbk_Po = 0;
float nbk_M = 0;
float nbk_Mo = 100.0f;
float nbk_dP = 0.5f;
uint16_t nbk_column_inertia = 180;
uint16_t nbk_opt_iter = 0;

struct SensorProbe { float avgTemp; };
static SensorProbe TankSensor = {0.0f};
static SensorProbe SteamSensor = {100.0f};

static uint32_t fakeMillis = 1000;
uint32_t millis() { return fakeMillis; }
uint32_t nbk_work_next_time = 0;
uint32_t safety_deadline_after(uint32_t now, uint32_t ms) { return now + ms; }

static int scheduleCalls = 0;
static float lastSpeed = -1.0f;
static float lastPower = -1.0f;
bool nbk_schedule_actuator_command(float m, float p, NbkActuatorDeadlineTarget, uint32_t, uint16_t) {
  scheduleCalls++;
  lastPower = m;
  lastSpeed = p;
  nbk_M = m;
  nbk_P = p;
  return true;
}
void nbk_enter_safe_wait(const String&) {}

static int sendMsgCalls = 0;
static String lastMsg;
static MESSAGE_TYPE lastMsgType = NOTIFY_MSG;
void SendMsg(const String& msg, MESSAGE_TYPE type) {
  sendMsgCalls++;
  lastMsg = msg;
  lastMsgType = type;
}

static void run_work_tick() {
@BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
static bool close(float a, float b) { return (a > b ? a - b : b - a) < 0.001f; }

static void reset_fixture() {
  fakeMillis = 1000;
  nbk_work_next_time = 0;
  nbk_Tn = 98.5f; nbk_dT = 0.5f; nbk_dD = 0.0f;
  nbk_Tp_lim = 81.0f;
  SteamSensor.avgTemp = 100.0f; // заведомо выше Тп_lim - не мешает веткам по Тб
  nbk_Po = 10.0f; nbk_Mo = 100.0f; nbk_M = 100.0f; nbk_P = 10.0f;
  nbk_dP = 0.5f;
  nbk_high_temp_ticks = 0;
  nbk_high_pressure_ticks = 0;
  scheduleCalls = 0; lastSpeed = -1.0f; lastPower = -1.0f;
  sendMsgCalls = 0; lastMsg = String(""); lastMsgType = NOTIFY_MSG;
}

// 1) Обычная просадка (< Тн-dT), но НЕ ниже порога пролива (Тн-3dT) - шаг
// dП/10, без упоминания пролива, тип NOTIFY_MSG.
static void test_normal_dip_no_spill() {
  reset_fixture();
  TankSensor.avgTemp = 97.9f; // < 98.0 (Тн-dT), > 97.0 (Тн-3dT)
  run_work_tick();
  check(close(nbk_Po, 9.95f), "1: обычная просадка обязана снизить По ровно на dП/10 (10-0.05)");
  check(sendMsgCalls == 1, "1: обязано уйти ровно одно сообщение");
  check(!lastMsg.contains("пролив"), "1: обычная просадка не должна упоминать пролив");
  check(lastMsgType == NOTIFY_MSG, "1: обычная просадка обязана слать NOTIFY_MSG, а не WARNING_MSG");
}

// 2) Пролив (< Тн-3dT) - шаг сразу на целый dП, сообщение про пролив, WARNING_MSG.
static void test_spill_full_step() {
  reset_fixture();
  TankSensor.avgTemp = 96.9f; // < 97.0 (Тн-3dT)
  run_work_tick();
  check(close(nbk_Po, 9.5f), "2: пролив обязан снизить По ровно на целый шаг dП (10-0.5)");
  check(sendMsgCalls == 1, "2: обязано уйти ровно одно сообщение");
  check(lastMsg.contains("пролив"), "2: сообщение обязано упоминать пролив");
  check(lastMsgType == WARNING_MSG, "2: пролив обязан слать WARNING_MSG");
}

// 3) Граница РОВНО на пороге пролива (Тб == Тн-3dT) - строгое "<", ветка
// пролива НЕ срабатывает, работает обычная просадка.
static void test_spill_boundary_is_strict() {
  reset_fixture();
  TankSensor.avgTemp = 97.0f; // == Тн-3dT ровно
  run_work_tick();
  check(close(nbk_Po, 9.95f), "3: граница ровно на пороге пролива обязана уйти в обычную ветку (dП/10)");
  check(!lastMsg.contains("пролив"), "3: на границе сообщение не должно упоминать пролив");
  check(lastMsgType == NOTIFY_MSG, "3: на границе обязан быть NOTIFY_MSG");
}

// 4) Пролив одновременно с низким Тп (который сам по себе тоже входил бы в
// условие обычной ветки) - коррекция всё равно ровно -dП, без суммирования.
static void test_spill_not_summed_with_low_steam() {
  reset_fixture();
  TankSensor.avgTemp = 96.9f; // < Тн-3dT (пролив)
  SteamSensor.avgTemp = 50.0f; // < Тп_lim(81) - тоже включил бы обычную ветку
  run_work_tick();
  check(close(nbk_Po, 9.5f), "4: пролив обязан дать ровно -dП, не суммируясь с обычной просадкой по Тп");
  check(lastMsg.contains("пролив"), "4: сообщение обязано быть про пролив, а не про низкий Тп");
}

int main() {
  test_normal_dip_no_spill();
  test_spill_full_step();
  test_spill_boundary_is_strict();
  test_spill_not_summed_with_low_steam();
  if (failures != 0) return 1;
  std::cout << "nbk spill reaction behaviour checks passed\n";
  return 0;
}
'''


def build_harness(nbk_source: str) -> str:
    body, _ = extract_braced_block_after(nbk_source, ANCHOR)
    body = body.replace("\r\n", "\n")

    define_start = nbk_source.find("#define NBK_SPILL_DT_MULT")
    if define_start < 0:
        raise ValueError("NBK_SPILL_DT_MULT define not found in nbk.h")
    define_end = nbk_source.find("\n", define_start)
    spill_mult_define = nbk_source[define_start:define_end].replace("\r", "").strip()

    harness = HARNESS_TEMPLATE.replace("@SPILL_MULT_DEFINE@", spill_mult_define)
    return harness.replace("@BODY@", body)


def compile_and_run(harness: str, emit: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-spill-reaction-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "test.cpp"
        binary = temp / "test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            if emit:
                sys.stderr.write("compile failed:\n")
                sys.stderr.write(compile_result.stdout)
                sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if emit:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode


def mutate_branch_order(source: str) -> str:
    if ORIGINAL_ORDER_ANCHOR not in source:
        raise ValueError("mutation anchor missing: spill/normal branch order")
    return source.replace(ORIGINAL_ORDER_ANCHOR, SWAPPED_ORDER, 1)


def mutate_spill_multiplier(source: str) -> str:
    if SPILL_DEFINE_ANCHOR not in source:
        raise ValueError("mutation anchor missing: NBK_SPILL_DT_MULT define")
    mutated = SPILL_DEFINE_ANCHOR.replace("NBK_SPILL_DT_MULT 3", "NBK_SPILL_DT_MULT 1", 1)
    return source.replace(SPILL_DEFINE_ANCHOR, mutated, 1)


def mutate_spill_step(source: str) -> str:
    if SPILL_STEP_ANCHOR not in source:
        raise ValueError("mutation anchor missing: spill branch dП step")
    mutated = SPILL_STEP_ANCHOR.replace("nbk_Po -= nbk_dP;", "nbk_Po -= nbk_dP / 10.0;", 1)
    return source.replace(SPILL_STEP_ANCHOR, mutated, 1)


def main() -> int:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")

    try:
        harness = build_harness(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if compile_and_run(harness, True) != 0:
        return 1

    mutations = [
        ("swap spill/normal branch order", mutate_branch_order),
        ("NBK_SPILL_DT_MULT 3 -> 1", mutate_spill_multiplier),
        ("spill step dП -> dП/10", mutate_spill_step),
    ]
    for name, mutate_fn in mutations:
        try:
            mutated = mutate_fn(nbk_source)
        except ValueError as error:
            print(f"FAIL: {error}", file=sys.stderr)
            return 1
        if mutated == nbk_source:
            print(f"FAIL: mutation had no effect: {name}", file=sys.stderr)
            return 1
        mutated_harness = build_harness(mutated)
        if compile_and_run(mutated_harness, False) == 0:
            print(f"FAIL: mutation survived (expected failure): {name}", file=sys.stderr)
            return 1

    print("nbk spill reaction checks (behaviour + mutations) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
