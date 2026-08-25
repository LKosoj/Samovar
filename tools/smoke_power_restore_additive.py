#!/usr/bin/env python3
"""Поведенческая проверка [T14 п.1/п.8]: восстановление мощности после серии
снижений не "залипает".

До floor'а из п.1 повторные снижения при захлёбе могли увести
target_power_volt точно в 0 (set_current_power() схлопывает любое значение
ниже порога в SLEEP и обнуляет target_power_volt). Для SEM-варианта
"ползучее" восстановление в alarm.h мультипликативно
(target_power_volt + target_power_volt/100*1) - от РОВНО нуля такая формула
не двигается НИКОГДА (0 + 0/100*1 == 0), то есть мощность "залипала" внизу
навсегда, а не просто медленно восстанавливалась.

Тест вытаскивает РЕАЛЬНЫЙ фрагмент снижения при захлёбе (тот же, что и в
smoke_power_floor_clamp.py) и РЕАЛЬНЫЙ фрагмент ползучего восстановления из
alarm.h (без переписывания логики), прогоняет цикл "много снижений подряд,
затем много восстановлений подряд" и проверяет: (1) снижения сходятся к
порогу WORK, а не к нулю; (2) восстановление от этой точки строго
монотонно растёт на каждом шаге (не "залипает"); (3) после достаточного
числа шагов восстановление достигает исходного (до-аварийного) значения.
Собирается ДВАЖДЫ (без и с -DSAMOVAR_USE_SEM_AVR), порог читается из
РЕАЛЬНОГО power_regulator.h.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

THRESHOLD_CONST = "static constexpr float POWER_WORK_MODE_THRESHOLD"
IFDEF_MARKER = "#ifdef SAMOVAR_USE_SEM_AVR"
REDUCE_START = '#ifdef SAMOVAR_USE_SEM_AVR\n      // [T14 п.1] Нижняя граница - без неё уход ниже порога SLEEP бесшумно гасит нагрев.'
RESTORE_START = '#ifdef SAMOVAR_USE_SEM_AVR\n        set_current_power(target_power_volt + target_power_volt / 100 * 1);'

HARNESS_TEMPLATE = r'''
#include <iostream>

float max(float left, float right) { return left > right ? left : right; }
#define PWR_FACTOR 1

static float target_power_volt = 0.0f;
static int callCount = 0;
// Не static: реальный код применяет своё же значение к target_power_volt -
// это симулирует эффект РЕАЛЬНОГО set_current_power() в этих двух точках
// (обе точки не пересекают SLEEP-порог, так как floor гарантирует значение
// >= power_work_mode_threshold()).
void set_current_power(float Volt) { callCount++; target_power_volt = Volt; }

@THRESHOLD_BLOCK@

static void do_reduce() {
@REDUCE_SNIPPET@
}

static void do_restore() {
@RESTORE_SNIPPET@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  const float threshold = power_work_mode_threshold();
  const float original = threshold * 5.0f;

  // --- Серия срабатываний захлёба подряд (до сходимости, с большим
  // запасом): без floor'а KVIC/RMVK (чисто аддитивное -1*PWR_FACTOR)
  // гарантированно пересёк бы 0 и set_current_power() обнулил бы
  // target_power_volt; SEM (мультипликативное -3%) асимптотически стремится
  // к 0. С floor'ом обе ветки обязаны остановиться РОВНО на пороге и не уйти
  // ниже (клэмп идемпотентен: max(порог - шаг, порог) == порог). ---
  target_power_volt = original;
  for (int i = 0; i < 100000 && target_power_volt > threshold; i++) do_reduce();
  check(target_power_volt >= threshold,
        "РЕГРЕСС: серия снижений при захлёбе не должна провалить мощность ниже порога WORK");
  check(target_power_volt == threshold,
        "после достаточного числа снижений мощность обязана осесть РОВНО на пороге (не в 0)");

  // --- Восстановление от порога: КАЖДЫЙ шаг обязан строго увеличивать
  // target_power_volt. Ключевой регресс-случай (SEM): от РОВНО нуля формула
  // target + target/100*1 не сдвинулась бы никогда (0 + 0 == 0) - floor из
  // п.1 гарантирует, что стартуем не с нуля, а с порога, где multiplicative
  // шаг уже ненулевой. ---
  float previous = target_power_volt;
  int steps = 0;
  while (target_power_volt < original && steps < 100000) {
    do_restore();
    check(target_power_volt > previous,
          "РЕГРЕСС: восстановление обязано строго расти на каждом шаге (не залипать)");
    previous = target_power_volt;
    steps++;
  }
  check(steps > 0, "восстановление обязано сделать хотя бы один шаг");
  check(steps < 100000, "восстановление обязано достичь исходного значения за разумное число шагов (не залипать)");
  check(target_power_volt >= original,
        "РЕГРЕСС: восстановление после серии снижений обязано вернуть мощность к исходному значению");

  if (failures != 0) return 1;
  std::cout << "additive power restoration after reduction series checks passed\n";
  return 0;
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


def extract_reduce_snippet(alarm_source: str) -> str:
    start = alarm_source.index(REDUCE_START)
    end = alarm_source.index("#endif", start) + len("#endif")
    return alarm_source[start:end]


def extract_restore_snippet(alarm_source: str) -> str:
    start = alarm_source.index(RESTORE_START)
    end = alarm_source.index("#endif", start) + len("#endif")
    return alarm_source[start:end]


def build_harness(threshold_block: str, reduce_snippet: str, restore_snippet: str) -> str:
    harness = HARNESS_TEMPLATE.replace("@THRESHOLD_BLOCK@", threshold_block)
    harness = harness.replace("@REDUCE_SNIPPET@", reduce_snippet)
    harness = harness.replace("@RESTORE_SNIPPET@", restore_snippet)
    return harness


def compile_and_run(harness: str, label: str, extra_define: str | None) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-power-restore-additive-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "power_restore_additive_test.cpp"
        binary = temp / "power_restore_additive_test"
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


def main() -> int:
    power_source = read_source("power_regulator.h")
    alarm_source = read_source("alarm.h")

    try:
        threshold_block = extract_threshold_block(power_source)
        reduce_snippet = extract_reduce_snippet(alarm_source)
        restore_snippet = extract_restore_snippet(alarm_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    harness = build_harness(threshold_block, reduce_snippet, restore_snippet)
    rc = compile_and_run(harness, "KVIC/RMVK", None)
    if rc != 0:
        return rc
    rc = compile_and_run(harness, "SEM_AVR", "-DSAMOVAR_USE_SEM_AVR")
    if rc != 0:
        return rc

    # --- Проверка содержательности: возвращаем снижение к сырому виду без
    # floor'а (как было до задачи) - на 50 итерациях мощность обязана
    # провалиться ниже порога/в 0, и последующее восстановление на
    # мультипликативной (SEM) формуле обязано "залипнуть" - мутация ловится
    # РОВНО на этих assert-ах, не на предупреждении компилятора.
    mutated_alarm = alarm_source.replace(
        "set_current_power(max(target_power_volt - target_power_volt / 100 * 3, power_work_mode_threshold()));",
        "set_current_power(target_power_volt - target_power_volt / 100 * 3);",
        1,
    ).replace(
        "set_current_power(max(target_power_volt - 1 * PWR_FACTOR, power_work_mode_threshold()));",
        "set_current_power(target_power_volt - 1 * PWR_FACTOR);",
        1,
    )
    if mutated_alarm == alarm_source:
        print("FAIL: mutation anchor missing (reduction floor)", file=sys.stderr)
        return 1
    mutated_reduce_snippet = extract_reduce_snippet(mutated_alarm)
    mutated_harness = build_harness(threshold_block, mutated_reduce_snippet, restore_snippet)
    mutation_rc = compile_and_run(mutated_harness, "mutation (no reduction floor) SEM_AVR", "-DSAMOVAR_USE_SEM_AVR")
    if mutation_rc == 0:
        print("FAIL: mutation (removed reduction floor) survived - restore-stuck regression not caught", file=sys.stderr)
        return 1

    print("power restore additive mutation check: mutation killed as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
