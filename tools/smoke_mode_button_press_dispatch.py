#!/usr/bin/env python3
"""Регресс-проверка: диспетчер короткого нажатия кнопки по таблице режимов.

Раньше loop() (Samovar.ino, блок `#ifdef BTN_PIN`, ветка `else if (mainButtonPressed)`)
вручную перечислял четыре почти одинаковые ветки по Samovar_Mode
(DISTILLATION/BK/NBK/BEER): при `!PowerOn` ставил powerOnCommand в очередь и
слал сообщение об отказе, при `PowerOn` звал finish() режима - кроме пива, где
короткое нажатие двигает программу дальше (run_beer_program(ProgramNum + 1)),
а не завершает процесс. Теперь это одна строка `mode_dispatch_button_press()`
в loop(), а режимные различия вынесены в два новых поля ModeOps
(`buttonPressAction`, `startBusyName`) в mode_registry.h.

Тест проверяет:
  a) `mode_button_press_beer()` при включённом питании зовёт именно
     `run_beer_program(ProgramNum + 1)`, а не `beer_finish()` - это
     принципиальное отличие пива от DISTILLATION/BK/NBK;
  b) таблица `mode_registry_table()` несёт правильные buttonPressAction/
     startBusyName для всех четырёх режимов, и имена режимов (startBusyName)
     различны - иначе сообщение об отказе для одного режима могло бы молча
     показывать имя другого;
  c) само тело `mode_dispatch_button_press()`, извлечённое из mode_registry.h
     (а не переписанное в тесте), ведёт себя по контракту в харнессе на g++ с
     мокнутыми зависимостями;
  d) три мутации тела диспетчера (снятие guard'а `!PowerOn`, замена
     `ops->startBusyName` на литерал, снятие guard'а на nullptr
     buttonPressAction) обязаны валить содержательные assert'ы харнесса, а не
     компиляцию.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "mode_registry.h"

DISPATCH_SIGNATURE = "inline void mode_dispatch_button_press()"


def read_registry() -> str:
    return REGISTRY_PATH.read_text(encoding="utf-8")


# --- (a) mode_button_press_beer(): следующая программа, а НЕ beer_finish() ----------------
def check_beer_wrapper(source: str, errors: list[str]) -> None:
    try:
        body = extract_function_body(
            strip_cpp_comments(source), "inline void mode_button_press_beer()"
        )
    except ValueError as exc:
        errors.append(str(exc))
        return
    if "run_beer_program(ProgramNum + 1);" not in body:
        errors.append(
            "mode_button_press_beer() должна звать run_beer_program(ProgramNum + 1)"
        )
    if "beer_finish" in body:
        errors.append(
            "mode_button_press_beer() не должна звать beer_finish() - у пива при "
            "PowerOn короткое нажатие переключает программу, а не завершает процесс"
        )


# --- (b) таблица: buttonPressAction/startBusyName по режимам, имена различны --------------
EXPECTED_BUTTON_FIELDS = {
    "SAMOVAR_DISTILLATION_MODE": ("distiller_finish", '"дистилляции"'),
    "SAMOVAR_BEER_MODE": ("mode_button_press_beer", '"пива"'),
    "SAMOVAR_BK_MODE": ("bk_finish", '"БК"'),
    "SAMOVAR_NBK_MODE": ("nbk_finish", '"НБК"'),
}

# Режимы, которые основную кнопку НЕ обслуживают: оба новых поля обязаны остаться
# nullptr, иначе короткое нажатие начнёт делать то, чего раньше не делало.
MODES_WITHOUT_BUTTON = (
    "SAMOVAR_RECTIFICATION_MODE",
    "SAMOVAR_SUVID_MODE",
    "SAMOVAR_LUA_MODE",
)


def parse_modeops_field_names(source: str) -> list[str]:
    """Ordered member names of struct ModeOps, as declared in mode_registry.h.

    Row fields are matched by NAME (index into this list), not by a fixed
    position/count - struct ModeOps grew from 12 to 16 members (tick/stopProcess/
    buildAvailable/unavailableReason appended after startBusyName), so any
    position pinned to the OLD layout silently reads the wrong field instead of
    failing loudly. Reading by name makes the check self-adjusting.
    """
    match = re.search(r"struct\s+ModeOps\s*\{", source)
    if match is None:
        raise ValueError("mode_registry.h: struct ModeOps not found")
    start = match.end()
    end = source.find("};", start)
    if end < 0:
        raise ValueError("mode_registry.h: struct ModeOps closing '};' not found")
    names = []
    for stmt in source[start:end].split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*$", stmt)
        if not m:
            raise ValueError(f"mode_registry.h: struct ModeOps: cannot parse member from {stmt!r}")
        names.append(m.group(1))
    return names


def check_table_rows(source: str, errors: list[str]) -> None:
    code = strip_cpp_comments(source)
    try:
        field_names = parse_modeops_field_names(code)
    except ValueError as exc:
        errors.append(str(exc))
        return
    if not field_names or field_names[0] != "mode":
        errors.append(f"struct ModeOps: expected first field 'mode', got {field_names[:1]!r}")
        return
    # The row regex below captures everything AFTER the leading `mode` field
    # (already matched separately), so row fields line up with field_names[1:].
    rest_field_names = field_names[1:]
    try:
        button_idx = rest_field_names.index("buttonPressAction")
        busy_idx = rest_field_names.index("startBusyName")
    except ValueError as exc:
        errors.append(f"struct ModeOps: {exc}")
        return

    try:
        table_body = extract_function_body(
            code, "inline const ModeOps* mode_registry_table(size_t& count)"
        )
    except ValueError as exc:
        errors.append(str(exc))
        return
    rows = dict(re.findall(r"\{\s*(SAMOVAR_[A-Z_]+_MODE)\s*,([^{}]*)\}", table_body))
    busy_names: list[str] = []
    for mode, (expected_fn, expected_name) in EXPECTED_BUTTON_FIELDS.items():
        rest = rows.get(mode)
        if rest is None:
            errors.append(f"mode_registry table: row for {mode} not found")
            continue
        fields = [f.strip() for f in rest.split(",")]
        if len(fields) != len(rest_field_names):
            errors.append(
                f"mode_registry table: row for {mode} has {len(fields)} fields, expected "
                f"{len(rest_field_names)} (per struct ModeOps): {rest}"
            )
            continue
        button_fn, busy_name = fields[button_idx], fields[busy_idx]
        if button_fn != expected_fn:
            errors.append(
                f"mode_registry table: {mode} buttonPressAction = {button_fn!r}, "
                f"expected {expected_fn!r}"
            )
        if busy_name != expected_name:
            errors.append(
                f"mode_registry table: {mode} startBusyName = {busy_name!r}, "
                f"expected {expected_name!r}"
            )
        busy_names.append(busy_name)
    if len(set(busy_names)) != len(busy_names):
        errors.append(
            "mode_registry table: startBusyName должны быть РАЗНЫМИ для разных "
            f"режимов, получено: {busy_names}"
        )
    for mode in MODES_WITHOUT_BUTTON:
        rest = rows.get(mode)
        if rest is None:
            errors.append(f"mode_registry table: row for {mode} not found")
            continue
        fields = [f.strip() for f in rest.split(",")]
        if len(fields) != len(rest_field_names):
            errors.append(
                f"mode_registry table: row for {mode} has {len(fields)} fields, expected "
                f"{len(rest_field_names)} (per struct ModeOps): {rest}"
            )
            continue
        if fields[button_idx] != "nullptr" or fields[busy_idx] != "nullptr":
            errors.append(
                f"mode_registry table: {mode} не обслуживает основную кнопку, "
                "buttonPressAction/startBusyName должны быть nullptr, получено "
                f"{[fields[button_idx], fields[busy_idx]]}"
            )


# --- (c)/(d) динамический харнесс для mode_dispatch_button_press() ------------------------
HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

// Мини-String с operator+ для const char* - реальное тело диспетчера строит
// сообщение об отказе через String(...) + ops->startBusyName + "...".
class String {
 public:
  String() : text_("") {}
  String(const char* s) : text_(s ? s : "") {}
  String operator+(const char* rhs) const {
    String result;
    result.text_ = text_ + std::string(rhs ? rhs : "");
    return result;
  }
  const std::string& str() const { return text_; }

 private:
  std::string text_;
};

enum SAMOVAR_MODE { MODE_ALPHA, MODE_BETA, MODE_GAMMA, MODE_DELTA };
enum SamovarCommands { CMD_NONE, CMD_ALPHA, CMD_BETA, CMD_GAMMA };
enum MESSAGE_TYPE { WARNING_MSG };

using ModeVoidFn = void (*)();
using ModeStatusFn = String (*)();

struct ModeOps {
  SAMOVAR_MODE mode;
  int16_t activeStatus;
  int16_t startvalRangeLow;
  int16_t startvalRangeHigh;
  const char* pagePath;
  SamovarCommands powerOnCommand;
  SamovarCommands startCommand;
  ModeVoidFn alarm;
  ModeVoidFn finish;
  ModeStatusFn status;
  ModeVoidFn buttonPressAction;
  const char* startBusyName;
};

// --- Глобальное состояние, которым управляют сценарии ---
bool PowerOn = false;
SAMOVAR_MODE Samovar_Mode = MODE_ALPHA;

// --- Моки очереди команд и уведомлений ---
static bool queueAcceptsCommand = true;
static int queueCalls = 0;
static SamovarCommands lastQueuedCommand = CMD_NONE;
bool queue_samovar_command(SamovarCommands command) {
  queueCalls++;
  lastQueuedCommand = command;
  return queueAcceptsCommand;
}

static int sendMsgCalls = 0;
static std::string sendMsgLastText;
void SendMsg(const String& m, MESSAGE_TYPE type) {
  (void)type;
  sendMsgCalls++;
  sendMsgLastText = m.str();
}

// --- buttonPressAction режимов синтетической таблицы ---
static int actionAlphaCalls = 0;
void actionAlpha() { actionAlphaCalls++; }
static int actionBetaCalls = 0;
void actionBeta() { actionBetaCalls++; }

// Синтетическая (НЕ реальная) минимальная таблица из 3 строк - тестируется
// общая логика mode_dispatch_button_press(), не зависящая от конкретного
// состава реальной таблицы. Реальный состав таблицы (buttonPressAction/
// startBusyName по режимам) проверяется ОТДЕЛЬНО, текстовым способом.
static const ModeOps kTable[] = {
  {MODE_ALPHA, 0, 0, 0, "", CMD_ALPHA, CMD_NONE, nullptr, nullptr, nullptr, actionAlpha, "тест-А"},
  {MODE_BETA, 0, 0, 0, "", CMD_BETA, CMD_NONE, nullptr, nullptr, nullptr, actionBeta, "тест-Б"},
  {MODE_GAMMA, 0, 0, 0, "", CMD_GAMMA, CMD_NONE, nullptr, nullptr, nullptr, nullptr, "гамма"},
};

const ModeOps* mode_ops_by_mode(SAMOVAR_MODE mode) {
  for (const ModeOps& row : kTable) {
    if (row.mode == mode) return &row;
  }
  return nullptr;
}

void mode_dispatch_button_press() {
@DISPATCH_BODY@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  PowerOn = false;
  Samovar_Mode = MODE_ALPHA;
  queueAcceptsCommand = true;
  queueCalls = 0;
  lastQueuedCommand = CMD_NONE;
  sendMsgCalls = 0;
  sendMsgLastText.clear();
  actionAlphaCalls = 0;
  actionBetaCalls = 0;
}

int main() {
  // 1. !PowerOn, очередь принимает -> команда поставлена (именно powerOnCommand
  //    из строки таблицы), SendMsg и buttonPressAction не трогаются.
  reset_fixture();
  Samovar_Mode = MODE_ALPHA;
  PowerOn = false;
  queueAcceptsCommand = true;
  mode_dispatch_button_press();
  check(queueCalls == 1, "1: очередь должна быть вызвана ровно один раз");
  check(lastQueuedCommand == CMD_ALPHA, "1: в очередь должна уйти powerOnCommand режима из таблицы");
  check(sendMsgCalls == 0, "1: SendMsg не должен вызываться при успешной постановке в очередь");
  check(actionAlphaCalls == 0, "1: buttonPressAction не должен вызываться при !PowerOn");

  // 2. !PowerOn, очередь отказала, режим "тест-А" -> SendMsg с точным текстом.
  reset_fixture();
  Samovar_Mode = MODE_ALPHA;
  PowerOn = false;
  queueAcceptsCommand = false;
  mode_dispatch_button_press();
  check(sendMsgCalls == 1, "2: SendMsg должен быть вызван ровно один раз при отказе очереди");
  check(
      sendMsgLastText == "Очередь команд занята: старт тест-А не поставлен",
      "2: текст сообщения должен быть \"Очередь команд занята: старт тест-А не поставлен\"");
  check(actionAlphaCalls == 0, "2: buttonPressAction не должен вызываться при отказе очереди");

  // 3. То же с другим режимом ("тест-Б") -> текст другой, имя берётся из таблицы, а не захардкожено.
  reset_fixture();
  Samovar_Mode = MODE_BETA;
  PowerOn = false;
  queueAcceptsCommand = false;
  mode_dispatch_button_press();
  check(
      sendMsgLastText == "Очередь команд занята: старт тест-Б не поставлен",
      "3: текст сообщения должен быть \"Очередь команд занята: старт тест-Б не поставлен\"");

  // 4. PowerOn == true -> buttonPressAction вызван ровно раз, очередь и SendMsg не трогаются.
  reset_fixture();
  Samovar_Mode = MODE_ALPHA;
  PowerOn = true;
  mode_dispatch_button_press();
  check(actionAlphaCalls == 1, "4: при PowerOn==true должен быть вызван buttonPressAction ровно один раз");
  check(queueCalls == 0, "4: очередь не должна вызываться при PowerOn==true");
  check(sendMsgCalls == 0, "4: SendMsg не должен вызываться при PowerOn==true");

  // 5. buttonPressAction == nullptr (эмуляция SUVID/LUA) -> ничего не происходит.
  reset_fixture();
  Samovar_Mode = MODE_GAMMA;
  PowerOn = false;
  queueAcceptsCommand = true;
  mode_dispatch_button_press();
  check(queueCalls == 0, "5: режим без buttonPressAction не должен ставить команду в очередь");
  check(sendMsgCalls == 0, "5: режим без buttonPressAction не должен слать сообщение");

  // 6. Режима нет в таблице (mode_ops_by_mode вернул nullptr) -> ничего не происходит, без падения.
  reset_fixture();
  Samovar_Mode = MODE_DELTA;
  PowerOn = true;
  mode_dispatch_button_press();
  check(queueCalls == 0, "6: неизвестный режим не должен трогать очередь");
  check(sendMsgCalls == 0, "6: неизвестный режим не должен слать сообщение");
  check(actionAlphaCalls == 0 && actionBetaCalls == 0, "6: неизвестный режим не должен вызывать чужой buttonPressAction");

  if (failures) return 1;
  std::cout << "mode dispatch button press smoke checks passed\n";
  return 0;
}
'''


def run_harness(dispatch_body: str) -> tuple[int, str, str]:
    harness_source = HARNESS_TEMPLATE.replace("@DISPATCH_BODY@", dispatch_body)
    with tempfile.TemporaryDirectory(prefix="samovar-mode-button-dispatch-") as temp_dir:
        temp = Path(temp_dir)
        cpp_path = temp / "mode_button_dispatch_test.cpp"
        binary_path = temp / "mode_button_dispatch_test"
        cpp_path.write_text(harness_source, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(cpp_path),
                "-o",
                str(binary_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            return compile_result.returncode, compile_result.stdout, compile_result.stderr
        run_result = subprocess.run(
            [str(binary_path)], capture_output=True, text=True, check=False
        )
        return run_result.returncode, run_result.stdout, run_result.stderr


def extract_dispatch_body(source: str) -> str:
    return extract_function_body(strip_cpp_comments(source), DISPATCH_SIGNATURE)


# Мутации тела mode_dispatch_button_press() (применяются к ПОЛНОМУ исходнику
# mode_registry.h, тело диспетчера извлекается из мутанта заново). Каждая
# обязана уронить харнесс содержательным assert'ом, а не компиляцией.
MUTATIONS = {
    "removed !PowerOn guard": ("if (!PowerOn) {", "if (true) {"),
    "hardcoded startBusyName literal": ("ops->startBusyName", '"фиксировано"'),
    "removed buttonPressAction nullptr guard": (
        " || ops->buttonPressAction == nullptr",
        "",
    ),
}


def main() -> int:
    source = read_registry()

    errors: list[str] = []
    check_beer_wrapper(source, errors)
    check_table_rows(source, errors)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    try:
        dispatch_body = extract_dispatch_body(source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    returncode, stdout, stderr = run_harness(dispatch_body)
    if returncode != 0:
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
        print("FAIL: baseline mode_dispatch_button_press() harness did not pass", file=sys.stderr)
        return 1

    for name, (needle, replacement) in MUTATIONS.items():
        if needle not in source:
            print(f"FAIL: не удалось построить мутацию ({name}): токен не найден в mode_registry.h", file=sys.stderr)
            return 1
        mutant_source = source.replace(needle, replacement, 1)
        if mutant_source == source:
            print(f"FAIL: не удалось построить мутацию ({name}): текст не изменился", file=sys.stderr)
            return 1
        try:
            mutant_body = extract_dispatch_body(mutant_source)
        except ValueError as error:
            print(f"FAIL: не удалось построить мутацию ({name}): {error}", file=sys.stderr)
            return 1
        if mutant_body == dispatch_body:
            print(f"FAIL: не удалось построить мутацию ({name}): тело диспетчера не изменилось", file=sys.stderr)
            return 1
        mutant_returncode, _mutant_stdout, mutant_stderr = run_harness(mutant_body)
        if mutant_returncode == 0:
            print(f"FAIL: mutation survived: {name}", file=sys.stderr)
            return 1
        if "FAIL:" not in mutant_stderr:
            print(
                f"FAIL: mutation ({name}) провалилась не содержательным assert'ом, а падением/ошибкой сборки:\n{mutant_stderr}",
                file=sys.stderr,
            )
            return 1

    sys.stdout.write(stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
