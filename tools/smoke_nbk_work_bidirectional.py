#!/usr/bin/env python3
"""Поведенческая проверка [T2]: двустороннее регулирование По в handle_nbk_stage_work.

Тест вытаскивает РЕАЛЬНЫЙ блок кода (else-if ветку повышения подачи при
устойчиво высокой Тб) из nbk.h через extract_braced_block_after — без
переписывания логики — и подставляет его в минимальный host-харнесс, замокав
только downstream-вызовы (set_current_power, SetSpeed, fromPower).

Регресс, который тест защищает: раньше регулирование По в Работе было
ОДНОСТОРОННИМ (только вниз при просадке Тб). Задача 2 добавила счётчик
nbk_high_temp_ticks и повышение По на dП/10 после NBK_HIGH_TB_HOLD_TICKS
тиков подряд устойчиво высокой Тб, с клампом на nbk_Po_ceiling и сбросом
счётчика при любом вмешательстве (nbk_P/nbk_M разошлись с nbk_Po/nbk_Mo).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]

ANCHOR = "else if (nbk_Tb > nbk_Tn + nbk_dT + nbk_dD) { // [T2] Тб держится выше Тн+dT"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

@HOLD_TICKS_DEFINE@

float nbk_P = 0;
float nbk_Po = 0;
float nbk_M = 0;
float nbk_Mo = 0;
float nbk_dP = 0;
float nbk_Po_ceiling = 0;
uint8_t nbk_high_temp_ticks = 0;

static int setSpeedCalls = 0;
static float lastSpeed = -1.0f;
static int powerCalls = 0;
static float lastPower = -1.0f;

// Заглушки НЕ static: единственный вызов каждой лежит во вклеенном теле блока
// (run_high_temp_tick ниже), и со static мутация, убравшая вызов, роняла бы
// компилятор по unused-function вместо содержательного assert-а.
//
// fromPower обязана быть ОТЛИЧИМА от тождества (см. smoke_nbk_po_floor.py) -
// иначе тест не поймал бы утечку сырых ватт в регулятор напряжения.
inline float fromPower(float m) { return m * 2.0f; }
inline void set_current_power(float v) { powerCalls++; lastPower = v; }
inline void SetSpeed(float v) { setSpeedCalls++; lastSpeed = v; }

static void run_high_temp_tick() {
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
  nbk_Po = po;
  nbk_dP = dp;
  nbk_Po_ceiling = ceiling;
  nbk_Mo = 100.0f;
  nbk_M = nbk_Mo;
  nbk_P = nbk_Po;
  nbk_high_temp_ticks = 0;
  setSpeedCalls = 0;
  powerCalls = 0;
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
    check(powerCalls == t, "set_current_power должен вызываться на каждом тике блока");
    check(setSpeedCalls == t, "SetSpeed должен вызываться на каждом тике блока");
  }

  run_high_temp_tick(); // NBK_HIGH_TB_HOLD_TICKS-й тик подряд без вмешательств
  check(nbk_Po == po + dp / 10.0f, "после NBK_HIGH_TB_HOLD_TICKS тиков подряд По должна вырасти РОВНО на dП/10");
  check(nbk_high_temp_ticks == 0, "счётчик обязан сброситься сразу после применения повышения");
  check(lastPower == fromPower(nbk_Mo), "мощность в регуляторе должна оставаться конвертированной nbk_Mo");
  check(lastSpeed == nbk_Po, "последняя команда насосу должна совпадать с обновлённой По");

  // Второй полный цикл: попытка ещё раз поднять По должна упереться в потолок.
  for (int t = 0; t < NBK_HIGH_TB_HOLD_TICKS; t++) {
    run_high_temp_tick();
  }
  check(nbk_Po == ceiling, "По обязана зафиксироваться РОВНО на nbk_Po_ceiling при достижении потолка");
  check(nbk_Po <= ceiling, "По не должна превышать nbk_Po_ceiling ни при каких обстоятельствах");
}

// Вмешательство (nbk_P разошлась с nbk_Po) обязано сбросить счётчик тиков,
// иначе повышение По применится, несмотря на постороннее изменение подачи.
static void test_intervention_resets_counter_for(float po, float dp) {
  reset_fixture(po, dp, po + 100.0f);

  for (int t = 1; t < NBK_HIGH_TB_HOLD_TICKS; t++) {
    run_high_temp_tick();
  }
  check(nbk_high_temp_ticks == static_cast<uint8_t>(NBK_HIGH_TB_HOLD_TICKS - 1),
        "перед вмешательством счётчик должен успеть накопиться");

  nbk_P = nbk_Po + 5.0f; // постороннее вмешательство: подача разошлась с По
  run_high_temp_tick();
  check(nbk_high_temp_ticks == 0, "РЕГРЕСС: вмешательство (nbk_P != nbk_Po) обязано сбрасывать счётчик тиков");
  check(nbk_Po == po, "По не должна меняться в тике, где обнаружено вмешательство");

  // Новый полный цикл без вмешательств снова должен поднять По ровно один раз.
  for (int t = 1; t < NBK_HIGH_TB_HOLD_TICKS; t++) {
    run_high_temp_tick();
    check(nbk_Po == po, "По не должна меняться раньше нового полного цикла после сброса счётчика");
  }
  run_high_temp_tick();
  check(nbk_Po == po + dp / 10.0f, "после сброса счётчика новый полный цикл тиков обязан снова поднять По");
}

int main() {
  test_hold_and_clamp_for(5.0f, 1.0f);
  test_hold_and_clamp_for(50.0f, 2.0f);
  test_intervention_resets_counter_for(5.0f, 1.0f);
  test_intervention_resets_counter_for(50.0f, 2.0f);
  if (failures != 0) return 1;
  std::cout << "nbk bidirectional Po regulation behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    body, _ = extract_braced_block_after(source, ANCHOR)
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
