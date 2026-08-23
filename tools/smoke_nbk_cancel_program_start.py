#!/usr/bin/env python3
"""Регресс-проверка [П2] nbk.h: свёртка шести отказов старта/перехода строки НБК
в общий хелпер nbk_cancel_program_start.

Раньше run_nbk_program() шесть раз повторял один и тот же блок отказа:
SendMsg(..., ALARM_MSG) -> ProgramNum = 0 -> startval = SAMOVAR_STARTVAL_IDLE ->
SamovarStatusInt = SAMOVAR_STATUS_IDLE -> [опциональный хвост закрытия лога] ->
return. beer.h для того же паттерна уже пользуется mode_cancel_process_start
(mode_common.h) - nbk.h теперь оборачивает его в nbk_cancel_program_start(message),
которая дополнительно сбрасывает ProgramNum (единственное, чего нет в
mode_cancel_process_start).

Часть 1 (компилируемая): вытаскивает РЕАЛЬНЫЕ тела mode_cancel_process_start
(mode_common.h) и nbk_cancel_program_start (nbk.h), собирает харнесс с
минимальным String и моком SendMsg, проверяет поведение на двух сценариях с
разными стартовыми значениями и разными сообщениями (правило AGENTS.md: кейс
на одно значение проходит от хардкода).

Часть 2 (структурная, без компиляции): для каждой из шести площадок в
run_nbk_program() проверяет точный текст сообщения, переданного в
nbk_cancel_program_start, и правильный хвост после хелпера (закрытие лога или
его отсутствие).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import (
    extract_braced_block_after,
    extract_function_body,
    strip_cpp_comments,
)

ROOT = Path(__file__).resolve().parents[1]

FUNCTIONS = [
    "inline void mode_cancel_process_start(const String& message)",
    "inline void nbk_cancel_program_start(const String& message)",
]

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

enum MESSAGE_TYPE {ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, NONE_MSG = 100};

constexpr int16_t SAMOVAR_STATUS_IDLE = 0;
constexpr int16_t SAMOVAR_STARTVAL_IDLE = 0;

// Минимальный совместимый с Arduino String: только то, что реально нужно
// извлечённым телам (конструирование из const char*, чтение как std::string
// для проверок в тесте).
class String {
public:
  String() : data_() {}
  String(const char* s) : data_(s ? s : "") {}
  const std::string& str() const { return data_; }
private:
  std::string data_;
};

// --- Глобальное состояние, которым управляют сценарии ---
volatile int16_t SamovarStatusInt = SAMOVAR_STATUS_IDLE;
volatile int16_t startval = SAMOVAR_STARTVAL_IDLE;
volatile uint8_t ProgramNum = 0;

// --- Мок истинно внешней зависимости (не-static) ---
static int sendMsgCalls = 0;
static std::string lastSendMsgText;
static int lastSendMsgType = -1;
void SendMsg(const String& msg, int type) {
  sendMsgCalls++;
  lastSendMsgText = msg.str();
  lastSendMsgType = type;
}

@FUNCTIONS@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture(int16_t status, int16_t start, uint8_t programNum) {
  SamovarStatusInt = status;
  startval = start;
  ProgramNum = programNum;
  sendMsgCalls = 0;
  lastSendMsgText.clear();
  lastSendMsgType = -1;
}

int main() {
  // Сценарий 1: произвольные стартовые значения, отличные от IDLE/0.
  reset_fixture(4000, 4000, 3);
  nbk_cancel_program_start(String("Сообщение A"));
  check(sendMsgCalls == 1, "1: должно быть отправлено ровно одно сообщение");
  check(lastSendMsgText == "Сообщение A", "1: текст сообщения должен совпасть");
  check(lastSendMsgType == ALARM_MSG, "1: тип сообщения должен быть ALARM_MSG");
  check(SamovarStatusInt == SAMOVAR_STATUS_IDLE, "1: SamovarStatusInt должен быть сброшен в IDLE");
  check(startval == SAMOVAR_STARTVAL_IDLE, "1: startval должен быть сброшен в IDLE");
  check(ProgramNum == 0, "1: ProgramNum должен быть сброшен в 0");

  // Сценарий 2: другие стартовые значения и другое сообщение - кейс на одном
  // значении не годится (можно было бы захардкодить одно число).
  reset_fixture(4001, 4001, 7);
  nbk_cancel_program_start(String("Другое сообщение B"));
  check(sendMsgCalls == 1, "2: должно быть отправлено ровно одно сообщение");
  check(lastSendMsgText == "Другое сообщение B", "2: текст сообщения должен совпасть");
  check(lastSendMsgType == ALARM_MSG, "2: тип сообщения должен быть ALARM_MSG");
  check(SamovarStatusInt == SAMOVAR_STATUS_IDLE, "2: SamovarStatusInt должен быть сброшен в IDLE");
  check(startval == SAMOVAR_STARTVAL_IDLE, "2: startval должен быть сброшен в IDLE");
  check(ProgramNum == 0, "2: ProgramNum должен быть сброшен в 0");

  if (failures != 0) return 1;
  std::cout << "nbk cancel program start behaviour checks passed\n";
  return 0;
}
'''


def build_harness(mode_common_source: str, nbk_source: str) -> str:
    mode_common_code = strip_cpp_comments(mode_common_source)
    nbk_code = strip_cpp_comments(nbk_source)

    bodies = []
    body = extract_function_body(mode_common_code, FUNCTIONS[0])
    bodies.append(f"{FUNCTIONS[0]} {{{body}}}")
    body = extract_function_body(nbk_code, FUNCTIONS[1])
    bodies.append(f"{FUNCTIONS[1]} {{{body}}}")

    harness = HARNESS_TEMPLATE.replace("@FUNCTIONS@", "\n\n".join(bodies))
    return harness


def run_behaviour_part() -> int:
    mode_common_source = (ROOT / "mode_common.h").read_text(encoding="utf-8")
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8", errors="ignore")

    try:
        harness = build_harness(mode_common_source, nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-nbk-cancel-program-start-") as temp_dir:
        temp = Path(temp_dir)
        cpp_source = temp / "nbk_cancel_program_start_test.cpp"
        binary = temp / "nbk_cancel_program_start_test"
        cpp_source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-I", str(ROOT), str(cpp_source), "-o", str(binary),
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


def check_site(
    errors: list[str],
    run_body: str,
    label: str,
    anchor: str,
    message: str,
    expect_close_log: bool,
    expect_warn_log_close_failed: bool,
    offset: int = 0,
    call_contains: list[str] | None = None,
) -> None:
    try:
        block, _ = extract_braced_block_after(run_body, anchor, offset)
    except ValueError as exc:
        errors.append(f"[{label}] {exc}")
        return

    if call_contains is not None:
        # [П70в] сообщение C собирается из nbkSessionConfigError, а не один
        # литерал - проверяем ключевые фрагменты вместо точного вызова.
        for fragment in call_contains:
            if fragment not in block:
                errors.append(f"[{label}] missing fragment in nbk_cancel_program_start call: {fragment}")
    else:
        call = f'nbk_cancel_program_start("{message}");'
        if call not in block:
            errors.append(f"[{label}] missing exact nbk_cancel_program_start call: {call}")

    if expect_close_log and "nbk_close_data_log();" not in block:
        errors.append(f"[{label}] missing nbk_close_data_log() tail")
    if not expect_close_log and "nbk_close_data_log();" in block:
        errors.append(f"[{label}] must not close the data log")

    if expect_warn_log_close_failed and "mode_warn_log_close_failed();" not in block:
        errors.append(f"[{label}] missing mode_warn_log_close_failed() tail")
    if not expect_warn_log_close_failed and "mode_warn_log_close_failed();" in block:
        errors.append(f"[{label}] must not call mode_warn_log_close_failed()")

    if "return;" not in block:
        errors.append(f"[{label}] block must return after cancelling the start")


def run_structural_part() -> list[str]:
    errors: list[str] = []
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8", errors="ignore")
    nbk_code = strip_cpp_comments(nbk_source)

    try:
        run_body = extract_function_body(nbk_code, "void run_nbk_program")
    except ValueError as exc:
        errors.append(str(exc))
        return errors

    # A: выключение нагрева ещё не завершено - хвоста закрытия лога нет.
    check_site(
        errors, run_body, "A",
        "if (!PowerOn && power_transition_active()) {",
        "Выключение нагрева ещё не завершено. Старт НБК отменён.",
        expect_close_log=False,
        expect_warn_log_close_failed=False,
    )

    # B: [T5] нагрев уже выключен, переход строки запрещён - хвоста нет.
    check_site(
        errors, run_body, "B",
        "if (num > 0 && !PowerOn) {",
        "Нагрев НБК выключен. Переход к строке №\" + String(num + 1) + \" отменён.",
        expect_close_log=False,
        expect_warn_log_close_failed=False,
    )

    # C: некорректный снимок конфигурации НБК - лог закрывается явно.
    # [П70в] сообщение теперь называет конкретное сорвавшееся поле
    # (nbkSessionConfigError), а не общую фразу.
    check_site(
        errors, run_body, "C",
        "if (!nbk_capture_session_config()) {",
        "",
        expect_close_log=True,
        expect_warn_log_close_failed=False,
        call_contains=[
            "nbk_cancel_program_start(",
            '"Запуск НБК отклонён: некорректная настройка - "',
            "String(nbkSessionConfigError)",
        ],
    )

    # D: не удалось создать файл лога - закрывать нечего, хвоста нет.
    check_site(
        errors, run_body, "D",
        "if (!create_data()) {",
        "Ошибка создания файла лога. Старт НБК отменён.",
        expect_close_log=False,
        expect_warn_log_close_failed=False,
    )

    # E: описание MQTT-сессии занято - хвост через mode_warn_log_close_failed
    # (другой текст WARNING при занятости, чем у nbk_close_data_log).
    check_site(
        errors, run_body, "E",
        "if (!copy_mqtt_session_description(sessionDescription, pdMS_TO_TICKS(50))) {",
        "Описание сессии занято. Старт НБК отменён.",
        expect_close_log=False,
        expect_warn_log_close_failed=True,
    )

    # F: нагрев НБК не включён при переходе на Разгон (WType == 'H'). Ищем со
    # смещением от заголовка ветки 'H' - иначе "if (!PowerOn) {" зацепит более
    # раннее вхождение (переход к Работе, около строки 1016).
    h_branch_index = run_body.find("if (program[ProgramNum].WType == 'H') {")
    if h_branch_index < 0:
        errors.append("[F] WType == 'H' branch not found in run_nbk_program")
    else:
        check_site(
            errors, run_body, "F",
            "if (!PowerOn) {",
            "Нагрев НБК не включён. Старт отменён.",
            expect_close_log=True,
            expect_warn_log_close_failed=False,
            offset=h_branch_index,
        )

    return errors


def main() -> int:
    behaviour_code = run_behaviour_part()
    if behaviour_code != 0:
        return behaviour_code

    errors = run_structural_part()
    if errors:
        print("NBK cancel program start smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1

    print("NBK cancel program start structural checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
