#!/usr/bin/env python3
"""Physical sensor readings and isolated device tests use the real firmware functions."""
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>
#include "safety_transition.h"
#define TR(key, text) text
#define NOTIFY_MSG 0
#define WARNING_MSG 1
#define PWM_START_VALUE 100
#define portMUX_TYPE int
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(mux) ((void)(mux), ++locks)
#define portEXIT_CRITICAL(mux) ((void)(mux), --locks)
static int locks = 0;
int timerMux = 0, configMux = 0, dsAddressMux = 0;
static uint32_t nowMs = 0;
static bool is_self_test = false, PowerOn = false, processActive = false, switching = false;
static uint64_t owner = 0;
static unsigned TargetStepps = 0;
static float ActualVolumePerHour = 0;
static uint8_t capacity_num = 0;
static std::vector<std::string> calls;
static struct { unsigned StepperStepMl = 17; } SamSetup;
uint32_t millis() { return nowMs; }
bool heater_power_on() { return PowerOn; }
void set_power(bool value, bool) { PowerOn = value; calls.push_back("heater"); }
bool samovar_process_active() { return processActive; }
bool mode_switch_in_progress() { return switching; }
bool safety_owner_generation_acquire(uint64_t& value) { value = ++owner; return true; }
bool safety_owner_generation_valid(uint64_t value) { return value == owner; }
void safety_owner_generation_release(uint64_t) {}
void SendMsg(const char*, int) {}
void set_pump_pwm(unsigned value) { calls.push_back(value ? "pump-on" : "pump-off"); }
void open_valve(bool value, bool) { calls.push_back(value ? "valve-on" : "valve-off"); }
void set_capacity(uint8_t value) { capacity_num = value; calls.push_back("capacity-" + std::to_string(value)); }
void next_capacity() { set_capacity(capacity_num + 1); }
void stopService() { calls.push_back("stepper-off"); }
void startService() { calls.push_back("stepper-on"); }
void stepper_safe_stop_reset() { calls.push_back("stepper-reset"); }
float get_speed_from_rate(float rate) { ActualVolumePerHour = rate; return rate * SamSetup.StepperStepMl; }
void stepper_safe_set_max_speed(float value) { calls.push_back("speed-" + std::to_string(int(value))); }
void stepper_safe_set_current(unsigned) {}
void stepper_safe_set_target(unsigned value) { TargetStepps = value; }
void reset_sensor_counter() { calls.push_back("reset-all"); }
struct StepperStub { void setAcceleration(unsigned) {} } stepper;
@SELFTEST@

using DeviceAddress = uint8_t[8];
static const uint8_t SAMOVAR_DS_ADDRESS_MAX = 6;
struct DSAddressSnapshot { DeviceAddress addr[SAMOVAR_DS_ADDRESS_MAX]; uint8_t count; };
struct DSTemperatureSnapshot { DSAddressSnapshot addresses; float temperature[SAMOVAR_DS_ADDRESS_MAX]; bool pending; };
static DSTemperatureSnapshot dsTemperatureSnapshot = {};
static DSAddressSnapshot registry = {};
void copy_ds_address_snapshot(DSAddressSnapshot& snapshot) { snapshot = registry; }
struct SensorsStub {
  float readings[6] = {};
  float getTempC(const uint8_t* address) {
    if (locks) std::abort();
    return readings[address[0]];
  }
} sensors;
void refresh_ds_address_temperatures() {@READINGS@}

using String = std::string;
@COMMAND_ENUM@
void apply_test_command(SamovarCommands command) {
  switch (command) { @DISPATCH@ default: break; }
}
struct Param { String data; String value() { return data; } };
struct AsyncWebServerRequest {
  bool hasDevice = true;
  Param param;
  int status = 0;
  bool hasParam(const char*, bool) { return hasDevice; }
  Param* getParam(const char*, bool) { return &param; }
  void send(int code, const char*, const char*) { status = code; }
};
static bool pending_stop_self_test_flag = false, queueAvailable = true, queueIdle = true;
static SamovarCommands queuedCommand = SAMOVAR_NONE;
bool queue_pending_flag(bool& flag) { if (!queueAvailable) return false; flag = true; return true; }
bool queue_samovar_command(SamovarCommands command) {
  if (!queueAvailable) return false;
  queuedCommand = command;
  return true;
}
bool samovar_command_queue_idle() { return queueIdle; }
void handle_device_test(AsyncWebServerRequest* request) {@WEB_COMMAND@}

void check(bool condition, const char* text) {
  if (!condition) { std::cerr << "FAIL: " << text << '\n'; std::exit(1); }
}
bool called(const std::string& text) {
  for (const auto& call : calls) if (call == text) return true;
  return false;
}
int main() {
  registry.count = 2;
  registry.addr[0][0] = 3;
  registry.addr[1][0] = 1;
  sensors.readings[3] = 21.25f;
  sensors.readings[1] = 37.75f;
  dsTemperatureSnapshot.pending = true;
  refresh_ds_address_temperatures();
  check(dsTemperatureSnapshot.addresses.count == 2 && !dsTemperatureSnapshot.pending,
        "physical sensor refresh must finish with the discovered addresses");
  check(dsTemperatureSnapshot.temperature[0] == 21.25f && dsTemperatureSnapshot.temperature[1] == 37.75f,
        "physical temperatures must follow their addresses, including unassigned sensors");
  registry.addr[0][0] = 1;
  sensors.readings[1] = -127;
  refresh_ds_address_temperatures();
  check(dsTemperatureSnapshot.temperature[0] == -127 && dsTemperatureSnapshot.addresses.addr[0][0] == 1,
        "a changed physical registry must not reuse a previous address or reading");

  for (uint8_t device = SELF_TEST_VALVE; device <= SELF_TEST_CAPACITY; device++) {
    calls.clear(); nowMs = 0;
    start_self_test(device);
    check(copy_self_test_snapshot().active && copy_self_test_snapshot().device == device,
          "only the selected device must be published before its test starts");
    tick_self_test();
    check(is_self_test, "an isolated test must start");
    check(called("valve-on") == (device == SELF_TEST_VALVE), "only the selected valve may start");
#ifdef USE_WATER_PUMP
    check(called("pump-on") == (device == SELF_TEST_WATER_PUMP), "only the selected water pump may start");
#endif
    check(called("stepper-on") == (device == SELF_TEST_STEPPER), "only the selected withdrawal pump may start");
    check(called("capacity-1") == (device == SELF_TEST_CAPACITY), "only the selected capacity servo may move");
    if (device == SELF_TEST_STEPPER) check(TargetStepps == 1700, "withdrawal target must use the pump calibration");
    if (device == SELF_TEST_VALVE) {
      nowMs = 14999; tick_self_test();
      check(is_self_test, "device must remain active before its deadline");
      nowMs = 15000; tick_self_test();
      check(!is_self_test && called("valve-off"), "device must stop automatically at its deadline");
    } else stop_self_test();
    check(!self_test_active(), "manual stop must finish an isolated test");
    check(!copy_self_test_snapshot().active, "HTTP status must confirm a finished test");
    check(!called("reset-all"), "isolated cleanup must not reset or move unrelated devices");
    check(called("valve-off") == (device == SELF_TEST_VALVE), "isolated cleanup must only close the selected valve");
    check(called("capacity-0") == (device == SELF_TEST_CAPACITY), "isolated cleanup must only return the selected servo");
    check(!called("heater"), "device tests must not energize the heater");
  }
  calls.clear(); processActive = true;
  start_self_test(SELF_TEST_VALVE); tick_self_test();
  check(!self_test_active() && calls.empty(), "active processes must reject device tests");
  processActive = false;
  start_self_test(SELF_TEST_STEPPER); tick_self_test();
  switching = true; tick_self_test();
  check(!self_test_active() && called("stepper-reset"), "mode switching must stop the selected device");
  switching = false; calls.clear();
  SamSetup.StepperStepMl = 29;
  start_self_test(SELF_TEST_STEPPER); tick_self_test();
  check(TargetStepps == 2900 && called("speed-29"), "another calibration must change both the target and speed");
  stop_self_test();
  check(TargetStepps == 0 && ActualVolumePerHour == 0, "isolated withdrawal cleanup must clear its target and rate");
  calls.clear();
  start_self_test(SELF_TEST_ALL); tick_self_test();
  check(called("valve-on") && called("stepper-on") && called("capacity-1"), "the original complete self-test must still start all devices");
  for (nowMs = 3000; nowMs <= 15000; nowMs += 3000) tick_self_test();
  check(called("capacity-5"), "the complete self-test must visit all five capacity positions");
  nowMs = 30000; tick_self_test();
  check(!self_test_active() && called("reset-all"), "the complete self-test must retain its original final reset");

  AsyncWebServerRequest request;
  for (const auto& item : std::vector<std::pair<String, SamovarCommands>>{
      {"valve", SAMOVAR_TEST_VALVE}, {"stepper", SAMOVAR_TEST_STEPPER}
#ifdef USE_WATER_PUMP
      , {"waterPump", SAMOVAR_TEST_WATER_PUMP}
#endif
#if defined(SERVO_PIN) || USER_SERVO
      , {"capacity", SAMOVAR_TEST_CAPACITY}
#endif
  }) {
    request.param.data = item.first; queuedCommand = SAMOVAR_NONE; calls.clear();
    handle_device_test(&request);
    check(request.status == 202 && queuedCommand == item.second, "HTTP must queue the selected physical device");
    check(calls.empty(), "HTTP must never operate physical hardware directly");
    apply_test_command(queuedCommand);
    const uint8_t expectedDevice = item.first == "valve" ? SELF_TEST_VALVE :
      item.first == "waterPump" ? SELF_TEST_WATER_PUMP :
      item.first == "stepper" ? SELF_TEST_STEPPER : SELF_TEST_CAPACITY;
    check(copy_self_test_snapshot().active && copy_self_test_snapshot().device == expectedDevice,
          "queued command must start the selected physical device in loop");
    tick_self_test(); stop_self_test();
  }
  request.param.data = "valve"; processActive = true; queuedCommand = SAMOVAR_NONE;
  handle_device_test(&request);
  check(request.status == 409 && queuedCommand == SAMOVAR_NONE, "HTTP must reject tests during a process");
  processActive = false; queueIdle = false;
  handle_device_test(&request);
  check(request.status == 409, "HTTP must reject a second command while the first is queued");
  queueIdle = true; request.param.data = "heater";
  handle_device_test(&request);
  check(request.status == 400, "the device interface must not accept an unimplemented heater test");
  request.param.data = "stepper"; SamSetup.StepperStepMl = 0;
  handle_device_test(&request);
  check(request.status == 409, "uncalibrated withdrawal must be rejected");
  request.param.data = "stop";
  handle_device_test(&request);
  check(request.status == 202 && pending_stop_self_test_flag, "HTTP stop must use the existing pending stop");
  queueAvailable = false; handle_device_test(&request);
  check(request.status == 503, "a rejected stop must be reported as a failure");
#ifndef USE_WATER_PUMP
  request.param.data = "waterPump"; handle_device_test(&request);
  check(request.status == 400, "a water pump absent from the build must be rejected");
#endif
#if !defined(SERVO_PIN) && !USER_SERVO
  request.param.data = "capacity"; handle_device_test(&request);
  check(request.status == 400, "a capacity servo absent from the build must be rejected");
#endif
}
'''


def main():
    selftest = (ROOT / 'selftest.h').read_text()
    sensor = (ROOT / 'sensorinit.h').read_text()
    # The declarations and every tested function come from the firmware itself.
    declarations = selftest[selftest.index('static SafetyTransition'):selftest.index('inline void finish_self_test_now')]
    functions = ['inline void finish_self_test_now', 'inline bool abort_self_test_if_owner_lost',
                 'inline bool self_test_active', 'inline void start_self_test',
                 'inline void tick_self_test', 'inline void stop_self_test']
    actual = declarations
    for token in functions:
        signature = selftest[selftest.index(token):selftest.index('{', selftest.index(token))]
        actual += signature + '{' + extract_function_body(selftest, token) + '}\n'
    readings = extract_function_body(sensor, 'inline void refresh_ds_address_temperatures')
    source = HARNESS.replace('@SELFTEST@', actual).replace('@READINGS@', readings)
    web = (ROOT / 'WebServer.ino').read_text()
    source = source.replace('@WEB_COMMAND@', extract_braced_block_after(web, 'server.on("/device-test", HTTP_POST')[0])
    header = (ROOT / 'Samovar.h').read_text()
    start = header.index('enum SamovarCommands')
    source = source.replace('@COMMAND_ENUM@', header[start:header.index(';', start) + 1])
    main_source = (ROOT / 'Samovar.ino').read_text()
    start = main_source.index('      case SAMOVAR_TEST_VALVE:')
    source = source.replace('@DISPATCH@', main_source[start:main_source.index('      case SAMOVAR_NONE:', start)])
    mutations = [
        ('selected device', source.replace('selfTestDevice = device;', '(void)device; selfTestDevice = SELF_TEST_ALL;'),
         'only the selected'),
        ('physical address', source.replace('sensors.getTempC(snapshot.addresses.addr[i])',
                                            'sensors.getTempC(snapshot.addresses.addr[0])'),
         'physical temperatures must follow their addresses'),
        ('loop dispatch', source.replace('case SAMOVAR_TEST_WATER_PUMP:\n        start_self_test(SELF_TEST_WATER_PUMP);',
                                         'case SAMOVAR_TEST_WATER_PUMP:\n        start_self_test(SELF_TEST_VALVE);'),
         'queued command must start the selected physical device in loop'),
    ]
    with tempfile.TemporaryDirectory(prefix='samovar-device-setup-') as temp:
        cpp, exe = Path(temp) / 'test.cpp', Path(temp) / 'test'
        for label, candidate, expected in [('real', source, None), ('without optional devices', source, None), *mutations]:
            cpp.write_text(candidate)
            flags = [] if label == 'without optional devices' else ['-DUSE_WATER_PUMP', '-DUSE_STEPPER_ACCELERATION', '-DSERVO_PIN=25']
            subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', *flags,
                            '-I', str(ROOT), str(cpp), '-o', str(exe)], check=True)
            result = subprocess.run([str(exe)], text=True, capture_output=True)
            if expected is None:
                if result.returncode: raise AssertionError(result.stderr)
            elif result.returncode == 0 or expected not in result.stderr:
                raise AssertionError(f'{label}: mutation missed meaningful assertion: {result.stderr}')
    print('device setup smoke passed (including three mutations)')


if __name__ == '__main__':
    main()
