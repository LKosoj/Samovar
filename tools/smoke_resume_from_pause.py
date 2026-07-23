#!/usr/bin/env python3
"""Регресс-проверка [P7 п.4/F5] resume_from_pause(): единая точка возобновления
после паузы (logic.h), используемая из трёх мест (Samovar.ino case
SAMOVAR_CONTINUE, Blynk.ino V13, Menu.ino menu_pause) вместо трёх независимых
копий одной и той же последовательности шагов, которые раньше расходились
(например, Blynk V13 вовсе не звал detector_on_manual_resume()).

[P7 F5] Раньше тело resume_from_pause() проверялось ЧИСТО ТЕКСТОВО
(require_ordered_tokens по исходнику функции) - такая проверка ищет подстроки
и не ловит поведенческие мутации (мёртвая ветка, ранний return после отказа
set_program_wait_type, переставленный порядок вызовов). Теперь тело
resume_from_pause() извлекается РЕАЛЬНЫМ образом (extract_function_body) и
компилируется в харнесс с не-static моками (pause_withdrawal,
set_program_wait_type, SendMsg, detector_on_manual_resume) - проверяется
фактическое поведение, а не текст:
  - pause_withdrawal(false) вызывается всегда;
  - t_min/program_Wait сбрасываются в 0/false всегда, независимо от исхода
    set_program_wait_type;
  - set_program_wait_type вызывается с PROGRAM_WAIT_NONE;
  - при отказе set_program_wait_type отправляется ровно одно WARNING_MSG с
    точным текстом;
  - detector_on_manual_resume() вызывается ВСЕГДА, в т.ч. при отказе
    set_program_wait_type (нет раннего return на отказе);
  - порядок вызовов зафиксирован (pause_withdrawal -> set_program_wait_type
    -> [SendMsg] -> detector_on_manual_resume).

Текстовая сверка трёх точек вызова (Samovar.ino case SAMOVAR_CONTINUE,
Blynk.ino V13, Menu.ino menu_pause) оставлена как есть - это уже не проверка
самого тела resume_from_pause(), а проверка того, что вызывающий код
действительно зовёт эту единую точку в правильном месте своей ветки.

[Ревью] Пакет П2 добавил ручную паузу пива (beerManualPause, гейтит нагрев в
beer.h), но её установка/снятие жили ТОЛЬКО инлайново в Samovar.ino
(case SAMOVAR_PAUSE/CONTINUE) - Menu.ino menu_pause() и Blynk.ino V13 звали
только pause_withdrawal(true) (no-op для пива), поэтому ручная пауза пива не
работала ни из LCD, ни из Blynk. Установка вынесена в новый общий хелпер
enter_manual_pause() (logic.h, рядом с resume_from_pause()), а снятие -
внутрь самого resume_from_pause() - теперь все три точки входа симметричны
и для паузы, и для возобновления. Ниже: (1) текстовые проверки всех трёх мест
вызова под новые хелперы (тонкие case-ветки в Samovar.ino, enter_manual_pause()
в Menu/Blynk, wasPaused учитывает beerManualPause), (2) поведенческие проверки
beer-ветки в resume_from_pause() тем же харнессом (не переписывая логику).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

FUNCTIONS = [
    "void resume_from_pause()",
]

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

using TickType_t = unsigned long;
#define pdMS_TO_TICKS(x) (x)

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum ProgramWaitType : uint8_t { PROGRAM_WAIT_NONE = 0, PROGRAM_WAIT_STEAM, PROGRAM_WAIT_PIPE, PROGRAM_WAIT_DETECTOR };

// Минимальный совместимый с Arduino String: только то, что реально нужно
// извлечённому телу (конструирование из const char*, чтение как std::string
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
unsigned long t_min = 0;
bool program_Wait = false;

// [Ревью] Минимальные моки для beer-ветки resume_from_pause() (снятие
// beerManualPause симметрично enter_manual_pause()).
enum SamovarModeEnum { SAMOVAR_RECTIFICATION_MODE = 0, SAMOVAR_BEER_MODE = 1 };
SamovarModeEnum Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
bool beerManualPause = false;

static std::vector<std::string> callOrder;

// --- Моки истинно внешних зависимостей (не-static) ---
static int pauseWithdrawalCalls = 0;
static bool lastPauseWithdrawalArg = true;
void pause_withdrawal(bool Pause) {
  pauseWithdrawalCalls++;
  lastPauseWithdrawalArg = Pause;
  callOrder.push_back("pause_withdrawal");
}

static bool setProgramWaitTypeReturn = true;
static int setProgramWaitTypeCalls = 0;
static ProgramWaitType lastSetProgramWaitTypeArg = PROGRAM_WAIT_STEAM;
bool set_program_wait_type(ProgramWaitType waitType, TickType_t timeout) {
  (void)timeout;
  setProgramWaitTypeCalls++;
  lastSetProgramWaitTypeArg = waitType;
  callOrder.push_back("set_program_wait_type");
  return setProgramWaitTypeReturn;
}

static int sendMsgCalls = 0;
static std::string lastSendMsgText;
static int lastSendMsgType = -1;
void SendMsg(const String& msg, int type) {
  sendMsgCalls++;
  lastSendMsgText = msg.str();
  lastSendMsgType = type;
  callOrder.push_back("SendMsg");
}

static int detectorOnManualResumeCalls = 0;
void detector_on_manual_resume() {
  detectorOnManualResumeCalls++;
  callOrder.push_back("detector_on_manual_resume");
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
  t_min = 123456;
  program_Wait = true;
  callOrder.clear();
  pauseWithdrawalCalls = 0;
  lastPauseWithdrawalArg = true;
  setProgramWaitTypeReturn = true;
  setProgramWaitTypeCalls = 0;
  lastSetProgramWaitTypeArg = PROGRAM_WAIT_STEAM;
  sendMsgCalls = 0;
  lastSendMsgText.clear();
  lastSendMsgType = -1;
  detectorOnManualResumeCalls = 0;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  beerManualPause = false;
}

int main() {
  // Сценарий 1: set_program_wait_type успешно сбрасывает тип паузы - без
  // предупреждения, детектор всё равно уведомлён о ручном возобновлении.
  reset_fixture();
  {
    resume_from_pause();
    check(pauseWithdrawalCalls == 1 && lastPauseWithdrawalArg == false, "1: pause_withdrawal(false) должен быть вызван ровно один раз");
    check(t_min == 0, "1: t_min должен быть сброшен в 0");
    check(program_Wait == false, "1: program_Wait должен быть сброшен в false");
    check(setProgramWaitTypeCalls == 1 && lastSetProgramWaitTypeArg == PROGRAM_WAIT_NONE, "1: set_program_wait_type должен быть вызван с PROGRAM_WAIT_NONE");
    check(sendMsgCalls == 0, "1: при успешном сбросе типа паузы предупреждение не отправляется");
    check(detectorOnManualResumeCalls == 1, "1: detector_on_manual_resume должен быть вызван ровно один раз");
    const std::vector<std::string> expectedOrder = {"pause_withdrawal", "set_program_wait_type", "detector_on_manual_resume"};
    check(callOrder == expectedOrder, "1: порядок вызовов должен быть pause_withdrawal -> set_program_wait_type -> detector_on_manual_resume");
  }

  // Сценарий 2: set_program_wait_type не смог захватить замок (false) -
  // предупреждение ДОЛЖНО быть отправлено, но detector_on_manual_resume всё
  // равно должен быть вызван (нет раннего return на отказе).
  reset_fixture();
  setProgramWaitTypeReturn = false;
  {
    resume_from_pause();
    check(pauseWithdrawalCalls == 1 && lastPauseWithdrawalArg == false, "2: pause_withdrawal(false) должен быть вызван ровно один раз даже при отказе set_program_wait_type");
    check(t_min == 0, "2: t_min должен быть сброшен в 0 даже при отказе set_program_wait_type");
    check(program_Wait == false, "2: program_Wait должен быть сброшен в false даже при отказе set_program_wait_type");
    check(sendMsgCalls == 1, "2: при отказе set_program_wait_type должно быть отправлено ровно одно предупреждение");
    check(lastSendMsgText == "Не удалось сбросить тип автоматической паузы.", "2: текст предупреждения должен быть точным");
    check(lastSendMsgType == WARNING_MSG, "2: предупреждение должно быть WARNING_MSG");
    check(detectorOnManualResumeCalls == 1, "2: detector_on_manual_resume должен быть вызван даже при отказе set_program_wait_type (нет раннего return)");
    const std::vector<std::string> expectedOrder = {"pause_withdrawal", "set_program_wait_type", "SendMsg", "detector_on_manual_resume"};
    check(callOrder == expectedOrder, "2: порядок вызовов должен включать SendMsg между set_program_wait_type и detector_on_manual_resume");
  }

  // [Ревью] Сценарий 3: режим пива, ручная пауза стоит (beerManualPause=true) -
  // resume_from_pause() обязан снять её и уведомить пользователя ровно одним
  // NOTIFY_MSG "Затирание продолжено.", ПОСЛЕ detector_on_manual_resume().
  reset_fixture();
  Samovar_Mode = SAMOVAR_BEER_MODE;
  beerManualPause = true;
  {
    resume_from_pause();
    check(beerManualPause == false, "3: resume_from_pause должен снять beerManualPause в режиме пива");
    check(sendMsgCalls == 1, "3: должно быть отправлено ровно одно уведомление о снятии паузы пива");
    check(lastSendMsgText == "Затирание продолжено.", "3: текст уведомления о снятии паузы пива должен быть точным");
    check(lastSendMsgType == NOTIFY_MSG, "3: уведомление о снятии паузы пива должно быть NOTIFY_MSG");
    const std::vector<std::string> expectedOrder = {"pause_withdrawal", "set_program_wait_type", "detector_on_manual_resume", "SendMsg"};
    check(callOrder == expectedOrder, "3: SendMsg о снятии паузы пива должен идти ПОСЛЕ detector_on_manual_resume");
  }

  // [Ревью] Сценарий 4 (симметрия/мутация): вне режима пива beerManualPause
  // трогать нельзя, даже если он почему-то true - иначе мутация "снимать
  // beerManualPause независимо от режима" осталась бы незамеченной.
  reset_fixture();
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  beerManualPause = true;
  {
    resume_from_pause();
    check(beerManualPause == true, "4: resume_from_pause не должен трогать beerManualPause вне режима пива");
    check(sendMsgCalls == 0, "4: вне режима пива не должно быть уведомления о снятии паузы пива");
  }

  if (failures != 0) return 1;
  std::cout << "resume_from_pause behaviour checks passed\n";
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
    with tempfile.TemporaryDirectory(prefix="samovar-resume-from-pause-") as temp_dir:
        temp = Path(temp_dir)
        cpp_source = temp / "resume_from_pause_test.cpp"
        binary = temp / "resume_from_pause_test"
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
    samovar_api = read_stripped("samovar_api.h")

    # --- Форвард-декларации в samovar_api.h ---
    if "void resume_from_pause();" not in samovar_api:
        errors.append("samovar_api.h: forward declaration of resume_from_pause() not found")
    if "void enter_manual_pause();" not in samovar_api:
        errors.append("samovar_api.h: forward declaration of enter_manual_pause() not found")

    # --- Samovar.ino: case SAMOVAR_PAUSE (тонкая ветка - тело в enter_manual_pause()) ---
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
            if "beerManualPause" in pause_block or "pause_withdrawal(true)" in pause_block:
                errors.append(
                    "Samovar.ino case SAMOVAR_PAUSE: логика ручной паузы (в т.ч. пива) не должна "
                    "дублироваться инлайново (должна быть только внутри enter_manual_pause())"
                )

    # --- Samovar.ino: case SAMOVAR_CONTINUE (тонкая ветка - снятие beerManualPause внутри resume_from_pause()) ---
    continue_start = samovar_ino.find("case SAMOVAR_CONTINUE:")
    if continue_start < 0:
        errors.append("Samovar.ino: case SAMOVAR_CONTINUE not found")
    else:
        next_case = samovar_ino.find("case SAMOVAR_SETBODYTEMP:", continue_start)
        if next_case < 0:
            errors.append("Samovar.ino: case SAMOVAR_SETBODYTEMP (next case after CONTINUE) not found")
        else:
            continue_block = samovar_ino[continue_start:next_case]
            require_ordered_tokens(
                "Samovar.ino case SAMOVAR_CONTINUE",
                continue_block,
                ["resume_from_pause();", "break;"],
                errors,
            )
            if "beerManualPause" in continue_block or "pause_withdrawal(false)" in continue_block:
                errors.append(
                    "Samovar.ino case SAMOVAR_CONTINUE: логика возобновления (в т.ч. пива) не должна "
                    "дублироваться инлайново (должна быть только внутри resume_from_pause())"
                )

    # --- Blynk.ino: BLYNK_WRITE(V13) ---
    try:
        v13_block, _ = extract_braced_block_after(blynk_ino, "BLYNK_WRITE(V13)")
    except ValueError as error:
        errors.append(str(error))
        v13_block = ""

    if v13_block:
        require_ordered_tokens(
            "Blynk.ino BLYNK_WRITE(V13)",
            v13_block,
            [
                "if (PauseOn",
                "beerManualPause",
                "resume_from_pause();",
                "enter_manual_pause();",
            ],
            errors,
        )

    # --- Menu.ino: menu_pause() ---
    try:
        menu_pause_body = extract_function_body(menu_ino, "void menu_pause()")
    except ValueError as error:
        errors.append(str(error))
        menu_pause_body = ""

    if menu_pause_body:
        require_ordered_tokens(
            "Menu.ino menu_pause",
            menu_pause_body,
            [
                "wasPaused",
                "= PauseOn",
                "beerManualPause",
                "if (wasPaused)",
                "resume_from_pause();",
                "enter_manual_pause();",
            ],
            errors,
        )
        if "if (PauseOn)" in menu_pause_body:
            errors.append(
                "Menu.ino menu_pause: ветвление должно идти по СТАРОМУ значению (wasPaused), "
                "а не заново читать PauseOn после его возможной мутации"
            )

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    # --- Реальное поведение resume_from_pause() (logic.h), через компилируемый харнесс ---
    try:
        harness = build_harness(logic_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    result = compile_and_run(harness)
    if result != 0:
        return result

    print("resume_from_pause smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
