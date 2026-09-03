#!/usr/bin/env python3
"""Поведенческая проверка нижнего клампа nbk_Po в nbk.h::handle_nbk_stage_work.

Тест вытаскивает РЕАЛЬНЫЙ блок кода (тело "пауза на инерцию вышла" -
if/else if/else понижения-повышения подачи по температуре плюс вычисление
commandNeeded и сама отправка составной команды, [Ремонт-2026-09-02 П11]) из
nbk.h через extract_braced_block_after - без переписывания логики - и
подставляет его в минимальный host-харнесс. Так проверяется реальное
поведение переменной nbk_Po при многократных тиках с температурой ниже
порога, а не наличие конкретной строки в исходнике.

[Ремонт-2026-09-02 П11] "Команду шлём, только если реально другая цель"
переместил currentM/currentP/candidateM/candidateP и решение
commandNeeded ВНУТРЬ извлекаемого блока (раньше их объявлял харнесс) - и
пара nbk_Tb/nbk_Tp теперь читается блоком из SteamSensor/TankSensor.avgTemp
на каждом тике, а не выставляется тестом напрямую.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

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
 private:
  std::string value_;
};
void SendMsg(const String&, MESSAGE_TYPE) {}

// [T2/П10] высокотемпературная ветка (не предмет этого теста, но должна компилироваться).
#define NBK_HIGH_TB_HOLD_TICKS 3
#define NBK_SPILL_DT_MULT 3
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
static float lastSpeed = 0;
static float lastPower = -1.0f;
// Заглушка моделирует мгновенно подтверждённую команду - симметрично
// упрощению, которое уже делал прежний харнесс (без отдельного PENDING).
bool nbk_schedule_actuator_command(float m, float p, NbkActuatorDeadlineTarget, uint32_t, uint16_t) {
  scheduleCalls++;
  lastPower = m;
  lastSpeed = p;
  nbk_M = m;
  nbk_P = p;
  return true;
}
void nbk_enter_safe_wait(const String&) {}

static void run_low_temp_tick() {
@BODY@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // Имитация длительного периода "температура ниже порога": Тб (из
  // TankSensor) ниже nbk_Tn-dT+dД на каждом тике, пар (SteamSensor) держится
  // заведомо выше предела и не мешает - декремент nbk_Po применяется на
  // каждой итерации, как при медленно греющемся или сбойном датчике пара.
  TankSensor.avgTemp = 0.0f;   // заведомо ниже nbk_Tn - nbk_dT + nbk_dD
  SteamSensor.avgTemp = 100.0f; // заведомо выше nbk_Tp_lim
  nbk_Po = 0.4f;               // меньше одного шага dП/10 = 0.05, но нужно много тиков
  nbk_Mo = 100.0f;
  nbk_M = nbk_Mo;
  nbk_P = nbk_Po;

  for (int tick = 0; tick < 200; tick++) {
    fakeMillis += 1000;
    run_low_temp_tick();
    check(nbk_Po >= 0.0f, "nbk_Po ушёл в минус на одном из тиков длительного периода низкой температуры");
    check(nbk_P >= 0.0f, "nbk_P (производная от nbk_Po) ушла в минус");
  }

  check(nbk_Po == 0.0f, "после длительного периода низкой температуры nbk_Po должен зафиксироваться на нуле, а не уйти в минус");
  check(lastSpeed == 0.0f, "последняя команда насосу должна быть 0, а не отрицательной");
  check(lastPower == nbk_Mo,
        "коррекция подачи не должна самовольно менять мощность");

  if (failures != 0) return 1;
  std::cout << "nbk_Po floor clamp behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    code = strip_cpp_comments(source)
    # [Ремонт-2026-09-02 П11] прежний якорь захватывал только первую if-ветку
    # (без commandNeeded/отправки команды, теперь вынесенных за пределы
    # if/else if/else) - берём внешний охватывающий блок целиком.
    anchor = "if (safety_deadline_expired(millis(), nbk_work_next_time))  {"
    body, _ = extract_braced_block_after(code, anchor)
    body = body.replace("\r\n", "\n")
    return HARNESS_TEMPLATE.replace("@BODY@", body)


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-nbk-po-floor-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "nbk_po_floor_test.cpp"
        binary = temp / "nbk_po_floor_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
