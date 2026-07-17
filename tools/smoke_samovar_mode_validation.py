#!/usr/bin/env python3
"""G6: единый валидатор диапазона режима самовара.

До фикса is_valid_samovar_mode() (WebServer.ino) не имела ни одного вызова
(мёртвый код), а сам диапазон [SAMOVAR_RECTIFICATION_MODE..SAMOVAR_LUA_MODE]
был продублирован инлайн в queue_profile_operation() и change_samovar_mode().
Отдельно set_lua_mode_value() (Samovar.ino) вообще не проверяла диапазон
входного int32_t перед приведением к SAMOVAR_MODE и записью в SamSetup.Mode/
Samovar_Mode/Samovar_CR_Mode.

Тест поведенчески проверяет:
  - is_valid_samovar_mode() (реальное тело, извлечённое из WebServer.ino)
    принимает ровно [0..SAMOVAR_LUA_MODE] и отвергает всё остальное, включая
    отрицательные значения (важно для int32_t из Lua);
  - set_lua_mode_value() (реальное тело, извлечённое из Samovar.ino) теперь
    отвергает некорректный индекс режима для КАЖДОЙ из трёх целей (SETUP/
    ACTIVE/CONTROL), не трогая состояние — это и есть требуемое владельцем
    падение с ошибкой на стороне Lua (set_lua_mode_value возвращает false ->
    lua_wrapper_set_num_variable поднимает luaL_error);
  - для ВАЛИДНЫХ значений семантика не изменилась: состояние обновляется,
    change_samovar_mode() вызывается ровно один раз при смене ACTIVE.

Структурно (на реальных извлечённых телах) проверяется, что дублирующиеся
инлайн-проверки диапазона в queue_profile_operation()/change_samovar_mode()
заменены вызовом is_valid_samovar_mode(), а не переписаны на месте.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

web_text = (ROOT / "WebServer.ino").read_text(encoding="utf-8", errors="ignore")
samovar_text = (ROOT / "Samovar.ino").read_text(encoding="utf-8", errors="ignore")
samovar_h_text = (ROOT / "Samovar.h").read_text(encoding="utf-8", errors="ignore")
api_text = (ROOT / "samovar_api.h").read_text(encoding="utf-8", errors="ignore")

mode_enum_match = re.search(r"enum SAMOVAR_MODE \{[^}]*\};", samovar_h_text)
if not mode_enum_match:
    errors.append("enum SAMOVAR_MODE not found in Samovar.h")
mode_enum_line = mode_enum_match.group(0) if mode_enum_match else ""

target_enum_match = re.search(r"enum LuaModeTarget[^{]*\{[^}]*\};", api_text)
if not target_enum_match:
    errors.append("enum LuaModeTarget not found in samovar_api.h")
target_enum_line = target_enum_match.group(0) if target_enum_match else ""

try:
    validator_body = extract_function_body(web_text, "bool is_valid_samovar_mode(long mode) {")
except ValueError as exc:
    errors.append(str(exc))
    validator_body = ""

try:
    set_lua_mode_body = extract_function_body(samovar_text, "bool set_lua_mode_value(LuaModeTarget target, int32_t value) {")
except ValueError as exc:
    errors.append(str(exc))
    set_lua_mode_body = ""

# --- Четвёртое место: кламп режима в apply_config_runtime (путь загрузки профиля).
#     SamSetup.Mode — знаковый int из профиля, поэтому проверять только верхнюю границу
#     мало: отрицательное значение проходило насквозь, mode_ops_by_mode() возвращал
#     nullptr и mode_dispatch_alarm() молча не вызывал ни одного обработчика аварий.
mode_clamp_match = re.search(
    r"if \(.*?\) SamSetup\.Mode = 0;\n\s*Samovar_Mode = \(SAMOVAR_MODE\)SamSetup\.Mode;",
    samovar_text)
if not mode_clamp_match:
    errors.append("mode clamp block not found in Samovar.ino (apply_config_runtime)")
mode_clamp_body = mode_clamp_match.group(0) if mode_clamp_match else ""

# --- Дедупликация: два прежних места дублирования обязаны звать единый
#     валидатор и не повторять диапазон инлайн.
try:
    queue_profile_body = extract_function_body(
        web_text,
        "static OperationError queue_profile_operation(")
except ValueError as exc:
    errors.append(str(exc))
    queue_profile_body = ""
if queue_profile_body:
    if "is_valid_samovar_mode(sourceMode)" not in queue_profile_body or \
            "is_valid_samovar_mode(targetMode)" not in queue_profile_body:
        errors.append("queue_profile_operation does not reuse is_valid_samovar_mode")
    if "SAMOVAR_RECTIFICATION_MODE" in queue_profile_body or "SAMOVAR_LUA_MODE" in queue_profile_body:
        errors.append("queue_profile_operation still duplicates the inline mode range check")

try:
    change_mode_body = extract_function_body(web_text, "void change_samovar_mode() {")
except ValueError as exc:
    errors.append(str(exc))
    change_mode_body = ""
if change_mode_body:
    require_ordered_tokens(
        "change_samovar_mode reuses the single validator",
        change_mode_body,
        [
            "if (!is_valid_samovar_mode(Samovar_Mode)) {",
            "Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;",
        ],
        errors,
    )
    if "SAMOVAR_LUA_MODE" in change_mode_body:
        errors.append("change_samovar_mode still duplicates the inline mode range check")

if set_lua_mode_body and "is_valid_samovar_mode(value)" not in set_lua_mode_body:
    errors.append("set_lua_mode_value does not validate the mode range via is_valid_samovar_mode")

# is_valid_samovar_mode больше не мёртвый код: минимум 3 использования
# (queue_profile_operation, change_samovar_mode, set_lua_mode_value).
call_sites = len(re.findall(r"is_valid_samovar_mode\(", web_text)) - web_text.count(
    "bool is_valid_samovar_mode(long mode)")
call_sites += len(re.findall(r"is_valid_samovar_mode\(", samovar_text)) - samovar_text.count(
    "bool is_valid_samovar_mode(long mode)")
if call_sites < 3:
    errors.append(f"is_valid_samovar_mode has only {call_sites} call site(s), expected >= 3")

# --- Поведенческая проверка: реальные тела is_valid_samovar_mode() и
#     set_lua_mode_value(), скомпилированные и выполненные вместе.
HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

@MODE_ENUM@
@TARGET_ENUM@

static int change_samovar_mode_calls = 0;
static bool pending_lock_result = true;
static int pending_lock_calls = 0;
static int pending_unlock_calls = 0;
static int profile_operation_phase = 0;   // PROFILE_OPERATION_EMPTY
static bool mode_switch_active = false;

static const int PROFILE_OPERATION_EMPTY = 0;
static long pdMS_TO_TICKS(long ms) { return ms; }
static bool pending_command_lock(long) { pending_lock_calls++; return pending_lock_result; }
static void pending_command_unlock(bool) { pending_unlock_calls++; }
static int profile_operation_phase_load() { return profile_operation_phase; }
static bool mode_switch_in_progress() { return mode_switch_active; }

struct SamSetupType { int Mode; };
static SamSetupType SamSetup;
static volatile SAMOVAR_MODE Samovar_Mode;
static volatile SAMOVAR_MODE Samovar_CR_Mode;

static void change_samovar_mode() { change_samovar_mode_calls++; }

static bool is_valid_samovar_mode(long mode) {
@VALIDATOR_BODY@
}

static bool set_lua_mode_value(LuaModeTarget target, int32_t value) {
@SET_LUA_MODE_BODY@
}

// Реальный кламп режима из apply_config_runtime (путь загрузки профиля).
static void apply_loaded_mode_clamp() {
@MODE_CLAMP_BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // --- is_valid_samovar_mode: границы диапазона -------------------------
  check(!is_valid_samovar_mode(-1), "negative mode must be rejected");
  check(is_valid_samovar_mode(0), "SAMOVAR_RECTIFICATION_MODE (0) must be accepted");
  check(is_valid_samovar_mode(static_cast<long>(SAMOVAR_LUA_MODE)),
        "SAMOVAR_LUA_MODE must be accepted");
  check(!is_valid_samovar_mode(static_cast<long>(SAMOVAR_LUA_MODE) + 1),
        "one past SAMOVAR_LUA_MODE must be rejected");
  check(!is_valid_samovar_mode(999999), "far out-of-range mode must be rejected");

  // --- set_lua_mode_value: некорректный индекс обязан падать с ошибкой,
  //     не трогая состояние (владелец: некорректный Lua-индекс -> ошибка).
  for (int target = 0; target <= 2; target++) {
    LuaModeTarget t = static_cast<LuaModeTarget>(target);
    SamSetup.Mode = 123;
    Samovar_Mode = static_cast<SAMOVAR_MODE>(2);
    Samovar_CR_Mode = static_cast<SAMOVAR_MODE>(2);
    change_samovar_mode_calls = 0;
    pending_lock_calls = 0;

    check(!set_lua_mode_value(t, -1), "negative Lua mode value must fail");
    check(!set_lua_mode_value(t, static_cast<int32_t>(SAMOVAR_LUA_MODE) + 1),
          "out-of-range Lua mode value must fail");
    check(SamSetup.Mode == 123 && Samovar_Mode == 2 && Samovar_CR_Mode == 2,
          "rejected Lua mode value must not mutate state");
  }

  // --- Валидные значения: семантика не изменилась -----------------------
  SamSetup.Mode = -1;
  check(set_lua_mode_value(LUA_MODE_TARGET_SETUP, 3), "valid SETUP mode must succeed");
  check(SamSetup.Mode == 3, "valid SETUP mode must be stored");

  Samovar_Mode = static_cast<SAMOVAR_MODE>(0);
  change_samovar_mode_calls = 0;
  check(set_lua_mode_value(LUA_MODE_TARGET_ACTIVE, static_cast<int32_t>(SAMOVAR_LUA_MODE)),
        "valid ACTIVE mode must succeed");
  check(Samovar_Mode == SAMOVAR_LUA_MODE, "valid ACTIVE mode must be applied");
  check(change_samovar_mode_calls == 1, "valid ACTIVE mode change must normalize exactly once");

  Samovar_CR_Mode = static_cast<SAMOVAR_MODE>(0);
  check(set_lua_mode_value(LUA_MODE_TARGET_CONTROL, static_cast<int32_t>(SAMOVAR_BEER_MODE)),
        "valid CONTROL mode must succeed");
  check(Samovar_CR_Mode == SAMOVAR_BEER_MODE, "valid CONTROL mode must be applied");

  // --- Кламп загрузки профиля: битый режим обязан приводиться к 0, а не проходить насквозь.
  // Отрицательное значение — главный кейс: SamSetup.Mode знаковый, и проверка только по
  // верхней границе его пропускала. Тогда Samovar_Mode уходил вне реестра режимов,
  // mode_ops_by_mode() отдавал nullptr, а mode_dispatch_alarm() молча не звал обработчик —
  // нагрев оставался без надзора за авариями.
  SamSetup.Mode = -1;
  apply_loaded_mode_clamp();
  check(SamSetup.Mode == 0,
        "отрицательный режим из профиля обязан сбрасываться в 0 (иначе теряется надзор за авариями)");
  check(Samovar_Mode == SAMOVAR_RECTIFICATION_MODE,
        "после сброса отрицательного режима Samovar_Mode обязан быть валидным");

  SamSetup.Mode = -12345;
  apply_loaded_mode_clamp();
  check(SamSetup.Mode == 0, "сильно отрицательный режим обязан сбрасываться в 0");

  SamSetup.Mode = SAMOVAR_LUA_MODE + 1;
  apply_loaded_mode_clamp();
  check(SamSetup.Mode == 0, "режим выше верхней границы обязан сбрасываться в 0");

  // Валидные значения кламп менять не должен — иначе сломаем загрузку настроек.
  for (int valid = SAMOVAR_RECTIFICATION_MODE; valid <= SAMOVAR_LUA_MODE; valid++) {
    SamSetup.Mode = valid;
    apply_loaded_mode_clamp();
    check(SamSetup.Mode == valid, "валидный режим кламп менять не должен");
    check((int)Samovar_Mode == valid, "валидный режим обязан доезжать до Samovar_Mode");
  }

  if (failures != 0) return 1;
  std::cout << "Samovar mode validation smoke checks passed\n";
  return 0;
}
'''


def run_behavioral_check() -> None:
    if not (validator_body and set_lua_mode_body and mode_enum_line and target_enum_line
            and mode_clamp_body):
        return
    harness = (
        HARNESS_TEMPLATE
        .replace("@MODE_ENUM@", mode_enum_line)
        .replace("@TARGET_ENUM@", target_enum_line)
        .replace("@VALIDATOR_BODY@", validator_body)
        .replace("@SET_LUA_MODE_BODY@", set_lua_mode_body)
        .replace("@MODE_CLAMP_BODY@", mode_clamp_body)
    )
    with tempfile.TemporaryDirectory(prefix="samovar-mode-validation-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "samovar_mode_validation_test.cpp"
        binary = temp / "samovar_mode_validation_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            errors.append("compile failed:\n" + compile_result.stdout + compile_result.stderr)
            return
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if run_result.returncode != 0:
            errors.append("runtime checks failed:\n" + run_result.stdout + run_result.stderr)


run_behavioral_check()

if errors:
    print("Samovar mode validation smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Samovar mode validation smoke check passed")
