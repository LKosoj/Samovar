#!/usr/bin/env python3
"""[T13] Аварийный останов дозирующего насоса по I2C - подтверждение и латч.

Проблема (SOLUTIONS_2026-08-24.md, п.14, "Аварийный останов может не остановить
дозирующий насос по I2C"): раньше perform_emergency_stop() (alarm.h) звал
set_stepper_target(0, 0, 0) "вслепую" - с отброшенным возвратом. Если I2C-шина
была занята (например, конфигурационный лок держит refresh_i2c_stepper_cache()
из SysTicker) или плата не подтвердила останов, привод мог продолжать
работать, и никто об этом не узнавал.

Решение:
  - stop_i2c_pump_confirmed() (I2CStepper.h) зовёт set_stepper_target(0, 0, 0,
    requireI2c) c requireI2c = (use_I2C_dev == I2CSTEPPER_PUMP_ADDR): признак
    "насос на этом аппарате есть" берём из use_I2C_dev - boot-стабильного
    флага, который detect_i2c_steppers() выставляет один раз при старте и
    больше не меняет. Если насос обнаружен - останов обязан пройти через шину
    и вернуть реальное подтверждение (никакого "тихого" фолбэка на локальный
    степпер), даже если секундный опрос шины i2cStepperPump.present только что
    сорвался из-за дребезга реле/просадки питания в момент самой аварии; если
    насоса на аппарате нет вовсе - действует обычный локальный останов, как и
    раньше.
  - attempt_i2c_pump_emergency_stop() (alarm.h) проверяет результат: отказ
    взводит 1-байтовый латч i2c_pump_stop_unconfirmed и один раз пишет код
    отказа в журнал (WriteConsoleLog); успех латч снимает.
  - retry_i2c_pump_stop_if_unconfirmed() вызывается из секундного тикера
    (Samovar.ino), сразу после refresh_i2c_stepper_cache(i2cStepperPump), и
    повторяет попытку, пока латч взведён.

(а) Текстовые проверки: perform_emergency_stop зовёт attempt_i2c_pump_emergency_stop
    (не "слепой" set_stepper_target) на прежнем месте; латч и прототипы на
    месте; секундный тикер зовёт retry_i2c_pump_stop_if_unconfirmed() ровно
    один раз, сразу после обновления кэша обоих I2C-степперов.

(б) Поведенческий харнесс на РЕАЛЬНЫХ телах attempt_i2c_pump_emergency_stop()
    и retry_i2c_pump_stop_if_unconfirmed() (extract_function_body) с
    подставным stop_i2c_pump_confirmed(): проверяет весь требуемый инвариант -
    отказ взводит латч и логирует один раз, каждый следующий такт повторяет
    попытку без повторного лога, успех снимает латч и останавливает повторы.

(в) Мутационная проверка на самом харнессе: снятие проверки результата
    останова или снятие повтора в тикере обязаны валить харнесс на assert'е
    (не на ошибке компиляции).

(г) Мутационная проверка на отдельном харнессе для РЕАЛЬНОГО тела
    stop_i2c_pump_confirmed() (I2CStepper.h) с подставным set_stepper_target():
    ловит откат блокера ревью - возврат к requireI2c = i2cStepperPump.present
    (секундный опросный кэш) вместо requireI2c = (use_I2C_dev ==
    I2CSTEPPER_PUMP_ADDR) (boot-стабильный флаг). Сценарий "насос на аппарате
    есть, но секундный опрос шины только что сорвался" обязан требовать
    подтверждения по I2C (requireI2c == true), а не тихо уходить в локальный
    запасной путь по выводам платы, к насосу отношения не имеющий.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


# ---- (а) Текстовые проверки ----

alarm_text = read_text("alarm.h")
api_text = read_text("samovar_api.h")
i2c_text = read_text("I2CStepper.h")
ino_text = read_text("Samovar.ino")

if alarm_text:
    try:
        emergency_body = extract_function_body(alarm_text, "inline void perform_emergency_stop")
    except ValueError as exc:
        errors.append(str(exc))
        emergency_body = ""

    if emergency_body:
        require_ordered_tokens(
            "perform_emergency_stop stops the I2C pump via the confirmed attempt, "
            "in the same place as before (after stopService, before mixer relay)",
            emergency_body,
            [
                "stopService();",
                "attempt_i2c_pump_emergency_stop();",
                "digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);",
            ],
            errors,
        )
        if "set_stepper_target(0, 0, 0);" in emergency_body:
            errors.append(
                "perform_emergency_stop must not call set_stepper_target(0,0,0) blindly - "
                "use attempt_i2c_pump_emergency_stop() so the confirmation is checked"
            )

    if "static volatile bool i2c_pump_stop_unconfirmed = false;" not in alarm_text:
        errors.append(
            "alarm.h missing the 1-byte volatile i2c_pump_stop_unconfirmed latch "
            "(written from loop() and from the SysTicker task - needs volatile)"
        )

    try:
        attempt_body = extract_function_body(alarm_text, "inline void attempt_i2c_pump_emergency_stop")
    except ValueError as exc:
        errors.append(str(exc))
        attempt_body = ""
    if attempt_body:
        require_ordered_tokens(
            "attempt_i2c_pump_emergency_stop checks the confirmation before touching the latch",
            attempt_body,
            [
                "if (stop_i2c_pump_confirmed()) {",
                "i2c_pump_stop_unconfirmed = false;",
                "return;",
                "}",
                "WriteConsoleLog(",
                "i2c_pump_stop_unconfirmed = true;",
            ],
            errors,
        )

    try:
        retry_body = extract_function_body(alarm_text, "inline void retry_i2c_pump_stop_if_unconfirmed")
    except ValueError as exc:
        errors.append(str(exc))
        retry_body = ""
    if retry_body and "attempt_i2c_pump_emergency_stop();" not in retry_body:
        errors.append("retry_i2c_pump_stop_if_unconfirmed must retry via attempt_i2c_pump_emergency_stop()")

if api_text:
    for token in [
        "inline bool stop_i2c_pump_confirmed();",
        "inline void retry_i2c_pump_stop_if_unconfirmed();",
    ]:
        if token not in api_text:
            errors.append(f"samovar_api.h missing prototype: {token}")

if i2c_text:
    try:
        stop_confirmed_body = extract_function_body(i2c_text, "inline bool stop_i2c_pump_confirmed")
    except ValueError as exc:
        errors.append(str(exc))
        stop_confirmed_body = ""
    if stop_confirmed_body and "use_I2C_dev == I2CSTEPPER_PUMP_ADDR" not in stop_confirmed_body:
        errors.append(
            "stop_i2c_pump_confirmed must gate requireI2c on the boot-stable use_I2C_dev flag "
            "(use_I2C_dev == I2CSTEPPER_PUMP_ADDR), not on the second-old i2cStepperPump.present "
            "poll cache - a single failed register read during the emergency itself would silently "
            "fall back to the local stepper path and return true without ever confirming the pump stopped"
        )

if ino_text:
    anchor = "refresh_i2c_stepper_cache(i2cStepperPump);"
    anchor_index = ino_text.find(anchor)
    if anchor_index < 0:
        errors.append("Samovar.ino missing refresh_i2c_stepper_cache(i2cStepperPump) call")
    else:
        tail = ino_text[anchor_index + len(anchor):anchor_index + len(anchor) + 200]
        if "retry_i2c_pump_stop_if_unconfirmed();" not in tail:
            errors.append(
                "Samovar.ino must call retry_i2c_pump_stop_if_unconfirmed() right after "
                "refresh_i2c_stepper_cache(i2cStepperPump)"
            )
    if ino_text.count("retry_i2c_pump_stop_if_unconfirmed();") != 1:
        errors.append("retry_i2c_pump_stop_if_unconfirmed() must be called exactly once from the ticker")

if errors:
    print("I2C pump stop latch smoke check FAILED (text checks):", file=sys.stderr)
    for err in errors:
        print(f"  - {err}", file=sys.stderr)
    sys.exit(1)


# ---- (б) Поведенческий харнесс на реальных телах ----

HARNESS_TEMPLATE = r'''
#include <iostream>
#include <string>

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}

 private:
  std::string value_;
};

#define F(x) (x)

// ---- Моки ----
static bool i2c_pump_stop_unconfirmed = false;

static bool mockStopConfirmedResult = true;
static int stopAttemptCalls = 0;
static bool stop_i2c_pump_confirmed() {
  stopAttemptCalls++;
  return mockStopConfirmedResult;
}

// Не static: под мутацией "результат не проверяется" единственный вызов
// WriteConsoleLog в коде под тестом пропадает, а static-функция без вызовов
// валит сборку на -Wunused-function ещё до runtime - это неинформативная
// (нечестная) поимка мутации. Реальная WriteConsoleLog (Samovar.ino) тоже не
// static, так что это не искажает семантику мока.
static int writeConsoleLogCalls = 0;
void WriteConsoleLog(String) { writeConsoleLogCalls++; }

// ---- Реальный код под тестом (extract_function_body) ----
@ATTEMPT_BODY@
@RETRY_BODY@

// ---- Тесты ----
static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  i2c_pump_stop_unconfirmed = false;
  mockStopConfirmedResult = true;
  stopAttemptCalls = 0;
  writeConsoleLogCalls = 0;
}

// Позитивный контроль: первая попытка сразу успешна - латч не взводится, лога
// нет. Доказывает, что харнесс не блокирует нормальный путь сам по себе.
static void test_first_attempt_success_no_latch() {
  reset_fixture();
  attempt_i2c_pump_emergency_stop();
  check(!i2c_pump_stop_unconfirmed, "успешный останов не должен взводить латч");
  check(writeConsoleLogCalls == 0, "успешный останов не должен писать код отказа");
  check(stopAttemptCalls == 1, "должна быть ровно одна попытка");
}

// (а) Отказ останова взводит латч и пишет код отказа один раз.
static void test_failure_sets_latch_and_logs_once() {
  reset_fixture();
  mockStopConfirmedResult = false;
  attempt_i2c_pump_emergency_stop();
  check(i2c_pump_stop_unconfirmed, "неподтверждённый останов должен взвести латч");
  check(writeConsoleLogCalls == 1, "отказ должен один раз записать код отказа в журнал");
  check(stopAttemptCalls == 1, "должна быть ровно одна попытка на этом шаге");
}

// (б) В следующем секундном такте попытка повторяется, пока плата не
// подтвердит; повторный отказ НЕ пишет код отказа снова (латч уже взведён).
static void test_retry_repeats_while_unconfirmed_without_spamming_log() {
  reset_fixture();
  mockStopConfirmedResult = false;
  attempt_i2c_pump_emergency_stop();  // первая попытка - из perform_emergency_stop()
  check(stopAttemptCalls == 1 && writeConsoleLogCalls == 1, "предусловие: латч взведён после первой неудачи");

  retry_i2c_pump_stop_if_unconfirmed();  // тик секундного тикера №1
  check(stopAttemptCalls == 2, "тик секундного тикера должен повторить попытку останова");
  check(writeConsoleLogCalls == 1, "повторная неудача не должна писать код отказа снова");
  check(i2c_pump_stop_unconfirmed, "латч должен остаться взведён, пока плата не подтвердит");

  retry_i2c_pump_stop_if_unconfirmed();  // тик секундного тикера №2
  check(stopAttemptCalls == 3, "каждый такт должен повторять попытку, пока латч взведён");
  check(writeConsoleLogCalls == 1, "код отказа по-прежнему должен быть записан только один раз");
}

// (в) Успех снимает латч, и дальнейшие такты больше не дёргают останов.
static void test_success_clears_latch_and_stops_retrying() {
  reset_fixture();
  mockStopConfirmedResult = false;
  attempt_i2c_pump_emergency_stop();
  retry_i2c_pump_stop_if_unconfirmed();
  check(i2c_pump_stop_unconfirmed, "предусловие: латч взведён перед подтверждением");

  mockStopConfirmedResult = true;  // плата наконец подтвердила нулевую скорость
  retry_i2c_pump_stop_if_unconfirmed();
  check(!i2c_pump_stop_unconfirmed, "подтверждённый останов должен снять латч");
  const int callsAfterConfirm = stopAttemptCalls;

  retry_i2c_pump_stop_if_unconfirmed();  // латч уже снят - повтора быть не должно
  check(stopAttemptCalls == callsAfterConfirm,
        "после снятия латча повторные такты не должны снова дёргать останов");
}

int main() {
  test_first_attempt_success_no_latch();
  test_failure_sets_latch_and_logs_once();
  test_retry_repeats_while_unconfirmed_without_spamming_log();
  test_success_clears_latch_and_stops_retrying();

  if (failures != 0) return 1;
  std::cout << "I2C pump emergency-stop confirmation latch behaviour checks passed\n";
  return 0;
}
'''


HARNESS2_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

// ---- Моки ----
static uint8_t use_I2C_dev = 0;
#define I2CSTEPPER_PUMP_ADDR 2

struct I2CStepperDevice {
  bool present;
};
static I2CStepperDevice i2cStepperPump = {};

static bool mockSetStepperTargetResult = true;
static bool lastRequireI2c = false;
static int setStepperTargetCalls = 0;
static bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target, bool requireI2c) {
  (void)spd;
  (void)direction;
  (void)target;
  setStepperTargetCalls++;
  lastRequireI2c = requireI2c;
  return mockSetStepperTargetResult;
}

// ---- Реальный код под тестом (extract_function_body) ----
static bool stop_i2c_pump_confirmed() {
@STOP_CONFIRMED_BODY@
}

// ---- Тесты ----
static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  use_I2C_dev = 0;
  i2cStepperPump.present = true;
  mockSetStepperTargetResult = true;
  lastRequireI2c = false;
  setStepperTargetCalls = 0;
}

// [Замечание 1] Насос на аппарате есть (use_I2C_dev равен I2CSTEPPER_PUMP_ADDR), но
// секундный опрос шины только что сорвался (i2cStepperPump.present == false -
// типичная картина при дребезге реле/просадке питания в момент самой аварии).
// Останов обязан требовать подтверждения по I2C (requireI2c == true), а НЕ
// тихо уходить в локальный запасной путь по выводам платы, к насосу
// отношения не имеющий.
static void test_pump_present_at_boot_but_poll_failed_requires_i2c_confirmation() {
  reset_fixture();
  use_I2C_dev = I2CSTEPPER_PUMP_ADDR;
  i2cStepperPump.present = false;
  stop_i2c_pump_confirmed();
  check(setStepperTargetCalls == 1, "stop_i2c_pump_confirmed должен вызвать set_stepper_target ровно один раз");
  check(lastRequireI2c,
        "насос обнаружен при старте - останов обязан требовать подтверждения по I2C, "
        "даже если секундный опрос шины только что сорвался");
}

// Контроль: то же самое, но опрос шины успешен - поведение не меняется.
static void test_pump_present_at_boot_and_poll_ok_requires_i2c_confirmation() {
  reset_fixture();
  use_I2C_dev = I2CSTEPPER_PUMP_ADDR;
  i2cStepperPump.present = true;
  stop_i2c_pump_confirmed();
  check(lastRequireI2c, "насос обнаружен при старте - останов обязан требовать подтверждения по I2C");
}

// Насоса на аппарате нет вовсе (use_I2C_dev != I2CSTEPPER_PUMP_ADDR) - прежний
// локальный запасной путь должен остаться доступным независимо от опросного кэша.
static void test_no_pump_on_this_rig_keeps_local_fallback() {
  reset_fixture();
  use_I2C_dev = 0;
  i2cStepperPump.present = false;
  stop_i2c_pump_confirmed();
  check(!lastRequireI2c, "насоса на этом аппарате нет - requireI2c должен быть false (локальный запасной путь)");
}

int main() {
  test_pump_present_at_boot_but_poll_failed_requires_i2c_confirmation();
  test_pump_present_at_boot_and_poll_ok_requires_i2c_confirmation();
  test_no_pump_on_this_rig_keeps_local_fallback();

  if (failures != 0) return 1;
  std::cout << "stop_i2c_pump_confirmed boot-stable presence flag checks passed\n";
  return 0;
}
'''


def build_stop_confirmed_harness() -> str:
    signature = "inline bool stop_i2c_pump_confirmed"
    body = extract_function_body(i2c_text, signature)
    return HARNESS2_TEMPLATE.replace("@STOP_CONFIRMED_BODY@", body)


def build_harness() -> str:
    attempt_signature = "inline void attempt_i2c_pump_emergency_stop"
    retry_signature = "inline void retry_i2c_pump_stop_if_unconfirmed"
    attempt_body = extract_function_body(alarm_text, attempt_signature)
    retry_body = extract_function_body(alarm_text, retry_signature)

    harness = HARNESS_TEMPLATE
    harness = harness.replace(
        "@ATTEMPT_BODY@",
        "static void attempt_i2c_pump_emergency_stop() {" + attempt_body + "}",
    )
    harness = harness.replace(
        "@RETRY_BODY@",
        "static void retry_i2c_pump_stop_if_unconfirmed() {" + retry_body + "}",
    )
    return harness


def compile_and_run(harness: str, show_output: bool = True) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-pump-stop-latch-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "i2c_pump_stop_latch_test.cpp"
        binary = temp / "i2c_pump_stop_latch_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write("compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if show_output:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if compile_and_run(harness) != 0:
        return 1

    # ---- (в) Мутационная проверка: харнесс должен ловить обе регрессии ----
    mutants = [
        (
            # [T13] Возврат к старому багу: результат stop_i2c_pump_confirmed()
            # вызывается, но игнорируется, латч не взводится никогда.
            "attempt_ignores_confirmation_result",
            "if (stop_i2c_pump_confirmed()) {\n"
            "    i2c_pump_stop_unconfirmed = false;\n"
            "    return;\n"
            "  }\n"
            '  if (!i2c_pump_stop_unconfirmed) WriteConsoleLog(F("i2c_pump_stop_unconfirmed"));\n'
            "  i2c_pump_stop_unconfirmed = true;\n",
            "stop_i2c_pump_confirmed();\n"
            "  i2c_pump_stop_unconfirmed = false;\n",
        ),
        (
            # [T13] Секундный тикер перестаёт повторять попытку останова.
            "retry_removed_from_ticker",
            "if (i2c_pump_stop_unconfirmed) attempt_i2c_pump_emergency_stop();\n",
            "(void)i2c_pump_stop_unconfirmed;\n",
        ),
    ]
    for name, original, replacement in mutants:
        mutant = harness.replace(original, replacement, 1)
        if mutant == harness:
            print(f"FAIL: не удалось построить мутацию {name}", file=sys.stderr)
            return 1
        if compile_and_run(mutant, show_output=False) == 0:
            print(f"FAIL: мутация {name} пережила тест", file=sys.stderr)
            return 1

    # ---- (г) Реальное тело stop_i2c_pump_confirmed() + мутация блокера ----
    try:
        harness2 = build_stop_confirmed_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if compile_and_run(harness2) != 0:
        return 1

    mutant2 = harness2.replace(
        "use_I2C_dev == I2CSTEPPER_PUMP_ADDR",
        "i2cStepperPump.present",
        1,
    )
    if mutant2 == harness2:
        print("FAIL: не удалось построить мутацию stop_confirmed_reverts_to_poll_cache", file=sys.stderr)
        return 1
    if compile_and_run(mutant2, show_output=False) == 0:
        print(
            "FAIL: мутация stop_confirmed_reverts_to_poll_cache пережила тест - "
            "requireI2c снова читает секундный опросный кэш вместо boot-стабильного use_I2C_dev",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
