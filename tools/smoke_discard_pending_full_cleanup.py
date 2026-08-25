#!/usr/bin/env python3
"""Регресс-проверка T39 (остаток пункта А2 "освобождать канал целиком"):
discard_pending_mode_control_commands() (WebServer.ino) обязана дочищать ВСЕ
отложенные команды режима, даже если I2C-ветка отказала.

Контекст: раньше стояло `if (!cancel_queued_i2c_operations_locked(cancelled))
return false;` - ранний выход посреди очистки. cancel_queued_i2c_operations_locked
возвращает false при рассинхроне флага и склада операций (карточки нет, а флаг
взведён) или при отказе operation_store_finish_locked. В этом случае
pending_pnbk_flag, pending_voltage_flag и четыре Lua-флага оставались
взведёнными, ХОТЯ cancelled уже был выставлен в true (пользователю уходит
"Отложенные управляющие команды отменены сменой режима").

Дальше switch_samovar_mode() (mode_switch.h:255-263) при неудаче ждёт дедлайн и
завершает смену принудительно через force_complete_mode_switch_failed() - барьер
снимается, режим меняется, а невычищенные флаги применяются УЖЕ В НОВОМ РЕЖИМЕ:
команда, адресованная старому режиму (например, отложенный запуск Lua-скрипта
или смена мощности НБК), исполняется в чужом.

Тест берёт РЕАЛЬНОЕ тело функции через extract_function_body и компилирует
g++-харнессом с заглушкой cancel_queued_i2c_operations_locked, возвращающей
false. Проверяется поведение (значения флагов после вызова и код возврата),
а не текст.

Мутации (тест обязан падать на ASSERT, не на ошибке компиляции):
  - вернуть ранний `return false` -> хвостовые флаги остаются взведёнными;
  - вернуть безусловное `return true` -> отказ I2C-ветки теряется.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "static bool discard_pending_mode_control_commands(bool& cancelled)"

HARNESS = r'''
#include <iostream>
#include <string>

#define SAMOVAR_USE_POWER
#define USE_LUA

static bool pending_rescan_ds_flag = true;
static bool pending_stop_self_test_flag = true;
static bool pending_mixer_flag = true;
static bool pending_water_temp_flag = true;
static bool pending_pump_speed_flag = true;
static bool pending_nbkopt_flag = true;
static bool pending_pnbk_flag = true;
static bool pending_voltage_flag = true;
static bool pending_lua_start_flag = true;
static bool pending_lua_file_flag = true;
static bool pending_lua_flag = true;
static bool pending_lua_reload_flag = true;
static std::string pending_lua_file = "rectificat.lua";
static std::string pending_lua_str = "print(1)";

static bool lockAvailable = true;
static bool i2cBranchResult = true;

struct PendingCommandLockGuard {
  bool held;
  PendingCommandLockGuard() : held(lockAvailable) {}
  explicit operator bool() const { return held; }
};

static bool pending_mode_control_commands_locked() {
  return pending_rescan_ds_flag || pending_stop_self_test_flag ||
         pending_mixer_flag || pending_water_temp_flag ||
         pending_pump_speed_flag || pending_nbkopt_flag ||
         pending_pnbk_flag || pending_voltage_flag ||
         pending_lua_start_flag || pending_lua_file_flag ||
         pending_lua_flag || pending_lua_reload_flag;
}

static bool cancel_queued_i2c_operations_locked(bool& cancelled) {
  if (!i2cBranchResult) cancelled = true;
  return i2cBranchResult;
}

static bool discard_pending_mode_control_commands(bool& cancelled) {
__BODY__
}

static int failures = 0;

static void expect(bool condition, const char* what) {
  if (!condition) {
    std::cout << "ASSERT: " << what << std::endl;
    failures++;
  }
}

static void reset_flags() {
  pending_rescan_ds_flag = true;
  pending_stop_self_test_flag = true;
  pending_mixer_flag = true;
  pending_water_temp_flag = true;
  pending_pump_speed_flag = true;
  pending_nbkopt_flag = true;
  pending_pnbk_flag = true;
  pending_voltage_flag = true;
  pending_lua_start_flag = true;
  pending_lua_file_flag = true;
  pending_lua_flag = true;
  pending_lua_reload_flag = true;
  pending_lua_file = "rectificat.lua";
  pending_lua_str = "print(1)";
}

static bool tail_flags_cleared() {
  return !pending_pnbk_flag && !pending_voltage_flag &&
         !pending_lua_start_flag && !pending_lua_file_flag &&
         !pending_lua_flag && !pending_lua_reload_flag &&
         pending_lua_file.empty() && pending_lua_str.empty();
}

int main() {
  // Отказ I2C-ветки: очистка обязана дойти до конца, возврат - false.
  reset_flags();
  lockAvailable = true;
  i2cBranchResult = false;
  bool cancelled = false;
  bool result = discard_pending_mode_control_commands(cancelled);
  expect(result == false, "отказ I2C-ветки обязан вернуться наружу как false");
  expect(cancelled, "cancelled взводится, раз команды были");
  expect(!pending_rescan_ds_flag && !pending_mixer_flag && !pending_nbkopt_flag,
         "головные флаги сброшены при отказе I2C-ветки");
  expect(tail_flags_cleared(),
         "хвостовые флаги (pnbk/voltage/lua) сброшены ДАЖЕ при отказе I2C-ветки");

  // Успешный путь: всё сброшено, возврат true.
  reset_flags();
  i2cBranchResult = true;
  cancelled = false;
  result = discard_pending_mode_control_commands(cancelled);
  expect(result == true, "успешная очистка возвращает true");
  expect(cancelled, "cancelled взводится на успешном пути");
  expect(tail_flags_cleared(), "хвостовые флаги сброшены на успешном пути");

  // Лок занят: не трогаем ничего, возврат false.
  reset_flags();
  lockAvailable = false;
  cancelled = false;
  result = discard_pending_mode_control_commands(cancelled);
  expect(result == false, "занятый лок возвращает false");
  expect(!cancelled, "занятый лок не взводит cancelled");
  expect(pending_pnbk_flag && pending_lua_flag,
         "занятый лок не трогает флаги - чистить без лока нельзя");

  if (failures) {
    std::cout << "FAILURES: " << failures << std::endl;
    return 1;
  }
  std::cout << "OK: очистка отложенных команд идёт до конца при любом исходе I2C-ветки" << std::endl;
  return 0;
}
'''


def build_and_run(body: str) -> tuple[int, str]:
    source = HARNESS.replace("__BODY__", body)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "harness.cpp"
        exe = Path(tmp) / "harness"
        src.write_text(source, encoding="utf-8")
        build = subprocess.run(
            ["g++", "-std=c++17", "-O0", "-o", str(exe), str(src)],
            capture_output=True, text=True)
        if build.returncode != 0:
            return 2, build.stderr
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        return run.returncode, run.stdout + run.stderr


def main() -> int:
    web = (ROOT / "WebServer.ino").read_text(encoding="utf-8", errors="replace")
    body = extract_function_body(web, SIGNATURE)

    code, output = build_and_run(body)
    if code != 0:
        print("Проверка не прошла на текущем коде:")
        print(output)
        return 1
    print(output.strip())

    # Мутация 1: ранний выход посреди очистки.
    mutated = body.replace(
        "const bool i2cDiscarded = cancel_queued_i2c_operations_locked(cancelled);",
        "if (!cancel_queued_i2c_operations_locked(cancelled)) return false;\n"
        "  const bool i2cDiscarded = true;")
    if mutated == body:
        print("Мутация 1 не применилась - тест перестал пинить нужное место")
        return 1
    code, output = build_and_run(mutated)
    if code == 2:
        print("Мутация 1 не собралась - тест ловит компилятор, а не поведение:")
        print(output)
        return 1
    if code == 0:
        print("Мутация 1 (ранний return false) НЕ поймана")
        return 1
    print("Мутация 1 поймана: ранний выход оставляет хвостовые флаги")

    # Мутация 2: отказ I2C-ветки теряется.
    mutated = body.replace("return i2cDiscarded;", "return true;")
    if mutated == body:
        print("Мутация 2 не применилась - тест перестал пинить нужное место")
        return 1
    code, output = build_and_run(mutated)
    if code == 2:
        print("Мутация 2 не собралась - тест ловит компилятор, а не поведение:")
        print(output)
        return 1
    if code == 0:
        print("Мутация 2 (потеря отказа I2C-ветки) НЕ поймана")
        return 1
    print("Мутация 2 поймана: отказ I2C-ветки обязан доходить до вызывающего")
    return 0


if __name__ == "__main__":
    sys.exit(main())
