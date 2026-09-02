#!/usr/bin/env python3
"""Поведенческая проверка [П2]: база для снижения мощности при аварии по воде.

mode_reduce_power_for_water_alarm_by_volts() раньше считало "на сколько
снизить" от target_power_volt. В разгоне (SAFETY_REGULATOR_MODE_SPEED)
target_power_volt == 0 (уставки ещё нет - греет на максимум), и снижение "от
нуля" сразу проваливалось в клэмп power_work_mode_threshold() одним скачком с
реального максимума мощности, а не плавным шагом вниз. mode_water_alarm_power_base()
берёт за базу target_power_volt, если он есть (>0), иначе current_power_volt -
фактическое напряжение/мощность регулятора, которое отражает реальный нагрев
независимо от режима.

Тест вытаскивает РЕАЛЬНЫЕ тела mode_water_alarm_power_base() и
mode_reduce_power_for_water_alarm_by_volts() из mode_common.h, а также
reduce_power_by_volts() из runtime_helpers.h - без переписывания логики - и
подставляет их в минимальный host-харнесс, замокав только downstream
set_current_power()/SendMsg()/set_buzzer().
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

BASE_SIGNATURE = "inline float mode_water_alarm_power_base()"
REDUCE_ALARM_SIGNATURE = (
    "inline void mode_reduce_power_for_water_alarm_by_volts(const String& alarmMessage, float reduceVolts)"
)
REDUCE_VOLTS_SIGNATURE = "inline float reduce_power_by_volts(float power, float volts)"

HARNESS_TEMPLATE = r'''
#include <iostream>
#include <string>

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}
  const std::string& value() const { return value_; }

 private:
  std::string value_;
};

enum { ALARM_MSG = 0 };

#define PWR_FACTOR 1
#define ALARM_WATER_TEMP 60.0f
// [T14 п.1] Порог WORK↔SLEEP - реальное числовое значение не предмет этого
// теста (его пинит tools/smoke_power_floor_clamp.py), здесь важно только, что
// база берётся из target_power_volt/current_power_volt, а не наоборот.
inline float power_work_mode_threshold() { return 40.0f; }

struct DSSensor {
  float avgTemp = 0.0f;
};

static DSSensor WaterSensor;
static float target_power_volt = 0.0f;
static float current_power_volt = 0.0f;

static int buzzerCalls = 0;
// Не static: единственный вызов лежит во вклеенном коде ниже.
void set_buzzer(bool) { buzzerCalls++; }

static int sendMsgCalls = 0;
void SendMsg(const String&, int) { sendMsgCalls++; }

static int setPowerCalls = 0;
static float lastSetPowerArg = -999.0f;
void set_current_power(float volt) { setPowerCalls++; lastSetPowerArg = volt; }

@REDUCE_VOLTS_BODY@

@BASE_BODY@

@REDUCE_ALARM_BODY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  WaterSensor.avgTemp = 0.0f;
  target_power_volt = 0.0f;
  current_power_volt = 0.0f;
  buzzerCalls = 0;
  sendMsgCalls = 0;
  setPowerCalls = 0;
  lastSetPowerArg = -999.0f;
}

// Разгон (SPEED): уставки ещё нет, target_power_volt == 0 - база обязана
// браться из current_power_volt (реальный нагрев), а не проваливаться в 0.
static void test_speed_mode_uses_current_power_as_base() {
  reset_fixture();
  target_power_volt = 0.0f;
  current_power_volt = 210.0f;
  check(mode_water_alarm_power_base() == 210.0f,
        "РЕГРЕСС: в разгоне (target_power_volt == 0) база обязана быть current_power_volt");

  WaterSensor.avgTemp = 90.0f;  // >= ALARM_WATER_TEMP
  mode_reduce_power_for_water_alarm_by_volts(String("предупреждение"), 5.0f);
  check(setPowerCalls == 1, "снижение при аварии по воде обязано вызвать set_current_power ровно один раз");
  check(lastSetPowerArg == reduce_power_by_volts(210.0f, 5.0f),
        "РЕГРЕСС: в разгоне снижение обязано идти от current_power_volt (210), а не от target_power_volt (0)");
}

// Рабочий режим (WORK): уставка уже есть - база обязана оставаться
// target_power_volt, current_power_volt (телеметрия) в расчёт не идёт.
static void test_work_mode_uses_target_power_as_base() {
  reset_fixture();
  target_power_volt = 150.0f;
  current_power_volt = 90.0f;
  check(mode_water_alarm_power_base() == 150.0f,
        "в рабочем режиме (target_power_volt > 0) база обязана быть target_power_volt");

  WaterSensor.avgTemp = 90.0f;  // >= ALARM_WATER_TEMP
  mode_reduce_power_for_water_alarm_by_volts(String("предупреждение"), 5.0f);
  check(lastSetPowerArg == reduce_power_by_volts(150.0f, 5.0f),
        "в рабочем режиме снижение обязано идти от target_power_volt (150), а не от current_power_volt (90)");
}

int main() {
  test_speed_mode_uses_current_power_as_base();
  test_work_mode_uses_target_power_as_base();
  if (failures != 0) return 1;
  std::cout << "mode_water_alarm_power_base behaviour checks passed\n";
  return 0;
}
'''


ALARM_CALL_TOKEN = "mode_reduce_power_for_water_alarm_by_volts("


def extract_call_statement(source: str, token: str) -> str:
    """Вырезает вызов-выражение целиком (до закрывающей ";" на уровне скобок 0) -
    без этого простой text.find(token) не различал бы "аргумент содержит
    подстроку" от "подстрока лежит в соседнем вызове"."""
    start = source.index(token)
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                end = source.index(";", index)
                return source[start:end + 1]
    raise ValueError(f"call statement not closed: {token}")


def build_harness(mode_common_source: str, runtime_source: str) -> str:
    base_body = extract_function_body(mode_common_source, BASE_SIGNATURE)
    reduce_alarm_body = extract_function_body(mode_common_source, REDUCE_ALARM_SIGNATURE)
    reduce_volts_body = extract_function_body(runtime_source, REDUCE_VOLTS_SIGNATURE)
    harness = HARNESS_TEMPLATE.replace(
        "@REDUCE_VOLTS_BODY@", REDUCE_VOLTS_SIGNATURE + " {" + reduce_volts_body + "}"
    )
    harness = harness.replace("@BASE_BODY@", BASE_SIGNATURE + " {" + base_body + "}")
    harness = harness.replace(
        "@REDUCE_ALARM_BODY@", REDUCE_ALARM_SIGNATURE + " {" + reduce_alarm_body + "}"
    )
    return harness


def compile_and_run(harness: str, label: str) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-water-alarm-power-base-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "mode_water_alarm_power_base_test.cpp"
        binary = temp / "mode_water_alarm_power_base_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-DSAMOVAR_USE_POWER", str(source), "-o", str(binary),
            ],
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


WATER_PRE_ALARM_ANCHOR = 'SendMsg(("Критическая температура воды!"), WARNING_MSG);'


def extract_sem_water_block(alarm_source: str) -> str:
    """Вырезает SEM-ветку блока критической температуры воды: от
    `#ifdef SAMOVAR_USE_SEM_AVR` до её `#else` (обе директивы ищутся после
    WATER_PRE_ALARM_ANCHOR, чтобы не задеть другие SEM-ветки alarm.h -
    захлёб реагирует на воду отдельным блоком выше по файлу)."""
    anchor = alarm_source.index(WATER_PRE_ALARM_ANCHOR)
    sem_start = alarm_source.index("#ifdef SAMOVAR_USE_SEM_AVR", anchor)
    else_idx = alarm_source.index("#else", sem_start)
    return alarm_source[sem_start:else_idx]


def check_sem_water_block_uses_base(alarm_source: str) -> None:
    """[П2, предупреждение 2 ревью] SEM-ветка критической температуры воды
    обязана считать и сообщение, и клэмп от mode_water_alarm_power_base(), а
    не от голого target_power_volt - иначе в разгоне (SPEED,
    target_power_volt == 0) снижение проваливается в power_work_mode_threshold()
    одним скачком с реального максимума вместо симметричного (не-SEM ветке)
    поведения."""
    block = extract_sem_water_block(alarm_source)
    if "target_power_volt" in block:
        raise AssertionError(
            "РЕГРЕСС: SEM-ветка критической температуры воды снова читает голый "
            f"target_power_volt напрямую:\n{block}"
        )
    base_calls = block.count("mode_water_alarm_power_base()")
    if base_calls < 3:
        raise AssertionError(
            "SEM-ветка критической температуры воды: mode_water_alarm_power_base() "
            f"встречается {base_calls} раз(а), ожидалось минимум 3 (сообщение + оба "
            f"аргумента клэмпа в set_current_power):\n{block}"
        )

    # Самопроверка от тавтологии: реконструируем ДО-фикс текст (mode_water_alarm_power_base()
    # обратно в target_power_volt) и убеждаемся, что он проваливает именно эту проверку -
    # иначе проверка выше могла бы молча ничего не ловить.
    pre_fix_block = block.replace("mode_water_alarm_power_base()", "target_power_volt")
    if pre_fix_block == block:
        raise AssertionError("не удалось смоделировать до-фикс текст SEM-ветки для самопроверки")
    if "target_power_volt" not in pre_fix_block:
        raise AssertionError("самопроверка сломана: реконструированный старый текст не содержит target_power_volt")


def check_alarm_message_uses_base(alarm_source: str) -> None:
    """[П2, предупреждение 1 ревью] Текст сообщения об аварии по воде обязан
    строиться из mode_water_alarm_power_base(), а не из голого
    target_power_volt - иначе в разгоне (SPEED, target_power_volt == 0)
    пользователь видит "снижаем с 0" вместо реального напряжения нагрева."""
    call_statement = extract_call_statement(alarm_source, ALARM_CALL_TOKEN)
    if "(String)target_power_volt" in call_statement:
        raise AssertionError(
            "РЕГРЕСС: alarm.h снова строит сообщение из голого target_power_volt "
            f"(в разгоне это 0):\n{call_statement}"
        )
    if "(String)mode_water_alarm_power_base()" not in call_statement:
        raise AssertionError(
            "alarm.h: не найден mode_water_alarm_power_base() в аргументе сообщения "
            f"(проверка стала бы тавтологией без этого):\n{call_statement}"
        )

    # Мутация "на месте": имитируем старый (до-фикса) текст и убеждаемся, что
    # эта же проверка его действительно ловит - иначе первый assert выше не
    # содержателен, а просто случайно не срабатывает.
    pre_fix_statement = call_statement.replace(
        "(String)mode_water_alarm_power_base()", "(String)target_power_volt"
    )
    if pre_fix_statement == call_statement:
        raise AssertionError("не удалось смоделировать до-фикс текст вызова для самопроверки")
    if "(String)target_power_volt" not in pre_fix_statement:
        raise AssertionError("самопроверка мутации сломана: старый текст не содержит target_power_volt")


def main() -> int:
    mode_common_source = (ROOT / "mode_common.h").read_text(encoding="utf-8")
    runtime_source = (ROOT / "runtime_helpers.h").read_text(encoding="utf-8")
    alarm_source = (ROOT / "alarm.h").read_text(encoding="utf-8")

    try:
        check_alarm_message_uses_base(alarm_source)
    except (ValueError, AssertionError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("alarm.h water-alarm message text check passed (uses mode_water_alarm_power_base())")

    try:
        check_sem_water_block_uses_base(alarm_source)
    except (ValueError, AssertionError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("alarm.h SEM water-alarm block check passed (uses mode_water_alarm_power_base() 3x, no bare target_power_volt)")

    try:
        harness = build_harness(mode_common_source, runtime_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rc, _, _ = compile_and_run(harness, "mode_water_alarm_power_base")
    if rc != 0:
        return rc

    # --- Проверка содержательности: мутация возвращает старое (сломанное)
    # поведение - база снова всегда target_power_volt. Мутация обязана
    # провалить харнесс на содержательном assert-е (не на компиляции).
    mutated_source = mode_common_source.replace(
        "inline float mode_water_alarm_power_base() {\n"
        "  return target_power_volt > 0 ? target_power_volt : current_power_volt;\n"
        "}",
        "inline float mode_water_alarm_power_base() {\n"
        "  return target_power_volt;\n"
        "}",
        1,
    )
    if mutated_source == mode_common_source:
        print("FAIL: mutation anchor missing in mode_water_alarm_power_base", file=sys.stderr)
        return 1
    mutated_harness = build_harness(mutated_source, runtime_source)
    mutation_rc, mutation_stdout, mutation_stderr = compile_and_run(
        mutated_harness, "mutation mode_water_alarm_power_base"
    )
    if mutation_rc == 0:
        print("FAIL: mutation (base always target_power_volt) survived", file=sys.stderr)
        return 1
    print("mutation failure text:")
    print(mutation_stdout + mutation_stderr)

    print("mode_water_alarm_power_base mutation check: FAIL as expected (mutation killed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
