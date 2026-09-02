#!/usr/bin/env python3
"""Поведенческая проверка A2 (`docs/plans/2026-09-02-bk-implementation-plan.md`,
задача A2, пункт 3): мягкий пуск насоса не должен зависеть от того, что
PWM_START_VALUE*10 (400 - с чего стартует разгон) случайно РАВНО
PWM_LOW_VALUE*40 (400 - исторический дефолт bk_pwm при перезагрузке,
sensorinit.h). Это два разных по смыслу числа, совпавшие арифметически
(40*10 == 10*40).

[Находка] Обе ветки set_pump_pwm() сравнивали duty с PWM_LOW_VALUE * 40 (400)
и по этому сравнению решали, писать ли сразу duty или держать старт. Из-за
этого разгон реально длился 10 тиков ТОЛЬКО когда duty случайно равнялся 400;
для любого другого duty (Пиво, самотест, PID-регулятор насоса) уже второй
подряд вызов писал duty напрямую, минуя весь смысл счётчика wp_count - мягкий
пуск фактически длился один вызов, а не десять.

Правка убирает сравнение с 400 из обеих веток: разгон теперь всегда держит
PWM_START_VALUE*10 на первом вызове и на всех последующих, пока wp_count < 10,
и применяет запрошенное duty только когда счётчик исчерпан - одинаково для
ЛЮБОГО duty > 0.

Тест извлекает РЕАЛЬНОЕ тело set_pump_pwm() из pumppwm.h, компилирует его
g++-харнессом и прогоняет для двух разных duty (400 и 700) одну и ту же
последовательность проверок:
  1. Первые 11 вызовов подряд (1 "фронтовой", переводящий pump_started в
     true, и 10 "продолжающих", пока wp_count идёт 0..9) обязаны держать
     PWM_START_VALUE*10 - для ОБОИХ duty одинаково.
  2. 12-й вызов подряд обязан применить именно duty (не старт, не что-то
     промежуточное) - граница wp_count < 10 проверяется явно по номеру
     вызова, а не "где-то рядом".
  3. duty == 0 останавливает насос немедленно из любого состояния разгона.
  4. duty, изменённый на лету посреди разгона, применяется по значению
     ПОСЛЕДНЕГО вызова, а не первого запрошенного - на этом свойстве держится
     корректность PID-пути (mode_update_water_pump_pid дёргает set_pump_pwm
     каждый тик со свежим выходом регулятора).

Мутации (каждая обязана уронить содержательный assert, а не компилятор):
  1. Вернуть сравнение с 400 во ВТОРУЮ (продолжающую) ветку разгона
     (буквальный откат A2). Та же подмена в первой ветке ничего не меняет:
     там водяной насос и так уже получил PWM_START_VALUE*10 до развилки, и
     обе старые ветки при любом duty сходятся к тому же water_pump_speed ==
     400 - разница проявляется только начиная со 2-го вызова, во второй ветке.
  2. Убрать wp_count++ во второй ветке - счётчик разгона никогда не
     исчерпается, duty не применится никогда.
  3. Убрать pump_started = true в первой ветке - функция каждый раз заново
     считает себя "не запущенной", wp_count обнуляется на каждом вызове.
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
#include <string>
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
static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  pump_started = false;
  wp_count = 0;
  water_pump_speed = 0;
  pump_pwm.lastWrite = -1;
  mode_switch_barrier_active = false;
}

int main() {
  // Сценарии 1+2: одна и та же последовательность проверок для ДВУХ разных
  // duty (400 - совпадает с историческим PWM_LOW_VALUE*40, и 700 - не
  // совпадает ни с чем) должна вести себя ОДИНАКОВО: 11 вызовов держат
  // старт, 12-й применяет duty.
  for (int duty : {400, 700}) {
    reset_fixture();
    for (int call = 1; call <= 12; call++) {
      set_pump_pwm((float)duty);
      if (call <= 11) {
        check(water_pump_speed == PWM_START_VALUE * 10,
              "РЕГРЕСС A2 п.3: duty=" + std::to_string(duty) +
              " - на вызове #" + std::to_string(call) +
              " разгон должен ещё держать старт, получили " +
              std::to_string(water_pump_speed));
        check(pump_pwm.lastWrite == PWM_START_VALUE * 10,
              "РЕГРЕСС A2 п.3: duty=" + std::to_string(duty) +
              " - фактическая запись в ШИМ на вызове #" + std::to_string(call) +
              " должна быть стартовым порогом");
      } else {
        check(water_pump_speed == (uint16_t)duty,
              "РЕГРЕСС A2 п.3: duty=" + std::to_string(duty) +
              " - 12-й вызов обязан применить запрошенное duty, получили " +
              std::to_string(water_pump_speed));
        check(pump_pwm.lastWrite == duty,
              "РЕГРЕСС A2 п.3: duty=" + std::to_string(duty) +
              " - фактическая запись в ШИМ на 12-м вызове должна совпасть с duty");
      }
    }
  }

  // Сценарий 3: duty == 0 останавливает насос немедленно, из уже
  // разогнанного состояния (продолжаем с состояния предыдущего цикла, где
  // duty=700 уже применилось).
  set_pump_pwm(0);
  check(water_pump_speed == 0, "duty == 0 обязан останавливать насос немедленно, минуя разгон");
  check(pump_pwm.lastWrite == 0, "duty == 0 обязан фактически обнулить запись в ШИМ");
  check(pump_started == false, "duty == 0 обязан сбросить pump_started");

  // Сценарий 4: duty меняется НА ЛЕТУ посреди разгона - применяется duty
  // ПОСЛЕДНЕГО вызова, а не первого запрошенного (на этом свойстве держится
  // корректность PID-пути: mode_update_water_pump_pid зовёт set_pump_pwm
  // каждый тик со свежим выходом регулятора). 6 вызовов с 700 (1 фронтовой +
  // 5 продолжающих, wp_count 0->5, всё ещё разгон) + 6 вызовов с 1023
  // (продолжающие wp_count 5->10, 12-й суммарный вызов исчерпывает счётчик и
  // применяет ПОСЛЕДНЕЕ duty - 1023, а не первое запрошенное - 700).
  reset_fixture();
  for (int call = 0; call < 6; call++) set_pump_pwm(700);
  for (int call = 0; call < 6; call++) set_pump_pwm(1023);
  check(water_pump_speed == 1023,
        "РЕГРЕСС: применяться должно duty ТЕКУЩЕГО (последнего) вызова, а не первое запрошенное");
  check(pump_pwm.lastWrite == 1023, "фактическая запись в ШИМ должна совпасть с последним запрошенным duty");

  if (failures != 0) return 1;
  std::cout << "pump pwm soft start target (A2 п.3) behaviour checks passed\n";
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


def run_mutation(name: str, body: str, mutant_body: str) -> int:
    if mutant_body == body:
        print(f"FAIL: не удалось создать мутацию ({name})", file=sys.stderr)
        return 1
    code, output = compile_and_run(HARNESS_TEMPLATE.replace("@BODY@", mutant_body))
    if code == 0:
        print(f"FAIL: мутация ({name}) пережила тест", file=sys.stderr)
        sys.stderr.write(output)
        return 1
    print(f"Mutation rejected as expected: {name}")
    return 0


def main() -> int:
    pwm_source = (ROOT / "pumppwm.h").read_text(encoding="utf-8")
    try:
        body = extract_function_body(pwm_source, SIGNATURE)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if "bk_pwm" in body:
        print("FAIL: тело set_pump_pwm снова ссылается на bk_pwm - харнесс этого теста не заводит такую переменную", file=sys.stderr)
        return 1

    code, output = compile_and_run(HARNESS_TEMPLATE.replace("@BODY@", body))
    sys.stdout.write(output)
    if code:
        return code

    # Мутация 1: буквально откатываем правку A2 - возвращаем сравнение с
    # PWM_LOW_VALUE * 40 во ВТОРУЮ (продолжающую) ветку разгона. Ровно в ней
    # был реальный дефект: старый код писал duty напрямую уже со 2-го вызова
    # для любого duty != 400, минуя весь смысл счётчика wp_count. (Такая же
    # подмена в ПЕРВОЙ ветке ничего не меняет: там перед развилкой уже
    # записан PWM_START_VALUE*10, и обе старые ветки при любом duty приводят
    # к тому же итоговому water_pump_speed == 400 - see §0 плана A2 - поэтому
    # мутировать имеет смысл только вторую ветку, которая реально исполняется
    # повторно.)
    old_continue = (
        "  if (duty > 0 && wp_count < 10 && pump_started) {\n"
        "    pump_pwm.write(PWM_START_VALUE * 10);\n"
        "    water_pump_speed = PWM_START_VALUE * 10;\n"
        "    wp_count++;\n"
        "    return ACTUATOR_COMMAND_APPLIED;\n"
        "  }\n"
    )
    new_continue = (
        "  if (duty > 0 && wp_count < 10 && pump_started) {\n"
        "    if (duty != PWM_LOW_VALUE * 40) {\n"
        "      pump_pwm.write(duty);\n"
        "      water_pump_speed = duty;\n"
        "    } else {\n"
        "      pump_pwm.write(PWM_START_VALUE * 10);\n"
        "      water_pump_speed = PWM_START_VALUE * 10;\n"
        "    }\n"
        "    wp_count++;\n"
        "    return ACTUATOR_COMMAND_APPLIED;\n"
        "  }\n"
    )
    if old_continue not in body:
        print("FAIL: не найден якорь мутации 1 (возврат сравнения с 400 во второй ветке)", file=sys.stderr)
        return 1
    result = run_mutation("вернуть сравнение с 400 во второй ветке разгона", body, body.replace(old_continue, new_continue, 1))
    if result:
        return result

    # Мутация 2: убрать инкремент wp_count во второй ветке - счётчик разгона
    # никогда не исчерпается, duty не применится никогда.
    result = run_mutation("убрать wp_count++ во второй ветке", body, body.replace("wp_count++;", "", 1))
    if result:
        return result

    # Мутация 3: убрать pump_started = true в первой ветке - функция каждый
    # раз заново считает себя "не запущенной", разгон никогда не продвинется.
    result = run_mutation("убрать pump_started = true в первой ветке", body, body.replace("pump_started = true;\n", "", 1))
    if result:
        return result

    print("Pump soft start A2 mutations were rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
