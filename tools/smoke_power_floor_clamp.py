#!/usr/bin/env python3
"""Поведенческая проверка [T14 п.1]: нижняя граница снижения мощности.

set_current_power(Volt) в power_regulator.h молча схлопывает мощность в SLEEP
(target_power_volt = 0), если запрошенное значение ниже
POWER_WORK_MODE_THRESHOLD (40 В для KVIC/RMVK, 100 Вт для SEM_AVR). До этой
задачи три "лестницы" снижения мощности вызывали set_current_power() без
проверки этого порога - обычный шаг вниз мог случайно погасить нагрев
целиком:
  - runtime_helpers.h::reduce_power_by_volts() (используется
    mode_common.h::mode_reduce_power_for_water_alarm_by_volts и напрямую
    alarm.h при ошибке подачи воды);
  - alarm.h: снижение при захлёбе (ветки SEM и KVIC/RMVK);
  - alarm.h: снижение при критической температуре воды (ветка SEM).

Тест вытаскивает РЕАЛЬНЫЙ код всех трёх точек через точный текстовый срез
(без переписывания логики) и подставляет в минимальные host-харнессы,
замокав только downstream set_current_power(). Каждый харнесс собирается
ДВАЖДЫ - без SAMOVAR_USE_SEM_AVR (порог 40 В) и с ним (порог 100 Вт) - порог
читается из РЕАЛЬНОГО power_regulator.h, а не дублируется числом в тесте.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

THRESHOLD_CONST = "static constexpr float POWER_WORK_MODE_THRESHOLD"
IFDEF_MARKER = "#ifdef SAMOVAR_USE_SEM_AVR"
REDUCE_SIGNATURE = "inline float reduce_power_by_volts(float power, float volts)"

HLS_START = '#ifdef SAMOVAR_USE_SEM_AVR\n      // [T14 п.1] Нижняя граница - без неё уход ниже порога SLEEP бесшумно гасит нагрев.'
WATER_START = 'SendMsg("Критическая температура воды! Ошибка подачи воды. "'
WATER_END = 'set_current_power(max(target_power_volt - target_power_volt / 100 * 8, power_work_mode_threshold()));'

COMMON_PRELUDE = r'''
#include <iostream>

// Не static: не в каждом харнессе, вклеенном ниже, используется max() -
// со static неиспользованный экземпляр падал бы на -Wunused-function.
float max(float left, float right) { return left > right ? left : right; }
#define PWR_FACTOR 1

static int callCount = 0;
static float lastArg = -999.0f;
// Заглушка НЕ static: единственный вызов лежит во вклеенном коде ниже, и со
// static мутация, убравшая клэмп, роняла бы компилятор по unused-function
// вместо содержательного assert-а.
void set_current_power(float Volt) { callCount++; lastArg = Volt; }

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
'''


def read_source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def extract_threshold_block(power_source: str) -> str:
    first = power_source.find(THRESHOLD_CONST)
    if first < 0:
        raise ValueError(f"constant not found: {THRESHOLD_CONST}")
    start = power_source.rfind(IFDEF_MARKER, 0, first)
    if start < 0:
        raise ValueError(f"enclosing {IFDEF_MARKER} not found before threshold constant")
    endif_idx = power_source.find("#endif", first)
    if endif_idx < 0:
        raise ValueError("closing #endif for threshold constant not found")
    endif_idx += len("#endif")
    block = power_source[start:endif_idx]
    return block + "\ninline float power_work_mode_threshold() { return POWER_WORK_MODE_THRESHOLD; }\n"


def extract_hls_snippet(alarm_source: str) -> str:
    start = alarm_source.index(HLS_START)
    end = alarm_source.index("#endif", start) + len("#endif")
    return alarm_source[start:end]


def extract_water_snippet(alarm_source: str) -> str:
    start = alarm_source.index(WATER_START)
    end = alarm_source.index(WATER_END) + len(WATER_END)
    return alarm_source[start:end]


def build_reduce_harness(threshold_block: str, runtime_source: str) -> str:
    body = extract_function_body(runtime_source, REDUCE_SIGNATURE)
    func = REDUCE_SIGNATURE + " {" + body + "}"
    return COMMON_PRELUDE + "\n" + threshold_block + "\n" + func + r'''

int main() {
  const float threshold = power_work_mode_threshold();

  // Обычный шаг вниз далеко от порога - обязан пройти как есть (не задет клэмпом).
  check(reduce_power_by_volts(threshold + 50.0f, 5.0f) == threshold + 45.0f,
        "обычное снижение вдали от порога не должно клэмпиться");

  // Шаг вниз, который БЕЗ клэмпа увёл бы ниже порога - обязан остановиться РОВНО на пороге.
  check(reduce_power_by_volts(threshold + 2.0f, 5.0f) == threshold,
        "РЕГРЕСС: снижение обязано клэмпиться к порогу WORK, а не уходить ниже него");

  // Уже НА пороге - шаг вниз не должен провалить ниже.
  check(reduce_power_by_volts(threshold, 5.0f) == threshold,
        "снижение от значения на пороге не должно уходить ниже порога");

  if (failures != 0) return 1;
  std::cout << "reduce_power_by_volts floor checks passed\n";
  return 0;
}
'''


def build_hls_harness(threshold_block: str, snippet: str) -> str:
    return COMMON_PRELUDE + "\n" + threshold_block + r'''
static float target_power_volt = 0.0f;

static void do_hls_reduction() {
''' + snippet + r'''
}

int main() {
  const float threshold = power_work_mode_threshold();

  callCount = 0; lastArg = -999.0f;
  target_power_volt = threshold + 200.0f;
  do_hls_reduction();
  check(callCount == 1, "снижение при захлёбе обязано вызвать set_current_power ровно один раз");
  check(lastArg >= threshold, "снижение при захлёбе не должно провалиться ниже порога WORK вдали от него");

  // Значение, близкое к порогу - без клэмпа мультипликативный (SEM) или
  // аддитивный (KVIC/RMVK) шаг вниз может провалить его ниже порога.
  callCount = 0; lastArg = -999.0f;
  target_power_volt = threshold + 1.0f;
  do_hls_reduction();
  check(lastArg >= threshold,
        "РЕГРЕСС: снижение при захлёбе рядом с порогом обязано клэмпиться, а не проваливаться в SLEEP");

  if (failures != 0) return 1;
  std::cout << "alarm.h head-level-sensor reduction floor checks passed\n";
  return 0;
}
'''


def build_water_harness(threshold_block: str, snippet: str) -> str:
    return COMMON_PRELUDE + "\n" + threshold_block + r'''
#include <string>

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}
  String(float value) : value_(std::to_string(value)) {}
  String operator+(const char* text) const { return String(value_ + (text ? text : "")); }
  String operator+(const String& other) const { return String(value_ + other.value_); }
  const std::string& value() const { return value_; }
 private:
  std::string value_;
};
String operator+(const char* lhs, const String& rhs) {
  return String(std::string(lhs ? lhs : "") + rhs.value());
}
enum { ALARM_MSG = 0 };
static const char* PWR_MSG = "";
static float target_power_volt = 0.0f;
// Не static: единственный вызов лежит во вклеенном коде ниже.
void SendMsg(const String&, int) {}

static void do_water_reduction() {
''' + snippet + r'''
}

int main() {
  const float threshold = power_work_mode_threshold();

  callCount = 0; lastArg = -999.0f;
  target_power_volt = threshold + 500.0f;
  do_water_reduction();
  check(lastArg >= threshold, "снижение по воде вдали от порога не должно проваливаться ниже него");

  // 8% от значения чуть выше порога - без клэмпа мультипликативный шаг уйдёт ниже.
  callCount = 0; lastArg = -999.0f;
  target_power_volt = threshold + 1.0f;
  do_water_reduction();
  check(lastArg >= threshold,
        "РЕГРЕСС: снижение по критической температуре воды обязано клэмпиться к порогу WORK");

  if (failures != 0) return 1;
  std::cout << "alarm.h water pre-alarm reduction floor checks passed\n";
  return 0;
}
'''


def compile_and_run(harness: str, label: str, extra_define: str | None) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-power-floor-clamp-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "power_floor_clamp_test.cpp"
        binary = temp / "power_floor_clamp_test"
        source.write_text(harness, encoding="utf-8")
        cmd = ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror"]
        if extra_define:
            cmd.append(extra_define)
        cmd += [str(source), "-o", str(binary)]
        compile_result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if compile_result.returncode != 0:
            sys.stderr.write(f"[{label}] compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(f"[{label}] ")
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def run_both(build_fn, name: str) -> int:
    rc = compile_and_run(build_fn(), f"{name} KVIC/RMVK", None)
    if rc != 0:
        return rc
    return compile_and_run(build_fn(), f"{name} SEM_AVR", "-DSAMOVAR_USE_SEM_AVR")


def main() -> int:
    power_source = read_source("power_regulator.h")
    runtime_source = read_source("runtime_helpers.h")
    alarm_source = read_source("alarm.h")

    try:
        threshold_block = extract_threshold_block(power_source)
        hls_snippet = extract_hls_snippet(alarm_source)
        water_snippet = extract_water_snippet(alarm_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rc = run_both(lambda: build_reduce_harness(threshold_block, runtime_source), "reduce_power_by_volts")
    if rc != 0:
        return rc
    rc = run_both(lambda: build_hls_harness(threshold_block, hls_snippet), "alarm.h HLS reduction")
    if rc != 0:
        return rc
    rc = run_both(lambda: build_water_harness(threshold_block, water_snippet), "alarm.h water reduction")
    if rc != 0:
        return rc

    # --- Проверка содержательности: убираем клэмп из reduce_power_by_volts()
    # в реальном исходнике - мутация обязана провалить сборочный харнесс на
    # assert-е "провалилось ниже порога", а не на предупреждении компилятора.
    mutated_runtime = runtime_source.replace(
        "float reduced = power - volts * PWR_FACTOR;\n  if (reduced < power_work_mode_threshold()) reduced = power_work_mode_threshold();\n  return reduced;",
        "float reduced = power - volts * PWR_FACTOR;\n  return reduced;",
        1,
    )
    if mutated_runtime == runtime_source:
        print("FAIL: mutation anchor missing in reduce_power_by_volts", file=sys.stderr)
        return 1
    mutation_rc = compile_and_run(
        build_reduce_harness(threshold_block, mutated_runtime), "mutation reduce_power_by_volts", None
    )
    if mutation_rc == 0:
        print("FAIL: mutation (removed floor clamp) survived reduce_power_by_volts test", file=sys.stderr)
        return 1

    print("power floor clamp mutation check: FAIL as expected without clamp (mutation killed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
