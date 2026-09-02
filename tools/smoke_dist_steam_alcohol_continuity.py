#!/usr/bin/env python3
"""Поведенческая проверка [П9]: лестница температура->крепость в
get_steam_alcohol() не должна иметь разрыва на стыке верхнего сегмента лестницы
("t >= 99 && t <= 99.84") и следующей ветки решения ("else if (t > 99.84)
r = get_alcohol(t1);").

ВАЖНАЯ ОГОВОРКА (обнаружено при построении мутационного теста, задокументировано
для координатора): порог 99.84 в обеих ветках - буквально ОДНО И ТО ЖЕ
значение типа double. Так как 99.84 не представимо точно в float, а t имеет
тип float, НИ ОДНО достижимое значение float не промотируется в double ровно
99.84 - соседние float-соседи (~99.839996 и ~99.840004) лежат строго по разные
стороны от double-литерала 99.84. Из-за этого сам по себе разворот "<" -> "<="
не даёт ни одного достижимого входа с иным результатом (проверено полным
перебором float32 в диапазоне [99.8; 99.9] - ни одно значение не проваливается
в "общий default"), и содержательную мутацию именно ЭТОЙ строки построить
нельзя (любая попытка обязательно даёт одинаковый результат до и после
разворота на всех достижимых float).

Реальный, ДОСТИЖИМЫЙ риск - в другом месте: порог 99.84 продублирован
буквально (используется дважды - в лестнице и в исходе "else if"). Если эти
два вхождения когда-нибудь разойдутся (например, поправят только одно), между
ними образуется настоящий, достижимый обычными float разрыв: температуры в
этом разрыве проваливаются в общий default (s=82, k=-1, t0=82), рассчитанный
для куда более низких температур, и дают скачок к ~64% вместо ожидаемых
единиц процента. Тест защищает именно это - непрерывность лестницы на всём
верхнем участке, включая стык с get_alcohol(), - мутацией, разводящей два
вхождения порога.

Тест вытаскивает РЕАЛЬНЫЕ тела get_steam_alcohol()/get_alcohol() из logic.h
(с форвард-декларацией get_alcohol - её вызывает get_steam_alcohol) - без
переписывания логики.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

STEAM_ALCOHOL_SIGNATURE = "float get_steam_alcohol(float t)"
ALCOHOL_SIGNATURE = "float get_alcohol(float t)"

HARNESS_TEMPLATE = r'''
#include <cmath>
#include <cstdint>
#include <iostream>

static bool boil_started = true;

// get_steam_alcohol() вызывает get_alcohol() для t > 99.84 - в реальном
// logic.h обе функции идут одна за другой в общем .ino-объединении, здесь
// нужна форвард-декларация.
float get_alcohol(float t);

@STEAM_ALCOHOL_BODY@

@ALCOHOL_BODY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // Мелкий шаг (0.01 градуса) по всему верхнему участку лестницы, включая
  // стык с get_alcohol() (t > 99.84). Обычный шаг внутри линейного сегмента
  // (k=-13) даёт ~0.13, натуральные "зазубрины" на стыках соседних сегментов
  // - до ~0.5; провал в общий default (s=82,k=-1,t0=82) даёт скачок на
  // ДЕСЯТКИ пунктов - порог 2.0 надёжно отделяет одно от другого.
  float previous = get_steam_alcohol(99.0f);
  int failingStep = -1;
  for (int i = 1; i <= 89; i++) {
    const float t = 99.0f + static_cast<float>(i) * 0.01f;
    const float value = get_steam_alcohol(t);
    if (std::fabs(value - previous) >= 2.0f && failingStep < 0) {
      failingStep = i;
      std::cout << "разрыв у t=" << t << ": " << previous << " -> " << value << '\n';
    }
    previous = value;
  }
  check(failingStep < 0, "РЕГРЕСС: разрыв на участке 99.0..99.89 get_steam_alcohol (провал в общий default)");

  if (failures != 0) return 1;
  std::cout << "get_steam_alcohol continuity checks passed\n";
  return 0;
}
'''


def build_harness(logic_source: str) -> str:
    steam_body = extract_function_body(logic_source, STEAM_ALCOHOL_SIGNATURE)
    alcohol_body = extract_function_body(logic_source, ALCOHOL_SIGNATURE)
    harness = HARNESS_TEMPLATE.replace(
        "@STEAM_ALCOHOL_BODY@", STEAM_ALCOHOL_SIGNATURE + " {" + steam_body + "}"
    )
    harness = harness.replace("@ALCOHOL_BODY@", ALCOHOL_SIGNATURE + " {" + alcohol_body + "}")
    return harness


def compile_and_run(harness: str, label: str) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-dist-steam-alcohol-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "dist_steam_alcohol_continuity_test.cpp"
        binary = temp / "dist_steam_alcohol_continuity_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(f"[{label}] compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode, compile_result.stdout, compile_result.stderr
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(f"[{label}] ")
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode, run_result.stdout, run_result.stderr


def main() -> int:
    logic_source = (ROOT / "logic.h").read_text(encoding="utf-8")

    try:
        harness = build_harness(logic_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rc, _, _ = compile_and_run(harness, "get_steam_alcohol")
    if rc != 0:
        return rc

    # --- Проверка содержательности: развести два вхождения порога 99.84 -
    # ладдер обрезается на 99.5 (условная опечатка при будущей правке одного
    # из двух вхождений), исход "t > 99.84" остаётся прежним. Между 99.5 и
    # 99.84 образуется ДОСТИЖИМЫЙ обычным float разрыв: t=99.7 не попадает ни
    # в один сегмент лестницы, ни в ветку get_alcohol(), и проваливается в
    # общий default (s=82, k=-1, t0=82) - скачок к ~64% вместо ~2%.
    mutated_source = logic_source.replace(
        "if (t >= 99 && t <= 99.84) {", "if (t >= 99 && t <= 99.5) {", 1
    )
    if mutated_source == logic_source:
        print("FAIL: mutation anchor missing in get_steam_alcohol", file=sys.stderr)
        return 1
    mutated_harness = build_harness(mutated_source)
    mutation_rc, mutation_stdout, mutation_stderr = compile_and_run(
        mutated_harness, "mutation ladder threshold diverges from outer decision"
    )
    if mutation_rc == 0:
        print("FAIL: mutation (ladder threshold diverges) survived", file=sys.stderr)
        return 1
    print("mutation failure text:")
    print(mutation_stdout + mutation_stderr)

    print("get_steam_alcohol mutation check: FAIL as expected (mutation killed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
