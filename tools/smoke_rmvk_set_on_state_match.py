#!/usr/bin/env python3
"""Поведенческая проверка mod_rmv.ino::RMVK_set_on — ответ обязан совпасть с
запрошенным состоянием.

RMVK_cmd(..., RMVK_ON, ...) отвечает "ON"->1 или "OFF"->0 в ОБОИХ направлениях:
и на команду включения, и на чтение текущего состояния (RMVK_get_state). Поэтому
сам RMVK_cmd трогать нельзя - его поведение закреплено tools/smoke_rmvk_contract.py.
RMVK_set_on раньше отдавал наружу что угодно, кроме RMVK_ERROR, как успех: если
регулятор отказал во включении и ответил "OFF", вызывающий код (mod_rmv.ino,
power_regulator_rmvk.h) видел ret=0 != RMVK_ERROR и принимал это за успешную
команду.

Тест вытаскивает РЕАЛЬНОЕ тело RMVK_set_on из mod_rmv.ino через
extract_function_body (без переписывания логики) и подставляет его в
минимальный host-харнесс с мокнутым RMVK_cmd, который просто возвращает
значение, заданное сценарием - никакого реального UART.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "uint16_t RMVK_set_on(uint16_t state, uint64_t powerGeneration)"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstdio>
#include <iostream>

typedef enum {
  RMVK_INT = 0,
  RMVK_OK,
  RMVK_ON
} rmvk_res_t;

#define RMVK_ERROR 255

static uint16_t mockReturn = 0;
static int cmdCalls = 0;
static rmvk_res_t lastRes = RMVK_INT;

// Заглушка НЕ static: единственный вызов лежит во вклеенном теле RMVK_set_on
// ниже, и со static мутация, убравшая вызов, роняла бы компилятор по
// unused-function вместо содержательного assert-а. Держится это на проверке
// cmdCalls/lastRes ниже.
uint8_t RMVK_cmd(const char* cmd, rmvk_res_t res, bool energizing, uint64_t powerGeneration) {
  (void)cmd;
  (void)energizing;
  (void)powerGeneration;
  cmdCalls++;
  lastRes = res;
  return (uint8_t)mockReturn;
}

uint16_t RMVK_set_on(uint16_t state, uint64_t powerGeneration) {
@BODY@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  mockReturn = 0;
  cmdCalls = 0;
  lastRes = RMVK_INT;
}

// Сценарий 1: попросили включить, регулятор ответил "OFF" (mock=0) - это
// отказ регулятора, а не успех.
static void test_on_request_off_reply_is_error() {
  reset_fixture();
  mockReturn = 0;
  uint16_t ret = RMVK_set_on(1, 7);
  check(ret == RMVK_ERROR, "ответ OFF на команду включения не признан отказом регулятора");
  check(cmdCalls == 1, "RMVK_cmd должен быть вызван ровно один раз");
  check(lastRes == RMVK_ON, "RMVK_set_on должен запрашивать RMVK_ON");
}

// Сценарий 2: попросили включить, регулятор подтвердил "ON" (mock=1).
static void test_on_request_on_reply_succeeds() {
  reset_fixture();
  mockReturn = 1;
  uint16_t ret = RMVK_set_on(1, 7);
  check(ret == 1, "подтверждённое включение должно вернуть 1");
}

// Сценарий 3: попросили выключить, регулятор подтвердил "OFF" (mock=0).
static void test_off_request_off_reply_succeeds() {
  reset_fixture();
  mockReturn = 0;
  uint16_t ret = RMVK_set_on(0, 7);
  check(ret == 0, "подтверждённое выключение должно вернуть 0");
}

// Сценарий 4: транспортная ошибка (таймаут/BUSY) обязана остаться RMVK_ERROR.
static void test_transport_error_stays_error() {
  reset_fixture();
  mockReturn = RMVK_ERROR;
  uint16_t ret = RMVK_set_on(1, 7);
  check(ret == RMVK_ERROR, "транспортная ошибка обязана остаться RMVK_ERROR");
}

int main() {
  test_on_request_off_reply_is_error();
  test_on_request_on_reply_succeeds();
  test_off_request_off_reply_succeeds();
  test_transport_error_stays_error();
  if (failures != 0) return 1;
  std::cout << "RMVK_set_on state-match checks passed\n";
  return 0;
}
'''


def build_harness(body: str | None = None) -> str:
    if body is None:
        source = (ROOT / "mod_rmv.ino").read_text(encoding="utf-8")
        body = extract_function_body(source, SIGNATURE)
    return HARNESS_TEMPLATE.replace("@BODY@", body)


def compile_and_run(harness: str, emit: bool) -> tuple[int, bool]:
    """Возвращает (код возврата, скомпилировался ли харнесс)."""
    with tempfile.TemporaryDirectory(prefix="samovar-rmvk-set-on-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "rmvk_set_on_test.cpp"
        binary = temp / "rmvk_set_on_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            if emit:
                sys.stderr.write(compile_result.stdout)
                sys.stderr.write(compile_result.stderr)
            return compile_result.returncode, False
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if emit:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode, True


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rc, _ = compile_and_run(harness, True)
    if rc != 0:
        return rc

    # Мутация: убираем сверку ответа с запрошенным состоянием - остаётся
    # только проверка на транспортную ошибку, как было ДО правки. Сценарий 1
    # (state=1, ответ "OFF") обязан провалиться с осмысленным assert-текстом,
    # а не с ошибкой компиляции.
    body = extract_function_body((ROOT / "mod_rmv.ino").read_text(encoding="utf-8"), SIGNATURE)
    mutation = body.replace(
        "if (ret == RMVK_ERROR || ret != state) return RMVK_ERROR;",
        "if (ret == RMVK_ERROR) return RMVK_ERROR;",
        1,
    )
    if mutation == body:
        print("FAIL: state-match mutation anchor missing", file=sys.stderr)
        return 1

    mutant_rc, mutant_compiled = compile_and_run(build_harness(mutation), False)
    if not mutant_compiled:
        print("FAIL: mutated RMVK_set_on failed to compile instead of failing the assert", file=sys.stderr)
        return 1
    if mutant_rc == 0:
        print("FAIL: state-match mutation survived (OFF-on-ON-request no longer caught)", file=sys.stderr)
        return 1

    print("RMVK_set_on state-match and mutation checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
