#!/usr/bin/env python3
"""Поведенческая проверка П68: напоминание про хмель работает на flame-out.

[Находка] Раньше и сообщение "Засыпьте хмель!", и HopStepperStep() требовали
program_type_at(ProgramNum + 1) == 'B' - то есть срабатывали, только если
СЛЕДУЮЩАЯ строка программы тоже кипячение. Это ломало flame-out (внесение
хмеля на выключение варки, без второй строки 'B' после текущей) - штатный
приём в пивоварении/дистилляции, а не ошибка программы. От повторного
срабатывания и так защищает флаг msgfl (взводится при входе в КАЖДУЮ строку
в run_beer_program(), гасится внутри самого условия) - от типа следующей
строки это не зависит, поэтому условие можно было просто убрать.

Тест извлекает РЕАЛЬНЫЙ код из beer.h:
  - блок определения начала кипения (msgfl=true/begintime=millis());
  - напоминание про хмель (условие БЕЗ program_type_at(...+1)=='B');
  - нижний переход на следующую строку;
  - beer_stage_elapsed_ms() (тот же общий хелпер из П1).
run_beer_program() не извлекается (это огромная функция с посторонними для
П68 зависимостями - Lua, автотюн, клапана) - вместо неё стоит счётчик-стаб,
а вход в новую строку эмулирует РЕАЛЬНЫЙ код входа (begintime=0; msgfl=true;
resetBoilingDetector() при несмежном 'B'), тоже извлечённый из run_beer_program.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

BOIL_DETECT_TOKEN = "if (begintime == 0) {\n      //Определяем начало кипения"
HOP_REMINDER_TOKEN = "if (begintime > 0 && msgfl && (beer_stage_elapsed_ms(millis())"
BOTTOM_TRANSITION_TOKEN = "if (begintime > 0 && (currentType == 'B' || currentType == 'P')"
ROW_ENTRY_RESET_TOKEN = (
    "if (program[ProgramNum].WType == 'B' &&\n"
    "      (ProgramNum == 0 || program_type_at(ProgramNum - 1) != 'B')) {"
)

HARNESS_TEMPLATE = r'''
#include <iostream>
#include <string>

using ProgramType = char;
struct WProgram { ProgramType WType; float Time; };

constexpr int NOTIFY_MSG = 2;
constexpr int PROGRAM_MAX = 4;

static WProgram program[PROGRAM_MAX];
static unsigned char ProgramNum = 0;
static unsigned long begintime = 0;
static bool msgfl = false;
static float temp = 0.0f;
static unsigned long beerStageIdleAccumMs = 0;
static unsigned long fakeMillis = 0;
unsigned long millis() { return fakeMillis; }

static bool boilingReached = false;
bool isBoilingStarted(float) { return boilingReached; }

// [П13] Таймаут разгона до кипения задействован извлечённым кодом
// (см. tools/smoke_beer_boil_cooling_timeout.py про его поведение отдельно).
#define BEER_BOIL_TIMEOUT_MS (120UL * 60UL * 1000UL)
static unsigned long beerBoilActiveAccumMs = 0;
static int abortCalls = 0;
void beer_abort_config_error(const char*) { abortCalls++; }

static int sendMsgCalls = 0;
void SendMsg(const char*, int) { sendMsgCalls++; }

static int buzzerCalls = 0;
void set_buzzer(bool) { buzzerCalls++; }

static int hopStepperCalls = 0;
void HopStepperStep() { hopStepperCalls++; }

static int resetBoilingDetectorCalls = 0;
void resetBoilingDetector() { resetBoilingDetectorCalls++; }

static ProgramType typeAt[PROGRAM_MAX];
ProgramType program_type_at(unsigned char index) { return typeAt[index]; }

static int runBeerProgramCalls = 0;
static int lastRunBeerProgramArg = -1;
void run_beer_program(unsigned char num) {
  runBeerProgramCalls++;
  lastRunBeerProgramArg = num;
}

@ELAPSED@

// Тик по строке 'B' - реальный код (детекция кипения + напоминание про хмель).
static void run_boil_row_tick() {
@CONTINUE_GLUE@
  if (begintime == 0) {
@BOIL_DETECT@
  }
@HOP_REMINDER@
}

// Реальный код нижнего перехода на следующую строку.
static void run_bottom_transition(ProgramType currentType) {
@BOTTOM_TRANSITION@
}

// Реальный код входа в строку (из run_beer_program): begintime=0, msgfl=true,
// и сброс детектора/накопителя ТОЛЬКО на несмежной 'B'.
static void enter_row(unsigned char num) {
  ProgramNum = num;
  begintime = 0;
  msgfl = true;
@ROW_ENTRY_RESET@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // Сценарий 1: одна строка 'B', за ней 'C' (без строки-затычки).
  // HopStepperStep() должен сработать РОВНО один раз, msgfl погашен.
  program[0].WType = 'B'; program[0].Time = 10.0f; // 10 минут
  program[1].WType = 'C'; program[1].Time = 5.0f;
  typeAt[0] = 'B'; typeAt[1] = 'C';
  fakeMillis = 0;
  boilingReached = false;
  hopStepperCalls = 0;
  runBeerProgramCalls = 0;
  beerBoilActiveAccumMs = 0;
  abortCalls = 0;
  enter_row(0);
  check(resetBoilingDetectorCalls == 1, "вход в первую строку 'B' должен сбросить детектор кипения");

  // Тик 1: фиксируем начало кипения. millis() должен быть НЕ нулевым - иначе
  // begintime = millis() совпадёт со значением-часовым "строка ещё не начата".
  fakeMillis = 1000;
  boilingReached = true;
  run_boil_row_tick();
  check(begintime != 0, "после фиксации кипения begintime должен быть установлен");
  check(msgfl == true, "msgfl должен остаться true сразу после фиксации кипения (хмель ещё не досыпан)");
  check(hopStepperCalls == 0, "хмель не должен досыпаться раньше времени строки");

  // Тик 2: время строки истекло (10 минут = 600000 мс от begintime).
  fakeMillis = begintime + 600000UL;
  run_boil_row_tick();
  check(hopStepperCalls == 1, "РЕГРЕСС (П68): напоминание про хмель на единственной строке 'B' (за ней 'C') должно сработать");
  check(msgfl == false, "после срабатывания напоминания msgfl должен быть погашен (защита от повтора)");

  // Ещё несколько тиков без входа в новую строку не должны досыпать хмель повторно.
  run_boil_row_tick();
  run_boil_row_tick();
  check(hopStepperCalls == 1, "РЕГРЕСС: напоминание про хмель не должно повторяться, пока msgfl погашен");

  // Нижний переход - variable currentType='B', Time истекло -> уходим на 'C'.
  run_bottom_transition('B');
  check(runBeerProgramCalls == 1, "по истечении времени строки должен быть вызван переход на следующую строку");
  check(lastRunBeerProgramArg == 1, "переход должен указывать на строку 1 ('C')");

  // Сценарий 2: две строки 'B' подряд - напоминание срабатывает на КАЖДОЙ,
  // msgfl взводится заново при входе во вторую строку.
  program[0].WType = 'B'; program[0].Time = 10.0f;
  program[1].WType = 'B'; program[1].Time = 10.0f;
  program[2].WType = 'C'; program[2].Time = 5.0f;
  typeAt[0] = 'B'; typeAt[1] = 'B'; typeAt[2] = 'C';
  fakeMillis = 0;
  boilingReached = false;
  hopStepperCalls = 0;
  resetBoilingDetectorCalls = 0;
  runBeerProgramCalls = 0;
  beerBoilActiveAccumMs = 0;
  abortCalls = 0;

  enter_row(0);
  fakeMillis = 1000;
  boilingReached = true;
  run_boil_row_tick(); // фиксируем начало кипения на строке 0
  fakeMillis = begintime + 600000UL;
  run_boil_row_tick();
  check(hopStepperCalls == 1, "РЕГРЕСС (П68): напоминание про хмель должно сработать на первой из двух строк 'B'");
  check(msgfl == false, "msgfl должен быть погашен после первого напоминания");

  run_bottom_transition('B');
  check(lastRunBeerProgramArg == 1, "после первой строки 'B' переход должен указывать на вторую строку 'B'");

  // Вход во вторую строку 'B' - смежная с первой 'B', поэтому детектор кипения
  // НЕ сбрасывается (продолжаем то же кипячение), но msgfl взводится заново.
  enter_row(1);
  check(msgfl == true, "РЕГРЕСС (П68): msgfl должен быть заново взведён при входе во вторую строку 'B'");
  check(resetBoilingDetectorCalls == 1, "смежная строка 'B'->'B' не должна сбрасывать детектор кипения повторно");

  // "Продолжаем кипятить" - склейка выставляет begintime сразу (без повторной детекции).
@CONTINUE_GLUE_CHECK@

  run_boil_row_tick(); // begintime уже > 0, детекция кипения повторно не идёт
  check(hopStepperCalls == 1, "на входе во вторую строку хмель ещё не должен досыпаться повторно");

  fakeMillis = begintime + 600000UL;
  run_boil_row_tick();
  check(hopStepperCalls == 2, "РЕГРЕСС (П68): напоминание про хмель должно сработать и на второй строке 'B'");

  if (failures != 0) return 1;
  std::cout << "beer hop flameout (П68) behaviour checks passed\n";
  return 0;
}
'''


def compile_and_run(harness: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-hop-flameout-") as temp_dir:
        source = Path(temp_dir) / "beer_hop_flameout.cpp"
        binary = Path(temp_dir) / "beer_hop_flameout"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-O1", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode:
            return compiled.returncode, compiled.stdout + compiled.stderr
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        return ran.returncode, ran.stdout + ran.stderr


def main() -> int:
    beer = (ROOT / "beer.h").read_text(encoding="utf-8")
    try:
        # strip_comments=False здесь и ниже: BOIL_DETECT_TOKEN использует текст
        # комментария как landmark, чтобы отличить нужный "if (begintime == 0)"
        # от 4 других таких же условий в beer.h - без комментария неоднозначно.
        # Текстовые проверки на реальный код ниже всё равно идут по
        # strip_cpp_comments(...), чтобы закомментированный код их не обманул.
        stage_body = extract_function_body(beer, "void beer_stage_tick()", strip_comments=False)
        b_branch, _ = extract_braced_block_after(
            stage_body, "if (currentType == 'B') {", strip_comments=False
        )

        continue_glue_token = (
            "if (begintime == 0 && ProgramNum > 0 && program_type_at(ProgramNum - 1) == 'B') begintime = millis();"
        )
        if continue_glue_token not in strip_cpp_comments(b_branch):
            raise ValueError(f"continue-glue line not found: {continue_glue_token}")

        boil_detect, _ = extract_braced_block_after(b_branch, BOIL_DETECT_TOKEN)

        hop_start = b_branch.find(HOP_REMINDER_TOKEN)
        if hop_start < 0:
            raise ValueError(f"hop reminder token not found: {HOP_REMINDER_TOKEN}")
        _, hop_end = extract_braced_block_after(b_branch, HOP_REMINDER_TOKEN)
        hop_reminder = strip_cpp_comments(b_branch[hop_start:hop_end])
        if "program_type_at(ProgramNum + 1)" in hop_reminder:
            raise ValueError(
                "hop reminder still gates on the next row's type (П68 not applied)"
            )

        bottom_start = stage_body.find(BOTTOM_TRANSITION_TOKEN)
        if bottom_start < 0:
            raise ValueError(f"bottom transition token not found: {BOTTOM_TRANSITION_TOKEN}")
        _, bottom_end = extract_braced_block_after(stage_body, BOTTOM_TRANSITION_TOKEN)
        bottom_transition = stage_body[bottom_start:bottom_end]

        run_beer_program_body = extract_function_body(beer, "void run_beer_program(")
        entry_start = run_beer_program_body.find(ROW_ENTRY_RESET_TOKEN)
        if entry_start < 0:
            raise ValueError(f"row-entry reset token not found: {ROW_ENTRY_RESET_TOKEN}")
        _, entry_end = extract_braced_block_after(run_beer_program_body, ROW_ENTRY_RESET_TOKEN)
        row_entry_reset = run_beer_program_body[entry_start:entry_end]

        elapsed_helper = extract_function_body(beer, "inline float beer_stage_elapsed_ms(unsigned long nowMs) {")
        elapsed_full = "inline float beer_stage_elapsed_ms(unsigned long nowMs) {" + elapsed_helper + "}"
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    harness = (
        HARNESS_TEMPLATE.replace("@ELAPSED@", elapsed_full)
        .replace("@CONTINUE_GLUE@", "  " + continue_glue_token)
        .replace("@BOIL_DETECT@", boil_detect)
        .replace("@HOP_REMINDER@", hop_reminder)
        .replace("@BOTTOM_TRANSITION@", bottom_transition)
        .replace("@ROW_ENTRY_RESET@", row_entry_reset)
        .replace(
            "@CONTINUE_GLUE_CHECK@",
            "  run_boil_row_tick();\n"
            "  check(begintime != 0, \"склейка 'B'->'B' должна сразу выставить begintime без повторной детекции\");",
        )
    )
    code, output = compile_and_run(harness)
    sys.stdout.write(output)
    if code:
        return code

    # Мутация: возвращаем условие "следующая строка тоже 'B'" - тест обязан упасть,
    # потому что в сценарии 1 следующая строка - 'C'.
    mutant = harness.replace(
        HOP_REMINDER_TOKEN,
        "if (begintime > 0 && msgfl && program_type_at(ProgramNum + 1) == 'B' && (beer_stage_elapsed_ms(millis())",
        1,
    )
    if mutant == harness:
        print("FAIL: не удалось создать мутацию (вернуть условие по следующей строке)", file=sys.stderr)
        return 1
    code, output = compile_and_run(mutant)
    if code == 0:
        print("FAIL: мутация (возврат условия по следующей строке) пережила тест", file=sys.stderr)
        sys.stderr.write(output)
        return 1
    print("Beer hop flameout next-row-type mutation was rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
