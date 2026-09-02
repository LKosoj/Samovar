#!/usr/bin/env python3
"""[9b] Шаговый регулятор охлаждения дефлегматора БК (check_alarm_bk(), блок
`if (bk_water_auto) { ... }` под #ifdef USE_WATER_PUMP): период применения не
чаще BK_WATER_ADJUST_PERIOD_MS, мёртвая зона BK_WATER_DEADBAND, шаг
BK_WATER_PWM_STEP, приоритет защиты по воде над уставкой пара, авария при
отказе датчика пара имеет приоритет над шагом регулятора.

Харнесс компилирует РЕАЛЬНОЕ тело check_alarm_bk() целиком (BK.h) - как и
tools/smoke_bk_full_route.py - чтобы не поддерживать два разных способа
вырезать один и тот же код (рекомендация из плана 9b).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cstdint>
#include <iostream>

#define portTICK_PERIOD_MS 1
static void vTaskDelay(int) {}

#define SAMOVAR_USE_POWER_NOT_DEFINED 1  // намеренно НЕ определяем SAMOVAR_USE_POWER
#define USE_WATER_PUMP 1

// [9b] Харнесс сам задаёт эти параметры (не подключая Samovar_ini.h целиком,
// как и остальные харнессы проекта) - значениями из §8 плана, это не
// заглушки-константы, а реальные параметры сценариев регулятора.
#define BK_WATER_ADJUST_PERIOD_MS 60000u
#define BK_WATER_DEADBAND 0.2f
#define BK_WATER_PWM_STEP 30
#define ALARM_WATER_TEMP 70
#define PWM_LOW_VALUE 10

#define constrain(x, a, b) ((x) < (a) ? (a) : ((x) > (b) ? (b) : (x)))

class String {
 public:
  String(const char* value) : value_(value) {}
  const char* c_str() const { return value_; }
 private:
  const char* value_;
};

struct Sensor { float avgTemp = 0; };
struct Setup { float SetWaterTemp = 25; };

static Sensor TankSensor, SteamSensor, PipeSensor, WaterSensor;
static Setup SamSetup;
static bool PowerOn = true;
static bool valve_status = false;
static bool pump_started = false;
static int8_t wp_count = 0;
static int bk_pwm = PWM_LOW_VALUE * 40;
static bool bk_work_power_pending = false;
static const float CHANGE_POWER_MODE_STEAM_TEMP = 39.0f;
static const float DELTA_T_CLOSE_VALVE = 2.0f;

// [9b] Управляемая заглушка (минимум два значения): различает TankSensor/
// SteamSensor так же, как smoke_bk_program_run.py - без этого нельзя было бы
// проверить сценарий 7 (авария датчика пара) отдельно от датчика куба.
static bool steamSensorValid = true;
static bool sensor_valid(const Sensor& sensor) {
  if (&sensor == &SteamSensor) return steamSensorValid;
  return true;
}

static int processSensorFailedCalls = 0;
static bool process_sensor_failed(const char*, const char*) {
  processSensorFailedCalls++;
  return false;
}

static int setPumpPwmCalls = 0;
static int lastSetPumpPwmArg = -1;
static void set_pump_pwm(int duty) {
  setPumpPwmCalls++;
  lastSetPumpPwmArg = duty;
}

static void mode_clear_alarm_pause_if_expired() {}
static bool mode_check_powered_cooling_sensors(const char*) { return true; }
// [9b, не в фокусе теста] Открытие/закрытие охлаждения не проверяется здесь
// (см. smoke_bk_full_route.py) - константные заглушки, всегда "не сейчас".
static bool mode_should_open_cooling(bool, bool, bool) { return false; }
static bool mode_should_close_cooling(float, bool) { return false; }
static void open_valve(bool, bool) {}
static void mode_stop_cooling_pump_if_started() {}
static bool check_boiling() { return false; }
static void bk_apply_work_power() {}
static void mode_request_overheat_emergency_if_needed() {}
static void mode_request_water_flow_emergency_if_needed() {}
static bool mode_water_pre_alarm_due() { return false; }
static void mode_handle_water_pre_alarm_if_due() {}
enum BoilingEvidence { BOILING_EVIDENCE_NONE = 0, BOILING_EVIDENCE_STEAM, BOILING_EVIDENCE_PIPE };
static void record_boiling_evidence(BoilingEvidence) {}

static unsigned long fakeMillis = 0;
static unsigned long millis() { return fakeMillis; }

static bool bk_water_auto = false;
static float bk_steam_setpoint = 0.0f;
static uint32_t bk_water_last_adjust_ms = 0;

@CHECK_ALARM_BK@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}

static void reset_all() {
  TankSensor = Sensor(); SteamSensor = Sensor(); PipeSensor = Sensor(); WaterSensor = Sensor();
  SamSetup = Setup();
  PowerOn = true;
  valve_status = false;
  pump_started = false;   // [9b] развязка с "мягким пуском" (другой блок check_alarm_bk) - не в фокусе теста
  wp_count = 0;
  bk_pwm = 500;
  bk_work_power_pending = false;
  steamSensorValid = true;
  processSensorFailedCalls = 0;
  setPumpPwmCalls = 0;
  lastSetPumpPwmArg = -1;
  fakeMillis = 1000000UL;
  bk_water_auto = false;
  bk_steam_setpoint = 0.0f;
  bk_water_last_adjust_ms = 0;
}

int main() {
  // Сценарий 1: период не прошёл - шаг не делается.
  reset_all();
  bk_water_auto = true;
  valve_status = true;
  wp_count = 10;
  bk_steam_setpoint = 80.0f;
  SteamSensor.avgTemp = 90.0f;   // diff = 10, далеко за пределами мёртвой зоны
  bk_water_last_adjust_ms = fakeMillis - 1000;   // прошло всего 1с из 60с периода
  int pwmBefore = bk_pwm;
  check_alarm_bk();
  check(setPumpPwmCalls == 0, "сценарий 1: период не прошёл - set_pump_pwm не должен вызываться");
  check(bk_pwm == pwmBefore, "сценарий 1: период не прошёл - bk_pwm не должен измениться");

  // Сценарий 2: период прошёл, мёртвая зона - ШИМ не меняется, но таймер сдвигается.
  reset_all();
  bk_water_auto = true;
  valve_status = true;
  wp_count = 10;
  bk_steam_setpoint = 80.0f;
  SteamSensor.avgTemp = 80.1f;   // diff = 0.1 < DEADBAND (0.2)
  bk_water_last_adjust_ms = fakeMillis - BK_WATER_ADJUST_PERIOD_MS;
  pwmBefore = bk_pwm;
  check_alarm_bk();
  check(bk_pwm == pwmBefore, "сценарий 2: мёртвая зона - bk_pwm не должен измениться");
  check(bk_water_last_adjust_ms == fakeMillis,
        "сценарий 2: таймер должен обновиться даже без изменения ШИМ (иначе период укорачивается шумом датчика)");

  // Сценарий 3: шаг вверх.
  reset_all();
  bk_water_auto = true;
  valve_status = true;
  wp_count = 10;
  bk_steam_setpoint = 80.0f;
  SteamSensor.avgTemp = 80.5f;   // diff = 0.5 >= DEADBAND
  bk_water_last_adjust_ms = fakeMillis - BK_WATER_ADJUST_PERIOD_MS;
  bk_pwm = 500;
  check_alarm_bk();
  check(bk_pwm == 500 + BK_WATER_PWM_STEP, "сценарий 3: шаг вверх должен увеличить bk_pwm ровно на BK_WATER_PWM_STEP");
  check(setPumpPwmCalls == 1 && lastSetPumpPwmArg == bk_pwm,
        "сценарий 3: set_pump_pwm должен быть вызван с новым значением");

  // Сценарий 4: шаг вниз (вода далеко от аварийной зоны).
  reset_all();
  bk_water_auto = true;
  valve_status = true;
  wp_count = 10;
  bk_steam_setpoint = 80.0f;
  SteamSensor.avgTemp = 79.0f;   // diff = -1.0 <= -DEADBAND
  WaterSensor.avgTemp = 20.0f;   // далеко от ALARM_WATER_TEMP - 5 == 65
  bk_water_last_adjust_ms = fakeMillis - BK_WATER_ADJUST_PERIOD_MS;
  bk_pwm = 500;
  check_alarm_bk();
  check(bk_pwm == 500 - BK_WATER_PWM_STEP, "сценарий 4: шаг вниз должен уменьшить bk_pwm ровно на BK_WATER_PWM_STEP");

  // Сценарий 5а: верхняя граница - шаг вверх не должен превысить 1023.
  reset_all();
  bk_water_auto = true;
  valve_status = true;
  wp_count = 10;
  bk_steam_setpoint = 80.0f;
  SteamSensor.avgTemp = 90.0f;
  bk_water_last_adjust_ms = fakeMillis - BK_WATER_ADJUST_PERIOD_MS;
  bk_pwm = 1023 - 10;
  check_alarm_bk();
  check(bk_pwm == 1023, "сценарий 5а: bk_pwm не должен превысить верхнюю границу 1023");

  // Сценарий 5б: нижняя граница - шаг вниз не должен уйти ниже PWM_LOW_VALUE*10.
  reset_all();
  bk_water_auto = true;
  valve_status = true;
  wp_count = 10;
  bk_steam_setpoint = 80.0f;
  SteamSensor.avgTemp = 70.0f;
  WaterSensor.avgTemp = 20.0f;
  bk_water_last_adjust_ms = fakeMillis - BK_WATER_ADJUST_PERIOD_MS;
  bk_pwm = PWM_LOW_VALUE * 10 + 10;
  check_alarm_bk();
  check(bk_pwm == PWM_LOW_VALUE * 10, "сценарий 5б: bk_pwm не должен уйти ниже нижней границы PWM_LOW_VALUE*10");

  // Сценарий 6: приоритет воды - diff требует шаг вниз, но вода уже в
  // пред-аварийной зоне (>= ALARM_WATER_TEMP - 5) - шаг запрещён, но таймер
  // всё равно обновляется (симметрично сценарию 2).
  reset_all();
  bk_water_auto = true;
  valve_status = true;
  wp_count = 10;
  bk_steam_setpoint = 80.0f;
  SteamSensor.avgTemp = 70.0f;    // diff <= -DEADBAND, требует шаг вниз
  WaterSensor.avgTemp = ALARM_WATER_TEMP - 5;   // ровно на границе пред-аварии
  bk_water_last_adjust_ms = fakeMillis - BK_WATER_ADJUST_PERIOD_MS;
  bk_pwm = 500;
  check_alarm_bk();
  check(bk_pwm == 500, "сценарий 6: приоритет воды - шаг вниз должен быть запрещён вопреки уставке пара");
  check(bk_water_last_adjust_ms == fakeMillis,
        "сценарий 6: таймер должен обновиться даже когда шаг запрещён приоритетом воды");

  // Сценарий 7: авария по датчику пара имеет приоритет над шагом регулятора,
  // независимо от того, истёк период или нет (проверка датчика стоит раньше).
  for (int periodElapsed = 0; periodElapsed < 2; periodElapsed++) {
    reset_all();
    bk_water_auto = true;
    valve_status = true;
    wp_count = 10;
    steamSensorValid = false;
    bk_steam_setpoint = 80.0f;
    SteamSensor.avgTemp = 90.0f;
    bk_water_last_adjust_ms = periodElapsed
        ? fakeMillis - BK_WATER_ADJUST_PERIOD_MS
        : fakeMillis - 1000;
    check_alarm_bk();
    check(processSensorFailedCalls == 1,
          "сценарий 7: авария датчика пара должна сработать ровно один раз за тик");
    check(setPumpPwmCalls == 0,
          "сценарий 7: шаг регулятора не должен выполняться при отказе датчика пара");
  }

  // Сценарий 8: авторежим выключен - ни шаг, ни авария не должны сработать,
  // даже если датчик пара невалиден (внешний гейт if (bk_water_auto)).
  reset_all();
  bk_water_auto = false;
  valve_status = true;
  wp_count = 10;
  steamSensorValid = false;
  bk_water_last_adjust_ms = fakeMillis - BK_WATER_ADJUST_PERIOD_MS;
  check_alarm_bk();
  check(processSensorFailedCalls == 0, "сценарий 8: auto выключен - авария датчика пара не должна вызываться");
  check(setPumpPwmCalls == 0, "сценарий 8: auto выключен - шаг регулятора не должен выполняться");

  // Сценарий 9: датчик валиден, период истёк, но привод ещё не готов
  // (wp_count < 10 или valve_status == false) - шаг не делается, авария не
  // вызывается (в отличие от сценария 7 - здесь датчик В ПОРЯДКЕ).
  reset_all();
  bk_water_auto = true;
  valve_status = true;
  wp_count = 9;   // плавный пуск насоса ещё не завершён
  bk_steam_setpoint = 80.0f;
  SteamSensor.avgTemp = 90.0f;
  bk_water_last_adjust_ms = fakeMillis - BK_WATER_ADJUST_PERIOD_MS;
  check_alarm_bk();
  check(processSensorFailedCalls == 0, "сценарий 9: датчик в порядке - авария не должна вызываться");
  check(setPumpPwmCalls == 0, "сценарий 9: wp_count < 10 - шаг регулятора не должен выполняться");

  reset_all();
  bk_water_auto = true;
  valve_status = false;   // клапан ещё не открыт
  wp_count = 10;
  bk_steam_setpoint = 80.0f;
  SteamSensor.avgTemp = 90.0f;
  bk_water_last_adjust_ms = fakeMillis - BK_WATER_ADJUST_PERIOD_MS;
  check_alarm_bk();
  check(processSensorFailedCalls == 0, "сценарий 9б: датчик в порядке - авария не должна вызываться");
  check(setPumpPwmCalls == 0, "сценарий 9б: valve_status == false - шаг регулятора не должен выполняться");

  if (failures != 0) return 1;
  std::cout << "BK water auto step passed\n";
  return 0;
}
'''


def compile_and_run(name: str, source: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="samovar-bk-water-auto-") as temp_dir:
        temp = Path(temp_dir)
        source_path = temp / f"{name}.cpp"
        binary_path = temp / name
        source_path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source_path), "-o", str(binary_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return result
        return subprocess.run([str(binary_path)], capture_output=True, text=True, check=False)


def main() -> int:
    bk_source = (ROOT / "BK.h").read_text(encoding="utf-8")
    try:
        alarm_body = extract_function_body(bk_source, "void check_alarm_bk()")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    harness = HARNESS.replace("@CHECK_ALARM_BK@", "void check_alarm_bk() {" + alarm_body + "}")

    result = compile_and_run("bk_water_auto_step", harness)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        return result.returncode

    def run_mutant(name: str, old: str, new: str, description: str) -> int:
        mutant = harness.replace(old, new, 1)
        if mutant == harness:
            print(f"FAIL: не удалось построить мутацию {name}", file=sys.stderr)
            return 1
        mutant_result = compile_and_run(name, mutant)
        if mutant_result.returncode == 0:
            print(f"FAIL: мутация {name} ({description}) пережила тест", file=sys.stderr)
            return 1
        return 0

    status = run_mutant(
        "wp_count_gate",
        "valve_status && wp_count >= 10 &&",
        "valve_status &&",
        "шаг регулятора выполняется до конца плавного пуска насоса",
    )
    if status != 0:
        return status

    status = run_mutant(
        "deadband_lost",
        "if (diff >= BK_WATER_DEADBAND)",
        "if (diff > 0)",
        "мёртвая зона потеряна - шаг происходит при незначимой разнице",
    )
    if status != 0:
        return status

    status = run_mutant(
        "water_priority_lost",
        "diff <= -BK_WATER_DEADBAND && WaterSensor.avgTemp < ALARM_WATER_TEMP - 5",
        "diff <= -BK_WATER_DEADBAND",
        "шаг вниз происходит вопреки защите по воде",
    )
    if status != 0:
        return status

    status = run_mutant(
        "auto_gate_swapped",
        "if (bk_water_auto) {\n    if (!sensor_valid(SteamSensor)) {",
        "if (true) {\n    if (!sensor_valid(SteamSensor)) {",
        "датчик пара проверяется даже при выключенном auto",
    )
    if status != 0:
        return status

    print("BK water auto step mutation checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
