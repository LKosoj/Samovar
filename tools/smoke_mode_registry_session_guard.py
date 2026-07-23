#!/usr/bin/env python3
"""Регресс-проверка [P7 п.1/п.2] mode_registry.h: mode_apply_power_on_command.

п.1 - команда старта "чужого" режима (SAMOVAR_START для ректификации или
табличная powerOnCommand-команда другого режима) не должна молча перезапускать
уже активную сессию (program_update_session_active() == true) - раньше она
форсированно переключала Samovar_Mode/SamovarStatusInt, что рвало текущий
процесс без предупреждения. Теперь при активной чужой сессии - отказ с
сообщением, без единой мутации состояния.

п.2 - БК (SAMOVAR_BK_MODE) в таблице mode_registry() имеет startCommand =
SAMOVAR_NONE (было SAMOVAR_START) - у БК нет действия "старт/следующая
программа" через SAMOVAR_START (это команда ректификации); веб-экшен
action=start для БК не должен молча дёргать чужой ректификационный старт.
SUVID/LUA сознательно НЕ трогаются (асимметрия) - проверяем, что они
по-прежнему SAMOVAR_START.

Тест вытаскивает РЕАЛЬНЫЕ тела mode_apply_power_on_command,
mode_ops_by_power_on_command, program_update_session_active,
mode_is_program_owner, mode_status_session_active, mode_startval_session_active
из mode_registry.h через extract_function_body и компилирует их в харнесс с
собственной МИНИМАЛЬНОЙ (синтетической, не реальной) таблицей mode_registry()/
mode_registry_count() - тестируется общая логика guard/isNewSession, которая не
зависит от конкретного состава реальной таблицы. Реальный состав таблицы
(п.2, BK/SUVID/LUA startCommand) проверяется ОТДЕЛЬНО, текстовым способом, на
самом файле mode_registry.h.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

FUNCTIONS = [
    "inline bool mode_is_program_owner(SAMOVAR_MODE mode)",
    "inline bool mode_status_session_active(int16_t status)",
    "inline bool mode_startval_session_active(int16_t value)",
    "inline bool program_update_session_active()",
    "inline const ModeOps* mode_ops_by_power_on_command(SamovarCommands command)",
    "inline bool mode_apply_power_on_command(SamovarCommands command)",
]

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstddef>
#include <iostream>

// String используется только как тип возврата ModeStatusFn/непроверяемых
// полей таблицы (в синтетических строках всегда nullptr) - функционирующий
// класс не нужен, достаточно неполного объявления.
class String;

enum SAMOVAR_MODE {SAMOVAR_RECTIFICATION_MODE, SAMOVAR_DISTILLATION_MODE, SAMOVAR_BEER_MODE, SAMOVAR_BK_MODE, SAMOVAR_NBK_MODE, SAMOVAR_SUVID_MODE, SAMOVAR_LUA_MODE};
enum SamovarCommands {SAMOVAR_NONE, SAMOVAR_START, SAMOVAR_POWER, SAMOVAR_RESET, CALIBRATE_START, CALIBRATE_STOP, SAMOVAR_PAUSE, SAMOVAR_CONTINUE, SAMOVAR_SETBODYTEMP, SAMOVAR_DISTILLATION, SAMOVAR_BEER, SAMOVAR_BEER_NEXT, SAMOVAR_BK, SAMOVAR_NBK, SAMOVAR_SELF_TEST, SAMOVAR_DIST_NEXT, SAMOVAR_NBK_NEXT};
enum MESSAGE_TYPE {ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, NONE_MSG = 100};

constexpr int16_t SAMOVAR_STATUS_IDLE = 0;
constexpr int16_t SAMOVAR_STATUS_DISTILLATION = 1000;
constexpr int16_t SAMOVAR_STATUS_BEER = 2000;
constexpr int16_t SAMOVAR_STATUS_BK = 3000;
constexpr int16_t SAMOVAR_STATUS_NBK = 4000;
constexpr int16_t SAMOVAR_STARTVAL_IDLE = 0;

using ModeVoidFn = void (*)();
using ModeStatusFn = String (*)();

struct ModeOps {
  SAMOVAR_MODE mode;
  int16_t activeStatus;
  int16_t startvalRangeLow;
  int16_t startvalRangeHigh;
  const char* pagePath;
  SamovarCommands powerOnCommand;
  SamovarCommands startCommand;
  ModeVoidFn alarm;
  ModeVoidFn finish;
  ModeStatusFn status;
};

// Синтетическая (НЕ реальная) минимальная таблица - только для проверки общей
// guard/isNewSession-логики mode_apply_power_on_command, не зависящей от
// конкретного состава реальной таблицы. Реальные BK/SUVID/LUA строки
// проверяются отдельно, текстовым способом (см. main() ниже, отдельная
// проверка не через этот харнесс).
inline const ModeOps* mode_registry() {
  static const ModeOps ops[] = {
    {SAMOVAR_BK_MODE, SAMOVAR_STATUS_BK, SAMOVAR_STATUS_BK, SAMOVAR_STATUS_BK + 1, "/bk.htm", SAMOVAR_BK, SAMOVAR_NONE, nullptr, nullptr, nullptr},
    {SAMOVAR_NBK_MODE, SAMOVAR_STATUS_NBK, SAMOVAR_STATUS_NBK, SAMOVAR_STATUS_NBK + 1000, "/nbk.htm", SAMOVAR_NBK, SAMOVAR_NBK_NEXT, nullptr, nullptr, nullptr},
  };
  return ops;
}

inline size_t mode_registry_count() {
  return 2;
}

// --- Глобальное состояние, которым управляют сценарии ---
bool PowerOn = false;
SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
int16_t SamovarStatusInt = SAMOVAR_STATUS_IDLE;
int16_t startval = SAMOVAR_STARTVAL_IDLE;

// --- Моки внешних зависимостей (не-static: единственные вызовы лежат во
// вклеенных реальных телах ниже; со static мутация, убравшая вызов, роняла бы
// компилятор по unused-function вместо содержательного assert-а) ---
static int modeSwitchInProgressReturn = 0; // 0 = false
bool mode_switch_in_progress() { return modeSwitchInProgressReturn != 0; }

static int changeSamovarModeCalls = 0;
void change_samovar_mode() { changeSamovarModeCalls++; }

static int menuSamovarStartCalls = 0;
void menu_samovar_start() { menuSamovarStartCalls++; }

static int requestHeatingStartCalls = 0;
static int16_t lastRequestHeatingStartStatus = -1;
void mode_request_heating_start(int16_t activeStatus) { requestHeatingStartCalls++; lastRequestHeatingStartStatus = activeStatus; }

static int sendMsgCalls = 0;
void SendMsg(const char*, int) { sendMsgCalls++; }

@FUNCTIONS@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  PowerOn = false;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  startval = SAMOVAR_STARTVAL_IDLE;
  modeSwitchInProgressReturn = 0;
  changeSamovarModeCalls = 0;
  menuSamovarStartCalls = 0;
  requestHeatingStartCalls = 0;
  lastRequestHeatingStartStatus = -1;
  sendMsgCalls = 0;
}

int main() {
  // Сценарий A: генерическая (табличная) ветка, чужая АКТИВНАЯ сессия ->
  // отказ, состояние не тронуто, флаг старта нагрева не взведён.
  reset_fixture();
  Samovar_Mode = SAMOVAR_NBK_MODE;
  SamovarStatusInt = SAMOVAR_STATUS_NBK;
  startval = SAMOVAR_STATUS_NBK;
  PowerOn = true;
  {
    bool result = mode_apply_power_on_command(SAMOVAR_BK);
    check(result == false, "A: старт БК при активной сессии НБК должен быть отклонён");
    check(Samovar_Mode == SAMOVAR_NBK_MODE, "A: Samovar_Mode не должен измениться при отказе");
    check(SamovarStatusInt == SAMOVAR_STATUS_NBK, "A: SamovarStatusInt не должен измениться при отказе");
    check(changeSamovarModeCalls == 0, "A: change_samovar_mode не должен вызываться при отказе");
    check(requestHeatingStartCalls == 0, "A: mode_request_heating_start не должен взводиться при отказе");
    check(sendMsgCalls == 1, "A: должно быть отправлено ровно одно сообщение об отказе");
  }

  // Сценарий B: генерическая ветка, сессии НЕТ -> команда проходит, режим и
  // статус меняются, isNewSession==true взводит mode_request_heating_start.
  reset_fixture();
  Samovar_Mode = SAMOVAR_LUA_MODE;
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  startval = SAMOVAR_STARTVAL_IDLE;
  PowerOn = false;
  {
    bool result = mode_apply_power_on_command(SAMOVAR_BK);
    check(result == true, "B: старт БК без активной сессии должен пройти");
    check(Samovar_Mode == SAMOVAR_BK_MODE, "B: Samovar_Mode должен стать BK");
    check(SamovarStatusInt == SAMOVAR_STATUS_BK, "B: SamovarStatusInt должен стать BK");
    check(startval == SAMOVAR_STATUS_BK, "B: startval должен стать BK");
    check(changeSamovarModeCalls == 1, "B: change_samovar_mode должен быть вызван ровно один раз");
    check(requestHeatingStartCalls == 1, "B: isNewSession==true должен взвести mode_request_heating_start ровно один раз");
    check(lastRequestHeatingStartStatus == SAMOVAR_STATUS_BK, "B: mode_request_heating_start должен быть взведён для activeStatus целевого режима (BK)");
  }

  // Сценарий C: SAMOVAR_START, чужая активная сессия (режим != RECT) -> отказ.
  reset_fixture();
  Samovar_Mode = SAMOVAR_BK_MODE;
  SamovarStatusInt = SAMOVAR_STATUS_BK;
  startval = SAMOVAR_STATUS_BK;
  PowerOn = true;
  {
    bool result = mode_apply_power_on_command(SAMOVAR_START);
    check(result == false, "C: SAMOVAR_START при активной сессии БК должен быть отклонён");
    check(Samovar_Mode == SAMOVAR_BK_MODE, "C: Samovar_Mode не должен измениться при отказе SAMOVAR_START");
    check(menuSamovarStartCalls == 0, "C: menu_samovar_start не должен вызываться при отказе");
    check(sendMsgCalls == 1, "C: должно быть отправлено ровно одно сообщение об отказе");
  }

  // Сценарий D: SAMOVAR_START, режим УЖЕ ректификация (та же ветка "своя
  // сессия") -> guard пропускает (mode == RECT), команда проходит как
  // "следующая программа/рестарт своей сессии", даже если сессия активна.
  reset_fixture();
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  SamovarStatusInt = 10; // произвольный ректификационный под-статус (активная сессия)
  startval = SAMOVAR_STARTVAL_IDLE;
  PowerOn = true;
  {
    bool result = mode_apply_power_on_command(SAMOVAR_START);
    check(result == true, "D: SAMOVAR_START из своего же режима (RECT) должен пройти даже при активной сессии");
    check(menuSamovarStartCalls == 1, "D: menu_samovar_start должен быть вызван ровно один раз");
  }

  // Сценарий E: генерическая ветка, ПОВТОРНАЯ команда в УЖЕ активную СВОЮ
  // сессию (тот же mode и тот же activeStatus) -> guard пропускает (ops->mode
  // == Samovar_Mode), но isNewSession==false - флаг НЕ взводится повторно.
  reset_fixture();
  Samovar_Mode = SAMOVAR_BK_MODE;
  SamovarStatusInt = SAMOVAR_STATUS_BK;
  startval = SAMOVAR_STATUS_BK;
  PowerOn = true;
  {
    bool result = mode_apply_power_on_command(SAMOVAR_BK);
    check(result == true, "E: повторная команда в свою же активную сессию должна проходить (не считается чужой)");
    check(requestHeatingStartCalls == 0, "E: isNewSession==false не должен взводить mode_request_heating_start повторно");
  }

  if (failures != 0) return 1;
  std::cout << "mode_registry session guard smoke checks passed\n";
  return 0;
}
'''


def build_harness(source: str) -> str:
    code = strip_cpp_comments(source)
    bodies = []
    for signature in FUNCTIONS:
        body = extract_function_body(code, signature)
        bodies.append(f"{signature} {{{body}}}")
    return HARNESS_TEMPLATE.replace("@FUNCTIONS@", "\n\n".join(bodies))


def check_table_start_commands(source: str, errors: list[str]) -> None:
    code = strip_cpp_comments(source)
    row_match = re.search(r"\{SAMOVAR_BK_MODE,[^}]*\}", code)
    if row_match is None:
        errors.append("mode_registry.h: BK row not found in mode_registry() table")
        return
    row = row_match.group(0)
    fields = [f.strip() for f in row.strip("{}").split(",")]
    if len(fields) < 7:
        errors.append(f"mode_registry.h: BK row has fewer than 7 fields: {row}")
        return
    if fields[6] != "SAMOVAR_NONE":
        errors.append(
            f"mode_registry.h: BK row startCommand expected SAMOVAR_NONE, got {fields[6]!r}"
        )

    for mode_name in ("SAMOVAR_SUVID_MODE", "SAMOVAR_LUA_MODE"):
        row_match = re.search(r"\{" + mode_name + r",[^}]*\}", code)
        if row_match is None:
            errors.append(f"mode_registry.h: {mode_name} row not found")
            continue
        row = row_match.group(0)
        fields = [f.strip() for f in row.strip("{}").split(",")]
        if len(fields) < 7:
            errors.append(f"mode_registry.h: {mode_name} row has fewer than 7 fields: {row}")
            continue
        if fields[6] != "SAMOVAR_START":
            errors.append(
                f"mode_registry.h: {mode_name} startCommand should stay SAMOVAR_START (asymmetry with BK), got {fields[6]!r}"
            )


def main() -> int:
    source = (ROOT / "mode_registry.h").read_text(encoding="utf-8")

    errors: list[str] = []
    check_table_start_commands(source, errors)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    try:
        harness = build_harness(source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-mode-registry-guard-") as temp_dir:
        temp = Path(temp_dir)
        cpp_source = temp / "mode_registry_session_guard_test.cpp"
        binary = temp / "mode_registry_session_guard_test"
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
