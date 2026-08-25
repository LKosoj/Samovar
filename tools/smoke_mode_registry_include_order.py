#!/usr/bin/env python3
"""
[WP12] Регресс-проверка порядка строк внутри samovar_api.h.

Файл заканчивается строкой `#include "mode_registry.h"`. Так сделано, потому
что mode_registry.h строит таблицу режимов и в ней по ИМЕНИ ссылается на
функции, реально определённые в ДРУГИХ заголовках (alarm.h, distiller.h,
beer.h, BK.h, nbk.h, suvid.h, mode_common.h, lua.h). Все эти заголовки сами
подключают samovar_api.h (нужны его перечисления/типы) - включить их отсюда
напрямую значило бы воссоздать цикл (A включает B, B включает A). Поэтому
mode_registry.h не подключает их - вместо этого samovar_api.h заранее (ВЫШЕ
по файлу) форвард-декларирует (объявляет без тела - "сигнатура уже известна,
код появится позже, когда дальше по сборке подключится настоящий заголовок")
каждую нужную функцию.

Это работает только пока порядок строк не нарушен: #include "mode_registry.h"
обязан стоять ПОСЛЕ всех этих форвард-деклараций. Тест проверяет три вещи на
РЕАЛЬНЫХ файлах:

1. `#include "mode_registry.h"` встречается ровно один раз, и после него в
   файле не осталось никакого кода (только эта строка - последняя).
2. Для каждого идентификатора, который реально используется в реальных телах
   mode_registry_table/mode_alarm_beer/mode_alarm_nbk/mode_button_press_beer
   (вытащены из mode_registry.h) и при этом ОБЪЯВЛЕН где-то в samovar_api.h -
   объявление обязано стоять РАНЬШЕ #include "mode_registry.h". Список имён
   не захардкожен - если в таблицу режимов добавят новую функцию, проверка
   сама её подхватит.
3. Компилируемый харнесс: те же реальные тела + реально найденные (п.2)
   объявления собираются g++ (-c, без линковки - нужна только видимость
   объявлений, не реальные тела внешних функций). Харнесс должен собраться.
   Мутация: харнесс без ОДНОГО из найденных объявлений (как будто его
   переставили после include) должен провалить сборку - это доказывает, что
   проверка реально чувствительна к порядку/наличию объявлений.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
INCLUDE_MARKER = '#include "mode_registry.h"'

CPP_KEYWORDS = {
    "if", "else", "return", "void", "bool", "true", "false", "nullptr",
    "const", "static", "inline", "struct", "class", "size_t", "int",
    "uint8_t", "int16_t", "uint16_t", "uint32_t", "float", "double",
    "char", "for", "while", "sizeof", "auto",
}

BODY_SIGNATURES = [
    "inline void mode_alarm_nbk()",
    "inline void mode_alarm_beer()",
    "inline void mode_button_press_beer()",
    # [WP17 п.40] Per-mode helpers added alongside tick/stopProcess in ModeOps -
    # same pattern as mode_alarm_beer above: defined right here in mode_registry.h,
    # referenced by name from mode_registry_table() below. Without a real body in
    # the harness, that reference is simply undeclared (not a decl-order issue) -
    # they must be pulled in like the other three per-mode callbacks.
    "inline void mode_tick_beer()",
    "inline void mode_stop_process_rectification()",
    "inline const ModeOps* mode_registry_table(size_t& count)",
]

MODEOPS_PRELUDE = """using ModeVoidFn = void (*)();
using ModeStatusFn = String (*)();

struct ModeOps {
  SAMOVAR_MODE mode;
  int16_t activeStatus;
  int16_t startvalRangeLow;
  int16_t startvalRangeHigh;
  int16_t statusRangeLow;
  int16_t statusRangeHigh;
  const char* pagePath;
  SamovarCommands powerOnCommand;
  SamovarCommands startCommand;
  ModeVoidFn alarm;
  ModeVoidFn finish;
  ModeStatusFn status;
  ModeVoidFn buttonPressAction;
  const char* startBusyName;
  ModeVoidFn tick;
  ModeVoidFn stopProcess;
  bool buildAvailable;
  const char* unavailableReason;
};
"""


def find_include_pos(text: str) -> int:
    positions = [m.start() for m in re.finditer(re.escape(INCLUDE_MARKER), text)]
    if len(positions) != 1:
        raise AssertionError(
            f"ожидалось ровно одно вхождение {INCLUDE_MARKER!r} в samovar_api.h, "
            f"найдено {len(positions)}"
        )
    return positions[0]


def check_nothing_after(text: str, include_pos: int, errors: list) -> None:
    tail = strip_cpp_comments(text[include_pos + len(INCLUDE_MARKER):])
    if tail.strip():
        errors.append(
            'после #include "mode_registry.h" в samovar_api.h остался код - '
            'это ломает гарантию "все нужные форвард-декларации уже видны к этой '
            f'строке" (остаток: {tail.strip()[:120]!r})'
        )


def used_identifiers(bodies_source: str) -> list:
    seen_set = set()
    ordered = []
    for tok in re.findall(r"\b[A-Za-z_]\w*\b", bodies_source):
        if tok in CPP_KEYWORDS or tok in seen_set:
            continue
        seen_set.add(tok)
        ordered.append(tok)
    return ordered


def decl_pos(name: str, api_stripped: str) -> int:
    m = re.search(rf"\b{re.escape(name)}\s*\(", api_stripped)
    return m.start() if m else -1


def decl_line(api_stripped: str, pos: int) -> str:
    start = api_stripped.rfind("\n", 0, pos) + 1
    end = api_stripped.find("\n", pos)
    if end < 0:
        end = len(api_stripped)
    return api_stripped[start:end].strip()


def build_object(harness: str, work_dir: Path, name: str):
    src = work_dir / f"{name}.cpp"
    obj = work_dir / f"{name}.o"
    src.write_text(harness, encoding="utf-8")
    return subprocess.run(
        # Без -Werror: интересуют жёсткие ошибки видимости объявлений (порядок
        # include), а не стилевые предупреждения - например, для реальных
        # inline-объявлений без тела здесь (тело - в другом заголовке, который
        # этот харнесс сознательно не подключает) gcc иначе ругается "used but
        # never defined", что к проверяемому инварианту не относится.
        ["g++", "-std=c++11", "-Wall", "-Wextra", "-c", str(src), "-o", str(obj)],
        capture_output=True,
        text=True,
        check=False,
    )


def assemble_harness(enum_block: str, decl_lines: list, macro_block: str, bodies: str) -> str:
    return f"""#include <cstdint>
#include <cstddef>

class String;

{enum_block}

constexpr int16_t SAMOVAR_STATUS_IDLE = 0;
constexpr int16_t SAMOVAR_STATUS_DISTILLATION = 1000;
constexpr int16_t SAMOVAR_STATUS_BEER = 2000;
constexpr int16_t SAMOVAR_STATUS_BK = 3000;
constexpr int16_t SAMOVAR_STATUS_NBK = 4000;
constexpr int16_t SAMOVAR_STARTVAL_BEER_START = 2000;
constexpr uint8_t PROGRAM_END = 0;

volatile uint8_t ProgramNum = 0;
volatile int16_t startval = 0;

{MODEOPS_PRELUDE}

{chr(10).join(decl_lines)}

{macro_block}

{bodies}
"""


def main() -> int:
    api_source = (ROOT / "samovar_api.h").read_text(encoding="utf-8")
    registry_source = (ROOT / "mode_registry.h").read_text(encoding="utf-8")
    samovar_h_source = (ROOT / "Samovar.h").read_text(encoding="utf-8")

    errors = []

    include_pos = find_include_pos(api_source)
    check_nothing_after(api_source, include_pos, errors)

    api_stripped = strip_cpp_comments(api_source)
    include_pos_stripped = find_include_pos(api_stripped)

    registry_code = strip_cpp_comments(registry_source)
    bodies_blob = "\n\n".join(
        f"{sig} {{{extract_function_body(registry_code, sig)}}}" for sig in BODY_SIGNATURES
    )

    names = used_identifiers(bodies_blob)
    found_decls = []  # (pos, line) вытащенных из samovar_api.h объявлений
    for name in names:
        pos = decl_pos(name, api_stripped)
        if pos < 0:
            continue  # объявлено не в samovar_api.h (enum/тип/локальное имя mode_registry.h) - не наша забота
        line = decl_line(api_stripped, pos)
        if pos > include_pos_stripped:
            errors.append(
                f'"{name}" объявлен в samovar_api.h ПОСЛЕ #include "mode_registry.h" '
                f"(строка: {line!r}) - mode_registry.h использует это имя, но к моменту "
                "его подключения объявления ещё не видно"
            )
            continue
        found_decls.append((pos, line))

    # SAMOVAR_LUA_ALARM_FN - макрос (не функция), используется в таблице как
    # bareword, поэтому не ловится сканом по "identifier(" выше - проверяем отдельно.
    macro_pos = api_stripped.find("#define SAMOVAR_LUA_ALARM_FN")
    if macro_pos < 0:
        errors.append("SAMOVAR_LUA_ALARM_FN: макрос не найден в samovar_api.h")
    elif macro_pos > include_pos_stripped:
        errors.append('SAMOVAR_LUA_ALARM_FN определён ПОСЛЕ #include "mode_registry.h"')
    check_alarm_lua_pos = decl_pos("check_alarm_lua", api_stripped)
    if check_alarm_lua_pos < 0:
        errors.append("check_alarm_lua: форвард-декларация не найдена в samovar_api.h")
    elif check_alarm_lua_pos > include_pos_stripped:
        errors.append('check_alarm_lua объявлен ПОСЛЕ #include "mode_registry.h"')

    # [WP17 п.45] SAMOVAR_NBK_BUILD_AVAILABLE / SAMOVAR_LUA_BUILD_AVAILABLE - тоже
    # object-like макросы-bareword'ы (buildAvailable в таблице режимов), не ловятся
    # сканом по "identifier(" выше по той же причине, что и SAMOVAR_LUA_ALARM_FN
    # (см. блок выше). Каждый определён дважды (#ifdef/#else true/false) - берём
    # ПОСЛЕДНЕЕ вхождение, чтобы поймать перестановку ЛЮБОЙ из двух веток после include.
    for macro_name in ("SAMOVAR_NBK_BUILD_AVAILABLE", "SAMOVAR_LUA_BUILD_AVAILABLE"):
        positions = [m.start() for m in re.finditer(rf"#define\s+{re.escape(macro_name)}\b", api_stripped)]
        if not positions:
            errors.append(f"{macro_name}: макрос не найден в samovar_api.h")
        elif max(positions) > include_pos_stripped:
            errors.append(f'{macro_name} определён ПОСЛЕ #include "mode_registry.h"')

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    found_decls.sort(key=lambda item: item[0])
    decl_lines = [line for _, line in found_decls]

    def enum_block_text() -> str:
        blocks = []
        for name in ("SAMOVAR_MODE", "SamovarCommands"):
            m = re.search(rf"enum\s+{name}\s*\{{[^}}]*\}}", samovar_h_source)
            if m is None:
                raise AssertionError(f"{name}: enum не найден в Samovar.h")
            blocks.append(m.group(0) + ";")
        return "\n".join(blocks)

    macro_block = (
        "#define SAMOVAR_LUA_ALARM_FN nullptr\n"
        "inline void check_alarm_lua();\n"
        "#define SAMOVAR_NBK_BUILD_AVAILABLE true\n"
        "#define SAMOVAR_LUA_BUILD_AVAILABLE true\n"
        # mode_alarm_beer() (real body, pulled in via BODY_SIGNATURES) calls this
        # helper. Its samovar_api.h forward declaration is `inline`, and an inline
        # function that is actually CALLED but never defined anywhere in this
        # translation unit is a real gcc diagnostic ("used but never defined") -
        # unlike every other name here, which is only ever used as a function-
        # pointer VALUE stored into the ops[] table, never called directly. Give it
        # a no-op body here (harness-only stub, never touches firmware) so that
        # diagnostic doesn't obscure the actual thing this test checks. This plays
        # no part in the include-order invariant: decl_lines still carries its real,
        # unmodified forward declaration from samovar_api.h, so the mutation below
        # (which may drop exactly that declaration) is unaffected by this stub.
        "inline void mode_request_water_flow_emergency_if_needed() {}\n"
    )

    enum_block = enum_block_text()

    with tempfile.TemporaryDirectory(prefix="samovar-mode-registry-include-order-") as tmp:
        work_dir = Path(tmp)

        harness_ok = assemble_harness(enum_block, decl_lines, macro_block, bodies_blob)
        result_ok = build_object(harness_ok, work_dir, "positive")
        if result_ok.returncode != 0:
            sys.stderr.write("FAIL: харнесс с полным набором реальных объявлений не собрался\n")
            sys.stderr.write(result_ok.stdout)
            sys.stderr.write(result_ok.stderr)
            return 1

        # Мутация: выбрасываем ОДНО из найденных объявлений (как будто include
        # переставили выше него) и убеждаемся, что сборка ломается.
        if not decl_lines:
            print("FAIL: не нашлось ни одного объявления для мутационной проверки", file=sys.stderr)
            return 1
        mutated_decls = decl_lines[1:]
        dropped = decl_lines[0]
        harness_mutated = assemble_harness(enum_block, mutated_decls, macro_block, bodies_blob)
        result_mutated = build_object(harness_mutated, work_dir, "mutated")
        if result_mutated.returncode == 0:
            print(
                f"FAIL: харнесс без объявления {dropped!r} собрался - проверка "
                "нечувствительна к порядку/наличию объявлений",
                file=sys.stderr,
            )
            return 1

    print(f"OK: {len(decl_lines)} forward-declaration(s) checked before mode_registry.h include")
    print("OK: mutation (dropped one declaration) correctly broke compilation")
    print("mode_registry.h include order smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
