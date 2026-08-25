#!/usr/bin/env python3
"""[T21-2] Переход RECT_STABILIZING -> RECT_STABLE в alarm.h должен срабатывать
по достижении порога, а не только при точном совпадении.

acceleration_temp - uint16_t, доступный Lua на запись (диапазон 0..UINT16_MAX,
см. lua.h). Скрипт может выставить его в значение БОЛЬШЕ 360 (60 * 6) за один
шаг. Раньше проверка была `acceleration_temp == 60 * 6` - если счётчик
"перескочил" точное значение 360, равенство никогда не станет истинным, и
переход в SAMOVAR_STATUS_RECT_STABLE не происходит никогда, хотя колонна уже
давно стабильна. Фикс меняет сравнение на `acceleration_temp >= 60 * 6` - для
штатного пути (счётчик растёт по +1 с нуля) поведение идентично.

Тест вытаскивает РЕАЛЬНЫЙ блок кода (тело
"if (SamovarStatusInt == SAMOVAR_STATUS_RECT_STABILIZING && SteamSensor.avgTemp
> CHANGE_POWER_MODE_STEAM_TEMP) { ... }" внутри check_alarm()) из alarm.h через
extract_braced_block_after - без переписывания логики - и подставляет его в
минимальный host-харнесс. Сценарий: acceleration_temp предустановлен в 400
(> 360 - счётчик "перескочил" порог), температура пара стабильна (дельта от
prev_stable_temp < 0.1) -> один тик -> SamovarStatusInt должен стать
SAMOVAR_STATUS_RECT_STABLE. Мутация ">=" -> "==" валит этот assert, так как
400 != 360.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

ANCHOR = (
    "if (SamovarStatusInt == SAMOVAR_STATUS_RECT_STABILIZING "
    "&& SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP) {"
)

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

enum { NOTIFY_MSG = 2 };
enum { SAMOVAR_STATUS_RECT_STABLE = 7 };

int SamovarStatusInt = 0;
uint16_t acceleration_temp = 0;

struct Sensor { float avgTemp = 0; };
static Sensor SteamSensor;

static int sendMsgCalls = 0;
void SendMsg(const char*, int) { sendMsgCalls++; }

// Заглушка НЕ static: единственный вызов лежит во вклеенном теле блока ниже,
// и со static мутация, откатывающая ">=" на "==", роняла бы компилятор по
// unused-function вместо содержательного assert-а по SamovarStatusInt.
int buzzerCalls = 0;
void set_buzzer(bool) { buzzerCalls++; }

static void rect_stable_check() {
@BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}

int main() {
  // acceleration_temp "перескочил" 360 (например, скрипт Lua выставил его
  // напрямую) - штатный путь по +1 никогда не остановился бы ровно на 360.
  SamovarStatusInt = 0;
  acceleration_temp = 400;
  sendMsgCalls = 0;
  buzzerCalls = 0;
  SteamSensor.avgTemp = 0.0f;  // prev_stable_temp стартует с 0 -> дельта 0 < 0.1

  rect_stable_check();

  check(SamovarStatusInt == SAMOVAR_STATUS_RECT_STABLE,
        "acceleration_temp > 360 обязан завершить стабилизацию (>=), а не требовать точного ==360");
  check(acceleration_temp == 0, "счётчик стабилизации должен сброситься после перехода");
  check(buzzerCalls == 1, "переход в RECT_STABLE должен подать один сигнал зуммера");

  if (failures != 0) return 1;
  std::cout << "alarm.h RECT_STABILIZING->RECT_STABLE threshold checks passed\n";
  return 0;
}
'''


def build_harness(source: str) -> str:
    code = strip_cpp_comments(source)
    body, _ = extract_braced_block_after(code, ANCHOR)
    body = body.replace("\r\n", "\n")
    return HARNESS_TEMPLATE.replace("@BODY@", body)


def main() -> int:
    source = (ROOT / "alarm.h").read_text(encoding="utf-8")
    try:
        harness = build_harness(source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-alarm-rect-stable-") as temp_dir:
        temp = Path(temp_dir)
        cpp_source = temp / "alarm_rect_stable_threshold_test.cpp"
        binary = temp / "alarm_rect_stable_threshold_test"
        cpp_source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp_source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
