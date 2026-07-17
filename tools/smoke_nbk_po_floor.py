#!/usr/bin/env python3
"""Поведенческая проверка нижнего клампа nbk_Po в nbk.h::handle_nbk_stage_work.

Тест вытаскивает РЕАЛЬНЫЙ блок кода (if-ветку понижения подачи при низкой
температуре/паре ниже предела) из nbk.h через extract_braced_block_after —
без переписывания логики — и подставляет его в минимальный host-харнесс,
замокав только downstream-вызовы (set_current_power, SetSpeed, fromPower).
Так проверяется реальное поведение переменной nbk_Po при многократных тиках
с температурой ниже порога, а не наличие конкретной строки в исходнике.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

HARNESS_TEMPLATE = r'''
#include <iostream>

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

static int setSpeedCalls = 0;
static float lastSpeed = 0;
static int powerCalls = 0;
static float lastPower = -1.0f;

// Заглушки НЕ static: единственный вызов каждой лежит во вклеенном теле блока
// (run_low_temp_tick ниже), и со static мутация, убравшая вызов, роняла бы
// компилятор по unused-function вместо содержательного assert-а. Держится это
// на проверках powerCalls/lastPower/setSpeedCalls ниже: без них снятие static
// меняет ложный улов на молчаливую слепую зону, что хуже.
//
// fromPower обязана быть ОТЛИЧИМА от тождества: настоящая (nbk.h:161) переводит
// мощность в напряжение через сопротивление ТЭНа. С тождественной заглушкой
// set_current_power(fromPower(nbk_M)) неотличимо от set_current_power(nbk_M) -
// в регулятор уехали бы ватты вместо вольт, а тест молчал бы. Коэффициент
// условный: пинится сам факт конверсии, а не число. Тождество - это реальная
// ветка настоящей fromPower под SAMOVAR_USE_SEM_AVR, но харнесс её не задаёт.
inline float fromPower(float m) { return m * 2.0f; }
inline void set_current_power(float v) { powerCalls++; lastPower = v; }
inline void SetSpeed(float v) { setSpeedCalls++; lastSpeed = v; }

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
  // Имитация длительного периода "температура ниже порога": условие
  // (Тб < Тн-dT+dД) истинно на каждом тике, вмешательств пользователя нет
  // (nbk_P/nbk_M синхронизированы с nbk_Po/nbk_Mo), поэтому декремент
  // nbk_Po применяется на каждой итерации, как при медленно греющемся или
  // сбойном датчике пара.
  nbk_Tb = 0.0f;              // заведомо ниже nbk_Tn - nbk_dT + nbk_dD
  nbk_Po = 0.4f;              // меньше одного шага dП/10 = 0.05, но нужно много тиков
  nbk_Mo = 100.0f;
  nbk_M = nbk_Mo;
  nbk_P = nbk_Po;

  for (int tick = 0; tick < 200; tick++) {
    run_low_temp_tick();
    check(nbk_Po >= 0.0f, "nbk_Po ушёл в минус на одном из тиков длительного периода низкой температуры");
    check(nbk_P >= 0.0f, "nbk_P (производная от nbk_Po) ушла в минус");
    // На следующем тике условие "не было вмешательств" должно остаться
    // истинным, чтобы декремент продолжался (nbk_P/nbk_M уже равны
    // nbk_Po/nbk_Mo после блока).
  }

  check(nbk_Po == 0.0f, "после длительного периода низкой температуры nbk_Po должен зафиксироваться на нуле, а не уйти в минус");
  check(setSpeedCalls == 200, "SetSpeed должен вызываться на каждом тике внутри блока");
  check(lastSpeed == 0.0f, "последняя команда насосу должна быть 0, а не отрицательной");
  // Подача обнуляется, но мощность обязана уходить в регулятор на каждом тике:
  // иначе НБК крутит подачу вслепую, а уставка нагрева остаётся от прошлой
  // итерации.
  check(powerCalls == 200, "set_current_power должен вызываться на каждом тике внутри блока");
  // Уставка обязана быть КОНВЕРТИРОВАННОЙ: nbk_M - это ватты, а set_current_power
  // ждёт напряжение. Второй терм страхует сам тест: если заглушку fromPower
  // вернут к тождеству, первый терм станет тавтологией и перестанет что-либо
  // ловить.
  check(lastPower == fromPower(nbk_Mo) && lastPower != nbk_Mo,
        "в регулятор ушла не конвертированная уставка (сырая мощность вместо напряжения)");

  if (failures != 0) return 1;
  std::cout << "nbk_Po floor clamp behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    code = strip_cpp_comments(source)
    anchor = "if ((nbk_Tb < nbk_Tn - nbk_dT + nbk_dD) || (nbk_Tp < nbk_Tp_lim)) {"
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
