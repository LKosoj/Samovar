#!/usr/bin/env python3
"""Поведенческая проверка [П8]: первый захлёб ПРЯМО в Работе обязан снижать
nbk_Mo/nbk_Po на первой паузе - раньше это держалось на флаге workrun,
который сбрасывался в false при КАЖДОМ входе в Разгон и становился true
только глубоко внутри той же самой обработки первой паузы (сразу ПОСЛЕ
проверки "if (workrun)"), поэтому к моменту первого захлёба в Работе workrun
был ещё false, и условие "if (workrun)" пропускало снижение именно в том
единственном случае, где оно было нужнее всего: первый захлёб прямо в
Работе. Снижение включалось лишь начиная со ВТОРОГО захлёба в той же сессии
Работы - отсюда и баг "первый захлёб не снижает параметры". Единственный
случай, который и должен был быть исключением из снижения на первой паузе -
захлёб в конце Оптимизации, откуда flag nbk_work_entry_overflow_pending
выставляется явно.

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

ANCHOR = "if (nbk_overflow_happened && !nbk_work_entry_overflow_pending) {"
TAIL_STMT = "nbk_work_entry_overflow_pending = false;"

HARNESS_TEMPLATE = r'''
#include <iostream>
#include <string>

static double nbk_Mo = 0;
static double nbk_Po = 0;
static double nbk_dM = 0;
static double nbk_dP = 0;
static bool nbk_overflow_happened = false;
static bool nbk_work_entry_overflow_pending = false;

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
  // --- РЕГРЕСС: первый захлёб ПРЯМО в Работе (не унаследованный из
  // Оптимизации) обязан снизить Mo/Po на первой же паузе. ---
  nbk_Mo = 1000; nbk_Po = 10;
  nbk_dM = 100; nbk_dP = 1;
  nbk_overflow_happened = true;
  nbk_work_entry_overflow_pending = false;
  run_reduction_fragment();
  check(nbk_Mo == 990, "первый захлёб в Работе обязан снизить Mo на dM/10");
  check(nbk_Po == 9.9, "первый захлёб в Работе обязан снизить Po на dP/10");
  check(!nbk_overflow_happened, "флаг захлёба обязан сброситься после обработки паузы");
  check(!nbk_work_entry_overflow_pending, "флаг входа из Оптимизации обязан остаться false, если уже был false");

  // --- Оптимизация завершилась захлёбом -> переход в Работу -> первая пауза:
  // снижение уже применено в конце Оптимизации, здесь повторного снижения
  // быть не должно (это тот самый случай, который флаг обязан подавить). ---
  nbk_Mo = 500; nbk_Po = 5;
  nbk_dM = 100; nbk_dP = 1;
  nbk_overflow_happened = true;  // пауза после захлёба, но снижение уже сделано в Оптимизации
  nbk_work_entry_overflow_pending = true;
  run_reduction_fragment();
  check(nbk_Mo == 500, "переход из Оптимизации после захлёба НЕ должен снижать Mo повторно");
  check(nbk_Po == 5, "переход из Оптимизации после захлёба НЕ должен снижать Po повторно");
  check(!nbk_work_entry_overflow_pending, "одноразовый флаг обязан потребиться (стать false) после первой же паузы");

  // --- Второй и последующие захлёбы В ТОМ ЖЕ запуске (после первого, уже
  // обработанного) обязаны снижать Mo/Po каждый раз - флаг больше не мешает,
  // он одноразовый. ---
  nbk_Mo = 990; nbk_Po = 9.9;
  nbk_overflow_happened = true;
  nbk_work_entry_overflow_pending = false;  // уже потреблён на первом захлёбе
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
  nbk_work_entry_overflow_pending = false;
  run_reduction_fragment();
  check(nbk_Mo == 700, "пауза без захлёба не должна снижать Mo");
  check(nbk_Po == 7, "пауза без захлёба не должна снижать Po");

  if (failures != 0) return 1;
  std::cout << "nbk work-entry overflow-pending reduction behaviour checks passed\n";
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
    # Между "}" снижения и сбросом nbk_work_entry_overflow_pending должна
    # быть только строка сброса nbk_overflow_happened (плюс комментарии) -
    # без этого гарантия "фрагмент = именно эти три инструкции" не работает.
    if "nbk_overflow_happened = false;" not in between:
        raise ValueError("nbk_overflow_happened reset not found between reduction and pending reset")
    tail_stmt_end = tail_end + len(TAIL_STMT)
    fragment = "if (nbk_overflow_happened && !nbk_work_entry_overflow_pending) {" + \
        body + "}" + nbk_source[tail_start:tail_stmt_end]

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

    with tempfile.TemporaryDirectory(prefix="samovar-nbk-work-entry-pending-") as temp_dir:
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
