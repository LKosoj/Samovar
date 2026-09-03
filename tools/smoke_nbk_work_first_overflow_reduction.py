#!/usr/bin/env python3
"""Поведенческая проверка [П8]: первый захлёб ПРЯМО в Работе обязан снижать
nbk_Mo/nbk_Po на первой паузе - раньше это держалось на флаге workrun,
который сбрасывался в false при КАЖДОМ входе в Разгон и становился true
только глубоко внутри той же самой обработки первой паузы (сразу ПОСЛЕ
проверки "if (workrun)"), поэтому к моменту первого захлёба в Работе workrun
был ещё false, и условие "if (workrun)" пропускало снижение именно в том
единственном случае, где оно было нужнее всего: первый захлёб прямо в
Работе. Снижение включалось лишь начиная со ВТОРОГО захлёба в той же сессии
Работы - отсюда и баг "первый захлёб не снижает параметры".

[Ремонт-2026-09-02 П1] Промежуточный костыль nbk_work_entry_overflow_pending
(одноразовый флаг, подавлявший повторное снижение после захлёба в конце
Оптимизации) УДАЛЁН целиком. Теперь единственный исключительный случай -
автовход из Оптимизации прямо в Работу с уже сниженными Мо/По - НЕ проходит
через эту паузу вообще: run_nbk_program(num, false, true) коммитит через
commitKeepsOptimum и переводит W сразу в паузу stage=1 с nbk_overflow_happened
уже сброшенным в false (см. smoke_nbk_actuator_results.py, кейс
commitKeepsOptimum). Поэтому здесь остаётся только один контракт:
nbk_overflow_happened=true -> снижение на dM/10, dP/10 и сброс флага в false;
nbk_overflow_happened=false -> снижения нет.

Тест вытаскивает РЕАЛЬНЫЙ фрагмент из handle_nbk_stage_work() (nbk.h) -
снижение Mo/Po на nbk_work_pause_stage==1 - через extract_braced_block_after
и подставляет в минимальный host-харнесс.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]

ANCHOR = "if (nbk_overflow_happened) {"
TAIL_STMT = "nbk_overflow_happened = false;"

HARNESS_TEMPLATE = r'''
#include <iostream>
#include <string>

static double nbk_Mo = 0;
static double nbk_Po = 0;
static double nbk_dM = 0;
static double nbk_dP = 0;
static bool nbk_overflow_happened = false;

static void run_reduction_fragment() {
@FRAGMENT@
}

static int failures = 0;
static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // --- РЕГРЕСС: первый захлёб ПРЯМО в Работе обязан снизить Mo/Po на первой
  // же паузе (без промежуточного флага, который раньше мог это подавить). ---
  nbk_Mo = 1000; nbk_Po = 10;
  nbk_dM = 100; nbk_dP = 1;
  nbk_overflow_happened = true;
  run_reduction_fragment();
  check(nbk_Mo == 990, "первый захлёб в Работе обязан снизить Mo на dM/10");
  check(nbk_Po == 9.9, "первый захлёб в Работе обязан снизить Po на dP/10");
  check(!nbk_overflow_happened, "флаг захлёба обязан сброситься после обработки паузы");

  // --- Второй и последующие захлёбы В ТОМ ЖЕ запуске (после первого, уже
  // обработанного) обязаны снижать Mo/Po каждый раз. ---
  nbk_Mo = 990; nbk_Po = 9.9;
  nbk_overflow_happened = true;
  run_reduction_fragment();
  check(nbk_Mo == 980, "второй захлёб в том же запуске тоже обязан снижать Mo");
  check(std::abs(nbk_Po - 9.8) < 1e-9, "второй захлёб в том же запуске тоже обязан снижать Po");

  nbk_overflow_happened = true;
  run_reduction_fragment();
  check(nbk_Mo == 970, "третий захлёб в том же запуске тоже обязан снижать Mo");

  // --- Если паузу вызвал НЕ захлёб (вмешательство пользователя), снижения
  // быть не должно (регресс: не привязываем к любой паузе без разбора). ---
  nbk_Mo = 700; nbk_Po = 7;
  nbk_overflow_happened = false;
  run_reduction_fragment();
  check(nbk_Mo == 700, "пауза без захлёба не должна снижать Mo");
  check(nbk_Po == 7, "пауза без захлёба не должна снижать Po");

  if (failures != 0) return 1;
  std::cout << "nbk work first-overflow reduction behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    body, end = extract_braced_block_after(nbk_source, ANCHOR)
    tail_start = end
    tail_end = nbk_source.find(TAIL_STMT, tail_start)
    if tail_end < 0:
        raise ValueError("tail reset statement not found right after the reduction block")
    between = nbk_source[tail_start:tail_end]
    # Между "}" снижения и сбросом nbk_overflow_happened не должно быть
    # ничего, кроме пробелов/комментариев - без этого гарантия "фрагмент =
    # именно эти инструкции" не работает.
    if between.strip(" \t\r\n"):
        raise ValueError("unexpected statements between reduction block and its flag reset")
    tail_stmt_end = tail_end + len(TAIL_STMT)
    fragment = ANCHOR + body + "}" + nbk_source[tail_start:tail_stmt_end]

    harness = HARNESS_TEMPLATE.replace("@FRAGMENT@", fragment)
    harness = harness.replace(
        "#include <iostream>", "#include <cmath>\n#include <iostream>", 1)
    return harness


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-nbk-work-first-overflow-reduction-") as temp_dir:
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
            sys.stderr.write("compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
