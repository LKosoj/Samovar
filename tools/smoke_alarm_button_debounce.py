#!/usr/bin/env python3
"""Реальная задача аварийной кнопки + GyverButton: помехи, удержание и повторный вход."""
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'libraries/GyverButton/src'
ARDUINO = '''#pragma once
#include <cstdint>
using boolean = bool;
using byte = uint8_t;
#define LOW 0
#define HIGH 1
#define INPUT 0
#define INPUT_PULLUP 2
void pinMode(int, int);
int digitalRead(int);
uint32_t millis();
'''
HARNESS = r'''
#include <GyverButton.h>
#include <vector>
#include <utility>
#include <iostream>
#include <cstdlib>
#define ALARM_BTN_PIN 35
#define pdTRUE 1
#define pdPASS 1
#define portMAX_DELAY 0xffffffffU
#define pdMS_TO_TICKS(ms) (ms)
#define FALLING 2
using BaseType_t = int;
using TaskHandle_t = void*;
static TaskHandle_t EmergencyButtonTask = nullptr;
static uint32_t nowMs = 0;
static unsigned pending = 0;
static std::vector<std::pair<uint32_t, uint32_t>> pulses;
static std::vector<uint32_t> stops;
struct Done {};
void pinMode(int, int) {}
uint32_t millis() { return nowMs; }
int digitalRead(int pin) {
  if (pin != ALARM_BTN_PIN) std::abort();
  for (auto p : pulses) if (nowMs >= p.first && nowMs < p.second) return LOW;
  return HIGH;
}
GButton alarm_btn(ALARM_BTN_PIN);
void check(bool ok, const char* message) {
  if (!ok) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}
void vTaskDelay(uint32_t ticks) {
  check(ticks > 0, "task must yield while polling");
  for (auto p : pulses) if (p.first > nowMs && p.first <= nowMs + ticks) ++pending;
  nowMs += ticks;
  check(nowMs < 1000, "task must sleep after release");
}
void ulTaskNotifyTake(int, uint32_t) {
  if (!pending) {
    bool found = false;
    for (auto p : pulses) if (p.first > nowMs) {
      nowMs = p.first; pending = 1; found = true; break;
    }
    if (!found) throw Done{};
  }
  pending = 0;
}
void emergencyButtonInterrupt() {}
void attachInterrupt(int, void (*)(), int) {}
void xTaskNotifyGive(TaskHandle_t) { ++pending; }
int xTaskCreatePinnedToCore(void (*)(void*), const char*, int, void*, int,
                           TaskHandle_t* handle, int) {
  *handle = reinterpret_cast<void*>(1); return pdPASS;
}
const char* emergency_button_reason() { return "alarm"; }
void request_emergency_stop(const char*) { stops.push_back(nowMs); }
void triggerEmergencyButton(void* parameter) { @TASK@ }
bool initEmergencyButtonTask() { @INIT@ }
void run(std::vector<std::pair<uint32_t, uint32_t>> input,
         std::vector<uint32_t> expected, const char* message) {
  nowMs = 0; pending = 0; pulses = input; stops.clear();
  check(initEmergencyButtonTask(), "task creation");
  try { triggerEmergencyButton(nullptr); } catch (Done&) {}
  check(stops == expected, message);
}
int main() {
  run({{0, 100}}, {30}, "held at boot: one stop at 30 ms");
  run({{20, 200}}, {50}, "interrupt wake: one stop despite long hold");
  run({{0, 1}, {30, 42}, {70, 99}}, {}, "short separated pulses must not trip");
  run({{10, 100}, {150, 220}}, {40, 180}, "release must rearm next press");
  run({{0, 12}, {20, 100}}, {50}, "bounce must restart debounce interval");
  run({}, {}, "idle input must not trip");
}
'''


def harness(source):
    return HARNESS.replace('@TASK@', extract_function_body(
        source, 'void triggerEmergencyButton(void *parameter)')).replace(
        '@INIT@', extract_function_body(source, 'bool initEmergencyButtonTask()'))


def run(source):
    with tempfile.TemporaryDirectory(prefix='samovar-alarm-gyver-') as temp:
        p = Path(temp)
        (p / 'Arduino.h').write_text(ARDUINO)
        (p / 'test.cpp').write_text(harness(source))
        subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror',
                        '-I' + temp, '-I' + str(LIB), str(p / 'test.cpp'),
                        str(LIB / 'GyverButton.cpp'), '-o', str(p / 'test')], check=True)
        return subprocess.run([str(p / 'test')], capture_output=True, text=True)


def main():
    source = (ROOT / 'Samovar.ino').read_text()
    result = run(source)
    assert result.returncode == 0, result.stderr
    for old, new, expected in (
        ('alarm_btn.setDebounce(30);', 'alarm_btn.setDebounce(10);', 'held at boot'),
        ('if (alarm_btn.isPress())', 'if (alarm_btn.state())', 'held at boot'),
        ('if (!alarm_btn.state()) break;', 'if (true) break;', 'held at boot'),
        ('alarm_btn.tick();', '(void)0;', 'held at boot'),
    ):
        assert source.count(old) == 1, old
        result = run(source.replace(old, new))
        assert result.returncode != 0 and 'FAIL: ' + expected in result.stderr, result.stderr
    init = extract_function_body(source, 'bool initEmergencyButtonTask()')
    assert init.index('alarm_btn.setDebounce(30);') < init.index('xTaskCreatePinnedToCore(')
    assert 'tick_alarm_button' not in source, 'loop must not poll the same button'
    assert source.count('alarm_btn.tick();') == 1, 'button must have one polling owner'
    assert 'emergency_button_press_confirmed' not in source, 'remove custom debounce'
    print('PASS: real GyverButton/task scenarios and 4 source mutations')


if __name__ == '__main__':
    main()
