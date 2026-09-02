#!/usr/bin/env python3
"""[В4/В5] Число 68 в строке предзахлёба трёх шаблонов не запинено НИЧЕМ.

data_raw/program_fruit.txt, program_grain.txt, program_shugar.txt содержат строку вида
"5;1.1;40;C;3;68" (шугар: "4;1.1;10;C;3;68") - последние два поля это дельта в вольтах
(3) и дельта в ваттах (68) от последней АБСОЛЮТНОЙ уставки. В шаблонах перед этой строкой
идут две паузы на 173 В и 170 В (см. соседние "0;200;0;P;173;1969"/"0;200;0;P;170;1901") -
68 это разница мощностей ЭТАЛОННОГО ТЭНа (3480 Вт при 230 В) между 173 В и 170 В, и её
считает РЕАЛЬНАЯ formula programVoltsToWatts() из data_raw/program.htm (та же, что рисует
6-ю колонку файла программы в браузере): watts(173) - watts(170) с mainsVolt=230,
heaterMaxPwr=3480.

Число посчитано верно, но раньше ничем не удерживалось - будущая правка могла тихо
заменить его на произвольную заглушку, и никакой тест бы не покраснел.

Проверка:
1. Ожидаемая дельта пересчитана НЕЗАВИСИМО в Python по документированной формуле
   P(V) = round(3480 * (V/230)**2) - без обращения к коду страницы - и сверена с
   жёстким 68 (самопроверка формулы, зафиксированной здесь). Требует только Python.
2. Все три шаблона содержат СТРОКУ (не закомментированную - паттерн начинается с цифры,
   комментарии в этих файлах начинаются с '#') с этим значением в 6-м поле. Требует
   только Python.
3. Тело programVoltsToWatts() вытаскивается из data_raw/program.htm РЕАЛЬНЫМ кодом
   (extract_function_body, как в tools/smoke_program_power_row.py) и выполняется в Node
   с mainsVolt=230 - это ловит изменение САМОЙ ФОРМУЛЫ в program.htm. Требует node.

Проверки 1 и 2 НЕ требуют Node и выполняются ВСЕГДА (раньше отсутствие node на PATH
снимало ВЕСЬ тест целиком через ранний `raise SystemExit(0)` внутри общей check() - даже
эти две проверки, которым node не нужен). Проверка 3 требует node: при его отсутствии
тест печатает "SMOKE_SKIP: ..." (конвенция tools/run_smoke_tests.py - см. также
tools/smoke_calibrate_save.py) и пропускает только её - если проверки 1/2 при этом ОК,
тест завершается кодом 0 и учитывается в сводке run_smoke_tests.py как SKIP, а не PASS,
то есть частичный пропуск не маскируется под полный успех.

Мутации (запускаются main() на временных копиях, не трогая рабочие файлы):
  (а) "68" -> "70" в одном шаблоне - должно покраснеть (число разошлось с формулой).
      Не требует node - проверяется независимо от того, доступен ли он: check()
      всегда сверяет шаблоны с независимым пересчётом (проверка 1/2 выше).
  (б) в programVoltsToWatts() убрать возведение в квадрат (ratio*ratio -> ratio) -
      формула перестаёт давать 68 - должно покраснеть (формула разошлась с шаблонами).
      Требует node (мутирует и исполняет JS-код program.htm); без node пропускается
      со своим SMOKE_SKIP-сообщением - без node её попросту нельзя исполнить.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
PROGRAM_PAGE = ROOT / "data_raw" / "program.htm"
TEMPLATE_PATHS = [
    ROOT / "data_raw" / "program_fruit.txt",
    ROOT / "data_raw" / "program_grain.txt",
    ROOT / "data_raw" / "program_shugar.txt",
]

FUNC_SIGNATURE = "function programVoltsToWatts(volts, heaterMaxPwr)"

# Строка предзахлёба: capacity;speed;percent;C;voltDelta(3);wattDelta(?). '^\d' не
# матчит строки-комментарии этих файлов (они начинаются с '#').
PREFLOOD_ROW = re.compile(r"^\d+;[\d.]+;\d+;C;3;(\d+)$", re.MULTILINE)

REFERENCE_MAINS_VOLT = 230
REFERENCE_HEATER_WATT = 3480
HIGH_VOLT = 173
LOW_VOLT = 170
EXPECTED_DELTA = 68

DRIVER_TEMPLATE = r'''
"use strict";
var mainsVolt = __MAINS__;
@SNIPPET@
var high = programVoltsToWatts(__HIGH__, __HEATER__);
var low = programVoltsToWatts(__LOW__, __HEATER__);
process.stdout.write(JSON.stringify({ high: high, low: low, delta: high - low }));
'''


def node_computed_delta(program_html_text: str) -> int:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node executable not found on PATH")
    body = extract_function_body(program_html_text, FUNC_SIGNATURE)
    snippet = FUNC_SIGNATURE + " {" + body + "}"
    driver = (
        DRIVER_TEMPLATE
        .replace("@SNIPPET@", snippet)
        .replace("__MAINS__", str(REFERENCE_MAINS_VOLT))
        .replace("__HIGH__", str(HIGH_VOLT))
        .replace("__LOW__", str(LOW_VOLT))
        .replace("__HEATER__", str(REFERENCE_HEATER_WATT))
    )
    with tempfile.TemporaryDirectory(prefix="samovar-preflood-watts-") as tmp:
        driver_path = Path(tmp) / "driver.js"
        driver_path.write_text(driver, encoding="utf-8")
        result = subprocess.run(
            [node, str(driver_path)], capture_output=True, text=True, check=False
        )
    if result.returncode != 0:
        raise RuntimeError(f"node driver failed (exit {result.returncode}): {result.stderr}")
    return json.loads(result.stdout)["delta"]


def independent_expected_delta() -> int:
    """Пересчёт по документированной формуле, независимый от кода program.htm."""

    def js_round(value: float) -> int:
        # Math.round округляет половину В БОЛЬШУЮ сторону (в отличие от python
        # round(), который банковское округление) - для этих конкретных чисел
        # разницы нет, но воспроизводим точную семантику, а не совпадение.
        import math

        return int(math.floor(value + 0.5))

    def watts(volts: float) -> int:
        ratio = volts / REFERENCE_MAINS_VOLT
        return js_round(REFERENCE_HEATER_WATT * ratio * ratio)

    return watts(HIGH_VOLT) - watts(LOW_VOLT)


def template_row_values(template_texts: dict[str, str]) -> dict[str, list[str]]:
    return {
        name: PREFLOOD_ROW.findall(text) for name, text in template_texts.items()
    }


def check(program_html_text: str, template_texts: dict[str, str], node_available: bool) -> list[str]:
    """Проверки 1 (независимый пересчёт) и 2 (шаблоны) выполняются ВСЕГДА - им node
    не нужен. Проверка 3 (реальная JS-формула из program.htm) выполняется только
    если node_available, иначе тихо пропускается (не считается ошибкой)."""
    errors: list[str] = []

    expected = independent_expected_delta()
    if expected != EXPECTED_DELTA:
        errors.append(
            f"independent recompute changed: expected {EXPECTED_DELTA}, formula now gives {expected} "
            "(update EXPECTED_DELTA only if the reference heater/voltages in the spec changed)"
        )

    if node_available:
        try:
            actual = node_computed_delta(program_html_text)
        except (RuntimeError, ValueError) as error:
            errors.append(f"programVoltsToWatts() in program.htm could not be evaluated: {error}")
            actual = None

        if actual is not None and actual != expected:
            errors.append(
                f"data_raw/program.htm::programVoltsToWatts({HIGH_VOLT},{REFERENCE_HEATER_WATT}) - "
                f"programVoltsToWatts({LOW_VOLT},{REFERENCE_HEATER_WATT}) = {actual}, "
                f"expected {expected} (formula in program.htm changed)"
            )

    rows = template_row_values(template_texts)
    for name, values in rows.items():
        if not values:
            errors.append(f"{name}: no 'capacity;speed;percent;C;3;<watts>' row found")
            continue
        if len(values) > 1:
            errors.append(f"{name}: expected exactly one such row, found {len(values)}: {values}")
            continue
        found = int(values[0])
        if found != expected:
            errors.append(f"{name}: pre-flood row watt delta is {found}, expected {expected}")

    return errors


def load_real_inputs() -> tuple[str, dict[str, str]]:
    program_html_text = PROGRAM_PAGE.read_text(encoding="utf-8")
    template_texts = {
        path.name: path.read_text(encoding="utf-8") for path in TEMPLATE_PATHS
    }
    return program_html_text, template_texts


def main() -> int:
    for path in [PROGRAM_PAGE, *TEMPLATE_PATHS]:
        if not path.exists():
            print(f"FAIL: {path} not found", file=sys.stderr)
            return 1

    program_html_text, template_texts = load_real_inputs()
    node_available = shutil.which("node") is not None

    # Текстовые/числовые проверки (1 и 2) не требуют node - выполняются всегда,
    # даже если node недоступен. Раньше отсутствие node снимало их тоже (ранний
    # raise SystemExit(0) внутри node_computed_delta прерывал всю check()).
    errors = check(program_html_text, template_texts, node_available)
    if not node_available:
        print(
            "SMOKE_SKIP: node executable not found on PATH - "
            "programVoltsToWatts() JS reference check (проверка 3) was not run"
        )
    if errors:
        print("Program pre-flood reference-heater watts smoke failed:", file=sys.stderr)
        for error in errors:
            print(f" - {error}", file=sys.stderr)
        return 1

    # ---- Мутация (а): число в шаблоне расходится с формулой - не требует node,
    # обязана красить тест независимо от того, доступен ли он ----
    mutated_templates = dict(template_texts)
    fruit_name = "program_fruit.txt"
    original_row = "5;1.1;40;C;3;68"
    if original_row not in mutated_templates[fruit_name]:
        print(f"FAIL: mutation anchor not found in {fruit_name}: {original_row!r}", file=sys.stderr)
        return 1
    mutated_templates[fruit_name] = mutated_templates[fruit_name].replace(
        original_row, "5;1.1;40;C;3;70", 1
    )
    mutant_a_errors = check(program_html_text, mutated_templates, node_available)
    if not mutant_a_errors:
        print(
            "FAIL: mutation (68 -> 70 in program_fruit.txt) survived - "
            "a silently changed template constant would no longer be caught",
            file=sys.stderr,
        )
        return 1

    # ---- Мутация (б): формула в program.htm расходится с шаблонами - требует
    # node (мутирует и исполняет JS); без node её нельзя провести ----
    if node_available:
        original_formula = "var ratio = volts / mainsVolt;\n  return Math.round(heaterMaxPwr * ratio * ratio);"
        if original_formula not in program_html_text:
            print(f"FAIL: mutation anchor not found in program.htm: {original_formula!r}", file=sys.stderr)
            return 1
        mutated_program_html = program_html_text.replace(
            original_formula,
            "var ratio = volts / mainsVolt;\n  return Math.round(heaterMaxPwr * ratio);",
            1,
        )
        mutant_b_errors = check(mutated_program_html, template_texts, node_available)
        if not mutant_b_errors:
            print(
                "FAIL: mutation (dropped squaring in programVoltsToWatts) survived - "
                "a formula change in program.htm would no longer be caught",
                file=sys.stderr,
            )
            return 1
    else:
        print(
            "SMOKE_SKIP: node executable not found on PATH - "
            "formula-drift mutation (б) was not exercised (it mutates and runs JS)"
        )

    print("Program pre-flood reference-heater watts smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
