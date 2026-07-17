#!/usr/bin/env python3
"""Поведенческая проверка окна включённого нагрева при загрузке (releN=true платы).

init_power_outputs_safe_off() (Samovar.ino) жёстко выставляет HIGH на все 4 канала
реле ДО загрузки профиля — полярность ещё не известна. Это безопасно только для
дефолтной полярности releN=false (HIGH=выключено). Для плат, где пользователь в
setup.htm настроил releN=true (активный высокий уровень реле), HIGH означает
ВКЛЮЧЕНО — то есть RELE_CHANNEL1 (пускатель нагревателя) на некоторое время
оказывается включён.

Тест берёт РЕАЛЬНЫЕ тела init_power_outputs_safe_off() и
apply_loaded_relay_polarity_off() из Samovar.ino (через extract_function_body —
без переписывания логики), а также реальный фрагмент setup() между
`SamSetup = startupProfile;` и `print_nvs_stats("after config load");` (через
source_slice — так же, как это делает smoke_profile_operation.py), и исполняет их
в том же порядке, что и настоящий setup(). Так проверяется, что реле физически
выключено сразу после загрузки профиля, а не то, что в исходнике есть нужная
строка.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]


def source_slice(source: str, start_token: str, end_token: str) -> str:
    start = source.find(start_token)
    end = source.find(end_token, start)
    if start < 0 or end < 0:
        raise ValueError(f"source slice not found: {start_token} .. {end_token}")
    return source[start:end]


HARNESS_TEMPLATE = r'''
#include <iostream>

using PinValue = int;
constexpr PinValue LOW = 0;
constexpr PinValue HIGH = 1;
constexpr int OUTPUT = 1;

constexpr int RELE_CHANNEL1 = 1;
constexpr int RELE_CHANNEL2 = 2;
constexpr int RELE_CHANNEL3 = 3;
constexpr int RELE_CHANNEL4 = 4;

static int pinState[8];

static void reset_pins() {
  for (int i = 0; i < 8; i++) pinState[i] = -1;  // -1 = ещё не записывали
}

static void pinMode(int pin, int mode) { (void)pin; (void)mode; }
static void digitalWrite(int pin, int value) { pinState[pin] = value; }

struct SetupEEPROM {
  bool rele1 = false;
  bool rele2 = false;
  bool rele3 = false;
  bool rele4 = false;
};

static SetupEEPROM SamSetup;

@SAFE_OFF_BODY@

@FIXUP_BODY@

// Воспроизводит реальную последовательность setup(): аварийный safe-off ДО загрузки
// профиля, затем — ровно тот фрагмент кода, что в Samovar.ino между присвоением
// SamSetup из startupProfile и print_nvs_stats("after config load").
static void run_boot_sequence(bool r1, bool r2, bool r3, bool r4) {
  reset_pins();
  init_power_outputs_safe_off();

  SetupEEPROM startupProfile{};
  startupProfile.rele1 = r1;
  startupProfile.rele2 = r2;
  startupProfile.rele3 = r3;
  startupProfile.rele4 = r4;

  @SLICE@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

// Регресс из бага: плата настроена на активный высокий уровень реле (releN=true).
// ВЫКЛ для такой полярности — LOW (см. power_regulator.h: ON пишет SamSetup.releN,
// OFF пишет !SamSetup.releN). Сразу после загрузки такого профиля реле должно
// физически быть в LOW, а не оставаться в HIGH (=ВКЛЮЧЕНО) от аварийного safe-off.
static void test_active_high_board_ends_off_after_profile_load() {
  run_boot_sequence(true, true, true, true);
  check(pinState[RELE_CHANNEL1] == LOW,
        "releN=true: пускатель нагревателя (RELE_CHANNEL1) остался включён (HIGH) после загрузки профиля");
  check(pinState[RELE_CHANNEL2] == LOW, "releN=true: канал 2 остался включён после загрузки профиля");
  check(pinState[RELE_CHANNEL3] == LOW, "releN=true: канал 3 остался включён после загрузки профиля");
  check(pinState[RELE_CHANNEL4] == LOW, "releN=true: канал 4 остался включён после загрузки профиля");
}

// Дефолтная/фейл-сейф полярность releN=false (set_default_setup_profile()) —
// ВЫКЛ это HIGH. Фикс не должен сломать существующее поведение для большинства плат.
static void test_default_polarity_board_ends_off_after_profile_load() {
  run_boot_sequence(false, false, false, false);
  check(pinState[RELE_CHANNEL1] == HIGH,
        "releN=false (дефолт/фейл-сейф): RELE_CHANNEL1 не в HIGH=выключено после загрузки профиля");
  check(pinState[RELE_CHANNEL4] == HIGH,
        "releN=false (дефолт/фейл-сейф): RELE_CHANNEL4 не в HIGH=выключено после загрузки профиля");
}

// Смешанная полярность по каналам (пользователь настроил их независимо в setup.htm) —
// каждый канал должен корректироваться по своей собственной полярности.
static void test_mixed_polarity_per_channel() {
  run_boot_sequence(true, false, true, false);
  check(pinState[RELE_CHANNEL1] == LOW, "смешанная полярность: канал1 (releN=true) не выключен (LOW)");
  check(pinState[RELE_CHANNEL2] == HIGH, "смешанная полярность: канал2 (releN=false) не выключен (HIGH)");
  check(pinState[RELE_CHANNEL3] == LOW, "смешанная полярность: канал3 (releN=true) не выключен (LOW)");
  check(pinState[RELE_CHANNEL4] == HIGH, "смешанная полярность: канал4 (releN=false) не выключен (HIGH)");
}

int main() {
  test_active_high_board_ends_off_after_profile_load();
  test_default_polarity_board_ends_off_after_profile_load();
  test_mixed_polarity_per_channel();
  if (failures != 0) return 1;
  std::cout << "relay boot-window polarity checks passed\n";
  return 0;
}
'''


def build_harness(source: str) -> str:
    safe_off_body = extract_function_body(
        source, "static void init_power_outputs_safe_off() {")
    fixup_body = extract_function_body(
        source, "static void apply_loaded_relay_polarity_off() {")
    slice_text = source_slice(
        source, "SamSetup = startupProfile;", 'print_nvs_stats("after config load");')

    harness = HARNESS_TEMPLATE.replace(
        "@SAFE_OFF_BODY@",
        "static void init_power_outputs_safe_off() {\n" + safe_off_body + "\n}")
    harness = harness.replace(
        "@FIXUP_BODY@",
        "void apply_loaded_relay_polarity_off() {\n" + fixup_body + "\n}")
    harness = harness.replace("@SLICE@", slice_text)
    return harness


def run_harness(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-relay-boot-window-") as temp_dir:
        temp = Path(temp_dir)
        source_file = temp / "relay_boot_window_test.cpp"
        binary = temp / "relay_boot_window_test"
        source_file.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source_file),
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


def main() -> int:
    source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    try:
        harness = build_harness(source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return run_harness(harness)


if __name__ == "__main__":
    raise SystemExit(main())
