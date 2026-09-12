#!/usr/bin/env python3
"""Поведенческая проверка явной команды SAMOVAR_POWER_ON.

V4/V32 кладут в FIFO только явные ON/OFF. Это исключает решение по устаревшему
PowerOn в Blynk-обработчике: ON проверяет PowerOn только при извлечении из
очереди. Реальное тело process_explicit_power_on_command извлекается из
Samovar.ino и запускается в host-харнессе; мутации обязаны ломать содержательный
assert, а не компиляцию обвязки.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]
SIGNATURE = "static void process_explicit_power_on_command()"

HARNESS = r'''
#include <iostream>

enum SamovarCommands {
  SAMOVAR_NONE, SAMOVAR_POWER, SAMOVAR_POWER_ON, SAMOVAR_POWER_OFF,
  SAMOVAR_DISTILLATION, SAMOVAR_CHEESE, SAMOVAR_NBK
};
enum SAMOVAR_MODE {
  SAMOVAR_RECTIFICATION_MODE, SAMOVAR_DISTILLATION_MODE,
  SAMOVAR_NBK_MODE, SAMOVAR_SUVID_MODE, SAMOVAR_LUA_MODE, SAMOVAR_CHEESE_MODE
};
constexpr int SAMOVAR_STATUS_RECT_ACCEL = 50;
enum MESSAGE_TYPE { ALARM_MSG, WARNING_MSG, NOTIFY_MSG };

static bool PowerOn = false;
static bool sensorsAssigned = true;
static SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
static int SamovarStatusInt = 0;
static int setPowerCalls = 0;
static int notifyCalls = 0;
static int modeApplyCalls = 0;
static SamovarCommands lastModeCommand = SAMOVAR_NONE;
static int sendMsgCalls = 0;
static const char* lastMessage = nullptr;
static MESSAGE_TYPE lastMessageType = NOTIFY_MSG;

bool rectification_ds_sensors_assigned() { return sensorsAssigned; }
void notify_rectification_sensors_unassigned() { notifyCalls++; }
SamovarCommands mode_power_on_command(SAMOVAR_MODE mode) {
  if (mode == SAMOVAR_CHEESE_MODE) return SAMOVAR_CHEESE;
  if (mode == SAMOVAR_DISTILLATION_MODE) return SAMOVAR_DISTILLATION;
  if (mode == SAMOVAR_NBK_MODE) return SAMOVAR_NBK;
  return SAMOVAR_POWER;
}
bool mode_apply_power_on_command(SamovarCommands command) {
  modeApplyCalls++;
  lastModeCommand = command;
  return true;
}
void set_power(bool on) {
  setPowerCalls++;
  PowerOn = on;
}
void SendMsg(const char* message, MESSAGE_TYPE type) {
  sendMsgCalls++;
  lastMessage = message;
  lastMessageType = type;
}

@BODY@

static int failures = 0;
static void check(bool value, const char* text) {
  if (!value) { std::cerr << "FAIL: " << text << '\n'; failures++; }
}
static void reset() {
  PowerOn = false;
  sensorsAssigned = true;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  SamovarStatusInt = 0;
  setPowerCalls = 0;
  notifyCalls = 0;
  modeApplyCalls = 0;
  lastModeCommand = SAMOVAR_NONE;
  sendMsgCalls = 0;
  lastMessage = nullptr;
  lastMessageType = NOTIFY_MSG;
}

int main() {
  reset();
  PowerOn = true;
  process_explicit_power_on_command();
  check(setPowerCalls == 0 && modeApplyCalls == 0 && notifyCalls == 0,
        "отложенный ON при уже включённом нагреве обязан быть no-op");

  reset();
  sensorsAssigned = false;
  process_explicit_power_on_command();
  check(notifyCalls == 1 && setPowerCalls == 0 && modeApplyCalls == 0,
        "ректификация без назначенных датчиков не должна включать нагрев");

  reset();
  process_explicit_power_on_command();
  check(setPowerCalls == 1 && PowerOn && SamovarStatusInt == SAMOVAR_STATUS_RECT_ACCEL,
        "ректификация обязана включить нагрев и установить статус разгона");

  reset();
  Samovar_Mode = SAMOVAR_SUVID_MODE;
  process_explicit_power_on_command();
  check(setPowerCalls == 1 && PowerOn && SamovarStatusInt == 0 && modeApplyCalls == 0,
        "Сувид обязан сохранить прямое включение без ректификационного статуса");

  reset();
  Samovar_Mode = SAMOVAR_CHEESE_MODE;
  process_explicit_power_on_command();
  check(setPowerCalls == 0 && modeApplyCalls == 1 && lastModeCommand == SAMOVAR_CHEESE,
        "Сыр обязан стартовать через режимную команду, а не напрямую включать нагрев");

  reset();
  Samovar_Mode = SAMOVAR_DISTILLATION_MODE;
  process_explicit_power_on_command();
  check(setPowerCalls == 0 && modeApplyCalls == 1 && lastModeCommand == SAMOVAR_DISTILLATION,
        "дистилляция обязана сохранить режимный путь старта");

  reset();
  Samovar_Mode = SAMOVAR_NBK_MODE;
  process_explicit_power_on_command();
#ifdef SAMOVAR_USE_POWER
  check(setPowerCalls == 0 && modeApplyCalls == 1 && lastModeCommand == SAMOVAR_NBK && sendMsgCalls == 0,
        "НБК с регулятором обязана сохранить режимный путь старта");
#else
  check(setPowerCalls == 0 && modeApplyCalls == 0 && sendMsgCalls == 1 &&
            lastMessageType == ALARM_MSG && lastMessage != nullptr && std::string(lastMessage) ==
                "Запуск НБК отклонён: регулятор мощности недоступен в этой сборке.",
        "НБК без регулятора обязана отказаться без изменения состояния");
#endif

  return failures == 0 ? 0 : 1;
}
'''


def run_harness(body: str, name: str, with_power: bool = False, show_output: bool = True) -> int:
    source = HARNESS.replace("@BODY@", f"{SIGNATURE} {{{body}}}")
    with tempfile.TemporaryDirectory(prefix=f"samovar-explicit-power-{name}-") as temp_dir:
        cpp = Path(temp_dir) / "test.cpp"
        binary = Path(temp_dir) / "test"
        cpp.write_text(source, encoding="utf-8")
        command = ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror"]
        if with_power:
            command.append("-DSAMOVAR_USE_POWER")
        command.extend([str(cpp), "-o", str(binary)])
        compile_result = subprocess.run(
            command,
            capture_output=True, text=True, check=False,
        )
        if compile_result.returncode != 0:
            if show_output:
                sys.stderr.write(compile_result.stdout)
                sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if show_output:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    samovar_h = (ROOT / "Samovar.h").read_text(encoding="utf-8")
    if "SAMOVAR_CHEESE_NEXT, SAMOVAR_POWER_ON}" not in samovar_h:
        print("FAIL: SAMOVAR_POWER_ON must be appended after existing commands", file=sys.stderr)
        return 1
    source = strip_cpp_comments((ROOT / "Samovar.ino").read_text(encoding="utf-8"))
    try:
        body = extract_function_body(source, SIGNATURE)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if run_harness(body, "original-no-power") != 0:
        return 1
    if run_harness(body, "original-with-power", with_power=True) != 0:
        return 1

    mutations = {
        "stale_on": ("if (PowerOn) return;", "if (false) return;"),
        "missing_sensor_guard": ("!rectification_ds_sensors_assigned()", "false"),
        "skip_mode_registry": ("if (modeCommand != SAMOVAR_POWER)", "if (false)"),
        "nbk_no_power_bypass": ("if (modeCommand == SAMOVAR_NBK)", "if (false)"),
    }
    for name, (old, new) in mutations.items():
        mutant = body.replace(old, new, 1)
        if mutant == body:
            print(f"FAIL: mutation anchor missing: {name}", file=sys.stderr)
            return 1
        if run_harness(mutant, name, show_output=False) == 0:
            print(f"FAIL: mutation survived: {name}", file=sys.stderr)
            return 1

    print("explicit power command smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
