#!/usr/bin/env python3
"""Поведенческая проверка [T7]: кламп nbk_Tp_lim по настройке NbkSteamT в nbk_proc().

Тест вытаскивает РЕАЛЬНЫЕ два оператора из nbk.h (подстановку значения по
умолчанию и кламп сверху) через прямой поиск в исходнике — без переписывания
логики — и подставляет их в минимальный host-харнесс.

Регресс, который тест защищает: до задачи 7 nbk_Tp_lim мог быть выставлен
пользователем ВЫШЕ порога "Кончилась брага" (98.0 в check_nbk_critical_alarms),
из-за чего предел этапа Работа никогда бы не сработал раньше срабатывания
аварии. Кламп на 97 обязан держать nbk_Tp_lim строго ниже этого порога, но не
трогать значения, уже находящиеся ниже 97 (в т.ч. значение по умолчанию).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STATEMENT_1 = "const float nbkSteamTSetting = SamSetup.NbkSteamT > 80 ? SamSetup.NbkSteamT : NBK_TP_DEFAULT;"
STATEMENT_2 = "nbk_Tp_lim = nbkSteamTSetting > 97 ? 97 : nbkSteamTSetting;"

HARNESS_TEMPLATE = r'''
#include <iostream>

@TP_DEFAULT_DEFINE@

struct SetupProbe {
  float NbkSteamT;
};

static SetupProbe SamSetup;

static float compute_nbk_Tp_lim() {
  float nbk_Tp_lim = 0;
  @STATEMENT_1@
  @STATEMENT_2@
  return nbk_Tp_lim;
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // Выше порога "Кончилась брага" (98.0) -> обязан зажаться на 97, строго ниже.
  SamSetup.NbkSteamT = 150;
  check(compute_nbk_Tp_lim() == 97.0f, "NbkSteamT=150 должен быть зажат на 97");

  // Ниже 97, но выше нижней границы дефолта (80) -> проходит без изменений.
  SamSetup.NbkSteamT = 90;
  check(compute_nbk_Tp_lim() == 90.0f, "NbkSteamT=90 не должен изменяться клампом");

  // Не задано (<= 80) -> подставляется значение по умолчанию, кламп его не трогает.
  SamSetup.NbkSteamT = 50;
  check(compute_nbk_Tp_lim() == static_cast<float>(NBK_TP_DEFAULT),
        "NbkSteamT=50 (не задано) должен подставить NBK_TP_DEFAULT");

  // Граничное значение: ровно 97 не должно зажиматься (строго БОЛЬШЕ 97 зажимается).
  SamSetup.NbkSteamT = 97;
  check(compute_nbk_Tp_lim() == 97.0f, "NbkSteamT=97 (граница) должен пройти без изменений");

  if (failures != 0) return 1;
  std::cout << "nbk steam limit clamp behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    source = (ROOT / "nbk.h").read_text(encoding="utf-8")

    idx1 = source.find(STATEMENT_1)
    if idx1 < 0:
        raise ValueError(f"statement not found in nbk.h: {STATEMENT_1}")
    idx2 = source.find(STATEMENT_2, idx1)
    if idx2 < 0:
        raise ValueError(f"statement not found after first in nbk.h: {STATEMENT_2}")

    define_start = source.find("#define NBK_TP_DEFAULT")
    if define_start < 0:
        raise ValueError("NBK_TP_DEFAULT define not found in nbk.h")
    define_end = source.find("\n", define_start)
    tp_default_define = source[define_start:define_end].replace("\r", "").strip()

    harness = HARNESS_TEMPLATE.replace("@TP_DEFAULT_DEFINE@", tp_default_define)
    harness = harness.replace("@STATEMENT_1@", STATEMENT_1)
    harness = harness.replace("@STATEMENT_2@", STATEMENT_2)
    return harness


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-nbk-steam-limit-clamp-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "nbk_steam_limit_clamp_test.cpp"
        binary = temp / "nbk_steam_limit_clamp_test"
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
