#!/usr/bin/env python3
"""[WP17 п.45] Регресс-проверка: режим, не скомпилированный в текущей сборке
(НБК без SAMOVAR_USE_POWER - Samovar_no_power; Lua без USE_LUA - все окружения,
кроме Samovar_lua_mqtt), больше нельзя ни выбрать в веб-интерфейсе, ни сохранить.

Было: НБК отклонялся только в момент СТАРТА (nbk.h::run_nbk_program(), сообщение
в лог/алярм), а до этого спокойно выбирался в /setup.htm и сохранялся через
/save - пользователь не понимал, почему режим "не работает". У Lua-режима такой
проверки не было вовсе ни на старте, ни на сохранении.

Стало: mode_registry.h несёт новое поле ModeOps::buildAvailable (для НБК/Lua -
через макросы SAMOVAR_NBK_BUILD_AVAILABLE/SAMOVAR_LUA_BUILD_AVAILABLE из
samovar_api.h, объявленные по SAMOVAR_USE_POWER/USE_LUA) и unavailableReason.
Хелперы mode_available_in_build()/mode_unavailable_reason() читают эти поля и
используются в ДВУХ местах WebServer.ino:
  - handleSave(): отказывает 400 с понятным текстом ДО того, как режим попадёт
    в staged-настройки (не только на старте);
  - setupKeyProcessor(): недоступный режим получает hidden вместо
    selected/пустой строки в <option> списка выбора режима на /setup.htm - его
    физически нельзя выбрать в интерфейсе.

[fix] Обе точки различают "это уже СОХРАНЁННЫЙ режим пользователя, ставший
недоступным" от "пользователь пытается переключиться на недоступный режим":
  - setupKeyProcessor() для сохранённого недоступного режима возвращает
    "hidden selected" (не просто "hidden") - иначе ни один <option> не
    получает selected, браузер сам выбирает первый пункт списка
    ("Ректификация"), и сохранение ЛЮБОЙ другой настройки (форма
    /setup.htm отправляется целиком) молча подменяет режим пользователя;
  - handleSave() отбивает 400 только если requestedMode недоступен И не
    совпадает с уже сохранённым SamSetup.Mode (sourceProfileMode) - иначе
    пользователь, у которого сохранён ставший недоступным режим, не смог
    бы сохранить вообще ни одну настройку.

Тест проверяет:
  a) макросы SAMOVAR_NBK_BUILD_AVAILABLE/SAMOVAR_LUA_BUILD_AVAILABLE в
     samovar_api.h определены в обеих ветках (#ifdef/#else) соответствующего
     флага сборки;
  b) строки mode_registry_table() используют эти макросы для НБК/Lua (а не
     захардкоженный true) и `true, nullptr` для остальных пяти режимов;
  c) mode_available_in_build()/mode_unavailable_reason(), извлечённые из
     исходника, ведут себя по контракту в харнессе на g++;
  d) handleSave() действительно проверяет доступность режима ДО модификации
     staged-настроек и ДО modeRequested = true;
  e) setupKeyProcessor() проверяет доступность РАНЬШЕ, чем "selected" (иначе
     выбранный ранее, но ставший недоступным режим не скрылся бы);
  f) мутации каждого из проверяемых фрагментов обязаны ломать соответствующую
     проверку (текстовую или харнесс), а не проходить незамеченными.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
API_PATH = ROOT / "samovar_api.h"
REGISTRY_PATH = ROOT / "mode_registry.h"
WEBSERVER_PATH = ROOT / "WebServer.ino"

AVAILABLE_SIGNATURE = "inline bool mode_available_in_build(SAMOVAR_MODE mode)"
REASON_SIGNATURE = "inline const char* mode_unavailable_reason(SAMOVAR_MODE mode)"
SAVE_SIGNATURE = "void handleSave(AsyncWebServerRequest *request) {"
SETUP_KEY_SIGNATURE = "String setupKeyProcessor(const String &var) {"

MACRO_PATTERN = (
    "#ifdef {flag}\n"
    "#define {macro} true\n"
    "#else\n"
    "#define {macro} false\n"
    "#endif"
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --- (a) макросы в samovar_api.h -------------------------------------------------------------
def check_macros(source: str, errors: list[str]) -> None:
    for flag, macro in (("SAMOVAR_USE_POWER", "SAMOVAR_NBK_BUILD_AVAILABLE"), ("USE_LUA", "SAMOVAR_LUA_BUILD_AVAILABLE")):
        pattern = MACRO_PATTERN.format(flag=flag, macro=macro)
        if pattern not in source:
            errors.append(f"samovar_api.h: не найден блок #ifdef {flag}/#else для {macro} в ожидаемом виде")


# --- (b) строки mode_registry_table() ----------------------------------------------------------
EXPECTED_AVAILABILITY = {
    "SAMOVAR_RECTIFICATION_MODE": "true",
    "SAMOVAR_DISTILLATION_MODE": "true",
    "SAMOVAR_BEER_MODE": "true",
    "SAMOVAR_BK_MODE": "true",
    "SAMOVAR_NBK_MODE": "SAMOVAR_NBK_BUILD_AVAILABLE",
    "SAMOVAR_SUVID_MODE": "true",
    "SAMOVAR_LUA_MODE": "SAMOVAR_LUA_BUILD_AVAILABLE",
}


def check_table_rows(source: str, errors: list[str]) -> None:
    code = strip_cpp_comments(source)
    try:
        table_body = extract_function_body(code, "inline const ModeOps* mode_registry_table(size_t& count)")
    except ValueError as exc:
        errors.append(str(exc))
        return
    rows = dict(re.findall(r"\{\s*(SAMOVAR_[A-Z_]+_MODE)\s*,([^{}]*)\}", table_body))
    for mode, expected_flag in EXPECTED_AVAILABILITY.items():
        rest = rows.get(mode)
        if rest is None:
            errors.append(f"mode_registry table: row for {mode} not found")
            continue
        fields = [f.strip() for f in rest.split(",")]
        if len(fields) < 2:
            errors.append(f"mode_registry table: row for {mode} has too few fields: {rest}")
            continue
        build_available, reason = fields[-2], fields[-1]
        if build_available != expected_flag:
            errors.append(
                f"mode_registry table: {mode} buildAvailable = {build_available!r}, expected {expected_flag!r}"
            )
        if expected_flag == "true" and reason != "nullptr":
            errors.append(f"mode_registry table: {mode} unavailableReason должен быть nullptr, а не {reason!r}")
        if expected_flag != "true" and reason == "nullptr":
            errors.append(f"mode_registry table: {mode} unavailableReason не должен быть nullptr")


# --- (d) handleSave: порядок проверок -----------------------------------------------------------
def check_handle_save_order(source: str, errors: list[str]) -> None:
    try:
        body = extract_function_body(strip_cpp_comments(source), SAVE_SIGNATURE)
    except ValueError as exc:
        errors.append(str(exc))
        return
    require_ordered_tokens(
        "handleSave",
        body,
        [
            "requestedMode = (SAMOVAR_MODE)requestedModeValue;",
            "if (!mode_available_in_build(requestedMode) &&",
            "requestedMode != (SAMOVAR_MODE)sourceProfileMode) {",
            "mode_unavailable_reason(requestedMode)",
            '"not_allowed"',
            "return;",
            "}",
            "modeRequested = true;",
        ],
        errors,
    )


# --- (e) setupKeyProcessor: hidden проверяется раньше selected --------------------------------
def check_setup_key_processor_order(source: str, errors: list[str]) -> None:
    try:
        body = extract_function_body(strip_cpp_comments(source), SETUP_KEY_SIGNATURE)
    except ValueError as exc:
        errors.append(str(exc))
        return
    require_ordered_tokens(
        "setupKeyProcessor",
        body,
        [
            "for (const GetModeSelectField &f : kGetModeSelectFields) {",
            "const bool isCurrentMode = (SAMOVAR_MODE)SamSetup.Mode == f.mode;",
            'if (!mode_available_in_build(f.mode)) return isCurrentMode ? "hidden selected" : "hidden";',
            'return isCurrentMode ? "selected" : "";',
        ],
        errors,
    )


# --- (c) харнесс: mode_available_in_build()/mode_unavailable_reason() --------------------------
HELPER_HARNESS_TEMPLATE = r'''
#include <iostream>
#include <cstring>

enum SAMOVAR_MODE { MODE_ALPHA };

struct ModeOps {
  SAMOVAR_MODE mode;
  bool buildAvailable;
  const char* unavailableReason;
};

static const ModeOps* opsForMode = nullptr;
const ModeOps* mode_ops_by_mode(SAMOVAR_MODE) { return opsForMode; }

bool mode_available_in_build(SAMOVAR_MODE mode) {
@AVAILABLE_BODY@
}

const char* mode_unavailable_reason(SAMOVAR_MODE mode) {
@REASON_BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // 1. ops == nullptr (неизвестный режим) -> недоступен, причина отсутствует.
  opsForMode = nullptr;
  check(mode_available_in_build(MODE_ALPHA) == false, "1: неизвестный режим должен быть недоступен");
  check(mode_unavailable_reason(MODE_ALPHA) == nullptr, "1: у неизвестного режима не должно быть причины");

  // 2. Режим доступен (buildAvailable == true) -> причина отсутствует, даже если поле заполнено мусором.
  ModeOps available = {MODE_ALPHA, true, "мусор, не должен быть виден"};
  opsForMode = &available;
  check(mode_available_in_build(MODE_ALPHA) == true, "2: доступный режим должен быть доступен");
  check(mode_unavailable_reason(MODE_ALPHA) == nullptr, "2: у доступного режима причина не должна отдаваться");

  // 3. Режим недоступен (buildAvailable == false) -> причина возвращается как есть.
  ModeOps unavailable = {MODE_ALPHA, false, "нет регулятора мощности"};
  opsForMode = &unavailable;
  check(mode_available_in_build(MODE_ALPHA) == false, "3: недоступный режим должен быть недоступен");
  check(
      mode_unavailable_reason(MODE_ALPHA) != nullptr &&
          std::strcmp(mode_unavailable_reason(MODE_ALPHA), "нет регулятора мощности") == 0,
      "3: причина недоступности должна вернуться как есть");

  if (failures) return 1;
  std::cout << "mode build availability helper smoke checks passed\n";
  return 0;
}
'''


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


def extract_available_body(source: str) -> str:
    return extract_function_body(strip_cpp_comments(source), AVAILABLE_SIGNATURE)


def extract_reason_body(source: str) -> str:
    return extract_function_body(strip_cpp_comments(source), REASON_SIGNATURE)


def build_helper_harness(registry_source: str) -> str:
    available_body = extract_available_body(registry_source)
    reason_body = extract_reason_body(registry_source)
    return HELPER_HARNESS_TEMPLATE.replace("@AVAILABLE_BODY@", available_body).replace(
        "@REASON_BODY@", reason_body
    )


# --- (g) харнесс: setupKeyProcessor "hidden selected" и handleSave guard по sourceProfileMode --
SETUP_SELECT_START = "const bool isCurrentMode = (SAMOVAR_MODE)SamSetup.Mode == f.mode;"
SETUP_SELECT_END = 'return isCurrentMode ? "selected" : "";'

SAVE_GUARD_START = "if (!mode_available_in_build(requestedMode) &&"
SAVE_GUARD_END = "requestedMode != (SAMOVAR_MODE)sourceProfileMode) {"


def extract_between(text: str, start: str, end: str) -> str:
    start_idx = text.find(start)
    if start_idx < 0:
        raise ValueError(f"marker not found: {start!r}")
    end_idx = text.find(end, start_idx)
    if end_idx < 0:
        raise ValueError(f"marker not found after start: {end!r}")
    return text[start_idx:end_idx + len(end)]


def extract_setup_select_body(webserver_source: str) -> str:
    body = extract_function_body(strip_cpp_comments(webserver_source), SETUP_KEY_SIGNATURE)
    return extract_between(body, SETUP_SELECT_START, SETUP_SELECT_END)


def extract_save_guard_condition(webserver_source: str) -> str:
    body = extract_function_body(strip_cpp_comments(webserver_source), SAVE_SIGNATURE)
    clause = extract_between(body, SAVE_GUARD_START, SAVE_GUARD_END)
    inner = clause[len("if ("):-len(") {")]
    return inner


BOTH_FIXES_HARNESS_TEMPLATE = r'''
#include <iostream>
#include <string>

enum SAMOVAR_MODE { MODE_RECT = 0, MODE_ALPHA = 4 };

static bool g_available = true;
bool mode_available_in_build(SAMOVAR_MODE) { return g_available; }

struct FakeSetup { int Mode; };
static FakeSetup SamSetup;

struct GetModeSelectField { SAMOVAR_MODE mode; };

std::string setup_select(const GetModeSelectField &f) {
@SETUP_BODY@
}

bool save_guard(SAMOVAR_MODE requestedMode, int sourceProfileMode) {
  return (@SAVE_COND@);
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  GetModeSelectField f{MODE_ALPHA};

  // --- setupKeyProcessor: конец 1 -------------------------------------
  g_available = true; SamSetup.Mode = (int)MODE_ALPHA;
  check(setup_select(f) == "selected", "available+current должен быть 'selected'");

  g_available = true; SamSetup.Mode = (int)MODE_RECT;
  check(setup_select(f) == "", "available+not current должен быть пустым");

  g_available = false; SamSetup.Mode = (int)MODE_ALPHA;
  check(setup_select(f) == "hidden selected",
        "unavailable+current должен быть 'hidden selected' (иначе конец 1 регрессирует)");

  g_available = false; SamSetup.Mode = (int)MODE_RECT;
  check(setup_select(f) == "hidden", "unavailable+not current должен быть 'hidden'");

  // --- handleSave: конец 2 ---------------------------------------------
  g_available = false;
  check(save_guard(MODE_ALPHA, (int)MODE_ALPHA) == false,
        "повторная присылка уже сохранённого недоступного режима не должна отбиваться (конец 2)");

  check(save_guard(MODE_ALPHA, (int)MODE_RECT) == true,
        "переключение на НЕДОСТУПНЫЙ режим обязано отбиваться");

  g_available = true;
  check(save_guard(MODE_RECT, (int)MODE_ALPHA) == false,
        "доступный режим не должен отбиваться");

  if (failures) return 1;
  std::cout << "setup-select/save-guard combined checks passed\n";
  return 0;
}
'''


def build_both_fixes_harness(webserver_source: str) -> str:
    setup_body = extract_setup_select_body(webserver_source)
    save_cond = extract_save_guard_condition(webserver_source)
    return BOTH_FIXES_HARNESS_TEMPLATE.replace("@SETUP_BODY@", setup_body).replace(
        "@SAVE_COND@", save_cond
    )


# --- мутации -------------------------------------------------------------------------------
def scoped_replace(source: str, signature: str, needle: str, replacement: str) -> str | None:
    anchor = source.find(signature)
    if anchor < 0:
        return None
    prefix, scoped = source[:anchor], source[anchor:]
    if needle not in scoped:
        return None
    mutated_scoped = scoped.replace(needle, replacement, 1)
    if mutated_scoped == scoped:
        return None
    return prefix + mutated_scoped


def main() -> int:
    api_source = read(API_PATH)
    registry_source = read(REGISTRY_PATH)
    webserver_source = read(WEBSERVER_PATH)

    errors: list[str] = []
    check_macros(api_source, errors)
    check_table_rows(registry_source, errors)
    check_handle_save_order(webserver_source, errors)
    check_setup_key_processor_order(webserver_source, errors)

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    helper_harness = build_helper_harness(registry_source)
    compiled, returncode, stdout, stderr = compile_and_run(helper_harness, "samovar-mode-avail-")
    if not compiled or returncode != 0:
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
        print("FAIL: baseline mode_available_in_build/mode_unavailable_reason harness did not pass", file=sys.stderr)
        return 1

    both_fixes_harness = build_both_fixes_harness(webserver_source)
    bf_compiled, bf_returncode, bf_stdout, bf_stderr = compile_and_run(both_fixes_harness, "samovar-mode-avail-bothfix-")
    if not bf_compiled or bf_returncode != 0:
        sys.stdout.write(bf_stdout)
        sys.stderr.write(bf_stderr)
        print("FAIL: setup-select/save-guard combined harness did not pass (конец 1/конец 2)", file=sys.stderr)
        return 1

    problems: list[str] = []

    # Мутация 1: макрос НБК перестаёт зависеть от SAMOVAR_USE_POWER (всегда true) - должно
    # быть поймано структурной проверкой check_macros.
    mutant_api = api_source.replace(
        "#ifdef SAMOVAR_USE_POWER\n#define SAMOVAR_NBK_BUILD_AVAILABLE true\n#else\n"
        "#define SAMOVAR_NBK_BUILD_AVAILABLE false\n#endif",
        "#define SAMOVAR_NBK_BUILD_AVAILABLE true",
        1,
    )
    if mutant_api == api_source:
        problems.append("мутация макроса НБК: текст не изменился (needle не найден)")
    else:
        mutant_errors: list[str] = []
        check_macros(mutant_api, mutant_errors)
        if not mutant_errors:
            problems.append("мутация макроса НБК (всегда true): check_macros не заметила регресс")

    # Мутация 2: строка НБК в таблице захардкожена в true вместо макроса - должно быть
    # поймано check_table_rows.
    mutant_registry = scoped_replace(
        registry_source, 'SAMOVAR_NBK_MODE',
        "SAMOVAR_NBK_BUILD_AVAILABLE, \"Недоступно в этой сборке прошивки: нет регулятора мощности\"",
        "true, nullptr",
    )
    if mutant_registry is None:
        problems.append("мутация строки НБК в таблице: needle не найден")
    else:
        mutant_errors = []
        check_table_rows(mutant_registry, mutant_errors)
        if not mutant_errors:
            problems.append("мутация строки НБК (buildAvailable=true, reason=nullptr): check_table_rows не заметила регресс")

    # Мутация 3: в handleSave убрана проверка доступности режима перед modeRequested = true -
    # должно быть поймано check_handle_save_order (ordered tokens).
    mutant_webserver = scoped_replace(
        webserver_source, SAVE_SIGNATURE,
        "      if (!mode_available_in_build(requestedMode) &&\n"
        "          requestedMode != (SAMOVAR_MODE)sourceProfileMode) {\n"
        "        const char* reason = mode_unavailable_reason(requestedMode);\n"
        "        send_no_store_response(\n"
        "            request, 400, \"application/json\",\n"
        "            build_error_envelope(\n"
        "                \"not_allowed\", \"mode\",\n"
        "                reason ? String(reason) : String(\"Режим недоступен в этой сборке прошивки\")));\n"
        "        return;\n"
        "      }\n",
        "",
    )
    if mutant_webserver is None:
        problems.append("мутация handleSave: needle не найден")
    else:
        mutant_errors = []
        check_handle_save_order(mutant_webserver, mutant_errors)
        if not mutant_errors:
            problems.append("мутация handleSave (удалена проверка доступности): check_handle_save_order не заметила регресс")

    # Мутация 4: в setupKeyProcessor порядок проверок инвертирован (selected раньше hidden) -
    # должно быть поймано check_setup_key_processor_order.
    mutant_webserver2 = scoped_replace(
        webserver_source, SETUP_KEY_SIGNATURE,
        "      const bool isCurrentMode = (SAMOVAR_MODE)SamSetup.Mode == f.mode;\n"
        '      if (!mode_available_in_build(f.mode)) return isCurrentMode ? "hidden selected" : "hidden";\n'
        '      return isCurrentMode ? "selected" : "";',
        '      if (!mode_available_in_build(f.mode)) return "hidden";\n'
        '      return (SAMOVAR_MODE)SamSetup.Mode == f.mode ? "selected" : "";',
    )
    if mutant_webserver2 is None:
        problems.append("мутация setupKeyProcessor: needle не найден")
    else:
        mutant_errors = []
        check_setup_key_processor_order(mutant_webserver2, mutant_errors)
        if not mutant_errors:
            problems.append("мутация setupKeyProcessor (порядок инвертирован): check_setup_key_processor_order не заметила регресс")

    # Мутация 5: в mode_available_in_build() снят guard ops != nullptr - харнесс должен упасть
    # (либо содержательным assert'ом, либо настоящим падением на разыменовании nullptr).
    mutant_registry2 = scoped_replace(
        registry_source, AVAILABLE_SIGNATURE, "ops != nullptr && ops->buildAvailable", "ops->buildAvailable"
    )
    if mutant_registry2 is None:
        problems.append("мутация mode_available_in_build: needle не найден")
    else:
        mutant_harness = build_helper_harness(mutant_registry2)
        m_compiled, m_returncode, _m_stdout, m_stderr = compile_and_run(mutant_harness, "samovar-mode-avail-mut-")
        if not m_compiled:
            problems.append(f"мутация mode_available_in_build не скомпилировалась:\n{m_stderr}")
        elif m_returncode == 0:
            problems.append("мутация mode_available_in_build (снят guard nullptr): mutation survived")

    # Мутация 6: конец 1 регрессирует ТОЧЕЧНО - "hidden selected" заменён обратно на "hidden"
    # (isCurrentMode сохранён в коде, но перестаёт влиять на исход для недоступного режима) -
    # должно быть поймано функциональным харнессом build_both_fixes_harness (setup_select),
    # а не только структурной check_setup_key_processor_order.
    mutant_webserver3 = scoped_replace(
        webserver_source, SETUP_KEY_SIGNATURE,
        'if (!mode_available_in_build(f.mode)) return isCurrentMode ? "hidden selected" : "hidden";',
        'if (!mode_available_in_build(f.mode)) return "hidden";',
    )
    if mutant_webserver3 is None:
        problems.append("мутация 6 (hidden selected -> hidden): needle не найден")
    else:
        try:
            mutant_harness6 = build_both_fixes_harness(mutant_webserver3)
        except ValueError as exc:
            problems.append(f"мутация 6: харнесс не смог извлечь мутированный код ({exc}) - структура сломана сильнее ожидаемого")
        else:
            m6_compiled, m6_returncode, _m6_stdout, m6_stderr = compile_and_run(mutant_harness6, "samovar-mode-avail-mut6-")
            if not m6_compiled:
                problems.append(f"мутация 6 не скомпилировалась:\n{m6_stderr}")
            elif m6_returncode == 0:
                problems.append("мутация 6 (сохранённый недоступный режим снова теряет selected): mutation survived")

    # Мутация 7: конец 2 регрессирует ТОЧЕЧНО - из guard'а handleSave убрана только часть
    # "requestedMode != (SAMOVAR_MODE)sourceProfileMode" (проверка доступности остаётся) -
    # должно быть поймано функциональным харнессом (save_guard), а не только текстовой
    # check_handle_save_order.
    mutant_webserver4 = scoped_replace(
        webserver_source, SAVE_SIGNATURE,
        "!mode_available_in_build(requestedMode) &&\n          requestedMode != (SAMOVAR_MODE)sourceProfileMode",
        "!mode_available_in_build(requestedMode)",
    )
    if mutant_webserver4 is None:
        problems.append("мутация 7 (guard без sourceProfileMode): needle не найден")
    else:
        # Уход всего условия целиком (назад к однострочной проверке) убирает и анкоры
        # SAVE_GUARD_START/END разом - функциональный харнесс тут ничего не извлечёт
        # (структура сломана сильнее, чем эта точечная мутация обязана ломать), поэтому
        # ловим регресс структурно - той же check_handle_save_order, что и мутация 3,
        # но именно на ЭТОМ, более узком варианте отката (проверка доступности осталась,
        # пропала только часть про sourceProfileMode).
        mutant_errors = []
        check_handle_save_order(mutant_webserver4, mutant_errors)
        if not mutant_errors:
            problems.append("мутация 7 (guard без sourceProfileMode): check_handle_save_order не заметила регресс")

    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1

    sys.stdout.write(stdout)
    sys.stdout.write(bf_stdout)
    print("static checks (macros/table rows/order) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
