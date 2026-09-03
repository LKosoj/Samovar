#!/usr/bin/env python3
"""Поведенческая проверка [T2]: двустороннее регулирование По в handle_nbk_stage_work.

Тест вытаскивает РЕАЛЬНЫЙ блок кода ("пауза на инерцию вышла": if/else if/else
понижения-повышения подачи по температуре плюс вычисление commandNeeded и
саму отправку составной команды, [Ремонт-2026-09-02 П11]) из nbk.h через
extract_braced_block_after — без переписывания логики — и подставляет его в
минимальный host-харнесс. Тб/Тп теперь читаются блоком из
SteamSensor/TankSensor.avgTemp на каждом тике (как и в
smoke_nbk_po_floor.py — тот же якорь, тот же приём).

Регресс, который тест защищает: раньше регулирование По в Работе было
ОДНОСТОРОННИМ (только вниз при просадке Тб). Задача 2 добавила счётчик
nbk_high_temp_ticks и повышение По на dП/10 после NBK_HIGH_TB_HOLD_TICKS
тиков подряд устойчиво высокой Тб, с клампом на nbk_Po_ceiling.

[Ремонт-2026-09-02 П4, план раздел 4] Кейс «вмешательство сбрасывает счётчик»
УДАЛЁН: условия «не было вмешательств» перед повышением/понижением По убраны
из реального кода (сброс nbk_high_temp_ticks в else-ветке тоже убран) —
блокировка ручного управления теперь отдельная зона ответственности
(nbk_manual_control_locked, пинится в smoke_nbk_manual_control_lock.py).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

ANCHOR = "if (safety_deadline_expired(millis(), nbk_work_next_time))  {"

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

@HOLD_TICKS_DEFINE@
#define NBK_SPILL_DT_MULT 3

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
float nbk_Mo = 0;
float nbk_dP = 0;
float nbk_Po_ceiling = 0;
uint8_t nbk_high_temp_ticks = 0;
uint16_t nbk_column_inertia = 180;
uint16_t nbk_opt_iter = 0;

struct SensorProbe { float avgTemp; };
static SensorProbe TankSensor = {0.0f};
static SensorProbe SteamSensor = {100.0f};

static uint32_t fakeMillis = 1000;
uint32_t millis() { return fakeMillis; }
uint32_t nbk_work_next_time = 0;
uint32_t safety_deadline_after(uint32_t now, uint32_t ms) { return now + ms; }

static float lastSpeed = -1.0f;
static float lastPower = -1.0f;
// Заглушка моделирует мгновенно подтверждённую команду - симметрично
// smoke_nbk_po_floor.py.
bool nbk_schedule_actuator_command(float m, float p, NbkActuatorDeadlineTarget, uint32_t, uint16_t) {
  lastPower = m;
  lastSpeed = p;
  nbk_M = m;
  nbk_P = p;
  return true;
}
void nbk_enter_safe_wait(const String&) {}

static void run_high_temp_tick() {
  fakeMillis += 1000;
@BODY@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture(float po, float dp, float ceiling) {
  // Тб устойчиво выше Тн+dT+dД, Тп устойчиво выше предела - только
  // высокотемпературная ветка [T2] должна срабатывать.
  TankSensor.avgTemp = nbk_Tn + nbk_dT + nbk_dD + 5.0f;
  SteamSensor.avgTemp = 100.0f;
  nbk_Po = po;
  nbk_dP = dp;
  nbk_Po_ceiling = ceiling;
  nbk_Mo = 100.0f;
  nbk_M = nbk_Mo;
  nbk_P = nbk_Po;
  nbk_high_temp_ticks = 0;
  lastPower = -1.0f;
  lastSpeed = -1.0f;
}

// Тики 1..(HOLD-1) не должны менять По, HOLD-й тик обязан поднять её на
// dП/10 и сбросить счётчик. Повторный цикл, упирающийся в потолок, должен
// зафиксироваться РОВНО на nbk_Po_ceiling, а не превысить его.
static void test_hold_and_clamp_for(float po, float dp) {
  const float ceiling = po + dp / 10.0f * 1.5f; // между одним и двумя шагами повышения
  reset_fixture(po, dp, ceiling);

  for (int t = 1; t < NBK_HIGH_TB_HOLD_TICKS; t++) {
    run_high_temp_tick();
    check(nbk_Po == po, "По не должна меняться раньше, чем счётчик наберёт NBK_HIGH_TB_HOLD_TICKS тиков подряд");
    check(nbk_high_temp_ticks == static_cast<uint8_t>(t), "счётчик тиков высокой Тб должен расти на каждом тике без вмешательств");
  }

  run_high_temp_tick(); // NBK_HIGH_TB_HOLD_TICKS-й тик подряд без вмешательств
  check(nbk_Po == po + dp / 10.0f, "после NBK_HIGH_TB_HOLD_TICKS тиков подряд По должна вырасти РОВНО на dП/10");
  check(nbk_high_temp_ticks == 0, "счётчик обязан сброситься сразу после применения повышения");
  check(lastPower == nbk_Mo, "коррекция подачи не должна менять мощность");
  check(lastSpeed == nbk_Po, "последняя команда насосу должна совпадать с обновлённой По");

  // Второй полный цикл: попытка ещё раз поднять По должна упереться в потолок.
  for (int t = 0; t < NBK_HIGH_TB_HOLD_TICKS; t++) {
    run_high_temp_tick();
  }
  check(nbk_Po == ceiling, "По обязана зафиксироваться РОВНО на nbk_Po_ceiling при достижении потолка");
  check(nbk_Po <= ceiling, "По не должна превышать nbk_Po_ceiling ни при каких обстоятельствах");
}

int main() {
  test_hold_and_clamp_for(5.0f, 1.0f);
  test_hold_and_clamp_for(50.0f, 2.0f);
  if (failures != 0) return 1;
  std::cout << "nbk bidirectional Po regulation behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    code = strip_cpp_comments(source)
    body, _ = extract_braced_block_after(code, ANCHOR)
    body = body.replace("\r\n", "\n")

    define_start = source.find("#define NBK_HIGH_TB_HOLD_TICKS")
    if define_start < 0:
        raise ValueError("NBK_HIGH_TB_HOLD_TICKS define not found in nbk.h")
    define_end = source.find("\n", define_start)
    hold_ticks_define = source[define_start:define_end].replace("\r", "").strip()

    harness = HARNESS_TEMPLATE.replace("@HOLD_TICKS_DEFINE@", hold_ticks_define)
    harness = harness.replace("@BODY@", body)
    return harness


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-nbk-work-bidirectional-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "nbk_work_bidirectional_test.cpp"
        binary = temp / "nbk_work_bidirectional_test"
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
