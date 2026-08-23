#!/usr/bin/env python3
"""[П6] Поведенческая проверка верхнего зажима get_speed_from_rate() (logic.h).

До правки функция клампила результат только СНИЗУ ("Минимальная скорость 1"), а
верхнюю границу не проверяла. На вызывающей стороне (logic.h::run_program(), см.
CurrrentStepperSpeed = (uint16_t)get_speed_from_rate(...)) результат кастуется в
uint16_t: если оператор вводит скорость отбора, требующую больше 65535 шагов/с
(например 3000 л/ч при типичном StepperStepMl), значение переполняется по кругу -
насос едет с произвольной ЗАНИЖЕННОЙ скоростью, а не с максимально возможной, и
без единого предупреждения.

Тест вытаскивает РЕАЛЬНОЕ тело get_speed_from_rate() из logic.h и компилирует его
g++-харнессом - проверяется настоящая арифметика зажима, а не переписанная копия.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "float get_speed_from_rate(float volume_per_hour)"

HARNESS_TEMPLATE = r'''
#include <cmath>
#include <cstdint>
#include <iostream>

using std::round;

struct SetupEEPROM {
  uint16_t StepperStepMl = 1000;
};

static SetupEEPROM SamSetup;
static float ActualVolumePerHour = 0;

// ---- Реальный код под тестом ----
@GET_SPEED_FROM_RATE_BODY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // Типичная калибровка насоса из смок-тестов проекта (StepperStepMl = 1000).
  SamSetup.StepperStepMl = 1000;

  // Разумная скорость (0.24 л/ч) - зажим не должен вмешиваться.
  float normal = get_speed_from_rate(0.24f);
  check(normal > 1.0f && normal < 65535.0f, "разумная скорость не должна зажиматься");

  // Оператор вводит заведомо избыточную скорость (сценарий из тикета - 3000 л/ч).
  float clamped = get_speed_from_rate(3000.0f);
  check(clamped <= 65535.0f, "верхний зажим обязан ограничить результат 65535 (uint16_t max)");
  check(clamped == 65535.0f, "при явном превышении предела результат должен зажаться ровно в потолок");

  // ГЛАВНАЯ проверка дефекта: каст в uint16_t (как делает run_program()) НЕ должен
  // заворачиваться по кругу в маленькое число.
  uint16_t asStepperSpeed = (uint16_t)clamped;
  check(asStepperSpeed > 60000, "каст в uint16_t не должен переполняться по кругу (был баг: 3000 л/ч -> ~169 л/ч)");

  // Нижний зажим (существовавшее поведение) не должен был сломаться.
  float zero = get_speed_from_rate(0.0f);
  check(zero == 1.0f, "минимальная скорость должна остаться 1 (нижний зажим)");

  if (failures != 0) return 1;
  std::cout << "get_speed_from_rate upper clamp behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    source = (ROOT / "logic.h").read_text(encoding="utf-8")
    body = extract_function_body(source, SIGNATURE)
    return HARNESS_TEMPLATE.replace(
        "@GET_SPEED_FROM_RATE_BODY@",
        "static float get_speed_from_rate(float volume_per_hour) {" + body + "}",
    )


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-speed-clamp-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "speed_clamp_test.cpp"
        binary = temp / "speed_clamp_test"
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


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return compile_and_run(harness)


if __name__ == "__main__":
    sys.exit(main())
