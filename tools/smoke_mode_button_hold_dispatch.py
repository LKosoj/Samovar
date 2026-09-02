#!/usr/bin/env python3
"""Регресс-проверка: диспетчер УДЕРЖАНИЯ кнопки по таблице режимов [П12].

Зеркало smoke_mode_button_press_dispatch.py, но для нового поля ModeOps
`buttonHoldAction` и нового диспетчера `mode_dispatch_button_hold()`
(mode_registry.h). Раньше единственным поведением дистилляции на основную
кнопку было завершение процесса по КОРОТКОМУ нажатию (`distiller_finish` в
buttonPressAction). Теперь короткое нажатие двигает программу дальше
(mode_button_press_dist, см. smoke_mode_button_press_dispatch.py), а
завершение процесса перенесено на УДЕРЖАНИЕ - buttonHoldAction=distiller_finish
для SAMOVAR_DISTILLATION_MODE, у всех остальных режимов buttonHoldAction
обязан остаться nullptr (иначе удержание кнопки во время работающего
пива/БК/НБК неожиданно завершило бы процесс).

[Ревью после первой волны] При PowerOn == false удержание кнопки раньше
ПРОГЛАТЫВАЛОСЬ: GyverButton гасит oneClick_f при пересечении порога
удержания (isClick() не сработает), а mode_dispatch_button_hold() выходил по
guard'у !PowerOn, ничего не делая. Раньше (до П12) isPress() включал нагрев
при ЛЮБОМ касании кнопки независимо от длительности - это поведение нужно
было сохранить. Теперь при !PowerOn mode_dispatch_button_hold() ДЕЛЕГИРУЕТ
mode_dispatch_button_press() (тот сам ставит powerOnCommand в очередь) - см.
mode_registry.h.

[Код-ревью, находка A] Оставался симметричный пробел: при PowerOn == true в
режимах БЕЗ buttonHoldAction (Пиво/БК/НБК) удержание кнопки тоже молча
ничего не делало - раньше в этих режимах короткое isPress() само завершало
процесс (bk_finish/nbk_finish/mode_button_press_beer). Пользователь держит
кнопку, чтобы остановить БК, а нагрев продолжается. Починка: диспетчер
удержания вызывает buttonHoldAction режима, только если PowerOn == true И
режим завёл собственное действие на удержание; во всех остальных случаях
(PowerOn == false, либо buttonHoldAction == nullptr) он теперь БЕЗУСЛОВНО
делегирует mode_dispatch_button_press() - тот сам разбирает и !PowerOn
(ставит powerOnCommand в очередь), и PowerOn == true с ops == nullptr
(ничего не делает).

Тест проверяет:
  a) таблица `mode_registry_table()` несёт buttonHoldAction=distiller_finish
     ТОЛЬКО у SAMOVAR_DISTILLATION_MODE, у остальных режимов - nullptr;
  b) само тело `mode_dispatch_button_hold()` (плюс реальное тело
     `mode_dispatch_button_press()`, которое оно теперь вызывает всякий раз,
     когда не выполнило own buttonHoldAction режима - извлечены из
     mode_registry.h, а не переписаны в тесте) ведут себя по контракту в
     харнессе на g++ с мокнутыми зависимостями (мок очереди команд/SendMsg -
     как в smoke_mode_button_press_dispatch.py):
       1) PowerOn==true, режим обслуживает удержание -> buttonHoldAction вызван;
       2) PowerOn==false, тот же режим (аналог DIST) -> удержание НЕ вызвано,
          вместо этого делегат поставил powerOnCommand в очередь;
       3) PowerOn==false, режим БЕЗ buttonHoldAction (аналог BEER/БК/НБК) ->
          тоже делегат ставит powerOnCommand в очередь - это и есть
          починенное поведение ("любое касание, включая долгое, включает
          нагрев");
       4) PowerOn==false, очередь отказала -> SendMsg с текстом отказа для
          ЭТОГО режима (startBusyName), удержание не вызвано;
       5) [находка A] PowerOn==true, режим без buttonHoldAction (аналог
          BEER/БК/НБК) -> делегат вызывает buttonPressAction ЭТОГО режима
          ровно один раз (betaPressCalls == 1) - удержание кнопки при
          включённом нагреве останавливает процесс так же, как раньше это
          делал isPress();
       6) неизвестный режим при PowerOn==true и при PowerOn==false -> ничего
          не происходит, без падения (в обоих случаях делегат сам находит
          ops==nullptr и не трогает очередь);
  c) две мутации обязаны валить содержательный assert харнесса, а не
     компиляцию:
       - "потеряно делегирование при !PowerOn" (возврат к самому первому
         бесследному `if (!PowerOn) return;` без делегата) - валит сценарии
         2-4;
       - [находка A] "потеряно делегирование при buttonHoldAction == nullptr
         и PowerOn == true" (возврат к промежуточному варианту, где после
         `if (!PowerOn) {...}` шёл голый
         `if (ops == nullptr || ops->buttonHoldAction == nullptr) return;`
         без делегата) - валит именно сценарий 5;
  d) guard'ы `ops != nullptr` и `ops->buttonHoldAction != nullptr` внутри
     объединённого условия ПРОВЕРЯЮТСЯ ТОЛЬКО ТЕКСТОВО, а не рантайм-мутацией:
     снятие любого из них в сценарии с реальным nullptr-действием (самый
     частый реальный кейс - работающие пиво/БК/НБК/Сувид/Lua/ректификация)
     означает вызов через нулевой указатель функции, т.е. SIGSEGV, а не
     содержательный assert. Такое падение запрещено правилами тестирования
     (AGENTS.md) - мутация обязана падать ЧИТАЕМЫМ текстом, а не
     крэшем/ошибкой сборки.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "mode_registry.h"

PRESS_SIGNATURE = "inline void mode_dispatch_button_press()"
HOLD_SIGNATURE = "inline void mode_dispatch_button_hold()"


def read_registry() -> str:
    return REGISTRY_PATH.read_text(encoding="utf-8")


# --- (a) таблица: buttonHoldAction по режимам ----------------------------------------------
EXPECTED_HOLD_FIELDS = {
    "SAMOVAR_DISTILLATION_MODE": "distiller_finish",
}

# Все остальные режимы обязаны иметь buttonHoldAction == nullptr - удержание их
# не завершает (для RECT/SUVID/LUA основная кнопка вообще не участвует в этом
# диспетчере, для BEER/BK/NBK удержание не обслуживается вовсе).
MODES_WITHOUT_HOLD = (
    "SAMOVAR_RECTIFICATION_MODE",
    "SAMOVAR_BEER_MODE",
    "SAMOVAR_BK_MODE",
    "SAMOVAR_NBK_MODE",
    "SAMOVAR_SUVID_MODE",
    "SAMOVAR_LUA_MODE",
)


def parse_modeops_field_names(source: str) -> list[str]:
    """Ordered member names of struct ModeOps, as declared in mode_registry.h.

    Row fields are matched by NAME (index into this list), not by a fixed
    position/count - see the identical rationale in
    smoke_mode_button_press_dispatch.py (struct ModeOps has grown several
    times already; reading by name makes the check self-adjusting)."""
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
    rest_field_names = field_names[1:]
    try:
        hold_idx = rest_field_names.index("buttonHoldAction")
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

    for mode, expected_fn in EXPECTED_HOLD_FIELDS.items():
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
        hold_fn = fields[hold_idx]
        if hold_fn != expected_fn:
            errors.append(
                f"mode_registry table: {mode} buttonHoldAction = {hold_fn!r}, "
                f"expected {expected_fn!r}"
            )

    for mode in MODES_WITHOUT_HOLD:
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
        if fields[hold_idx] != "nullptr":
            errors.append(
                f"mode_registry table: {mode} не обслуживает удержание кнопки, "
                f"buttonHoldAction должен быть nullptr, получено {fields[hold_idx]!r}"
            )


# --- (d) текстовая проверка null-safety guard'ов диспетчера --------------------------------
def check_guard_texts(hold_body: str, errors: list[str]) -> None:
    required_fragments = (
        "ops != nullptr",
        "ops->buttonHoldAction != nullptr",
        "PowerOn",
        "mode_dispatch_button_press();",
    )
    for fragment in required_fragments:
        if fragment not in hold_body:
            errors.append(
                f"mode_dispatch_button_hold(): не найден обязательный фрагмент {fragment!r} "
                "- см. обоснование в module docstring (снятие guard'а на nullptr-действие "
                "приводит к вызову через нулевой указатель функции, а не к content-assert; "
                "безусловное делегирование mode_dispatch_button_press() - починка "
                "проглатывания долгого нажатия и при выключенном нагреве, и в режимах без "
                "buttonHoldAction при включённом)"
            )


# --- (b)/(c) динамический харнесс для mode_dispatch_button_hold()+press --------------------
HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

// Мини-String с operator+ для const char* - реальное тело mode_dispatch_button_press()
// строит сообщение об отказе через String(...) + ops->startBusyName + "...".
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

enum SAMOVAR_MODE { MODE_ALPHA, MODE_BETA, MODE_DELTA };
enum SamovarCommands { CMD_NONE, CMD_ALPHA, CMD_BETA };
enum MESSAGE_TYPE { WARNING_MSG };

using ModeVoidFn = void (*)();

struct ModeOps {
  SAMOVAR_MODE mode;
  SamovarCommands powerOnCommand;
  ModeVoidFn buttonPressAction;
  ModeVoidFn buttonHoldAction;
  const char* startBusyName;
};

// --- Глобальное состояние, которым управляют сценарии ---
bool PowerOn = false;
SAMOVAR_MODE Samovar_Mode = MODE_ALPHA;

// --- Моки очереди команд и уведомлений (как в smoke_mode_button_press_dispatch.py) ---
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

// --- buttonPressAction/buttonHoldAction режимов синтетической таблицы ---
static int alphaPressCalls = 0;
void alphaPress() { alphaPressCalls++; }
static int alphaHoldCalls = 0;
void alphaHold() { alphaHoldCalls++; }
static int betaPressCalls = 0;
void betaPress() { betaPressCalls++; }

// MODE_ALPHA - аналог ДИСТИЛЛЯЦИИ: обслуживает и клик, и удержание.
// MODE_BETA - аналог ПИВА/БК/НБК: обслуживает клик, buttonHoldAction=nullptr
// (это самый частый реальный случай "проглатывания" из отчёта ревью).
static const ModeOps kTable[] = {
  {MODE_ALPHA, CMD_ALPHA, alphaPress, alphaHold, "тест-А"},
  {MODE_BETA, CMD_BETA, betaPress, nullptr, "тест-Б"},
};

const ModeOps* mode_ops_by_mode(SAMOVAR_MODE mode) {
  for (const ModeOps& row : kTable) {
    if (row.mode == mode) return &row;
  }
  return nullptr;
}

void mode_dispatch_button_press() {
@PRESS_BODY@
}

void mode_dispatch_button_hold() {
@HOLD_BODY@
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
  alphaPressCalls = 0;
  alphaHoldCalls = 0;
  betaPressCalls = 0;
}

int main() {
  // 1. PowerOn==true, режим обслуживает удержание -> buttonHoldAction вызван ровно раз,
  //    очередь/клик/SendMsg не трогаются.
  reset_fixture();
  Samovar_Mode = MODE_ALPHA;
  PowerOn = true;
  mode_dispatch_button_hold();
  check(alphaHoldCalls == 1, "1: при PowerOn==true buttonHoldAction должен быть вызван ровно один раз");
  check(alphaPressCalls == 0 && queueCalls == 0, "1: click-путь и очередь не должны трогаться");

  // 2. [починка] PowerOn==false, тот же режим (аналог DIST) -> удержание НЕ вызвано,
  //    вместо этого делегат поставил powerOnCommand в очередь - как раньше делал isPress()
  //    при любом касании независимо от длительности.
  reset_fixture();
  Samovar_Mode = MODE_ALPHA;
  PowerOn = false;
  mode_dispatch_button_hold();
  check(alphaHoldCalls == 0, "2: при !PowerOn buttonHoldAction не должен вызываться");
  check(queueCalls == 1 && lastQueuedCommand == CMD_ALPHA,
        "2: удержание при !PowerOn должно ставить powerOnCommand в очередь (делегат mode_dispatch_button_press)");
  check(sendMsgCalls == 0, "2: при успешной постановке в очередь SendMsg не должен вызываться");

  // 3. [починка] PowerOn==false, режим БЕЗ buttonHoldAction (аналог BEER/БК/НБК) ->
  //    тоже должно включить нагрев - это и есть суть предупреждения ревью.
  reset_fixture();
  Samovar_Mode = MODE_BETA;
  PowerOn = false;
  mode_dispatch_button_hold();
  check(queueCalls == 1 && lastQueuedCommand == CMD_BETA,
        "3: удержание в режиме без buttonHoldAction при !PowerOn всё равно должно включить нагрев");
  check(betaPressCalls == 0, "3: включение через очередь не должно сразу вызывать buttonPressAction");

  // 4. PowerOn==false, очередь отказала -> SendMsg с текстом отказа ИМЕННО для этого режима
  //    (startBusyName берётся из таблицы, а не захардкожен), удержание не вызвано.
  reset_fixture();
  Samovar_Mode = MODE_ALPHA;
  PowerOn = false;
  queueAcceptsCommand = false;
  mode_dispatch_button_hold();
  check(sendMsgCalls == 1, "4: SendMsg должен быть вызван ровно один раз при отказе очереди");
  check(
      sendMsgLastText == "Очередь команд занята: старт тест-А не поставлен",
      "4: текст сообщения должен быть \"Очередь команд занята: старт тест-А не поставлен\"");
  check(alphaHoldCalls == 0, "4: при отказе очереди buttonHoldAction не должен вызываться");

  // 5. [находка A] PowerOn==true, режим без buttonHoldAction (аналог BEER/БК/НБК) ->
  //    делегат вызывает buttonPressAction ЭТОГО режима - удержание кнопки при включённом
  //    нагреве обязано останавливать процесс так же, как раньше это делал isPress()
  //    (bk_finish/nbk_finish/mode_button_press_beer). Раньше здесь ничего не вызывалось -
  //    это и есть регресс из находки A.
  reset_fixture();
  Samovar_Mode = MODE_BETA;
  PowerOn = true;
  mode_dispatch_button_hold();
  check(betaPressCalls == 1, "5: режим без buttonHoldAction при PowerOn==true должен делегировать в buttonPressAction");
  check(alphaHoldCalls == 0 && queueCalls == 0,
        "5: делегирование не должно трогать удержание другого режима или очередь команд");

  // 6. Неизвестный режим (mode_ops_by_mode вернул nullptr), PowerOn==true -> ничего не происходит.
  reset_fixture();
  Samovar_Mode = MODE_DELTA;
  PowerOn = true;
  mode_dispatch_button_hold();
  check(alphaHoldCalls == 0 && betaPressCalls == 0 && queueCalls == 0,
        "6: неизвестный режим при PowerOn==true не должен ничего вызывать");

  // 7. Неизвестный режим, PowerOn==false -> делегат сам находит ops==nullptr и не трогает очередь.
  reset_fixture();
  Samovar_Mode = MODE_DELTA;
  PowerOn = false;
  mode_dispatch_button_hold();
  check(queueCalls == 0 && sendMsgCalls == 0,
        "7: неизвестный режим при !PowerOn не должен ставить команду в очередь или слать сообщение");

  if (failures) return 1;
  std::cout << "mode dispatch button hold smoke checks passed\n";
  return 0;
}
'''


def run_harness(press_body: str, hold_body: str) -> tuple[int, str, str]:
    harness_source = HARNESS_TEMPLATE.replace("@PRESS_BODY@", press_body).replace(
        "@HOLD_BODY@", hold_body
    )
    with tempfile.TemporaryDirectory(prefix="samovar-mode-button-hold-dispatch-") as temp_dir:
        temp = Path(temp_dir)
        cpp_path = temp / "mode_button_hold_dispatch_test.cpp"
        binary_path = temp / "mode_button_hold_dispatch_test"
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


def extract_bodies(source: str) -> tuple[str, str]:
    stripped = strip_cpp_comments(source)
    press_body = extract_function_body(stripped, PRESS_SIGNATURE)
    hold_body = extract_function_body(stripped, HOLD_SIGNATURE)
    return press_body, hold_body


# Мутации тела mode_dispatch_button_hold() (применяются к ПОЛНОМУ исходнику
# mode_registry.h, тела извлекаются из мутанта заново). Обе воспроизводят
# исторические баги, найденные ревью (см. module docstring), заменяя один и
# тот же (текущий, правильный) текст тела на более старый. Guard'ы
# `ops != nullptr` / `ops->buttonHoldAction != nullptr` внутри условия
# проверяются только текстово (check_guard_texts) - см. module docstring (d).
CURRENT_HOLD_BODY_TEXT = (
    "const ModeOps* ops = mode_ops_by_mode(Samovar_Mode);\n"
    "  if (PowerOn && ops != nullptr && ops->buttonHoldAction != nullptr) {\n"
    "    ops->buttonHoldAction();\n"
    "    return;\n"
    "  }\n"
    "  mode_dispatch_button_press();"
)

MUTATIONS = {
    # Самый первый исторический баг: удержание при !PowerOn бесследно проглатывалось.
    # Валит сценарии 2-4.
    "lost !PowerOn delegation (reverted to bare return)": (
        CURRENT_HOLD_BODY_TEXT,
        "if (!PowerOn) return;\n"
        "  const ModeOps* ops = mode_ops_by_mode(Samovar_Mode);\n"
        "  if (ops == nullptr || ops->buttonHoldAction == nullptr) return;\n"
        "  ops->buttonHoldAction();",
    ),
    # [Находка A] Промежуточное состояние ДО этой правки: !PowerOn уже делегировал
    # в press, но PowerOn==true с buttonHoldAction==nullptr всё ещё бесследно ничего
    # не делал. Обязана валить именно сценарий 5.
    "lost delegation when buttonHoldAction == nullptr at PowerOn == true": (
        CURRENT_HOLD_BODY_TEXT,
        "if (!PowerOn) {\n"
        "    mode_dispatch_button_press();\n"
        "    return;\n"
        "  }\n"
        "  const ModeOps* ops = mode_ops_by_mode(Samovar_Mode);\n"
        "  if (ops == nullptr || ops->buttonHoldAction == nullptr) return;\n"
        "  ops->buttonHoldAction();",
    ),
}


def main() -> int:
    source = read_registry()

    errors: list[str] = []
    check_table_rows(source, errors)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    try:
        press_body, hold_body = extract_bodies(source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    check_guard_texts(hold_body, errors)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    returncode, stdout, stderr = run_harness(press_body, hold_body)
    if returncode != 0:
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
        print("FAIL: baseline mode_dispatch_button_hold() harness did not pass", file=sys.stderr)
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
            mutant_press_body, mutant_hold_body = extract_bodies(mutant_source)
        except ValueError as error:
            print(f"FAIL: не удалось построить мутацию ({name}): {error}", file=sys.stderr)
            return 1
        if mutant_hold_body == hold_body:
            print(f"FAIL: не удалось построить мутацию ({name}): тело диспетчера не изменилось", file=sys.stderr)
            return 1
        mutant_returncode, _mutant_stdout, mutant_stderr = run_harness(mutant_press_body, mutant_hold_body)
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
