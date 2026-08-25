#!/usr/bin/env python3
"""Поведенческая проверка П14: мягкий пуск насоса должен сходиться к ЗАПРОШЕННОЙ
мощности (duty), а не к постороннему bk_pwm (уставка водяного насоса режима БК).

[Находка] Ветки мягкого пуска в set_pump_pwm() сравнивали и писали bk_pwm вместо
duty - аргумента ЭТОГО вызова. Для БК это было незаметно, т.к. BK.h всегда
вызывает set_pump_pwm(bk_pwm) (duty == bk_pwm). Но для остальных вызывающих
(Пиво: beer_set_cooling_pump вызывает set_pump_pwm(1023) каждый тик, пока
охлаждение нужно) насос при повторных вызовах сходился не к 1023, а к
произвольному bk_pwm, оставшемуся от прошлого запуска БК - на практике застревал
на заниженной мощности. Отдельно: если bk_pwm случайно равнялся дефолту
PWM_LOW_VALUE*40=400 (sensorinit.h, значение при старте прошивки), мягкий пуск
пропускался целиком на первом же вызове - насос сразу получал полную мощность,
минуя защитный стартовый порог (тот самый "соседний вопрос" из ревью).

Тест извлекает РЕАЛЬНОЕ тело set_pump_pwm() из pumppwm.h, компилирует его
g++-харнессом и прогоняет сценарии:
  1. Циклические вызовы (как теперь делает beer.h - каждый тик) с duty=1023,
     пока bk_pwm держит НЕСВЯЗАННОЕ значение - мощность должна дойти до 1023,
     а не застрять на bk_pwm или на стартовом пороге.
  2. bk_pwm ровно на дефолте (PWM_LOW_VALUE*40) - первый же вызов НЕ должен
     пропускать стартовый порог (защита от броска пускового тока).
  3. Регресс для БК: duty всегда равен bk_pwm (как в BK.h) - поведение не
     должно измениться относительно исходного кода.

Плюс мутация: подменяем duty обратно на bk_pwm в ветке мягкого пуска (буквально
откатываем фикс П14) и убеждаемся, что сценарий 1 при этом падает.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SIGNATURE = "ActuatorCommandResult set_pump_pwm(float duty)"

HARNESS_TEMPLATE = r'''
#include <iostream>
#include <cstdint>

enum ActuatorCommandResult : uint8_t {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};

// Те же значения, что и в Samovar_ini.h.
#define PWM_LOW_VALUE 10
#define PWM_START_VALUE 40

#ifndef constrain
#define constrain(amt, low, high) ((amt) < (low) ? (low) : ((amt) > (high) ? (high) : (amt)))
#endif

static bool pump_started = false;
static int bk_pwm = 0;
static int8_t wp_count = 0;
static uint16_t water_pump_speed = 0;
static bool mode_switch_barrier_active = false;

struct FakePwm {
  int lastWrite = -1;
  void write(int value) { lastWrite = value; }
};
static FakePwm pump_pwm;

static ActuatorCommandResult set_pump_pwm(float duty) {
@BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  pump_started = false;
  bk_pwm = 0;
  wp_count = 0;
  water_pump_speed = 0;
  pump_pwm.lastWrite = -1;
  mode_switch_barrier_active = false;
}

int main() {
  // Сценарий 1: циклические вызовы (как в beer.h - каждый тик) с duty=1023,
  // пока bk_pwm держит НЕСВЯЗАННОЕ значение (150 - не 0, не 400, не 1023).
  reset_fixture();
  bk_pwm = 150;
  set_pump_pwm(1023);
  check(water_pump_speed == PWM_START_VALUE * 10,
        "первый вызов должен выставить стартовый порог мягкого пуска (400), а не сразу полную мощность");
  check(water_pump_speed != (uint16_t)bk_pwm,
        "первый вызов не должен подмешивать посторонний bk_pwm");

  for (int tick = 0; tick < 14; tick++) {
    set_pump_pwm(1023);
    check(water_pump_speed != (uint16_t)bk_pwm,
          "ГЛАВНЫЙ РЕГРЕСС П14: мощность насоса застряла на постороннем bk_pwm вместо запрошенной duty");
  }
  check(water_pump_speed == 1023,
        "ГЛАВНЫЙ РЕГРЕСС П14: после серии циклических вызовов насос должен дойти до полной запрошенной мощности (1023)");
  check(pump_pwm.lastWrite == 1023, "фактическая запись в ШИМ должна совпасть с полной мощностью");

  // Сценарий 2: bk_pwm ровно на дефолте (см. sensorinit.h) - мягкий пуск не
  // должен пропускаться на первом же вызове.
  reset_fixture();
  bk_pwm = PWM_LOW_VALUE * 40;
  set_pump_pwm(1023);
  check(water_pump_speed == PWM_START_VALUE * 10,
        "РЕГРЕСС (соседний вопрос ревью): при bk_pwm на дефолте мягкий пуск не должен пропускаться");

  // Сценарий 3: БК-паттерн (duty всегда равен bk_pwm, см. BK.h) - поведение
  // не должно отличаться от исходного кода.
  reset_fixture();
  bk_pwm = 700;
  set_pump_pwm((float)bk_pwm);
  check(water_pump_speed == PWM_START_VALUE * 10, "БК: первый вызов - стартовый порог");
  set_pump_pwm((float)bk_pwm);
  check(water_pump_speed == 700, "БК: второй вызов должен выйти на целевую мощность bk_pwm");

  if (failures != 0) return 1;
  std::cout << "pump pwm soft start target (П14) behaviour checks passed\n";
  return 0;
}
'''


def compile_and_run(harness: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-pump-soft-start-") as temp_dir:
        source = Path(temp_dir) / "pump_soft_start.cpp"
        binary = Path(temp_dir) / "pump_soft_start"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-O1", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode:
            return compiled.returncode, compiled.stdout + compiled.stderr
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        return ran.returncode, ran.stdout + ran.stderr


def main() -> int:
    pwm_source = (ROOT / "pumppwm.h").read_text(encoding="utf-8")
    try:
        body = extract_function_body(pwm_source, SIGNATURE)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    harness = HARNESS_TEMPLATE.replace("@BODY@", body)
    code, output = compile_and_run(harness)
    sys.stdout.write(output)
    if code:
        return code

    # Мутация: буквально откатываем фикс П14 - возвращаем bk_pwm вместо duty
    # в ветке мягкого пуска, которая держит цикл рампы. Тест обязан упасть.
    mutant_body = body.replace(
        "if (duty != PWM_LOW_VALUE * 40) {\n      pump_pwm.write(duty);\n      water_pump_speed = duty;",
        "if (bk_pwm != PWM_LOW_VALUE * 40) {\n      pump_pwm.write(bk_pwm);\n      water_pump_speed = bk_pwm;",
        1,
    )
    if mutant_body == body:
        print("FAIL: не удалось создать мутацию (откат bk_pwm в ветке рампы)", file=sys.stderr)
        return 1
    mutant_harness = HARNESS_TEMPLATE.replace("@BODY@", mutant_body)
    code, output = compile_and_run(mutant_harness)
    if code == 0:
        print("FAIL: мутация (откат bk_pwm вместо duty) пережила тест", file=sys.stderr)
        sys.stderr.write(output)
        return 1
    print("Pump soft start bk_pwm/duty mutation was rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
