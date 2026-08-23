#!/usr/bin/env python3
"""Поведенческая проверка [П7]: отказ датчика давления не должен молча снимать
защиту от захлёба (overflow()) и не должен вечно молчать при устойчивом отказе.

Раньше pressure_sensor_get() (sensorinit.h, ветка USE_PRESSURE_XGZ) при
неудачном чтении/незахваченном семафоре I2C просто ничего не делал -
pressure_value оставался старым, а overflow() продолжал сравнивать его с
порогом, как будто данные свежие. Тест вытаскивает РЕАЛЬНЫЕ тела
pressure_sensor_get() (sensorinit.h), nbk_pressure_stale()/overflow()/
nbk_overflow_source() (nbk.h) и фрагмент 60-секундной эскалации из
check_nbk_critical_alarms (nbk.h) через smoke_helpers и подставляет их в
минимальный g++-харнесс - логика не переписывается, только доопределяются
заглушки I/O (семафор, датчик, millis, SendMsg, request_emergency_stop).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

PRESSURE_GET_SIGNATURE = "void pressure_sensor_get()"
STALE_SIGNATURE = "inline bool nbk_pressure_stale()"
OVERFLOW_SIGNATURE = "bool overflow()"
SOURCE_SIGNATURE = "inline const char* nbk_overflow_source()"
ESCALATION_ANCHOR = "if (nbk_pressure_stale()) {"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <climits>
#include <iostream>
#include <string>

#define USE_PRESSURE_XGZ 1

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}
  String operator+(const char* text) const { return String(value_ + (text ? text : "")); }
  String operator+(const String& other) const { return String(value_ + other.value_); }
  const std::string& value() const { return value_; }

 private:
  std::string value_;
};

// --- заглушки окружения sensorinit.h::pressure_sensor_get() (XGZ ветка) ---
typedef int TickType_t;
static const bool pdTRUE = true;
static const int portTICK_RATE_MS = 1;
static bool semaphoreAvailable = true;
static int xI2CSemaphore = 0;
static bool xSemaphoreTake(int, TickType_t) { return semaphoreAvailable; }
static void xSemaphoreGive(int) {}

struct PressureSensorStub {
  bool nextReadOk = true;
  float nextRaw = 0.0f;
  bool readSensor(float& t, float& raw) {
    t = 0.0f;
    raw = nextRaw;
    return nextReadOk;
  }
};
static PressureSensorStub pressure_sensor;

bool use_pressure_sensor = true;
float pressure_value = 0.0f;
float old_pressure_value = 0.0f;
int pressure_err_count = 0;

@PRESSURE_GET@

// --- заглушки окружения nbk.h::overflow()/nbk_overflow_source() ---
bool PowerOn = true;
float nbk_overflow_pressure = 40.0f;

@STALE@

@OVERFLOW@

@SOURCE@

// --- заглушки окружения фрагмента 60-секундной эскалации ---
static uint32_t fakeMillis = 0;
uint32_t millis() { return fakeMillis; }
uint32_t nbk_pressure_stale_start_time = 0;
static int emergencyStopCalls = 0;
static std::string lastEmergencyReason;
void request_emergency_stop(const String& reason) {
  emergencyStopCalls++;
  lastEmergencyReason = reason.value();
}

static bool run_escalation_tick() {
@ESCALATION@
  return false;
}

static int failures = 0;
static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // --- 1..10 неудачных чтений ничего не меняют (порог >10, а не >=10) ---
  pressure_err_count = 0;
  use_pressure_sensor = true;
  semaphoreAvailable = true;
  pressure_sensor.nextReadOk = false;
  for (int i = 1; i <= 10; i++) {
    pressure_sensor_get();
    check(pressure_err_count == i, "err_count должен расти на 1 за неудачный цикл");
    check(!nbk_pressure_stale(), "после <=10 неудач подряд данные ещё не должны считаться несвежими");
  }
  pressure_value = 999.0f;  // маркер: не должен трогаться неудачными чтениями
  check(pressure_value == 999.0f, "sanity");

  // --- 11-е неудачное чтение - данные несвежие, overflow()==true, источник != "ДД" ---
  pressure_sensor_get();
  check(pressure_err_count == 11, "11-я неудача должна довести счётчик до 11");
  check(nbk_pressure_stale(), "после 11 неудач подряд данные обязаны считаться несвежими");
  check(overflow(), "РЕГРЕСС: несвежие данные ДД обязаны трактоваться как захлёб (fail-safe)");
  std::string source = nbk_overflow_source();
  check(source != "ДД", "источник несвежих данных не должен маскироваться под реальный захлёб по ДД");
  check(source == "нет данных ДД", "источник несвежих данных должен явно называть причину");

  // --- семафор не захвачен - тоже неудача, pressure_value не подменяется ---
  pressure_err_count = 0;
  semaphoreAvailable = false;
  pressure_value = 42.0f;
  pressure_sensor_get();
  check(pressure_err_count == 1, "незахваченный семафор I2C должен считаться неудачным чтением");
  check(pressure_value == 42.0f, "при незахваченном семафоре старое pressure_value не должно подменяться");

  // --- один успешный цикл посреди серии обнуляет счётчик ---
  semaphoreAvailable = true;
  pressure_sensor.nextReadOk = false;
  pressure_err_count = 0;
  for (int i = 0; i < 5; i++) pressure_sensor_get();
  check(pressure_err_count == 5, "перед проверкой сброса счётчик должен успеть подрасти");
  pressure_sensor.nextReadOk = true;
  pressure_sensor.nextRaw = 133.32f;  // 1 мм рт. ст. после деления
  pressure_sensor_get();
  check(pressure_err_count == 0, "успешное чтение обязано обнулить счётчик неудач");
  check(!nbk_pressure_stale(), "после успешного чтения данные не должны считаться несвежими");

  // --- установки без датчика давления не получают ложных аварий ---
  use_pressure_sensor = false;
  pressure_err_count = 0;
  for (int i = 0; i < 20; i++) pressure_sensor_get();
  check(pressure_err_count == 0, "РЕГРЕСС: без датчика давления (use_pressure_sensor=false) счётчик не должен расти");
  check(!nbk_pressure_stale(), "без датчика давления данные не должны считаться несвежими");
  check(!overflow(), "без датчика давления overflow() не должен ложно срабатывать");

  // --- 60+ секунд устойчивой потери дают аварию с внятным текстом ---
  pressure_err_count = 11;  // несвежие данные
  check(nbk_pressure_stale(), "sanity: подготовка к проверке эскалации");
  nbk_pressure_stale_start_time = 0;
  fakeMillis = 1000;
  check(!run_escalation_tick(), "первый тик несвежих данных не должен сразу давать аварию");
  check(emergencyStopCalls == 0, "авария не должна срабатывать раньше 60 секунд");
  fakeMillis = 1000 + 60000 + 1;
  check(run_escalation_tick(), "устойчивая потеря дольше 60 секунд обязана давать аварийный останов");
  check(emergencyStopCalls == 1, "авария должна сработать ровно один раз на переходе через 60 секунд");
  check(lastEmergencyReason.find("давления") != std::string::npos,
        "текст аварии обязан внятно называть причину (отказ датчика давления)");

  // --- восстановление свежести до истечения 60 секунд сбрасывает таймер ---
  pressure_err_count = 11;
  nbk_pressure_stale_start_time = 0;
  fakeMillis = 2000;
  run_escalation_tick();
  check(nbk_pressure_stale_start_time == 2000, "таймер эскалации должен взвестись на первом тике несвежих данных");
  pressure_err_count = 0;  // данные снова свежие
  fakeMillis = 2000 + 60000 + 1;
  check(!run_escalation_tick(), "восстановление свежести обязано отменить эскалацию");
  check(nbk_pressure_stale_start_time == 0, "таймер эскалации должен сброситься при восстановлении свежести");
  check(emergencyStopCalls == 1, "повторной аварии после восстановления быть не должно");

  if (failures != 0) return 1;
  std::cout << "pressure sensor staleness behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    sensorinit_source = (ROOT / "sensorinit.h").read_text(encoding="utf-8")
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")

    pressure_get_body = extract_function_body(sensorinit_source, PRESSURE_GET_SIGNATURE)
    stale_body = extract_function_body(nbk_source, STALE_SIGNATURE)
    overflow_body = extract_function_body(nbk_source, OVERFLOW_SIGNATURE)
    source_body = extract_function_body(nbk_source, SOURCE_SIGNATURE)
    escalation_if_body, if_end = extract_braced_block_after(nbk_source, ESCALATION_ANCHOR)
    # Тот же if - обязан иметь "else { ...сброс таймера... }" сразу следом
    # (сброс nbk_pressure_stale_start_time при восстановлении свежести) -
    # вытаскиваем и его, иначе тест пинил бы только половину логики.
    else_marker = "else"
    else_start = nbk_source.find(else_marker, if_end)
    if else_start < 0 or nbk_source[if_end:else_start].strip() != "":
        raise ValueError("escalation if-block is not immediately followed by else")
    escalation_else_body, _ = extract_braced_block_after(nbk_source, else_marker, if_end)

    harness = HARNESS_TEMPLATE
    harness = harness.replace(
        "@PRESSURE_GET@", f"{PRESSURE_GET_SIGNATURE} {{{pressure_get_body}}}")
    harness = harness.replace(
        "@STALE@", f"{STALE_SIGNATURE} {{{stale_body}}}")
    harness = harness.replace(
        "@OVERFLOW@", f"{OVERFLOW_SIGNATURE} {{{overflow_body}}}")
    harness = harness.replace(
        "@SOURCE@", f"{SOURCE_SIGNATURE} {{{source_body}}}")
    harness = harness.replace(
        "@ESCALATION@",
        f"if (nbk_pressure_stale()) {{{escalation_if_body}}} else {{{escalation_else_body}}}")
    return harness


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-pressure-staleness-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "pressure_sensor_staleness_test.cpp"
        binary = temp / "pressure_sensor_staleness_test"
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
            sys.stderr.write("compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
