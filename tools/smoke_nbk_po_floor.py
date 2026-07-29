#!/usr/bin/env python3
"""Поведенческая проверка нижнего клампа nbk_Po в nbk.h::handle_nbk_stage_work.

Тест вытаскивает РЕАЛЬНЫЙ блок кода (if-ветку понижения подачи при низкой
температуре/паре ниже предела) из nbk.h через extract_braced_block_after —
без переписывания логики — и подставляет его в минимальный host-харнесс,
который моделирует commit уже принятой составной команды. Так проверяется
реальное поведение переменной nbk_Po при многократных тиках с температурой
ниже порога, а не наличие конкретной строки в исходнике.
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

static float lastSpeed = 0;
static float lastPower = -1.0f;

static void run_low_temp_tick() {
  const float currentM = nbk_M;
  const float currentP = nbk_P;
  float candidateM = currentM;
  float candidateP = currentP;
  bool commandNeeded = false;
@BODY@
  if (commandNeeded) {
    lastPower = candidateM;
    lastSpeed = candidateP;
    nbk_M = candidateM;
    nbk_P = candidateP;
  }
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
