#!/usr/bin/env python3
"""Поведенческая регресс-проверка эскалации в alarm.h::check_alarm().

Тест берёт РЕАЛЬНОЕ тело температурного лимита (блок
"if ((SteamSensor.avgTemp >= MAX_STEAM_TEMP || ... ) && PowerOn) { ... }")
из alarm.h через extract_function_body — без переписывания логики — и
подставляет его в минимальный host-харнесс, замокав только downstream-
зависимости (queue_samovar_command, request_emergency_stop, SendMsg).

Регресс, который тест защищает: отключение нагрева при перегреве куба идёт
через очередь команд (queue_samovar_command(SAMOVAR_POWER)). Раньше отказ
постановки в очередь просто логировался предупреждением, и ветка
"else request_emergency_stop(...)" становилась НЕДОСТИЖИМОЙ, пока
TankSensor.avgTemp >= SamSetup.DistTemp остаётся истинным — то есть при
мёртвой очереди нагрев не выключился бы никогда. Тест проверяет поведение
через моки (сколько раз и с какими аргументами вызваны queue_samovar_command
и request_emergency_stop), а не текст исходника.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

# Сигнатура внешнего if-условия температурного лимита в check_alarm().
# Используется и как ключ поиска в исходнике (extract_function_body ищет
# "{" сразу после этой строки), и как буквальный текст в харнессе ниже —
# так тест ловит переформулировку условия, а не только тела.
OUTER_IF_SIGNATURE = (
    "if ((SteamSensor.avgTemp >= MAX_STEAM_TEMP || WaterSensor.avgTemp >= MAX_WATER_TEMP || "
    "TankSensor.avgTemp >= SamSetup.DistTemp || sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP)) "
    "&& PowerOn)"
)

HARNESS_TEMPLATE = r'''
#include <cmath>
#include <cstdint>
#include <iostream>
#include <string>

using TickType_t = int;

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}
  String operator+(const char* text) const { return String(value_ + (text ? text : "")); }
  const std::string& value() const { return value_; }

 private:
  std::string value_;
};

static String operator+(const char* lhs, const String& rhs) {
  return String(std::string(lhs ? lhs : "") + rhs.value());
}

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum SamovarCommands { SAMOVAR_NONE, SAMOVAR_START, SAMOVAR_POWER, SAMOVAR_RESET };

#define MAX_STEAM_TEMP 98.8
#define MAX_WATER_TEMP 75
#define MAX_ACP_TEMP 75

struct DSSensor {
  float avgTemp = 0.0f;
};

struct SetupEEPROM {
  float DistTemp = 0.0f;
};

static DSSensor SteamSensor;
static DSSensor WaterSensor;
static DSSensor TankSensor;
static DSSensor ACPSensor;
static SetupEEPROM SamSetup;
static bool PowerOn = false;

// ACP-датчик не является предметом этого теста, упрощённая, но
// поведенчески достаточная реализация (реальная функция живёт в alarm.h).
static bool sensor_temp_at_least(const DSSensor& sensor, float temp) {
  return sensor.avgTemp >= temp;
}

static int sendMsgCalls = 0;
// Заглушки НЕ static: единственный вызов каждой лежит во вклеенном теле
// блока лимита куба, и со static мутация, убравшая вызов, роняла бы
// компилятор по unused-function вместо содержательного assert-а. Держится
// это на проверках sendMsgCalls/queueCalls: без них снятие static меняет
// ложный улов на молчаливую слепую зону, что хуже.
void SendMsg(const String&, MESSAGE_TYPE) { sendMsgCalls++; }

static int queueCalls = 0;
static SamovarCommands lastQueuedCommand = SAMOVAR_NONE;
static bool queueResult = true;
bool queue_samovar_command(SamovarCommands command, TickType_t timeout = 0) {
  (void)timeout;
  queueCalls++;
  lastQueuedCommand = command;
  return queueResult;
}

static int emergencyStopCalls = 0;
static std::string lastEmergencyReason;
static void request_emergency_stop(const String& reason) {
  emergencyStopCalls++;
  lastEmergencyReason = reason.value();
}

static void check_alarm_temp_limit_block() {
@OUTER_IF_SIGNATURE@ {
@BODY@
  }
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  SteamSensor.avgTemp = 20.0f;
  WaterSensor.avgTemp = 20.0f;
  TankSensor.avgTemp = 20.0f;
  ACPSensor.avgTemp = 20.0f;
  SamSetup.DistTemp = 96.0f;
  PowerOn = false;
  sendMsgCalls = 0;
  queueCalls = 0;
  lastQueuedCommand = SAMOVAR_NONE;
  queueResult = true;
  emergencyStopCalls = 0;
  lastEmergencyReason.clear();
}

// Штатный путь не сломан: очередь принимает команду -> аварийный останов не
// вызывается, в очередь поставлена именно SAMOVAR_POWER.
static void test_tank_limit_queue_success_no_emergency_stop() {
  reset_fixture();
  PowerOn = true;
  TankSensor.avgTemp = 96.0f;  // >= DistTemp
  queueResult = true;
  check_alarm_temp_limit_block();
  check(queueCalls == 1, "штатное завершение по лимиту куба не поставило команду в очередь ровно один раз");
  check(lastQueuedCommand == SAMOVAR_POWER, "в очередь по лимиту куба должна была уйти команда SAMOVAR_POWER");
  check(emergencyStopCalls == 0, "штатное завершение по лимиту куба не должно вызывать аварийный останов");
  // Программа завершается сама, без участия человека, поэтому пользователь
  // обязан быть уведомлён: иначе ректификация просто молча прекратится, и
  // причина останется неизвестной. Пинится ФАКТ уведомления, не текст - тексты
  // сообщений правит владелец, и тест не должен ему это запрещать.
  check(sendMsgCalls == 1, "штатное завершение по лимиту куба прошло без уведомления пользователя");
}

// Главный регресс-кейс: очередь отказывает (мертва) -> аварийный останов
// обязан сработать напрямую, иначе нагрев не выключился бы никогда.
static void test_tank_limit_queue_failure_triggers_emergency_stop() {
  reset_fixture();
  PowerOn = true;
  TankSensor.avgTemp = 96.0f;  // >= DistTemp
  queueResult = false;
  check_alarm_temp_limit_block();
  check(queueCalls == 1, "попытка штатной остановки по лимиту куба должна была произойти");
  check(emergencyStopCalls == 1,
        "РЕГРЕСС: отказ очереди команд при лимите температуры куба должен приводить к аварийному отключению нагрева");
}

// Ключевой кейс на недостижимость else: лимит куба и перегрев пара
// одновременно, очередь отказывает -> перегрев пара не должен остаться без
// реакции только из-за того, что внешнее условие поймала ветка куба.
static void test_tank_and_steam_limit_simultaneously_queue_failure_still_stops() {
  reset_fixture();
  PowerOn = true;
  TankSensor.avgTemp = 96.0f;    // >= DistTemp
  SteamSensor.avgTemp = 99.0f;   // >= MAX_STEAM_TEMP
  queueResult = false;
  check_alarm_temp_limit_block();
  check(emergencyStopCalls == 1,
        "РЕГРЕСС: одновременный перегрев пара при лимите куба и отказе очереди должен приводить к аварийному отключению");
}

// Существующее поведение else не сломано: перегрев пара без лимита куба
// по-прежнему приводит к аварийному отключению напрямую, без очереди.
static void test_steam_limit_alone_triggers_emergency_stop() {
  reset_fixture();
  PowerOn = true;
  SteamSensor.avgTemp = 99.0f;  // >= MAX_STEAM_TEMP
  TankSensor.avgTemp = 50.0f;   // < DistTemp
  check_alarm_temp_limit_block();
  check(queueCalls == 0, "перегрев пара без лимита куба не должен ставить команду штатного завершения в очередь");
  check(emergencyStopCalls == 1, "перегрев пара без лимита куба должен приводить к аварийному отключению напрямую");
}

// Внешний guard: PowerOn=false -> блок вообще не выполняется, независимо от
// показаний датчиков.
static void test_power_off_guard_blocks_everything() {
  reset_fixture();
  PowerOn = false;
  TankSensor.avgTemp = 999.0f;
  SteamSensor.avgTemp = 999.0f;
  check_alarm_temp_limit_block();
  check(queueCalls == 0, "при PowerOn=false команда штатного завершения не должна ставиться в очередь");
  check(emergencyStopCalls == 0, "при PowerOn=false аварийный останов не должен вызываться");
}

int main() {
  test_tank_limit_queue_success_no_emergency_stop();
  test_tank_limit_queue_failure_triggers_emergency_stop();
  test_tank_and_steam_limit_simultaneously_queue_failure_still_stops();
  test_steam_limit_alone_triggers_emergency_stop();
  test_power_off_guard_blocks_everything();
  if (failures != 0) return 1;
  std::cout << "alarm.h tank temp-limit escalation behaviour checks passed\n";
  return 0;
}
'''


def build_harness(alarm_header_path: Path) -> str:
    source = alarm_header_path.read_text(encoding="utf-8")
    body = extract_function_body(source, OUTER_IF_SIGNATURE)
    harness = HARNESS_TEMPLATE.replace("@OUTER_IF_SIGNATURE@", OUTER_IF_SIGNATURE)
    return harness.replace("@BODY@", body)


def compile_and_run(harness: str, label: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-alarm-tank-overheat-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "alarm_tank_overheat_escalation_test.cpp"
        binary = temp / "alarm_tank_overheat_escalation_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(f"[{label}] compile failed:\n")
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
    try:
        harness = build_harness(ROOT / "alarm.h")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    return compile_and_run(harness, "alarm.h")


if __name__ == "__main__":
    raise SystemExit(main())
