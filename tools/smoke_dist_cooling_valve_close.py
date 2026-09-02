#!/usr/bin/env python3
"""Поведенческая проверка [П10]: клапан охлаждения обязан закрываться и по
остывшему кубу, а не только по остывшей воде охлаждения.

mode_should_close_cooling() раньше закрывал клапан ТОЛЬКО когда WaterSensor
(вода охлаждения) остывала ниже closeTemp: летом (тёплая проточная вода) этот
порог почти никогда не достигается - клапан не закрывается вовсе, а на уже
холодной воде клапан захлопывался СРАЗУ по команде "стоп", даже если куб ещё
кипяток. Добавлена вторая, независимая причина закрытия - куб остыл ниже
OPEN_VALVE_TANK_TEMP - 7, и минимальная выдержка 3 минуты с момента
выключения нагрева перед закрытием по одной лишь температуре воды.

Критично для НБК (nbk.h вызывает эту же функцию, но там куб физически не
греется - датчик куба может быть всегда ниже порога): критерий "куб остыл"
взводится флагом tankWasHot, который взводится, ТОЛЬКО если куб реально
прогревался в эту сессию (PowerOn и датчик валиден, и температура доходила до
OPEN_VALVE_TANK_TEMP). Без этой защиты у НБК клапан закрывался бы немедленно
при каждой остановке, минуя выдержку по воде.

Тест вытаскивает РЕАЛЬНЫЕ тела mode_should_close_cooling() (mode_common.h),
safety_deadline_after()/safety_deadline_expired() (safety_transition.h) и
sensor_configured()/sensor_reading_valid()/sensor_valid() (alarm.h) - без
переписывания логики - и прогоняет их через хронологический сценарий
(millis() управляется тестом) с моками только PowerOn/valve_status/is_self_test
и показаний датчиков.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SENSOR_CONFIGURED_SIGNATURE = "inline bool sensor_configured(const DSSensor& sensor)"
SENSOR_READING_VALID_SIGNATURE = "inline bool sensor_reading_valid(const DSSensor& sensor)"
SENSOR_VALID_SIGNATURE = "inline bool sensor_valid(const DSSensor& sensor)"
DEADLINE_EXPIRED_SIGNATURE = "inline bool safety_deadline_expired(uint32_t now, uint32_t deadline)"
DEADLINE_AFTER_SIGNATURE = "inline uint32_t safety_deadline_after(uint32_t now, uint32_t delayMs)"
SHOULD_CLOSE_SIGNATURE = "inline bool mode_should_close_cooling(float closeTemp, bool requireAcpCoolEnough)"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

#define OPEN_VALVE_TANK_TEMP 77
#define MAX_ACP_TEMP 75

static uint32_t fake_millis_value = 0;
// Не static: единственный вызов - изнутри вклеенного тела mode_should_close_cooling.
uint32_t millis() { return fake_millis_value; }

using DeviceAddress = uint8_t[8];
struct DSSensor {
  DeviceAddress Sensor = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
  volatile float avgTemp = 0.0f;
  volatile int ErrCount = 0;
};

@SENSOR_CONFIGURED_BODY@

@SENSOR_READING_VALID_BODY@

@SENSOR_VALID_BODY@

@DEADLINE_AFTER_BODY@

@DEADLINE_EXPIRED_BODY@

static DSSensor WaterSensor;
static DSSensor TankSensor;
static DSSensor ACPSensor;
static bool PowerOn = false;
static bool is_self_test = false;
static bool valve_status = true;

@SHOULD_CLOSE_BODY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void configure_sensor(DSSensor& sensor, bool configured) {
  sensor.Sensor[0] = configured ? 0x01 : 0xFF;
}

int main() {
  const float closeTemp = 40.0f;               // условное SetWaterTemp - DELTA_T_CLOSE_VALVE
  const float tankCoolThreshold = OPEN_VALVE_TANK_TEMP - 7;  // как в реальном коде

  configure_sensor(TankSensor, true);
  configure_sensor(ACPSensor, false);  // группам A-C ТСА не участвует

  // --- Bootstrap: до первого перехода PowerOn true->false modeHeatOffDeadlineArmed
  // внутри функции ещё не взведён - критерий воды обязан работать немедленно,
  // как было до этой правки. Раньше признаком "ещё не взведено" служил
  // сентинел modeHeatOffDeadline == 0, и safety_deadline_expired() (используемая
  // и для настоящих дедлайнов) действительно трактует 0 как "уже истёк" для
  // разумных millis() - проверяем этот факт отдельно ниже, - но сам сентинел
  // ломался, когда millis() перешагивал через переполнение int32
  // (~24.85 суток, 2^31 мс): (int32_t)(millis() - 0) уходил в отрицательные
  // числа, и "уже истёк" внезапно превращалось в "нет". Флаг
  // modeHeatOffDeadlineArmed от этого не зависит - проверяем на трёх значениях
  // millis(), включая значение сразу после переполнения.
  fake_millis_value = 12345;  // произвольный, но реалистичный аптайм в мс
  check(safety_deadline_expired(fake_millis_value, 0),
        "safety_deadline_expired(millis(), 0) обязано считаться «уже истёк» для разумного millis()");
  for (const uint32_t bootstrapMillis : {12345UL, 0UL, 0x80000000UL + 1000UL}) {
    fake_millis_value = bootstrapMillis;
    PowerOn = false;
    is_self_test = false;
    valve_status = true;
    WaterSensor.avgTemp = closeTemp - 5.0f;  // уже холодная вода
    TankSensor.avgTemp = 20.0f;              // куб холодный, но ещё не участвует (PowerOn ни разу не включался)
    check(mode_should_close_cooling(closeTemp, false) == true,
          "РЕГРЕСС: до первого цикла нагрева критерий воды обязан работать немедленно при любом millis() "
          "(в т.ч. после переполнения int32 в 0x80000000+1000), без вынужденного ожидания");
  }

  // --- Группа A: обычная сессия (ректификация/дистилляция) - куб грелся,
  // закрытие по одной лишь холодной воде обязано ждать 3 минуты с момента
  // выключения нагрева.
  PowerOn = true;  // фронт false->true: tankWasHot сбрасывается (уже false)
  mode_should_close_cooling(closeTemp, false);
  TankSensor.avgTemp = OPEN_VALVE_TANK_TEMP + 10.0f;  // куб прогрелся выше порога открытия клапана
  mode_should_close_cooling(closeTemp, false);         // tankWasHot -> true
  PowerOn = false;  // фронт true->false: дедлайн 3 минуты взводится от текущего millis()
  WaterSensor.avgTemp = closeTemp + 5.0f;  // вода ещё тёплая
  check(mode_should_close_cooling(closeTemp, false) == false,
        "сразу после остановки нагрева клапан не должен закрываться - ни вода, ни куб ещё не остыли");

  fake_millis_value += 60UL * 1000;  // +1 минута - меньше выдержки в 3 минуты
  WaterSensor.avgTemp = closeTemp - 5.0f;  // вода уже остыла
  // куб всё ещё горячий -> критерий куба не готов; критерий воды блокирует
  // дедлайном (прошла только 1 минута из 3)
  check(mode_should_close_cooling(closeTemp, false) == false,
        "РЕГРЕСС: закрытие по одной лишь холодной воде не должно происходить раньше выдержки в 3 минуты");

  fake_millis_value += 2UL * 60 * 1000 + 1000;  // ещё +2 мин 1 с - итого больше 3 минут
  check(mode_should_close_cooling(closeTemp, false) == true,
        "после выдержки 3 минуты остывшая вода обязана закрывать клапан");

  // --- Группа B: куб остыл раньше, чем истекла 3-минутная выдержка по воде -
  // независимый путь закрытия по кубу обязан сработать сам, не дожидаясь воды.
  valve_status = true;
  PowerOn = true;  // фронт false->true: новая сессия, tankWasHot сбрасывается в false
  mode_should_close_cooling(closeTemp, false);
  TankSensor.avgTemp = OPEN_VALVE_TANK_TEMP + 10.0f;  // куб снова прогрелся
  mode_should_close_cooling(closeTemp, false);         // tankWasHot -> true
  PowerOn = false;  // фронт true->false: дедлайн 3 минуты взводится заново
  WaterSensor.avgTemp = closeTemp + 5.0f;  // вода ещё тёплая - её путь не готов
  check(mode_should_close_cooling(closeTemp, false) == false,
        "сразу после остановки (группа B) клапан не должен закрываться");

  fake_millis_value += 30UL * 1000;  // +30 c - явно меньше 3 минут
  TankSensor.avgTemp = tankCoolThreshold - 1.0f;  // куб остыл ниже порога
  check(mode_should_close_cooling(closeTemp, false) == true,
        "куб, остывший ниже порога, обязан закрывать клапан независимо от выдержки по воде");

  // --- Группа C (НБК): куб НИКОГДА не грелся в этой сессии - датчик куба
  // может быть всегда ниже OPEN_VALVE_TANK_TEMP. Без tankWasHot критерий
  // "куб остыл" сработал бы СРАЗУ при остановке, минуя выдержку по воде.
  valve_status = true;
  PowerOn = true;  // фронт false->true: tankWasHot сбрасывается в false
  TankSensor.avgTemp = 20.0f;  // куб физически не греется - никогда не достигает OPEN_VALVE_TANK_TEMP
  mode_should_close_cooling(closeTemp, false);  // тик - куб холодный, tankWasHot остаётся false
  PowerOn = false;  // фронт true->false: дедлайн 3 минуты взводится
  WaterSensor.avgTemp = closeTemp + 5.0f;  // вода ещё тёплая
  // TankSensor.avgTemp по-прежнему 20 (< tankCoolThreshold) - без защиты
  // критерий куба сработал бы немедленно.
  check(mode_should_close_cooling(closeTemp, false) == false,
        "РЕГРЕСС (НБК): куб, который никогда не грелся, не должен закрывать клапан немедленно при остановке");

  fake_millis_value += 3UL * 60 * 1000 + 1000;  // выдержка по воде прошла
  WaterSensor.avgTemp = closeTemp - 5.0f;  // вода остыла
  check(mode_should_close_cooling(closeTemp, false) == true,
        "НБК: закрытие всё же происходит по критерию воды + выдержка, когда он выполнен");

  // --- Группа D: критерий ТСА - при requireAcpCoolEnough=true и
  // сконфигурированном горячем датчике ТСА закрытие обязано откладываться,
  // даже когда вода и куб уже дают добро.
  valve_status = true;
  PowerOn = true;
  TankSensor.avgTemp = OPEN_VALVE_TANK_TEMP + 10.0f;
  mode_should_close_cooling(closeTemp, true);
  PowerOn = false;  // фронт true->false: дедлайн 3 минуты взводится от ТЕКУЩЕГО millis()
  WaterSensor.avgTemp = closeTemp + 5.0f;  // вода ещё тёплая
  // Тик СРАЗУ на фронте - иначе дедлайн будет взведён от millis() уже ПОСЛЕ
  // сдвига времени ниже, а не от момента остановки нагрева.
  check(mode_should_close_cooling(closeTemp, true) == false,
        "сразу после остановки (группа D) клапан не должен закрываться");

  fake_millis_value += 3UL * 60 * 1000 + 1000;
  WaterSensor.avgTemp = closeTemp - 5.0f;
  configure_sensor(ACPSensor, true);
  ACPSensor.avgTemp = MAX_ACP_TEMP;  // выше MAX_ACP_TEMP - 10 -> ещё горячий
  check(mode_should_close_cooling(closeTemp, true) == false,
        "горячий ТСА обязан откладывать закрытие клапана, даже если вода и куб остыли");

  ACPSensor.avgTemp = MAX_ACP_TEMP - 20.0f;  // ниже MAX_ACP_TEMP - 10
  check(mode_should_close_cooling(closeTemp, true) == true,
        "остывший ТСА снимает последнюю преграду для закрытия клапана");
  configure_sensor(ACPSensor, false);

  // --- Группа E: жёсткие блокировки, не зависящие от температур.
  PowerOn = true;
  check(mode_should_close_cooling(closeTemp, false) == false, "при включённом нагреве клапан не закрывается");
  PowerOn = false;
  is_self_test = true;
  check(mode_should_close_cooling(closeTemp, false) == false, "в режиме самопроверки клапан не закрывается");
  is_self_test = false;
  valve_status = false;
  check(mode_should_close_cooling(closeTemp, false) == false, "уже закрытый клапан не требует повторного закрытия");
  valve_status = true;

  if (failures != 0) return 1;
  std::cout << "mode_should_close_cooling behaviour checks passed\n";
  return 0;
}
'''


def build_harness(mode_common_source: str, safety_source: str, alarm_source: str) -> str:
    sensor_configured_body = extract_function_body(alarm_source, SENSOR_CONFIGURED_SIGNATURE)
    sensor_reading_valid_body = extract_function_body(alarm_source, SENSOR_READING_VALID_SIGNATURE)
    sensor_valid_body = extract_function_body(alarm_source, SENSOR_VALID_SIGNATURE)
    deadline_after_body = extract_function_body(safety_source, DEADLINE_AFTER_SIGNATURE)
    deadline_expired_body = extract_function_body(safety_source, DEADLINE_EXPIRED_SIGNATURE)
    should_close_body = extract_function_body(mode_common_source, SHOULD_CLOSE_SIGNATURE)

    harness = HARNESS_TEMPLATE
    harness = harness.replace(
        "@SENSOR_CONFIGURED_BODY@", SENSOR_CONFIGURED_SIGNATURE + " {" + sensor_configured_body + "}"
    )
    harness = harness.replace(
        "@SENSOR_READING_VALID_BODY@", SENSOR_READING_VALID_SIGNATURE + " {" + sensor_reading_valid_body + "}"
    )
    harness = harness.replace("@SENSOR_VALID_BODY@", SENSOR_VALID_SIGNATURE + " {" + sensor_valid_body + "}")
    harness = harness.replace("@DEADLINE_AFTER_BODY@", DEADLINE_AFTER_SIGNATURE + " {" + deadline_after_body + "}")
    harness = harness.replace(
        "@DEADLINE_EXPIRED_BODY@", DEADLINE_EXPIRED_SIGNATURE + " {" + deadline_expired_body + "}"
    )
    harness = harness.replace("@SHOULD_CLOSE_BODY@", SHOULD_CLOSE_SIGNATURE + " {" + should_close_body + "}")
    return harness


def compile_and_run(harness: str, label: str) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-dist-cooling-valve-close-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "dist_cooling_valve_close_test.cpp"
        binary = temp / "dist_cooling_valve_close_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(f"[{label}] compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode, compile_result.stdout, compile_result.stderr
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(f"[{label}] ")
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode, run_result.stdout, run_result.stderr


def run_mutation(label: str, mode_common_source: str, safety_source: str, alarm_source: str,
                  old: str, new: str) -> int:
    mutated = mode_common_source.replace(old, new, 1)
    if mutated == mode_common_source:
        print(f"FAIL: mutation anchor missing for {label}", file=sys.stderr)
        return 1
    harness = build_harness(mutated, safety_source, alarm_source)
    rc, out, err = compile_and_run(harness, f"mutation {label}")
    if rc == 0:
        print(f"FAIL: mutation ({label}) survived", file=sys.stderr)
        return 1
    print(f"mutation ({label}) failure text:")
    print(out + err)
    return 0


def main() -> int:
    mode_common_source = (ROOT / "mode_common.h").read_text(encoding="utf-8")
    safety_source = (ROOT / "safety_transition.h").read_text(encoding="utf-8")
    alarm_source = (ROOT / "alarm.h").read_text(encoding="utf-8")

    try:
        harness = build_harness(mode_common_source, safety_source, alarm_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rc, _, _ = compile_and_run(harness, "mode_should_close_cooling")
    if rc != 0:
        return rc

    # --- Мутация 1 (по требованию координатора): "убрать tankWasHot" - куб,
    # который никогда не грелся (НБК), снова закрывал бы клапан немедленно.
    # (void)tankWasHot; добавлен, чтобы мутация падала на содержательном
    # assert-е, а не на -Werror=unused-but-set-variable (переменная всё ещё
    # взводится выше по функции, просто перестаёт влиять на результат).
    rc = run_mutation(
        "убрать tankWasHot",
        mode_common_source, safety_source, alarm_source,
        "const bool tankCooledEnough =\n"
        "    tankWasHot && sensor_valid(TankSensor) && TankSensor.avgTemp < OPEN_VALVE_TANK_TEMP - 7;",
        "(void)tankWasHot;\n  const bool tankCooledEnough =\n"
        "    sensor_valid(TankSensor) && TankSensor.avgTemp < OPEN_VALVE_TANK_TEMP - 7;",
    )
    if rc != 0:
        return rc

    # --- Мутация 2: убрать выдержку 3 минуты - холодная вода закрывала бы
    # клапан немедленно по команде "стоп", как до этой правки. (void) для обеих
    # переменных выдержки по той же причине, что и в мутации 1.
    rc = run_mutation(
        "убрать выдержку 3 минуты",
        mode_common_source, safety_source, alarm_source,
        "const bool waterCooledLongEnough =\n"
        "    WaterSensor.avgTemp <= closeTemp &&\n"
        "    (!modeHeatOffDeadlineArmed || safety_deadline_expired(millis(), modeHeatOffDeadline));",
        "(void)modeHeatOffDeadline;\n  (void)modeHeatOffDeadlineArmed;\n  const bool waterCooledLongEnough =\n"
        "    WaterSensor.avgTemp <= closeTemp;",
    )
    if rc != 0:
        return rc

    # --- Мутация 3 (предупреждение 2 ревью): вернуть старый сентинел
    # modeHeatOffDeadline == 0 вместо явного флага modeHeatOffDeadlineArmed.
    # Ловится ИМЕННО новым пост-переполненным bootstrap-сценарием выше (при
    # millis() == 12345 и 0 эта мутация ничем не отличается от исправленного
    # кода - safety_deadline_expired(x, 0) истинно для обоих): при
    # millis() == 0x80000000 + 1000 (int32_t)(millis() - 0) уходит в
    # отрицательные числа, "выдержка уже прошла" становится false, и клапан
    # не закрывается, хотя нагрев в этой сессии ни разу не включался.
    rc = run_mutation(
        "вернуть сентинел modeHeatOffDeadline==0 вместо флага",
        mode_common_source, safety_source, alarm_source,
        "const bool waterCooledLongEnough =\n"
        "    WaterSensor.avgTemp <= closeTemp &&\n"
        "    (!modeHeatOffDeadlineArmed || safety_deadline_expired(millis(), modeHeatOffDeadline));",
        "(void)modeHeatOffDeadlineArmed;\n  const bool waterCooledLongEnough =\n"
        "    WaterSensor.avgTemp <= closeTemp && safety_deadline_expired(millis(), modeHeatOffDeadline);",
    )
    if rc != 0:
        return rc

    print("mode_should_close_cooling mutation checks: FAIL as expected (mutations killed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
