#!/usr/bin/env python3
"""[WP17 п.45, хвост] Регресс-проверка: apply_config_runtime() (Samovar.ino)
сообщает пользователю, если ВЫСТАВЛЕННЫЙ им режим (SamSetup.Mode) не
скомпилирован в этой сборке прошивки (НБК без SAMOVAR_USE_POWER, Lua без
USE_LUA).

Было: apply_config_runtime() проверял только диапазон номера режима
(is_valid_samovar_mode) и молча выставлял Samovar_Mode из настроек - для
недоступного, но валидного по диапазону режима (НБК/Lua) устройство
оказывалось в режиме, который ничего не делает, без единого сообщения.
Функция вызывается на старте (setup()), при применении профиля
(commit_profile_operation) и из меню устройства (Menu.ino::setup_go_back) - во
всех трёх случаях уже ПОСЛЕ xMsgSemaphore = xSemaphoreCreateMutexStatic(...) в
setup(), так что SendMsg() безопасен.

Стало: если mode_available_in_build(Samovar_Mode) == false, шлём SendMsg с
текстом из mode_unavailable_reason() и уровнем ALARM_MSG (та же связка
сообщение+уровень, что и в nbk.h::run_nbk_program() при отказе запуска НБК в
сборке без регулятора мощности). Режим САМОВОЛЬНО не переключаем (это была бы
та же молчаливая подмена настройки, которую WebServer.ino::handleSave как раз
не допускает с другого конца) - Samovar_Mode остаётся как есть.

"Не спамить": функция вызывается на КАЖДОЕ применение профиля, а не только
когда режим реально сменился. Приём - "сообщить один раз при входе в
состояние", тот же, что noDZ_message_sent (nbk.h) и pressure_alarm_sent
(Samovar.ino, triggerSysTicker): static-флаг запоминает, для какого именно
режима сообщение уже отправлено, и сбрасывается, когда режим снова становится
доступен (иначе повторный вход в ТОТ ЖЕ недоступный режим после промежуточного
доступного не предупредил бы снова).

Тест вытаскивает РЕАЛЬНЫЙ фрагмент apply_config_runtime() (только новый блок,
между static-объявлением флага и его сбросом в else) текстовыми маркерами и
компилирует его в минимальный харнесс на g++ с поддельными
mode_available_in_build/mode_unavailable_reason/SendMsg - проверяется
функциональное поведение (сообщение, уровень, дедупликация, повторный вход),
а не только структура текста.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
SAMOVAR_INO_PATH = ROOT / "Samovar.ino"

APPLY_SIGNATURE = "void apply_config_runtime() {"

BLOCK_START = "static int modeUnavailableWarnedFor = -1;"
BLOCK_END = "    modeUnavailableWarnedFor = -1;\n  }"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_between(text: str, start: str, end: str) -> str:
    start_idx = text.find(start)
    if start_idx < 0:
        raise ValueError(f"marker not found: {start!r}")
    end_idx = text.find(end, start_idx)
    if end_idx < 0:
        raise ValueError(f"marker not found after start: {end!r}")
    return text[start_idx:end_idx + len(end)]


def extract_warning_block(samovar_source: str) -> str:
    body = extract_function_body(strip_cpp_comments(samovar_source), APPLY_SIGNATURE)
    return extract_between(body, BLOCK_START, BLOCK_END)


# --- структурные проверки -------------------------------------------------------------------
def check_no_self_switch(fragment: str, errors: list[str]) -> None:
    # [Ограничение задачи] Сброс в доступный режим - та же молчаливая подмена настройки,
    # которую только что починили с другого конца (WebServer.ino handleSave). Фрагмент не
    # имеет права присваивать Samovar_Mode вообще.
    if "Samovar_Mode =" in fragment or "Samovar_Mode=" in fragment:
        errors.append("mode warning block присваивает Samovar_Mode - самовольное переключение режима запрещено")


def check_structure(fragment: str, errors: list[str]) -> None:
    require_ordered_tokens(
        "apply_config_runtime mode warning block",
        fragment,
        [
            "static int modeUnavailableWarnedFor = -1;",
            "if (!mode_available_in_build(Samovar_Mode)) {",
            "if ((int)Samovar_Mode != modeUnavailableWarnedFor) {",
            "mode_unavailable_reason(Samovar_Mode);",
            "SendMsg(",
            "ALARM_MSG);",
            "modeUnavailableWarnedFor = (int)Samovar_Mode;",
            "} else {",
            "modeUnavailableWarnedFor = -1;",
            "}",
        ],
        errors,
    )


# --- харнесс ---------------------------------------------------------------------------------
HARNESS_TEMPLATE = r'''
#include <iostream>
#include <string>
#include <vector>

enum SAMOVAR_MODE { MODE_RECT = 0, MODE_NBK = 4, MODE_LUA = 6 };
enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, NONE_MSG = 100 };

class String : public std::string {
 public:
  String() = default;
  String(const char* s) : std::string(s ? s : "") {}
  String(const std::string& s) : std::string(s) {}
};
inline String operator+(const String& lhs, const char* rhs) {
  return String(std::string(lhs) + (rhs ? rhs : ""));
}

static bool g_available = true;
static const char* g_reason = nullptr;
bool mode_available_in_build(SAMOVAR_MODE) { return g_available; }
const char* mode_unavailable_reason(SAMOVAR_MODE) { return g_reason; }

struct SentMsg { std::string text; MESSAGE_TYPE level; };
static std::vector<SentMsg> g_sent;
void SendMsg(const String& m, MESSAGE_TYPE level) { g_sent.push_back({std::string(m), level}); }

SAMOVAR_MODE Samovar_Mode = MODE_RECT;

void warn_step() {
@BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // 1. Режим доступен - вызовы (сколько угодно раз) не должны слать сообщений.
  g_available = true; g_reason = nullptr; Samovar_Mode = MODE_RECT;
  warn_step(); warn_step(); warn_step();
  check(g_sent.empty(), "1: доступный режим не должен слать сообщений");

  // 2. Режим недоступен (НБК) - первый вызов шлёт сообщение с текстом причины и ALARM_MSG.
  g_available = false; g_reason = "нет регулятора мощности"; Samovar_Mode = MODE_NBK;
  warn_step();
  check(g_sent.size() == 1, "2: первый вход в недоступный режим должен послать ровно одно сообщение");
  if (!g_sent.empty()) {
    check(g_sent.back().text == "Режим из настроек не активирован: нет регулятора мощности",
          "2: текст сообщения должен включать причину из mode_unavailable_reason()");
    check(g_sent.back().level == ALARM_MSG, "2: уровень сообщения должен быть ALARM_MSG");
  }

  // 3. Повторные вызовы С ТЕМ ЖЕ недоступным режимом (имитация повторного применения
  // профиля) не должны спамить - счётчик сообщений не растёт.
  warn_step(); warn_step(); warn_step();
  check(g_sent.size() == 1, "3: повторные применения профиля с тем же недоступным режимом не должны повторять сообщение");

  // 4. Режим стал доступен (например, другая прошивка со своим регулятором) - вызов не
  // шлёт нового сообщения (нечего сообщать), но обязан сбросить дедуп-флаг.
  g_available = true; g_reason = nullptr;
  warn_step();
  check(g_sent.size() == 1, "4: переход в доступный режим не должен сам по себе слать сообщение");

  // 5. Повторный вход в ТОТ ЖЕ недоступный режим после промежуточного доступного состояния
  // обязан предупредить СНОВА (флаг должен был сброситься на шаге 4).
  g_available = false; g_reason = "нет регулятора мощности";
  warn_step();
  check(g_sent.size() == 2, "5: повторный вход в тот же недоступный режим после доступного состояния должен снова предупредить");

  // 6. Смена на ДРУГОЙ недоступный режим (Lua) без промежуточного доступного состояния тоже
  // обязана предупредить - дедуп ключирован по конкретному режиму, а не только по флагу "недоступен".
  g_reason = "не включён Lua"; Samovar_Mode = MODE_LUA;
  warn_step();
  check(g_sent.size() == 3, "6: смена на другой недоступный режим должна снова предупредить");
  if (g_sent.size() == 3) {
    check(g_sent.back().text == "Режим из настроек не активирован: не включён Lua",
          "6: текст должен отражать причину именно нового режима (Lua)");
  }

  // 7. mode_unavailable_reason() == nullptr (защитный случай) не должен уронить харнесс -
  // используется резервный текст.
  g_available = false; g_reason = nullptr; Samovar_Mode = MODE_NBK;
  size_t before = g_sent.size();
  warn_step();
  check(g_sent.size() == before + 1, "7: nullptr-причина всё равно должна дать сообщение (fallback-текст)");
  if (g_sent.size() == before + 1) {
    check(g_sent.back().text == "Режим из настроек не активирован: недоступен в этой сборке прошивки",
          "7: при nullptr-причине должен использоваться резервный текст");
  }

  if (failures) return 1;
  std::cout << "apply_config_runtime mode-unavailable warning checks passed\n";
  return 0;
}
'''


def build_harness(fragment: str) -> str:
    return HARNESS_TEMPLATE.replace("@BODY@", fragment)


def compile_and_run(harness_source: str, prefix: str) -> tuple[bool, int, str, str]:
    with tempfile.TemporaryDirectory(prefix=prefix) as temp_dir:
        temp = Path(temp_dir)
        cpp_path = temp / "test.cpp"
        binary_path = temp / "test_bin"
        cpp_path.write_text(harness_source, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp_path), "-o", str(binary_path)],
            capture_output=True, text=True, check=False,
        )
        if compile_result.returncode != 0:
            return False, compile_result.returncode, compile_result.stdout, compile_result.stderr
        run_result = subprocess.run([str(binary_path)], capture_output=True, text=True, check=False)
        return True, run_result.returncode, run_result.stdout, run_result.stderr


def scoped_replace(source: str, needle: str, replacement: str) -> str | None:
    if needle not in source:
        return None
    mutated = source.replace(needle, replacement, 1)
    if mutated == source:
        return None
    return mutated


def main() -> int:
    samovar_source = read(SAMOVAR_INO_PATH)

    try:
        fragment = extract_warning_block(samovar_source)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    errors: list[str] = []
    check_no_self_switch(fragment, errors)
    check_structure(fragment, errors)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    harness = build_harness(fragment)
    compiled, returncode, stdout, stderr = compile_and_run(harness, "samovar-apply-cfg-warn-")
    if not compiled or returncode != 0:
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
        print("FAIL: baseline apply_config_runtime mode-warning harness did not pass", file=sys.stderr)
        return 1

    problems: list[str] = []

    # Мутация 1: дедупликация снята (условие всегда true) - сообщение будет слаться на
    # КАЖДЫЙ вызов, спамя пользователя при каждом сохранении настроек. Должно быть поймано
    # проверкой 3 (повторные вызовы с тем же режимом).
    # ([-Werror=unused-but-set-variable] ловушка: простое "if (true)" убирает единственное
    # чтение modeUnavailableWarnedFor - падает компилятор, а не assert, что по конвенции
    # проекта НЕ считается "тест поймал". Условие ослаблено через "|| 1", а не заменено -
    # переменная остаётся прочитанной, компилируется, поведение (всегда true) то же.
    mutant1 = scoped_replace(
        fragment,
        "if ((int)Samovar_Mode != modeUnavailableWarnedFor) {",
        "if ((int)Samovar_Mode != modeUnavailableWarnedFor || 1) {",
    )
    if mutant1 is None:
        problems.append("мутация 1 (дедуп снят): needle не найден")
    else:
        m_compiled, m_rc, _out, m_err = compile_and_run(build_harness(mutant1), "samovar-apply-cfg-warn-m1-")
        if not m_compiled:
            problems.append(f"мутация 1 не скомпилировалась:\n{m_err}")
        elif m_rc == 0:
            problems.append("мутация 1 (дедуп снят, спам на каждый вызов): mutation survived")

    # Мутация 2: убран static у флага дедупликации - каждый вызов функции заново
    # инициализирует локальную переменную, эффект тот же спам, что в мутации 1, но другой
    # текстовый needle (реалистичная опечатка при правке).
    mutant2 = scoped_replace(fragment, "static int modeUnavailableWarnedFor = -1;", "int modeUnavailableWarnedFor = -1;")
    if mutant2 is None:
        problems.append("мутация 2 (static снят): needle не найден")
    else:
        m_compiled, m_rc, _out, m_err = compile_and_run(build_harness(mutant2), "samovar-apply-cfg-warn-m2-")
        if not m_compiled:
            problems.append(f"мутация 2 не скомпилировалась:\n{m_err}")
        elif m_rc == 0:
            problems.append("мутация 2 (static снят, дедуп не переживает вызовы): mutation survived")

    # Мутация 3: SendMsg удалён из веток (пользователь вообще не узнаёт о недоступном режиме) -
    # должна быть поймана проверкой 2 (первое сообщение).
    needle3 = (
        'SendMsg(String("Режим из настроек не активирован: ") +\n'
        '                  (reason ? reason : "недоступен в этой сборке прошивки"),\n'
        '              ALARM_MSG);'
    )
    mutant3 = scoped_replace(fragment, needle3, "(void)reason;")
    if mutant3 is None:
        problems.append("мутация 3 (SendMsg удалён): needle не найден")
    else:
        m_compiled, m_rc, _out, m_err = compile_and_run(build_harness(mutant3), "samovar-apply-cfg-warn-m3-")
        if not m_compiled:
            problems.append(f"мутация 3 не скомпилировалась:\n{m_err}")
        elif m_rc == 0:
            problems.append("мутация 3 (сообщение не шлётся вообще): mutation survived")

    # Мутация 4: уровень сообщения понижен до WARNING_MSG - должна быть поймана проверкой 2
    # (точный уровень ALARM_MSG, как у аналогичного отказа в nbk.h).
    mutant4 = scoped_replace(fragment, "              ALARM_MSG);", "              WARNING_MSG);")
    if mutant4 is None:
        problems.append("мутация 4 (уровень понижен): needle не найден")
    else:
        m_compiled, m_rc, _out, m_err = compile_and_run(build_harness(mutant4), "samovar-apply-cfg-warn-m4-")
        if not m_compiled:
            problems.append(f"мутация 4 не скомпилировалась:\n{m_err}")
        elif m_rc == 0:
            problems.append("мутация 4 (ALARM_MSG -> WARNING_MSG): mutation survived")

    # Мутация 5: сброс дедуп-флага в else-ветке убран - повторный вход в ТОТ ЖЕ недоступный
    # режим после промежуточного доступного состояния перестанет предупреждать (проверка 5).
    mutant5 = scoped_replace(fragment, "  } else {\n    modeUnavailableWarnedFor = -1;\n  }", "  }")
    if mutant5 is None:
        problems.append("мутация 5 (сброс флага убран): needle не найден")
    else:
        m_compiled, m_rc, _out, m_err = compile_and_run(build_harness(mutant5), "samovar-apply-cfg-warn-m5-")
        if not m_compiled:
            problems.append(f"мутация 5 не скомпилировалась:\n{m_err}")
        elif m_rc == 0:
            problems.append("мутация 5 (флаг не сбрасывается при доступном режиме): mutation survived")

    # Мутация 6: условие инвертировано (сообщение шлётся, когда режим ДОСТУПЕН) - должна быть
    # поймана проверкой 1 (доступный режим не должен слать сообщений).
    mutant6 = scoped_replace(
        fragment, "if (!mode_available_in_build(Samovar_Mode)) {", "if (mode_available_in_build(Samovar_Mode)) {"
    )
    if mutant6 is None:
        problems.append("мутация 6 (условие инвертировано): needle не найден")
    else:
        m_compiled, m_rc, _out, m_err = compile_and_run(build_harness(mutant6), "samovar-apply-cfg-warn-m6-")
        if not m_compiled:
            problems.append(f"мутация 6 не скомпилировалась:\n{m_err}")
        elif m_rc == 0:
            problems.append("мутация 6 (условие инвертировано): mutation survived")

    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1

    sys.stdout.write(stdout)
    print("apply_config_runtime mode-unavailable warning smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
