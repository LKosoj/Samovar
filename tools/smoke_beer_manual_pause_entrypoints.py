#!/usr/bin/env python3
"""Регресс-проверка [Ревью] enter_manual_pause() (logic.h) и трёх точек входа
ручной паузы: Samovar.ino (case SAMOVAR_PAUSE), Blynk.ino (BLYNK_WRITE(V13)),
Menu.ino (menu_pause()).

[Находка] Пакет П2 добавил ручную паузу пива (beerManualPause, гейтит нагрев в
beer.h) только инлайново в Samovar.ino case SAMOVAR_PAUSE/CONTINUE. Menu.ino
menu_pause() и Blynk.ino BLYNK_WRITE(V13) звали только pause_withdrawal(true),
которая для пива - no-op (ранний return при Samovar_Mode != SAMOVAR_RECTIFICATION_MODE):
на LCD надпись менялась на "Continue", а варка продолжала греть; в Blynk -
тихий no-op. Фикс выносит установку ручной паузы в общий хелпер
enter_manual_pause() (logic.h, рядом с resume_from_pause()), которым теперь
пользуются все три точки входа.

Этот файл проверяет:
  1. Текстово - все три точки входа зовут именно enter_manual_pause() (а не
     инлайн pause_withdrawal(true) + copy-paste beer-ветки).
  2. Поведенчески - РЕАЛЬНОЕ тело enter_manual_pause() извлекается из logic.h
     (extract_function_body, без переписывания логики) и компилируется в
     харнесс с не-static моками (pause_withdrawal, SendMsg, current_program_type):
       - beer-ветка не потеряна: в режиме пива, при startval выше порога и вне
         автокалибровки, beerManualPause выставляется в true и отправляется
         ровно один NOTIFY_MSG с точным текстом;
       - автокалибровка ПИД ('A') блокирует ручную паузу отдельным WARNING_MSG,
         beerManualPause не трогается;
       - повторный вызов при уже установленной beerManualPause не шлёт второе
         уведомление (идемпотентность подстраховки от двойного нажатия);
       - вне режима пива (ректификация) beer-ветка целиком пропускается, но
         pause_withdrawal(true) всё равно вызывается (безусловно, первой
         строкой) - её собственный guard на режим уже проверяется в logic.h::pause_withdrawal
         (smoke_resume_from_pause.py), тут не дублируется;
       - startval не выше порога SAMOVAR_STARTVAL_BEER_START - beer-ветка тоже
         пропускается (сессия ещё не дошла до стадии, где нагрев вообще идёт).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

FUNCTIONS = [
    "void enter_manual_pause()",
]

HARNESS_TEMPLATE = r'''
#include <iostream>
#include <string>

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum SamovarModeEnum { SAMOVAR_RECTIFICATION_MODE = 0, SAMOVAR_BEER_MODE = 1 };

class String {
public:
  String() : data_() {}
  String(const char* s) : data_(s ? s : "") {}
  const std::string& str() const { return data_; }
private:
  std::string data_;
};

// --- Глобальное состояние, которым управляют сценарии ---
SamovarModeEnum Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
static const int16_t SAMOVAR_STARTVAL_BEER_START = 2000;
int16_t startval = 0;
bool beerManualPause = false;
static char programTypeStub = 'M';

// --- Моки истинно внешних зависимостей (не-static) ---
static int pauseWithdrawalCalls = 0;
static bool lastPauseWithdrawalArg = false;
void pause_withdrawal(bool Pause) {
  pauseWithdrawalCalls++;
  lastPauseWithdrawalArg = Pause;
}

static int sendMsgCalls = 0;
static std::string lastSendMsgText;
static int lastSendMsgType = -1;
void SendMsg(const String& msg, int type) {
  sendMsgCalls++;
  lastSendMsgText = msg.str();
  lastSendMsgType = type;
}

char current_program_type() {
  return programTypeStub;
}

@FUNCTIONS@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  startval = 0;
  beerManualPause = false;
  programTypeStub = 'M';
  pauseWithdrawalCalls = 0;
  lastPauseWithdrawalArg = false;
  sendMsgCalls = 0;
  lastSendMsgText.clear();
  lastSendMsgType = -1;
}

int main() {
  // Сценарий 1: пиво, сессия за порогом старта, обычный тип строки (не 'A') -
  // ручная пауза должна реально встать: beerManualPause=true, ровно одно
  // NOTIFY_MSG с точным текстом. [Находка] Это и есть та самая beer-ветка,
  // ранее не вызывавшаяся из Menu/Blynk.
  reset_fixture();
  Samovar_Mode = SAMOVAR_BEER_MODE;
  startval = SAMOVAR_STARTVAL_BEER_START + 1;
  programTypeStub = 'M';
  {
    enter_manual_pause();
    check(pauseWithdrawalCalls == 1 && lastPauseWithdrawalArg == true, "1: pause_withdrawal(true) должен быть вызван ровно один раз");
    check(beerManualPause == true, "1: beerManualPause должен быть выставлен в true");
    check(sendMsgCalls == 1, "1: должно быть отправлено ровно одно уведомление");
    check(lastSendMsgText == "Затирание поставлено на паузу.", "1: текст уведомления должен быть точным");
    check(lastSendMsgType == NOTIFY_MSG, "1: уведомление должно быть NOTIFY_MSG");
  }

  // Сценарий 2: автокалибровка ПИД ('A') - пауза недоступна, отдельное
  // WARNING_MSG, beerManualPause НЕ трогается.
  reset_fixture();
  Samovar_Mode = SAMOVAR_BEER_MODE;
  startval = SAMOVAR_STARTVAL_BEER_START + 1;
  programTypeStub = 'A';
  {
    enter_manual_pause();
    check(beerManualPause == false, "2: автокалибровка ПИД не должна выставлять beerManualPause");
    check(sendMsgCalls == 1, "2: должно быть отправлено ровно одно предупреждение");
    check(lastSendMsgText == "Пауза недоступна во время автокалибровки ПИД.", "2: текст предупреждения должен быть точным");
    check(lastSendMsgType == WARNING_MSG, "2: предупреждение должно быть WARNING_MSG");
  }

  // Сценарий 3: повторный вызов при уже установленной паузе - идемпотентно,
  // второго уведомления быть не должно (защита от двойного нажатия кнопки).
  reset_fixture();
  Samovar_Mode = SAMOVAR_BEER_MODE;
  startval = SAMOVAR_STARTVAL_BEER_START + 1;
  programTypeStub = 'M';
  beerManualPause = true;
  {
    enter_manual_pause();
    check(beerManualPause == true, "3: beerManualPause должен остаться true");
    check(sendMsgCalls == 0, "3: повторный вызов не должен слать уведомление снова");
  }

  // Сценарий 4 (мутация "убери beer-ветку"): вне режима пива beer-ветка не
  // выполняется вовсе, но pause_withdrawal(true) всё равно вызывается
  // безусловно (её собственный guard на режим - в logic.h::pause_withdrawal).
  reset_fixture();
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  startval = SAMOVAR_STARTVAL_BEER_START + 1;
  {
    enter_manual_pause();
    check(pauseWithdrawalCalls == 1 && lastPauseWithdrawalArg == true, "4: pause_withdrawal(true) должен быть вызван безусловно");
    check(beerManualPause == false, "4: вне режима пива beerManualPause не должен трогаться");
    check(sendMsgCalls == 0, "4: вне режима пива уведомлений быть не должно");
  }

  // Сценарий 5: пиво, но сессия ЕЩЁ НЕ дошла до порога старта (startval не
  // выше SAMOVAR_STARTVAL_BEER_START) - beer-ветка тоже пропускается.
  reset_fixture();
  Samovar_Mode = SAMOVAR_BEER_MODE;
  startval = SAMOVAR_STARTVAL_BEER_START;
  {
    enter_manual_pause();
    check(beerManualPause == false, "5: ниже порога старта beerManualPause не должен выставляться");
    check(sendMsgCalls == 0, "5: ниже порога старта уведомлений быть не должно");
  }

  if (failures != 0) return 1;
  std::cout << "enter_manual_pause behaviour checks passed\n";
  return 0;
}
'''


def build_harness(source: str) -> str:
    code = strip_cpp_comments(source)
    bodies = []
    for signature in FUNCTIONS:
        body = extract_function_body(code, signature)
        bodies.append(f"{signature} {{{body}}}")
    return HARNESS_TEMPLATE.replace("@FUNCTIONS@", "\n\n".join(bodies))


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-enter-manual-pause-") as temp_dir:
        temp = Path(temp_dir)
        cpp_source = temp / "enter_manual_pause_test.cpp"
        binary = temp / "enter_manual_pause_test"
        cpp_source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                str(cpp_source), "-o", str(binary),
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


def read_stripped(name: str) -> str:
    return strip_cpp_comments((ROOT / name).read_text(encoding="utf-8"))


def main() -> int:
    errors: list[str] = []

    logic_source = (ROOT / "logic.h").read_text(encoding="utf-8")
    samovar_ino = read_stripped("Samovar.ino")
    blynk_ino = read_stripped("Blynk.ino")
    menu_ino = read_stripped("Menu.ino")

    # --- Samovar.ino: case SAMOVAR_PAUSE зовёт enter_manual_pause() ---
    pause_start = samovar_ino.find("case SAMOVAR_PAUSE:")
    if pause_start < 0:
        errors.append("Samovar.ino: case SAMOVAR_PAUSE not found")
    else:
        continue_case = samovar_ino.find("case SAMOVAR_CONTINUE:", pause_start)
        if continue_case < 0:
            errors.append("Samovar.ino: case SAMOVAR_CONTINUE (next case after PAUSE) not found")
        else:
            pause_block = samovar_ino[pause_start:continue_case]
            require_ordered_tokens(
                "Samovar.ino case SAMOVAR_PAUSE",
                pause_block,
                ["enter_manual_pause();", "break;"],
                errors,
            )

    # --- Blynk.ino: BLYNK_WRITE(V13) зовёт enter_manual_pause() в else-ветке ---
    try:
        v13_block, _ = extract_braced_block_after(blynk_ino, "BLYNK_WRITE(V13)")
    except ValueError as error:
        errors.append(str(error))
        v13_block = ""
    if v13_block and "enter_manual_pause();" not in v13_block:
        errors.append("Blynk.ino BLYNK_WRITE(V13): enter_manual_pause() not called")

    # --- Menu.ino: menu_pause() зовёт enter_manual_pause() в else-ветке ---
    try:
        menu_pause_body = extract_function_body(menu_ino, "void menu_pause()")
    except ValueError as error:
        errors.append(str(error))
        menu_pause_body = ""
    if menu_pause_body and "enter_manual_pause();" not in menu_pause_body:
        errors.append("Menu.ino menu_pause(): enter_manual_pause() not called")

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    # --- Реальное поведение enter_manual_pause() (logic.h), через компилируемый харнесс ---
    try:
        harness = build_harness(logic_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    result = compile_and_run(harness)
    if result != 0:
        return result

    print("enter_manual_pause entrypoints smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
