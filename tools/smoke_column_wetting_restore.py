#!/usr/bin/env python3
"""Регресс-проверка T06 (п.5 Уровня 3): восстановление мощности после успешного
смачивания насадки колонны.

Во время смачивания column_wetting() (logic.h) ступенчато СНИЖАЕТ мощность
(по 2% каждые 50 с) до 80% от исходной target_power_volt, ожидая срабатывания
датчика уровня флегмы. В ветке успеха (head_level_sensor_holded()) раньше сразу
звался reset_wetting_state(), который обнуляет initial_voltage, но НЕ трогает
саму target_power_volt регулятора - сниженные 80% оставались базой навсегда.
Дальше alarm.h зовёт apply_program_power_row(program[0].Power): при Power > 40
это абсолютная уставка (восстановится само), но при Power <= 40 (дельта) или
Power == 0 ("не менять") пониженная база так и оставалась.

Фикс - перед reset_wetting_state() в ветке успеха, если снижение уже началось
(voltage_decrease_started), мощность возвращается на initial_voltage.

Второй раунд (после ревью): set_current_power() при уже рабочей уставке НЕ пишет
target_power_volt синхронно - она лишь кладёт заявку регулятору и будит задачу-
воркер, которая применяет её с задержкой (power_regulator.h). А alarm.h вызывает
apply_program_power_row() сразу вслед за column_wetting(), до пробуждения воркера,
и считает дельту от ТЕКУЩЕГО target_power_volt - поэтому первого раунда фикса не
хватало для дельта-строк программы (Power <= 40). Добавлена прямая синхронная
запись target_power_volt = initial_voltage. Мок set_current_power() здесь
воспроизводит именно эту асинхронность: пишет только "последнюю заявку", а
target_power_volt харнесс обновляет отдельно через apply_pending_regulator_request()
(эмулирует воркер между тактами смачивания - интервалы там реальные 50 с) - но не
перед финальным тактом успеха, чтобы смоделировать ту же гонку, что и в прошивке.

Тест вытаскивает РЕАЛЬНЫЙ код column_wetting() из logic.h и apply_program_power_row()
из power_regulator.h через extract_function_body (без переписывания логики),
компилирует их в один host-харнесс с моками millis()/head_level_sensor_holded()/
set_current_power() и гоняет сценарий "смачивание довели до снижения -> датчик
сработал" для ДВУХ разных исходных мощностей (180 и 250 - чтобы тест не проходил
от случайного совпадения с захардкоженным числом).

Третий раунд (код-ревью): set_current_power() в ветке успеха может вернуть
ACTUATOR_COMMAND_FAILED (!PowerOn, взведённый аварийный латч или активный барьер
смены режима - power_regulator.h:790-796). Раньше target_power_volt = initial_voltage
писалась безусловно, даже если заявка регулятору не прошла - телеметрия, Lua и
check_power_error() видели "мощность восстановлена", хотя регулятор её не получал.
Фикс - пишем target_power_volt только если set_current_power() != ACTUATOR_COMMAND_FAILED.
Мок set_current_power() теперь возвращает ActuatorCommandResult (управляется
set_current_power_result) и, как настоящая функция на FAILED-пути, вообще не
трогает last_regulator_request при отказе.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

COLUMN_WETTING_SIGNATURE = "bool column_wetting() {"
APPLY_POWER_ROW_SIGNATURE = "inline void apply_program_power_row(float power) {"

HARNESS_TEMPLATE = r'''
#include <iostream>
#include <string>

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, NONE_MSG = 100 };

// abs() во прошивке приходит из Arduino.h как макрос для float - без него
// apply_program_power_row() ушла бы в целочисленный abs(int) и обрубала дробную часть.
#define abs(x) ((x) > 0 ? (x) : -(x))

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(float value) : value_(std::to_string(value)) {}
  String(double value) : value_(std::to_string(value)) {}

  friend String operator+(String left, const String& right) {
    left.value_ += right.value_;
    return left;
  }

 private:
  std::string value_;
};

// --- моки окружения column_wetting()/apply_program_power_row() ---

static unsigned long current_millis = 0;
unsigned long millis() { return current_millis; }

void SendMsg(const String&, MESSAGE_TYPE) {}

static bool head_level_sensor_holded_result = false;
bool head_level_sensor_holded() { return head_level_sensor_holded_result; }

enum ActuatorCommandResult {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};

// При уже рабочей уставке (наш сценарий: 180/250 > 40) настоящий set_current_power()
// НЕ пишет target_power_volt синхронно - он кладёт заявку регулятору и будит
// задачу-воркер (power_regulator.h, request_regulator_state_locked), которая
// применяет её отдельно, с задержкой. Мок воспроизводит это: пишет только заявку.
// set_current_power_result управляет возвратом мока (ACCEPTED/PENDING/APPLIED -
// заявка принята, FAILED - !PowerOn/латч/барьер смены режима, power_regulator.h:790-796).
// На FAILED настоящая функция выходит ДО записи заявки регулятору - мок повторяет
// это и не трогает last_regulator_request.
static float last_regulator_request = -1.0f;
float target_power_volt = 0;
static ActuatorCommandResult set_current_power_result = ACTUATOR_COMMAND_PENDING;
ActuatorCommandResult set_current_power(float Volt) {
  if (set_current_power_result == ACTUATOR_COMMAND_FAILED) return ACTUATOR_COMMAND_FAILED;
  last_regulator_request = Volt;
  return set_current_power_result;
}

// Порог WORK/SLEEP регулятора (power_regulator.h, вариант не-SEM_AVR) - нужен
// внутри извлечённого тела column_wetting(), которое теперь его проверяет.
static constexpr float POWER_WORK_MODE_THRESHOLD = 40.0f;

// Симулирует применение отложенной заявки регулятором-воркером - как будто между
// тактами column_wetting() прошло достаточно реального времени (интервалы там
// 50 с, воркеру хватает vTaskDelay(100)).
static void apply_pending_regulator_request() { target_power_volt = last_regulator_request; }

struct SetupEEPROM { bool UseHLS; };
SetupEEPROM SamSetup;

// file-scope флаг [L-36fix] - в logic.h объявлен рядом с column_wetting().
bool wetting_failed = false;

static bool column_wetting() {
@COLUMN_WETTING_BODY@
}

static constexpr float PROGRAM_POWER_ABS_THRESHOLD = 40.0f;

static void apply_program_power_row(float power) {
@APPLY_POWER_ROW_BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
static void check_near(float actual, float expected, float tol, const char* message) {
  float diff = actual - expected;
  if (diff < 0) diff = -diff;
  if (diff > tol) {
    std::cerr << "FAIL: " << message << " (expected ~" << expected << ", got " << actual << ")\n";
    failures++;
  }
}

// Гоняет смачивание базовой мощности basePower до этапа снижения (voltage_decrease_started
// == true, мощность ~80% от basePower), затем "срабатывает" датчик уровня флегмы.
// Возвращает мощность на момент срабатывания датчика ПОСЛЕ обработки успеха.
// failFinalSetCurrentPower выставляет set_current_power_result в ACTUATOR_COMMAND_FAILED
// непосредственно перед финальным (успешным по датчику) тактом - до этого момента
// заявки на снижение должны проходить как обычно, иначе не наберутся ~80%.
static float run_wetting_to_success(float basePower, float* poweredDownOut,
                                     bool failFinalSetCurrentPower = false) {
  target_power_volt = basePower;
  last_regulator_request = basePower;
  head_level_sensor_holded_result = false;
  set_current_power_result = ACTUATOR_COMMAND_PENDING;

  // Инициализация процесса (wetting_started=false -> true, initial_voltage=basePower,
  // т.к. basePower > 40).
  column_wetting();

  // Домотка до истечения 120 с (max_wetting_time) - включает ступенчатое снижение.
  current_millis += 120000;
  column_wetting();  // voltage_decrease_started выставляется в true

  // 11 циклов по 50 с (voltage_decrease_interval): 0.98^11 ~= 0.8007, то есть
  // мощность опускается чуть выше нижней границы 80% - последний из 11 шагов ещё
  // проходит "new_voltage >= min_voltage", 12-й уже упёрся бы в min_voltage.
  // Между тактами реальных 50 с воркеру хватает времени применить предыдущую
  // заявку - симулируем это apply_pending_regulator_request().
  for (int i = 0; i < 11; ++i) {
    current_millis += 50000;
    column_wetting();
    apply_pending_regulator_request();
  }
  *poweredDownOut = target_power_volt;

  // Датчик сработал - ветка успеха проверяется ПЕРВОЙ (до всех таймаутов).
  // Воркер НЕ успевает применить предыдущую заявку до этого такта - та же гонка,
  // что и в прошивке (alarm.h зовёт apply_program_power_row() сразу вслед за
  // column_wetting(), до пробуждения воркера) - apply_pending_regulator_request()
  // здесь намеренно не зовём.
  if (failFinalSetCurrentPower) set_current_power_result = ACTUATOR_COMMAND_FAILED;
  head_level_sensor_holded_result = true;
  bool result = column_wetting();
  check(result, "column_wetting() должен вернуть true при срабатывании датчика");
  return target_power_volt;
}

int main() {
  SamSetup.UseHLS = true;  // без этого весь #ifdef USE_HEAD_LEVEL_SENSOR блок не выполняется

  // Сценарий 1: база 180.
  float poweredDown180 = 0;
  float afterSuccess180 = run_wetting_to_success(180.0f, &poweredDown180);
  check_near(poweredDown180, 144.0f, 0.5f, "мощность 180 должна снизиться примерно до 80% (144)");
  check(afterSuccess180 == 180.0f,
        "РЕГРЕСС: после успешного смачивания (база 180) target_power_volt должен быть синхронно восстановлен к исходной 180, а не остаться сниженной");
  check(last_regulator_request == 180.0f,
        "РЕГРЕСС: после успешного смачивания (база 180) регулятору должна быть выставлена заявка на исходную мощность 180");

  // Сценарий 2: другая база 250 - чтобы тест не проходил на захардкоженном числе.
  float poweredDown250 = 0;
  float afterSuccess250 = run_wetting_to_success(250.0f, &poweredDown250);
  check_near(poweredDown250, 200.0f, 0.5f, "мощность 250 должна снизиться примерно до 80% (200)");
  check(afterSuccess250 == 250.0f,
        "РЕГРЕСС: после успешного смачивания (база 250) target_power_volt должен быть синхронно восстановлен к исходной 250, а не остаться сниженной");
  check(last_regulator_request == 250.0f,
        "РЕГРЕСС: после успешного смачивания (база 250) регулятору должна быть выставлена заявка на исходную мощность 250");

  // Сценарий 3 (код-ревью): set_current_power() в финальном такте отказывает
  // (ACTUATOR_COMMAND_FAILED - !PowerOn/латч/барьер смены режима). Заявка до
  // регулятора не дошла, поэтому target_power_volt должен остаться сниженным
  // (как и last_regulator_request) - ни телеметрия, ни Lua, ни check_power_error()
  // не должны увидеть "мощность восстановлена".
  float poweredDown200 = 0;
  float afterFailure200 = run_wetting_to_success(200.0f, &poweredDown200,
                                                  /*failFinalSetCurrentPower=*/true);
  check(afterFailure200 == poweredDown200,
        "РЕГРЕСС: при ACTUATOR_COMMAND_FAILED от set_current_power() target_power_volt "
        "не должен переписываться на исходную базу - должен остаться сниженным");
  check(afterFailure200 != 200.0f,
        "при отказе set_current_power() target_power_volt не должен выглядеть "
        "восстановленным до исходной базы 200");
  check(last_regulator_request == poweredDown200,
        "при отказе set_current_power() регулятору не должна уходить заявка на "
        "исходную базу 200 - last_regulator_request должен остаться сниженным");
  // Сценарий 3 оставил set_current_power_result = ACTUATOR_COMMAND_FAILED - без
  // сброса следующий блок (apply_program_power_row) тоже видел бы отказ.
  set_current_power_result = ACTUATOR_COMMAND_PENDING;

  // Пункт 3: поверх восстановленной базы прогоняем реальную семантику
  // apply_program_power_row() из power_regulator.h - Power==0 не должен менять
  // мощность, Power==30 (<=40, не абсолют) должен дать дельту +30. Сама
  // apply_program_power_row() тоже лишь зовёт set_current_power() (заявку) -
  // поэтому итог проверяем по last_regulator_request, а не по target_power_volt.
  target_power_volt = afterSuccess180;
  apply_program_power_row(0.0f);
  check(target_power_volt == 180.0f, "apply_program_power_row(0) не должен менять мощность (\"не трогать регулятор\")");

  apply_program_power_row(30.0f);
  check_near(last_regulator_request, 210.0f, 0.01f,
             "apply_program_power_row(30) должен дать дельту от восстановленной базы: 180 + 30 = 210 (заявка регулятору)");

  if (failures != 0) return 1;
  std::cout << "column_wetting() power restoration checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    logic_source = (ROOT / "logic.h").read_text(encoding="utf-8")
    wetting_body = extract_function_body(logic_source, COLUMN_WETTING_SIGNATURE)

    power_regulator_source = (ROOT / "power_regulator.h").read_text(encoding="utf-8")
    power_row_body = extract_function_body(power_regulator_source, APPLY_POWER_ROW_SIGNATURE)

    harness = HARNESS_TEMPLATE.replace("@COLUMN_WETTING_BODY@", wetting_body)
    harness = harness.replace("@APPLY_POWER_ROW_BODY@", power_row_body)
    return harness


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-column-wetting-restore-") as temp_dir:
        temp = Path(temp_dir)
        cpp_source = temp / "column_wetting_restore_test.cpp"
        binary = temp / "column_wetting_restore_test"
        cpp_source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-DCOLUMN_WETTING",
                "-DUSE_HEAD_LEVEL_SENSOR",
                str(cpp_source),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
