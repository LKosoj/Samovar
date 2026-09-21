#!/usr/bin/env python3
"""Антидребезг аварийной кнопки (21.09.2026).

Задача кнопки срабатывала по одному спаду сигнала: любая наводка на входе (GPIO35 без
внутренней подтяжки, длинные провода к датчикам протечки и паров спирта) глушила процесс.
Теперь emergency_button_press_confirmed() (Samovar.ino) засчитывает срабатывание, только
если вход держит LOW все 30 мс подряд.

Харнесс вытаскивает из исходника РЕАЛЬНОЕ тело функции и обе константы. Вход задан
сценарием «уровень от времени», vTaskDelay() двигает время - заглушки моделируют
зависимость функции от состояния входа, а не её ответ.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SIGNATURE = "bool emergency_button_press_confirmed()"
CONSTANT_PATTERN = r"static constexpr \w+ EMERGENCY_BUTTON_DEBOUNCE_\w+ = \d+;"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

#define LOW 0
#define HIGH 1
#define ALARM_BTN_PIN 35
#define pdMS_TO_TICKS(ms) (ms)

static uint32_t nowMs = 0;
static uint32_t lowFromMs = 0;   // вход LOW на отрезке [lowFromMs, lowUntilMs)
static uint32_t lowUntilMs = 0;
static uint32_t secondLowFromMs = 0;  // вторая помеха: [secondLowFromMs, secondLowUntilMs)
static uint32_t secondLowUntilMs = 0;
static int readPin = -1;

static int digitalRead(int pin) {
  readPin = pin;
  const bool low = (nowMs >= lowFromMs && nowMs < lowUntilMs) ||
                   (nowMs >= secondLowFromMs && nowMs < secondLowUntilMs);
  return low ? LOW : HIGH;
}
static void vTaskDelay(uint32_t ticks) { nowMs += ticks; }

@CONSTANTS@

@SIGNATURE@ {@BODY@}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static bool run(uint32_t lowFrom, uint32_t lowUntil, uint32_t secondLowFrom = 0, uint32_t secondLowUntil = 0) {
  nowMs = 0;
  secondLowFromMs = secondLowFrom;
  secondLowUntilMs = secondLowUntil;
  lowFromMs = lowFrom;
  lowUntilMs = lowUntil;
  return emergency_button_press_confirmed();
}

int main() {
  check(run(0, 1000000) == true, "устойчивый LOW (кнопка или сработавший датчик) обязан засчитаться");
  check(readPin == ALARM_BTN_PIN, "читать обязаны вход аварийной кнопки");
  check(nowMs == 30, "подтверждение обязано занимать 30 мс");

  check(run(0, 1) == false, "помеха короче 1 мс не должна засчитываться");
  check(run(0, 12) == false, "помеха 12 мс не должна засчитываться");
  check(run(0, 29) == false, "LOW, пропавший к последней проверке (29 мс), не должен засчитываться");
  check(run(0, 31) == true, "LOW дольше 30 мс обязан засчитаться");
  check(run(0, 1, 30, 31) == false, "две помехи с разрывом (0 и 30 мс) - это не удержание, засчитывать нельзя");
  check(run(1, 1000000) == false, "HIGH на первой же проверке - не срабатывание");
  check(nowMs == 0, "при HIGH на входе ждать нечего: выход сразу, без задержки");

  if (failures == 0) std::cout << "OK\n";
  return failures == 0 ? 0 : 1;
}
'''

# Каждая мутация обязана упасть на названном содержательном assert-е, а не на компиляторе.
MUTATIONS = [
    ("засчитывается любой спад", "    if (digitalRead(ALARM_BTN_PIN) != LOW) return false;",
     "    if (digitalRead(ALARM_BTN_PIN) != LOW && false) return false;", "две помехи с разрывом"),
    ("нет последней проверки", "  return digitalRead(ALARM_BTN_PIN) == LOW;",
     "  return digitalRead(ALARM_BTN_PIN) == LOW || true;", "пропавший к последней проверке"),
    ("окно короче 30 мс", "EMERGENCY_BUTTON_DEBOUNCE_SAMPLES = 6;", "EMERGENCY_BUTTON_DEBOUNCE_SAMPLES = 2;",
     "помеха 12 мс"),
    ("срабатывание не засчитывается", "  return digitalRead(ALARM_BTN_PIN) == LOW;",
     "  return digitalRead(ALARM_BTN_PIN) == LOW && false;", "устойчивый LOW"),
]


def build_harness(source: str) -> str:
    constants = re.findall(CONSTANT_PATTERN, source)
    if len(constants) != 2:
        raise ValueError(f"expected 2 EMERGENCY_BUTTON_DEBOUNCE_* constants, found {len(constants)}")
    return (HARNESS_TEMPLATE
            .replace("@CONSTANTS@", "\n".join(constants))
            .replace("@SIGNATURE@", SIGNATURE)
            .replace("@BODY@", extract_function_body(source, SIGNATURE)))


def compile_and_run(harness: str, label: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-alarm-button-debounce-") as temp_dir:
        source = Path(temp_dir) / "alarm_button_debounce_test.cpp"
        binary = Path(temp_dir) / "alarm_button_debounce_test"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if compiled.returncode != 0:
            return compiled.returncode, f"[{label}] compile failed:\n{compiled.stdout}{compiled.stderr}"
        result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        return result.returncode, result.stdout + result.stderr


def main() -> int:
    source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    try:
        rc, output = compile_and_run(build_harness(source), "baseline")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if rc != 0:
        print(output, file=sys.stderr)
        return 1

    for label, old, new, expected in MUTATIONS:
        if source.count(old) != 1:
            print(f"FAIL: mutation anchor not unique for «{label}»", file=sys.stderr)
            return 1
        rc, output = compile_and_run(build_harness(source.replace(old, new)), label)
        if rc == 0:
            print(f"FAIL: mutation «{label}» survived", file=sys.stderr)
            return 1
        if expected not in output:
            print(f"FAIL: mutation «{label}» failed for the wrong reason:\n{output}", file=sys.stderr)
            return 1

    # Срабатывание обязано проходить через антидребезг, а оба пути кнопки - давать один текст.
    task_body = extract_function_body(source, "void triggerEmergencyButton(void *parameter)")
    confirm = task_body.find("if (!emergency_button_press_confirmed()) continue;")
    stop = task_body.find("request_emergency_stop(emergency_button_reason());")
    if confirm < 0 or stop < 0 or confirm > stop:
        print("FAIL: triggerEmergencyButton must confirm the press before request_emergency_stop", file=sys.stderr)
        return 1
    tick_body = extract_function_body(source, "static void tick_alarm_button()")
    if "request_emergency_stop(emergency_button_reason());" not in tick_body:
        print("FAIL: tick_alarm_button must report the same emergency_button_reason()", file=sys.stderr)
        return 1

    print("OK: smoke_alarm_button_debounce")
    return 0


if __name__ == "__main__":
    sys.exit(main())
