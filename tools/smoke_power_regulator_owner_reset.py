#!/usr/bin/env python3
"""Регресс-проверка [P7 п.3b] power_regulator.h: fail_close_regulator_locked
должен ронять СЕССИЮ владельца "ленивого" старта нагрева (distiller/BK/NBK), а
не просто гасить реле - иначе она сама молча переподнимет нагрев на следующем
тике proc() без нового действия пользователя (см. mode_common.h::
mode_begin_heating_session и [P7 п.3a] - флаг там защищает вход, но если
SamovarStatusInt остаётся активным статусом владельца, ветка mode_run_heating_start
в distiller.h/BK.h была бы вызвана заново тем же тиком, взяв уже устаревшую
сессию).

lazy_start_owner_status(status) - true для статусов, которые реально стартуют
через эту "ленивую" машинерию (DISTILLATION/BK/NBK); ректификация и пиво в неё
не входят. fail_close_regulator_locked теперь возвращает true, если статус был
статусом владельца (и она сбросила SamovarStatusInt/startval в IDLE) - false,
если нет (тогда состояние НЕ трогается вовсе - ректификация/пиво сами
разбираются со своим состоянием при отказе регулятора).

Тест вытаскивает РЕАЛЬНЫЕ тела lazy_start_owner_status и
fail_close_regulator_locked из power_regulator.h, реальный SafetyTransition/
safety_transition_advance из safety_transition.h (через -I ROOT), реальную
структуру PowerTransitionState - и мокает единственную истинно внешнюю
зависимость force_heater_output_off_locked (не-static, со счётчиком вызовов).

[P7 F6] Дополнительно (текстовая проверка, статические пины): 4 отчётных
блока в power_regulator.h ("Сессия прервана: отказ регулятора нагрева...")
после фикса [P7 F4] используют guard nbk_transition_reports_interruption()
вместо слишком широкого nbk_transition_active() (последний глушил сообщение
и на фазах мягкого финиша NBK, где никакого собственного сообщения об
прерывании NBK не отправляет). Извлекать сами функции tick_power_transition/
process_pending_power_request в компилируемый харнесс непрактично (тяжёлые
зависимости: UART-регистры, семафоры, #ifdef SAMOVAR_USE_POWER/RMVK/SEM_AVR) -
вместо этого проверяются ровно 4 вхождения нужного guard'а, порядок
portEXIT_CRITICAL -> guard -> mode_warn_log_close_failed -> SendMsg, и
отсутствие отката к старому guard'у.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

FUNCTIONS = [
    "inline bool lazy_start_owner_status(int16_t status)",
    "inline bool fail_close_regulator_locked(uint32_t now, bool enqueueResetCommand)",
]

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

#include "safety_transition.h"

constexpr int16_t SAMOVAR_STATUS_IDLE = 0;
constexpr int16_t SAMOVAR_STATUS_DISTILLATION = 1000;
constexpr int16_t SAMOVAR_STATUS_BEER = 2000;
constexpr int16_t SAMOVAR_STATUS_BK = 3000;
constexpr int16_t SAMOVAR_STATUS_NBK = 4000;
constexpr int16_t SAMOVAR_STARTVAL_IDLE = 0;

@STRUCT@

static PowerTransitionState powerTransition = {
  {SAFETY_TRANSITION_IDLE, 0},
  false,
  false,
  0,
  0,
};

// --- Глобальное состояние, которым управляют сценарии ---
int16_t SamovarStatusInt = SAMOVAR_STATUS_IDLE;
int16_t startval = SAMOVAR_STARTVAL_IDLE;

// --- Мок единственной истинно внешней зависимости (не-static) ---
static int forceHeaterOffCalls = 0;
static bool lastForceHeaterOffArg = false;
void force_heater_output_off_locked(bool requestSleep) {
  forceHeaterOffCalls++;
  lastForceHeaterOffArg = requestSleep;
}

@FUNCTIONS@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture(int16_t status) {
  SamovarStatusInt = status;
  startval = status;
  powerTransition.transition.phase = SAFETY_TRANSITION_IDLE;
  powerTransition.transition.deadline = 0;
  powerTransition.enqueueResetCommand = false;
  forceHeaterOffCalls = 0;
  lastForceHeaterOffArg = false;
}

int main() {
  // lazy_start_owner_status: 3 статуса-владельца + 2 не-владельца.
  check(lazy_start_owner_status(SAMOVAR_STATUS_DISTILLATION) == true, "owner: DISTILLATION должен быть владельцем");
  check(lazy_start_owner_status(SAMOVAR_STATUS_BK) == true, "owner: BK должен быть владельцем");
  check(lazy_start_owner_status(SAMOVAR_STATUS_NBK) == true, "owner: NBK должен быть владельцем");
  check(lazy_start_owner_status(SAMOVAR_STATUS_BEER) == false, "owner: BEER не должен быть владельцем");
  check(lazy_start_owner_status(SAMOVAR_STATUS_IDLE) == false, "owner: IDLE не должен быть владельцем");

  // fail_close_regulator_locked для каждого статуса-владельца: возвращает
  // true, сбрасывает SamovarStatusInt/startval в IDLE, реле гасит, помечает
  // enqueueResetCommand, переводит переход в OFF_REGULATOR_WAIT.
  for (int16_t ownerStatus : {SAMOVAR_STATUS_DISTILLATION, SAMOVAR_STATUS_BK, SAMOVAR_STATUS_NBK}) {
    reset_fixture(ownerStatus);
    bool result = fail_close_regulator_locked(12345, true);
    check(result == true, "owner-status: fail_close_regulator_locked должен вернуть true");
    check(SamovarStatusInt == SAMOVAR_STATUS_IDLE, "owner-status: SamovarStatusInt должен сброситься в IDLE");
    check(startval == SAMOVAR_STARTVAL_IDLE, "owner-status: startval должен сброситься в IDLE");
    check(forceHeaterOffCalls == 1 && lastForceHeaterOffArg == true, "owner-status: реле должны быть погашены (true)");
    check(powerTransition.enqueueResetCommand == true, "owner-status: enqueueResetCommand должен быть выставлен");
    check(powerTransition.transition.phase == POWER_TRANSITION_OFF_REGULATOR_WAIT, "owner-status: переход должен уйти в OFF_REGULATOR_WAIT");
  }

  // fail_close_regulator_locked для НЕ-владельца (пиво): возвращает false,
  // SamovarStatusInt/startval НЕ трогаются - реле всё равно гасятся (это не
  // специфично для владельцев), но состояние сессии остаётся как было.
  reset_fixture(SAMOVAR_STATUS_BEER);
  {
    bool result = fail_close_regulator_locked(6789, true);
    check(result == false, "non-owner: fail_close_regulator_locked должен вернуть false для BEER");
    check(SamovarStatusInt == SAMOVAR_STATUS_BEER, "non-owner: SamovarStatusInt НЕ должен измениться для BEER");
    check(startval == SAMOVAR_STATUS_BEER, "non-owner: startval НЕ должен измениться для BEER");
    check(forceHeaterOffCalls == 1, "non-owner: реле всё равно должны быть погашены");
  }

  if (failures != 0) return 1;
  std::cout << "power regulator owner reset smoke checks passed\n";
  return 0;
}
'''


def check_owner_reset_report_guard(source: str, errors: list[str]) -> None:
    code = strip_cpp_comments(source)
    guard = "if (ownerReset && !nbk_transition_reports_interruption()) {"
    warn = "mode_warn_log_close_failed();"
    send = (
        'SendMsg("Сессия прервана: отказ регулятора нагрева. '
        'Требуется повторный запуск.", ALARM_MSG);'
    )
    exit_critical = "portEXIT_CRITICAL(&emergencyStopMux);"

    offset = 0
    count = 0
    while True:
        guard_index = code.find(guard, offset)
        if guard_index < 0:
            break
        count += 1
        exit_index = code.rfind(exit_critical, offset, guard_index)
        if exit_index < 0:
            errors.append(
                f"power_regulator.h: owner-reset report block #{count} "
                "guard is not preceded by portEXIT_CRITICAL(&emergencyStopMux)"
            )
        warn_index = code.find(warn, guard_index)
        send_index = code.find(send, guard_index)
        if warn_index < 0 or send_index < 0 or not (guard_index < warn_index < send_index):
            errors.append(
                f"power_regulator.h: owner-reset report block #{count} does not follow the "
                "guard -> mode_warn_log_close_failed -> SendMsg order"
            )
        offset = guard_index + len(guard)

    if count != 4:
        errors.append(
            "power_regulator.h: expected exactly 4 owner-reset report blocks guarded by "
            f"nbk_transition_reports_interruption(), found {count}"
        )

    # [P7 F4] Старый (слишком широкий) guard не должен вернуться в эти отчётные блоки -
    # он глушит сообщение и на фазах мягкого финиша NBK, где своего сообщения нет.
    if "ownerReset && !nbk_transition_active()" in code:
        errors.append(
            "power_regulator.h: found the old (too broad) guard "
            "'ownerReset && !nbk_transition_active()' - should be "
            "'ownerReset && !nbk_transition_reports_interruption()'"
        )


def build_harness(source: str) -> str:
    code = strip_cpp_comments(source)
    struct_body, _ = extract_braced_block_after(code, "struct PowerTransitionState {")
    struct_text = f"struct PowerTransitionState {{{struct_body}}};"

    bodies = []
    for signature in FUNCTIONS:
        body = extract_function_body(code, signature)
        bodies.append(f"{signature} {{{body}}}")

    harness = HARNESS_TEMPLATE.replace("@STRUCT@", struct_text)
    harness = harness.replace("@FUNCTIONS@", "\n\n".join(bodies))
    return harness


def main() -> int:
    source = (ROOT / "power_regulator.h").read_text(encoding="utf-8")

    errors: list[str] = []
    check_owner_reset_report_guard(source, errors)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    try:
        harness = build_harness(source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-power-regulator-owner-reset-") as temp_dir:
        temp = Path(temp_dir)
        cpp_source = temp / "power_regulator_owner_reset_test.cpp"
        binary = temp / "power_regulator_owner_reset_test"
        cpp_source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-I", str(ROOT), str(cpp_source), "-o", str(binary),
            ],
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
