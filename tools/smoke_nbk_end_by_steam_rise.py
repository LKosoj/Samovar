#!/usr/bin/env python3
"""Поведенческая проверка [T4-2026-09-03]: компилируемая опция
USE_NBK_END_BY_STEAM_RISE (п.5 отчёта) - доп. признак конца браги: завершать
Работу НБК, когда Тп выросла на NBK_END_STEAM_RISE относительно минимума,
зафиксированного в Работе (не в паузе), дольше 2*Ин.

Тест вытаскивает РЕАЛЬНЫЙ #ifdef-блок из тела check_nbk_critical_alarms()
(без переписывания логики) и компилирует его с #define USE_NBK_END_BY_STEAM_RISE
- харнесс сам включает опцию, обычная (не флагованная) сборка её не видит.

extract_function_body() уже прогоняет strip_cpp_comments(), поэтому искать
"#ifdef USE_NBK_END_BY_STEAM_RISE" через find() без учёта позиции нельзя:
в теле функции этот же #define стоит ДВАЖДЫ - первый раз в раннем return
(сброс nbk_steam_rise_start при выходе из режима, [T4] п.1.4 плана), второй
раз - основной блок логики роста Тп (п.1.5 плана), который нужен здесь.
Поэтому extract_steam_rise_block берёт ПОСЛЕДНЕЕ вхождение якоря.

Сценарии A-F:
  A) минимум фиксируется на первом тике W (80) и опускается при снижении (78).
  B) рост +4.9 (меньше порога 5.0) - таймер не взводится.
  C) рост ровно +5.0 (граница >=) - таймер взводится = millis(); за 1мс до
     истечения 2*Ин завершения ещё нет, сообщений/команд нет.
  D) истечение 2*Ин+1мс - завершение (true), 1 SendMsg, 1 queue_samovar_command,
     0 request_emergency_stop.
  D2) очередь команд отклоняет - завершение всё равно true, но
      request_emergency_stop вызывается 1 раз.
  E) пауза Работы (nbk_work_in_pause) - рост Тп не копит время (таймер держится
     на нуле), минимум не трогается; после выхода из паузы первый тик с
     всё ещё большой Тп не завершает мгновенно, а заново взводит таймер.
  F) типы 'H' и 'O' (не W) - блок молчит: таймер 0, минимум не фиксируется.
  G) Тп после взвода таймера откатилась ниже минимум+5 (оставаясь на W вне
     паузы) - внутренний else сбрасывает таймер; повторный рост взводит его
     заново от нового millis().
  H) текстовый пин: при входе в строку O сбрасываются nbk_steam_min и
     nbk_steam_rise_start (после повторной Оптимизации рабочая точка Тп другая).

Мутации (все обязаны провалить этот же харнесс/сценарии):
  1) ">=" -> ">" в пороге роста (ломает граничную часть сценария C - таймер
     не взводится ровно на +5.0).
  2) "> 2*Ин" -> "if (true)" (ломает сценарий C - завершение раньше срока).
  3) в ветке else (не-W либо пауза) добавлен nbk_steam_min = 0; (ломает
     сценарий E - минимум не должен меняться в паузе).
  4) во внутреннем else (рост прекратился) убран сброс таймера (ломает
     сценарий G - таймер обязан обнулиться при откате Тп).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "bool check_nbk_critical_alarms"
IFDEF_ANCHOR = "#ifdef USE_NBK_END_BY_STEAM_RISE"

# Мутация 1: ">=" -> ">" у порога роста Тп.
THRESHOLD_MUTATION_ANCHOR = "if (steamTemp >= nbk_steam_min + NBK_END_STEAM_RISE) {"

# Мутация 2: удержание 2*Ин заменяется на безусловное срабатывание.
DWELL_MUTATION_ANCHOR = "if (millis() - nbk_steam_rise_start > uint32_t(2) * nbk_column_inertia * 1000) {"

# Мутация 3: в ветке "не W либо пауза" минимум начинает сбрасываться вместе
# с таймером. Якорь - многострочный, с комментарием: короткая подстрока
# "nbk_steam_rise_start = 0;" не уникальна в файле (встречается ещё в раннем
# return [T4 п.1.4] и во внутреннем else того же блока).
ELSE_BRANCH_MUTATION_ANCHOR = (
    "    } else {\n"
    "      // Не строка W либо пауза после захлёба — временный рост Тп из-за снижения\n"
    "      // подачи/мощности не должен копить время до срабатывания; минимум НЕ трогаем\n"
    "      // (он взят до захлёба и остаётся опорным после паузы).\n"
    "      nbk_steam_rise_start = 0;\n"
    "    }\n"
)


# Мутация 4: внутренний else (рост Тп прекратился, всё ещё W вне паузы) перестаёт
# сбрасывать таймер. Якорь - многострочный: включает закрывающую скобку
# if-ветки и начало внешнего else, чтобы не спутать с другими сбросами.
INNER_ELSE_MUTATION_ANCHOR = (
    "      } else {\n"
    "        nbk_steam_rise_start = 0;\n"
    "      }\n"
    "    } else {\n"
)

O_ENTRY_ANCHOR = "if (program[ProgramNum].WType == 'O') {"


def extract_steam_rise_block(nbk_source: str) -> str:
    body = extract_function_body(nbk_source, SIGNATURE)  # уже strip_cpp_comments
    occurrences = body.count(IFDEF_ANCHOR)
    if occurrences != 2:
        raise ValueError(
            f"expected exactly 2 occurrences of {IFDEF_ANCHOR!r} in check_nbk_critical_alarms "
            f"(сброс на раннем return [T4 п.1.4] + основная логика [T4 п.1.5]), найдено {occurrences}"
        )
    start = body.rfind(IFDEF_ANCHOR)  # последнее вхождение - основной блок логики
    end = body.find("#endif", start)
    if end < 0:
        raise ValueError("closing #endif for steam-rise block not found")
    end += len("#endif")
    return body[start:end]


HEADER = r'''
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <string>

#define USE_NBK_END_BY_STEAM_RISE
#define NBK_END_STEAM_RISE 5.0f

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum SamovarCommands { SAMOVAR_NONE, SAMOVAR_POWER };

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
'''

STRING_CLASS = r'''
class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(float value, int precision) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.*f", precision, static_cast<double>(value));
    value_ = buf;
  }
  String operator+(const char* rhs) const { return String((value_ + (rhs ? rhs : "")).c_str()); }
  String operator+(const String& rhs) const { return String((value_ + rhs.value_).c_str()); }
  String& operator+=(const char* rhs) { value_ += (rhs ? rhs : ""); return *this; }
  String& operator+=(const String& rhs) { value_ += rhs.value_; return *this; }
  void reserve(size_t) {}
  bool contains(const char* needle) const { return value_.find(needle) != std::string::npos; }
 private:
  explicit String(const std::string& value) : value_(value) {}
  std::string value_;
};
'''


def build_harness(nbk_source: str) -> str:
    block = extract_steam_rise_block(nbk_source)
    wrapped = "static bool tick(char currentType) {\n" + block + "\n  return false;\n}\n"
    return HEADER + STRING_CLASS + r'''
struct SensorProbe { float avgTemp; };
static SensorProbe SteamSensor = {0.0f};

bool nbk_work_in_pause = false;
uint16_t nbk_column_inertia = 180;
float nbk_steam_min = 0;
uint32_t nbk_steam_rise_start = 0;

static uint32_t fakeMillis = 1000;
uint32_t millis() { return fakeMillis; }

static bool queueShouldSucceed = true;
static int queueCalls = 0;
bool queue_samovar_command(SamovarCommands) {
  queueCalls++;
  return queueShouldSucceed;
}

static int emergencyCalls = 0;
void request_emergency_stop(const String&) { emergencyCalls++; }

static int sendMsgCalls = 0;
static String lastMsg;
void SendMsg(const String& msg, MESSAGE_TYPE) {
  sendMsgCalls++;
  lastMsg = msg;
}

''' + wrapped + r'''

static void reset_fixture() {
  fakeMillis = 1000;
  SteamSensor.avgTemp = 0.0f;
  nbk_work_in_pause = false;
  nbk_column_inertia = 180;
  nbk_steam_min = 0;
  nbk_steam_rise_start = 0;
  queueShouldSucceed = true;
  queueCalls = 0;
  emergencyCalls = 0;
  sendMsgCalls = 0;
  lastMsg = String("");
}

int main() {
  const uint32_t dwellMs = 2u * static_cast<uint32_t>(nbk_column_inertia) * 1000u;

  // A: минимум фиксируется на первом тике W и опускается при снижении Тп.
  reset_fixture();
  SteamSensor.avgTemp = 80.0f;
  check(!tick('W'), "A: первый тик W не должен завершать программу");
  check(nbk_steam_min == 80.0f, "A: минимум обязан зафиксироваться на первом тике W (80)");
  check(nbk_steam_rise_start == 0, "A: таймер не должен взводиться при первом тике (роста относительно себя нет)");

  SteamSensor.avgTemp = 78.0f;
  check(!tick('W'), "A: снижение Тп не должно завершать программу");
  check(nbk_steam_min == 78.0f, "A: минимум обязан опуститься до нового меньшего значения (78)");

  // B: рост +4.9 (меньше порога 5.0) - таймер не взводится.
  reset_fixture();
  SteamSensor.avgTemp = 80.0f;
  tick('W'); // фиксирует минимум = 80
  SteamSensor.avgTemp = 84.9f;
  check(!tick('W'), "B: рост +4.9 меньше порога 5.0 не должен завершать");
  check(nbk_steam_rise_start == 0, "B: таймер не должен взводиться при росте меньше порога");

  // C: рост ровно +5.0 (граница >=) - таймер взводится = millis(); за 1мс до
  // истечения 2*Ин завершения ещё нет, сообщений/команд нет.
  reset_fixture();
  SteamSensor.avgTemp = 80.0f;
  tick('W'); // минимум = 80
  fakeMillis = 2000;
  SteamSensor.avgTemp = 85.0f; // ровно +5.0 от минимума
  check(!tick('W'), "C: на тике взвода таймера завершение ещё не должно произойти");
  check(nbk_steam_rise_start == 2000, "C: таймер обязан взвестись = текущему millis() при достижении порога (>=)");

  fakeMillis = 2000 + dwellMs - 1;
  check(!tick('W'), "C: за 1мс до истечения 2*Ин завершение НЕ должно произойти");
  check(sendMsgCalls == 0, "C: сообщений быть не должно");
  check(queueCalls == 0, "C: команд в очередь быть не должно");

  // D: истечение 2*Ин+1мс - завершение, 1 SendMsg, 1 queue, 0 emergency.
  fakeMillis = 2000 + dwellMs + 1;
  check(tick('W'), "D: истечение 2*Ин дольше порога обязано завершить программу");
  check(sendMsgCalls == 1, "D: обязано уйти ровно одно сообщение");
  check(queueCalls == 1, "D: обязана уйти ровно одна команда SAMOVAR_POWER в очередь");
  check(emergencyCalls == 0, "D: аварийный останов не должен вызываться при успешной постановке в очередь");
  check(lastMsg.contains("Тп выросла"), "D: сообщение обязано упоминать рост Тп");

  // D2: очередь команд отклоняет - завершение всё равно true, но emergency 1.
  reset_fixture();
  queueShouldSucceed = false;
  SteamSensor.avgTemp = 80.0f;
  tick('W'); // минимум = 80
  fakeMillis = 1000;
  SteamSensor.avgTemp = 85.0f;
  tick('W'); // взводит таймер = 1000
  fakeMillis = 1000 + dwellMs + 1;
  check(tick('W'), "D2: истечение таймера обязано вернуть true независимо от результата очереди");
  check(queueCalls == 1, "D2: попытка постановки в очередь обязана произойти");
  check(emergencyCalls == 1, "D2: отказ очереди обязан вызвать аварийный останов ровно один раз");

  // E: пауза Работы - рост Тп не копит время, минимум не трогается; после
  // выхода из паузы первый тик заново взводит таймер, а не завершает сразу.
  reset_fixture();
  SteamSensor.avgTemp = 80.0f;
  tick('W'); // минимум = 80 (не в паузе)
  nbk_work_in_pause = true;
  SteamSensor.avgTemp = 200.0f;
  for (int i = 0; i < 3; i++) {
    fakeMillis += 1000000;
    check(!tick('W'), "E: в паузе рост Тп не должен приводить к завершению");
    check(nbk_steam_rise_start == 0, "E: в паузе таймер обязан оставаться на нуле");
    check(nbk_steam_min == 80.0f, "E: в паузе минимум не должен меняться");
  }
  nbk_work_in_pause = false;
  fakeMillis += 1000;
  check(!tick('W'), "E: первый тик после паузы не должен завершать программу мгновенно");
  check(nbk_steam_rise_start == fakeMillis, "E: таймер после паузы обязан взвестись заново = текущему millis()");

  // F: типы 'H' и 'O' (не W) - блок молчит, минимум не фиксируется.
  reset_fixture();
  SteamSensor.avgTemp = 200.0f;
  check(!tick('H'), "F: тип H не должен обрабатываться логикой роста Тп");
  check(nbk_steam_rise_start == 0, "F: таймер для типа H обязан оставаться на нуле");
  check(nbk_steam_min == 0.0f, "F: минимум для типа H не должен фиксироваться");

  reset_fixture();
  SteamSensor.avgTemp = 200.0f;
  check(!tick('O'), "F: тип O не должен обрабатываться логикой роста Тп");
  check(nbk_steam_rise_start == 0, "F: таймер для типа O обязан оставаться на нуле");
  check(nbk_steam_min == 0.0f, "F: минимум для типа O не должен фиксироваться");

  // G: откат Тп ниже минимум+5 после взвода таймера (W, не пауза) - таймер
  // сбрасывается внутренним else; повторный рост взводит его заново.
  reset_fixture();
  SteamSensor.avgTemp = 80.0f;
  tick('W'); // минимум = 80
  fakeMillis = 2000;
  SteamSensor.avgTemp = 85.0f;
  check(!tick('W'), "G: взвод таймера не должен завершать программу");
  check(nbk_steam_rise_start == 2000, "G: таймер обязан взвестись = 2000");
  fakeMillis = 2500;
  SteamSensor.avgTemp = 83.0f; // +3 < порога 5 - рост прекратился
  check(!tick('W'), "G: откат Тп не должен завершать программу");
  check(nbk_steam_rise_start == 0, "G: при откате Тп ниже порога таймер обязан сброситься");
  check(nbk_steam_min == 80.0f, "G: минимум при откате не меняется (83 > 80)");
  fakeMillis = 3000;
  SteamSensor.avgTemp = 85.0f;
  check(!tick('W'), "G: повторный взвод не должен завершать программу");
  check(nbk_steam_rise_start == 3000, "G: повторный рост обязан взвести таймер заново от нового millis()");

  if (failures != 0) return 1;
  std::cout << "nbk end-by-steam-rise checks (A-G) passed\n";
  return 0;
}
'''


def compile_and_run(harness: str, label: str, emit: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-steam-rise-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "test.cpp"
        binary = temp / "test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            if emit:
                sys.stderr.write(f"[{label}] compile failed:\n")
                sys.stderr.write(compile_result.stdout)
                sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if emit:
            sys.stdout.write(f"[{label}] ")
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode


def mutate_threshold(nbk_source: str) -> str:
    if THRESHOLD_MUTATION_ANCHOR not in nbk_source:
        raise ValueError("mutation anchor missing: steam-rise threshold >=")
    mutated_anchor = THRESHOLD_MUTATION_ANCHOR.replace(
        "steamTemp >= nbk_steam_min", "steamTemp > nbk_steam_min", 1
    )
    return nbk_source.replace(THRESHOLD_MUTATION_ANCHOR, mutated_anchor, 1)


def mutate_dwell(nbk_source: str) -> str:
    if DWELL_MUTATION_ANCHOR not in nbk_source:
        raise ValueError("mutation anchor missing: steam-rise 2*Ин dwell condition")
    return nbk_source.replace(DWELL_MUTATION_ANCHOR, "if (true) {", 1)


def mutate_else_branch(nbk_source: str) -> str:
    if ELSE_BRANCH_MUTATION_ANCHOR not in nbk_source:
        raise ValueError("mutation anchor missing: else-branch (not-W / pause) block")
    mutated_anchor = ELSE_BRANCH_MUTATION_ANCHOR.replace(
        "      nbk_steam_rise_start = 0;\n    }\n",
        "      nbk_steam_rise_start = 0;\n      nbk_steam_min = 0;\n    }\n",
        1,
    )
    return nbk_source.replace(ELSE_BRANCH_MUTATION_ANCHOR, mutated_anchor, 1)


def mutate_inner_else(nbk_source: str) -> str:
    if INNER_ELSE_MUTATION_ANCHOR not in nbk_source:
        raise ValueError("mutation anchor missing: inner else (steam rise stopped) timer reset")
    mutated_anchor = INNER_ELSE_MUTATION_ANCHOR.replace("        nbk_steam_rise_start = 0;\n", "", 1)
    return nbk_source.replace(INNER_ELSE_MUTATION_ANCHOR, mutated_anchor, 1)


def check_o_entry_reset_pin(nbk_source: str) -> None:
    stripped = strip_cpp_comments(nbk_source)
    block = extract_braced_block_after(stripped, O_ENTRY_ANCHOR)[0]
    for token in ("nbk_steam_min = 0;", "nbk_steam_rise_start = 0;"):
        if token not in block:
            raise ValueError(f"O-entry reset pin missing: {token!r} in block after {O_ENTRY_ANCHOR!r}")


def main() -> int:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")

    try:
        check_o_entry_reset_pin(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    try:
        rc = compile_and_run(build_harness(nbk_source), "nbk end-by-steam-rise", True)
        if rc != 0:
            return rc
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    mutations = [
        ("threshold >= -> >", mutate_threshold),
        ("dwell 2*Ин -> if (true)", mutate_dwell),
        ("else-branch resets nbk_steam_min too", mutate_else_branch),
        ("inner else drops timer reset", mutate_inner_else),
    ]
    for name, mutate_fn in mutations:
        try:
            mutated = mutate_fn(nbk_source)
        except ValueError as error:
            print(f"FAIL: {error}", file=sys.stderr)
            return 1
        if mutated == nbk_source:
            print(f"FAIL: mutation had no effect: {name}", file=sys.stderr)
            return 1
        try:
            mutated_harness = build_harness(mutated)
        except ValueError as error:
            print(f"FAIL: mutation broke extraction unexpectedly [{name}]: {error}", file=sys.stderr)
            return 1
        if compile_and_run(mutated_harness, f"mutation [{name}]", False) == 0:
            print(f"FAIL: mutation survived (expected failure): {name}", file=sys.stderr)
            return 1

    print("nbk end-by-steam-rise checks (A-G behaviour + O-entry pin + 4 mutations) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
