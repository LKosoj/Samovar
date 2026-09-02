#!/usr/bin/env python3
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import (
    extract_braced_block_after,
    extract_function_body,
    require_ordered_tokens,
    strip_cpp_comments,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "Samovar.ino"


def extract_button_parts(source: str) -> tuple[str, str, str, str, str]:
    loop_body = strip_cpp_comments(extract_function_body(source, "void loop()"))
    button_start = loop_body.find("\n  btn.tick();")
    if button_start < 0:
        raise ValueError("loop(): обработчик основной кнопки не найден")
    button_start += 3
    button_end = loop_body.find("#endif", button_start)
    if button_end < 0:
        raise ValueError("loop(): конец BTN_PIN-блока не найден")
    button_block = loop_body[button_start:button_end]
    rect_body, rect_end = extract_braced_block_after(
        button_block, "if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE)"
    )
    hold_body, _ = extract_braced_block_after(
        rect_body, "if (mainButtonHeld && PowerOn"
    )
    click_body, _ = extract_braced_block_after(
        rect_body, "else if (mainButtonClicked)"
    )
    # [П12] Ветка ДЛЯ ОСТАЛЬНЫХ режимов (не ректификация) - идёт в button_block
    # ПОСЛЕ закрывающей скобки rect-блока (rect_end), поэтому поиск токенов
    # начинаем с этого смещения - иначе нашёлся бы "else if (mainButtonClicked)"
    # внутри самого rect_body (click_body выше), а не нужная нам ветка.
    non_rect_hold_body, non_rect_hold_end = extract_braced_block_after(
        button_block, "else if (mainButtonHeld)", rect_end
    )
    non_rect_click_body, _ = extract_braced_block_after(
        button_block, "else if (mainButtonClicked)", non_rect_hold_end
    )
    return button_block, rect_body, hold_body + "\n" + click_body, non_rect_hold_body, non_rect_click_body


def validate_source(source: str) -> list[str]:
    errors: list[str] = []
    setup_body = strip_cpp_comments(extract_function_body(source, "void setup()"))
    if setup_body.count("btn.setTimeout(2000);") != 1:
        errors.append("setup(): удержание основной кнопки должно быть ровно 2000 мс")

    try:
        button_block, rect_body, combined_action_bodies, non_rect_hold_body, non_rect_click_body = (
            extract_button_parts(source)
        )
    except ValueError as error:
        return errors + [str(error)]

    require_ordered_tokens(
        "loop() button events",
        button_block,
        [
            "btn.tick();",
            "const bool mainButtonHeld = btn.isHolded();",
            "const bool mainButtonClicked = btn.isClick();",
            "if (!mode_switch_in_progress())",
            "if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE)",
            "} else if (mainButtonHeld) {",
            "mode_dispatch_button_hold();",
            "} else if (mainButtonClicked) {",
            "mode_dispatch_button_press();",
        ],
        errors,
    )
    # [П12] Для остальных режимов удержание и короткий клик обязаны звать РАЗНЫЕ
    # диспетчеры реестра - одного лишь порядка токенов выше недостаточно, чтобы
    # поймать перепутывание местами (оба текста всё равно есть где-то в файле по
    # порядку), поэтому проверяем принадлежность вызова СВОЕЙ ветке.
    if "mode_dispatch_button_hold();" not in non_rect_hold_body:
        errors.append(
            "удержание вне ректификации должно звать mode_dispatch_button_hold()"
        )
    if "mode_dispatch_button_press();" in non_rect_hold_body:
        errors.append(
            "удержание вне ректификации не должно звать mode_dispatch_button_press()"
        )
    if "mode_dispatch_button_press();" not in non_rect_click_body:
        errors.append(
            "короткий клик вне ректификации должен звать mode_dispatch_button_press()"
        )
    if "mode_dispatch_button_hold();" in non_rect_click_body:
        errors.append(
            "короткий клик вне ректификации не должен звать mode_dispatch_button_hold()"
        )
    require_ordered_tokens(
        "rectification button actions",
        rect_body,
        [
            "if (mainButtonHeld && PowerOn",
            "startval != SAMOVAR_STARTVAL_IDLE",
            "startval != SAMOVAR_STARTVAL_CALIBRATION",
            "SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION",
            "menu_samovar_start();",
            "else if (mainButtonClicked)",
            "if (!PowerOn)",
            "set_power(true);",
            "pause_withdrawal(!PauseOn);",
        ],
        errors,
    )
    if "mainButtonPressed" in rect_body:
        errors.append("ректификация не должна выполнять короткое действие до отпускания")
    if combined_action_bodies.count("menu_samovar_start();") != 3:
        errors.append("ветки удержания и короткого клика изменили число переходов программы")
    return errors


HARNESS = r'''
#include <cstdint>
#include <iostream>

constexpr int16_t SAMOVAR_STARTVAL_IDLE = 0;
constexpr int16_t SAMOVAR_STARTVAL_RECT_RUNNING = 1;
constexpr int16_t SAMOVAR_STARTVAL_CALIBRATION = 100;
constexpr int16_t SAMOVAR_STATUS_RECT_WITHDRAWAL = 10;
constexpr int16_t SAMOVAR_STATUS_DISTILLATION = 1000;

bool PowerOn = true;
bool program_Pause = false;
bool program_Wait = false;
bool PauseOn = false;
int16_t startval = SAMOVAR_STARTVAL_RECT_RUNNING;
int16_t SamovarStatusInt = SAMOVAR_STATUS_RECT_WITHDRAWAL;

int setPowerCalls = 0;
int menuStartCalls = 0;
int pauseCalls = 0;
int calibrateCalls = 0;
int menuFocusCalls = 0;
bool lastPauseArg = false;

void set_power(bool enabled) {
  setPowerCalls++;
  PowerOn = enabled;
}

void menu_samovar_start() {
  menuStartCalls++;
  PauseOn = false;
  program_Pause = false;
  program_Wait = false;
}

void pause_withdrawal(bool paused) {
  pauseCalls++;
  lastPauseArg = paused;
  PauseOn = paused;
}

void menu_calibrate() {
  calibrateCalls++;
}

void menu_switch_focus() {
  menuFocusCalls++;
}

void handle_rect_button(bool mainButtonHeld, bool mainButtonClicked) {
@RECT_BODY@
}

int failures = 0;

void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

void reset_fixture() {
  PowerOn = true;
  program_Pause = false;
  program_Wait = false;
  PauseOn = false;
  startval = SAMOVAR_STARTVAL_RECT_RUNNING;
  SamovarStatusInt = SAMOVAR_STATUS_RECT_WITHDRAWAL;
  setPowerCalls = 0;
  menuStartCalls = 0;
  pauseCalls = 0;
  calibrateCalls = 0;
  menuFocusCalls = 0;
  lastPauseArg = false;
}

int main() {
  reset_fixture();
  handle_rect_button(false, true);
  check(pauseCalls == 1 && lastPauseArg, "короткий клик должен поставить активный отбор на паузу");
  check(menuStartCalls == 0, "короткий клик не должен пропускать обычную строку");

  reset_fixture();
  PauseOn = true;
  handle_rect_button(false, true);
  check(pauseCalls == 1 && !lastPauseArg, "короткий клик должен снять ручную паузу");
  check(menuStartCalls == 0, "снятие ручной паузы не должно менять строку");

  reset_fixture();
  program_Pause = true;
  handle_rect_button(false, true);
  check(menuStartCalls == 1, "короткий клик должен сохранить переход из программной паузы P");
  check(pauseCalls == 0, "строка P не должна переключать ручную паузу");

  reset_fixture();
  PauseOn = true;
  handle_rect_button(true, false);
  check(menuStartCalls == 1 && !PauseOn, "удержание должно перейти дальше и снять ручную паузу");
  check(pauseCalls == 0, "удержание не должно сначала возобновлять текущую строку");

  reset_fixture();
  program_Wait = true;
  handle_rect_button(true, false);
  check(menuStartCalls == 1 && !program_Wait, "удержание должно перейти дальше и снять автоматическую паузу");

  reset_fixture();
  handle_rect_button(true, true);
  check(menuStartCalls == 1, "удержание должно иметь приоритет над коротким кликом");
  check(pauseCalls == 0, "удержание не должно выполнять короткое действие");

  reset_fixture();
  startval = SAMOVAR_STARTVAL_IDLE;
  handle_rect_button(true, false);
  check(menuStartCalls == 0 && setPowerCalls == 0, "удержание в idle не должно запускать процесс");

  reset_fixture();
  PowerOn = false;
  handle_rect_button(true, false);
  check(menuStartCalls == 0 && setPowerCalls == 0, "удержание без нагрева не должно включать его");
  handle_rect_button(false, true);
  check(setPowerCalls == 1 && PowerOn, "короткий клик должен сохранить включение нагрева");

  reset_fixture();
  startval = SAMOVAR_STARTVAL_CALIBRATION;
  handle_rect_button(true, false);
  check(menuStartCalls == 0 && calibrateCalls == 0, "удержание не должно вмешиваться в калибровку");

  if (failures) return 1;
  std::cout << "rectification main-button long-press checks passed\n";
  return 0;
}
'''


def compile_and_run(rect_body: str) -> int:
    source = HARNESS.replace("@RECT_BODY@", rect_body)
    with tempfile.TemporaryDirectory(prefix="samovar-rect-button-") as temp_dir:
        temp = Path(temp_dir)
        cpp_path = temp / "rect_button_test.cpp"
        binary_path = temp / "rect_button_test"
        cpp_path.write_text(source, encoding="utf-8")
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
        if compile_result.returncode:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run(
            [str(binary_path)], capture_output=True, text=True, check=False
        )
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    source = SOURCE_PATH.read_text(encoding="utf-8")
    errors = validate_source(source)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    mutations = {
        "short hold timeout": source.replace(
            "btn.setTimeout(2000);", "btn.setTimeout(500);", 1
        ),
        "hold performs short action": source.replace(
            "if (mainButtonHeld && PowerOn", "if (mainButtonClicked && PowerOn", 1
        ),
        "short action on press": source.replace(
            "else if (mainButtonClicked) {", "else if (mainButtonPressed) {", 1
        ),
        "calibration is skippable": source.replace(
            "          startval != SAMOVAR_STARTVAL_CALIBRATION &&\n", "", 1
        ),
        "non-rect hold and click calls swapped": (
            source.replace("mode_dispatch_button_hold();", "@SWAP_TMP@", 1)
            .replace("mode_dispatch_button_press();", "mode_dispatch_button_hold();", 1)
            .replace("@SWAP_TMP@", "mode_dispatch_button_press();", 1)
        ),
    }
    for name, mutant in mutations.items():
        if not validate_source(mutant):
            print(f"FAIL: mutation survived: {name}", file=sys.stderr)
            return 1

    loop_body = strip_cpp_comments(extract_function_body(source, "void loop()"))
    button_start = loop_body.find("\n  btn.tick();") + 3
    button_end = loop_body.find("#endif", button_start)
    button_block = loop_body[button_start:button_end]
    rect_body, _ = extract_braced_block_after(
        button_block, "if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE)"
    )
    return compile_and_run(rect_body)


if __name__ == "__main__":
    raise SystemExit(main())
