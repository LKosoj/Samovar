#!/usr/bin/env python3
"""Проверка постановки и исполнения команды удалённой перезагрузки V39."""

import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
sketch = (ROOT / "Samovar.ino").read_text()
blynk = (ROOT / "Blynk.ino").read_text()

HARNESS = r"""
#include <cassert>
#include <cstdint>
#include <initializer_list>
#include "numeric_parse.h"

#define SAMOVAR_USE_BLYNK
#define USE_WATER_PUMP
#define USE_LUA

bool PowerOn, heater_state, valve_status, is_self_test, switching, luaHeating;
bool pending_blynk_reboot, pending_reset_wifi_flag, is_reboot;
bool pendingLockAvailable = true;
uint16_t water_pump_speed;
unsigned restarts, wifiResets;
struct {
  uint32_t bootId;
} runtimePairState{4294967295U};

struct PendingCommandLockGuard {
  explicit operator bool() const { return pendingLockAvailable; }
  void release() {}
};
struct {
  void restart() { ++restarts; }
} ESP;
bool mode_switch_in_progress() { return switching; }
bool lua_heater_channel_raised() { return luaHeating; }
void delay(unsigned) {}
void menu_reset_wifi() { ++wifiResets; }

struct Param {
  const char* value;
  const char* asStr() const { return value; }
};
void receive_reboot(Param param) { @RECEIVE@ }
bool blynk_reboot_allowed() { @ALLOWED@ }
void tick_process_recovery_commands() { @TICK@ }

int main() {
  receive_reboot({"4294967294"});
  receive_reboot({"4294967296"});
  receive_reboot({"4294967295x"});
  assert(!pending_blynk_reboot && "old or invalid boot ID was accepted");

  pendingLockAvailable = false;
  receive_reboot({"4294967295"});
  assert(!pending_blynk_reboot && "could not acquire command queue lock");
  pendingLockAvailable = true;

  for (bool* active : {&PowerOn, &heater_state, &valve_status, &is_self_test, &switching, &luaHeating}) {
    receive_reboot({"4294967295"});
    assert(pending_blynk_reboot);
    *active = true;
    tick_process_recovery_commands();
    assert(!pending_blynk_reboot && restarts == 0 && "condition must be checked at execution");
    *active = false;
  }
  receive_reboot({"4294967295"});
  water_pump_speed = 100;
  tick_process_recovery_commands();
  assert(restarts == 0 && "pump running with the valve closed must block reboot");
  water_pump_speed = 0;

  receive_reboot({"4294967295"});
  receive_reboot({"4294967295"});
  tick_process_recovery_commands();
  tick_process_recovery_commands();
  assert(restarts == 1 && "duplicate waiting requests must coalesce");
  runtimePairState.bootId = 17;
  receive_reboot({"4294967295"});
  tick_process_recovery_commands();
  assert(restarts == 1 && "retry from previous boot must not restart");

  PowerOn = true;
  is_reboot = true;
  tick_process_recovery_commands();
  assert(restarts == 2 && "local recovery must still work");
}
"""
HARNESS = HARNESS.replace("@RECEIVE@", extract_function_body(blynk, "BLYNK_WRITE(V39)"))
HARNESS = HARNESS.replace("@ALLOWED@", extract_function_body(sketch, "static bool blynk_reboot_allowed()"))
HARNESS = HARNESS.replace("@TICK@", extract_function_body(sketch, "static void tick_process_recovery_commands()"))
with tempfile.TemporaryDirectory(prefix="samovar-blynk-reboot-") as directory:
    src = Path(directory) / "test.cpp"
    binary = Path(directory) / "test"
    src.write_text(HARNESS)
    subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT),
                    str(src), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print("Blynk reboot smoke passed")
