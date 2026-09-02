#!/usr/bin/env python3
"""[П10] run_dist_program() должна применять ёмкость/напряжение ПОСЛЕДНЕЙ строки
программы дистилляции - но только строки, реально входящей в ТЕКУЩУЮ программу.

До правки П10 функция выходила раньше (ранний return в ветке "программы
закончились", num >= ProgramLen), не доходя до блока
set_capacity()/apply_program_power_row() для program[num - 1]. Практическое
следствие: когда отбор проходит последнюю строку программы (вызов
run_dist_program(ProgramLen)), ёмкость и напряжение, заданные ЭТОЙ последней
строкой, никогда не применялись - хвосты продолжали течь в ёмкость
предпоследней строки.

Правка П10 перенесла блок в начало функции БЕЗУСЛОВНО (при любом num > 0), не
заметив третьего вызывающего - SAMOVAR_DIST_NEXT (Samovar.ino), который шлёт
run_dist_program(ProgramNum + 1) без проверки ProgramNum < ProgramLen. Повторное
нажатие "следующая строка" после того, как программа уже закончилась, даёт
num - 1 == ProgramLen - индекс строки, которая НЕ входит в текущую программу и
может хранить "хвостовые" значения от прошлой, более длинной программы (если
program_commit() не обнулил их целиком).

Тест компилирует РЕАЛЬНЫЕ тела run_dist_program() (distiller.h) и
program_commit() (program_io.h) через extract_function_body в изолированном
харнессе с замоканными set_capacity/apply_program_power_row/SendMsg и проверяет:
  1) переход ЗА последнюю строку (num == ProgramLen) - обязан применить поля
     program[ProgramLen - 1] (последней строки);
  2) обычный переход между строками (num < ProgramLen) - применяет поля
     предыдущей строки, как и раньше;
  3) самый первый вызов (num == 0, старт программы) - ёмкость/напряжение не трогает;
  4) [defect] повторное нажатие ПОСЛЕ конца программы (num == ProgramLen + 1,
     ProgramNum уже стоит на ProgramLen) - строка num - 1 не входит в программу,
     ёмкость/напряжение переключаться не должны, даже если в program[ProgramLen]
     лежат "чужие" значения;
  5) [defect] program_commit() должен обнулять удаляемые строки ЦЕЛИКОМ, а не
     только WType - после укорачивания программы старые capacity_num/Power не
     должны переживать commit.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "void run_dist_program(uint8_t num)"
COMMIT_SIGNATURE = "void program_commit(const ProgramDraft& draft)"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

#define SAMOVAR_USE_POWER 1

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };

struct String {
  std::string s;
  String() {}
  String(const char* value) : s(value) {}
  String(int value) : s(std::to_string(value)) {}
  String operator+(const String& other) const { String r; r.s = s + other.s; return r; }
};
static String operator+(const char* left, const String& right) {
  String r; r.s = std::string(left) + right.s; return r;
}

using ProgramType = char;
static const ProgramType PROGRAM_TYPE_NONE = 0;
struct WProgram { ProgramType WType = PROGRAM_TYPE_NONE; uint8_t capacity_num = 0; float Power = 0; };
static bool program_type_empty(ProgramType value) { return value == PROGRAM_TYPE_NONE; }

static const uint8_t PROGRAM_END = 8;
struct ProgramDraft { WProgram rows[PROGRAM_END]; uint8_t len = 0; };

static WProgram program[PROGRAM_END];
static uint8_t ProgramLen = 0;
static uint8_t ProgramNum = 0;

struct TimePredictor {
  unsigned long startTime = 0;
  float initialAlcohol = 0;
  float initialSteamAlcohol = 0;
  float initialTemp = 0;
  unsigned long lastUpdateTime = 0;
  float remainingTime = 0;
  float rowPredictedTotalTime = 0;
  bool rowPredictionAvailable = false;
  bool baselineValid = false;
};
static TimePredictor timePredictor;

enum DistPredictionReason { DIST_PREDICTION_AWAITING_BOIL = 0, DIST_PREDICTION_COLLECTING };
static DistPredictionReason distRowPredictionReason = DIST_PREDICTION_AWAITING_BOIL;

struct Sensor { float avgTemp = 0; float StartProgTemp = 0; };
static Sensor TankSensor, SteamSensor, PipeSensor, WaterSensor;

static bool distBoostGated = false;

static unsigned long fakeMillis = 0;
static unsigned long millis() { return fakeMillis; }
static float get_alcohol(float t) { return 100.0f - t; }
static float get_steam_alcohol(float t) { return 100.0f - t; }

static int capacityCalls = 0;
static uint8_t lastCapacity = 255;
static void set_capacity(uint8_t cap) { capacityCalls++; lastCapacity = cap; }

static int powerCalls = 0;
static float lastPower = -999.0f;
static void apply_program_power_row(float power) { powerCalls++; lastPower = power; }

static void heater_boost_output_off() {}

static int sendMsgCalls = 0;
static std::string lastMsg;
static void SendMsg(const String& message, MESSAGE_TYPE) { sendMsgCalls++; lastMsg = message.s; }

// [T29] program_commit() теперь пишет program[]/ProgramLen под спинлоком configMux.
using portMUX_TYPE = int;
static portMUX_TYPE configMux = 0;
#define portENTER_CRITICAL(mux) do { (void)(mux); } while (0)
#define portEXIT_CRITICAL(mux) do { (void)(mux); } while (0)

@RUN_DIST_PROGRAM_BODY@

@PROGRAM_COMMIT_BODY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}

static void reset_mocks() {
  capacityCalls = 0;
  lastCapacity = 255;
  powerCalls = 0;
  lastPower = -999.0f;
  sendMsgCalls = 0;
  lastMsg.clear();
}

int main() {
  // Программа из двух строк: последняя строка (индекс 1) задаёт СВОЮ ёмкость/напряжение.
  program[0].WType = 'T'; program[0].capacity_num = 1; program[0].Power = 10.0f;
  program[1].WType = 'T'; program[1].capacity_num = 2; program[1].Power = 20.0f;
  ProgramLen = 2;

  // [П10] Переход ЗА последнюю строку - как реальный вызов run_dist_program(ProgramNum+1)
  // при ProgramNum == ProgramLen - 1 (последняя строка только что завершилась).
  ProgramNum = 1;
  reset_mocks();
  run_dist_program(2);
  check(capacityCalls == 1, "переход за последнюю строку обязан применить её ёмкость");
  check(lastCapacity == 2, "должна примениться ёмкость ИМЕННО последней строки (program[1]), а не предыдущей");
  check(powerCalls == 1, "переход за последнюю строку обязан применить её напряжение");
  check(lastPower == 20.0f, "должно примениться напряжение ИМЕННО последней строки (program[1])");
  check(ProgramNum == ProgramLen, "ProgramNum должен встать в ProgramLen после конца программы");
  check(sendMsgCalls == 1, "должно уйти ровно одно сообщение о завершении программ");

  // Обычный переход со строки 0 на строку 1 (num=1 < ProgramLen=2): применяются
  // поля ЗАВЕРШИВШЕЙСЯ строки 0, как и раньше.
  ProgramNum = 0;
  reset_mocks();
  run_dist_program(1);
  check(capacityCalls == 1, "обычный переход строки должен применить ёмкость завершившейся строки");
  check(lastCapacity == 1, "обычный переход должен применить ёмкость program[0]");
  check(powerCalls == 1, "обычный переход строки должен применить напряжение завершившейся строки");
  check(lastPower == 10.0f, "обычный переход должен применить напряжение program[0]");
  check(ProgramNum == 1, "ProgramNum должен стать 1");

  // Самый первый вызов - старт программы, num == 0: предыдущей строки нет,
  // ёмкость/напряжение трогать нельзя (иначе program[-1] - обращение за границу).
  ProgramNum = 0;
  reset_mocks();
  run_dist_program(0);
  check(capacityCalls == 0, "старт программы (num=0) не должен трогать ёмкость");
  check(powerCalls == 0, "старт программы (num=0) не должен трогать напряжение");
  check(ProgramNum == 0, "ProgramNum должен остаться 0 на старте");

  // [defect] Повторное нажатие "следующая строка" ПОСЛЕ того, как программа уже
  // закончилась: SAMOVAR_DIST_NEXT (Samovar.ino) шлёт run_dist_program(ProgramNum + 1)
  // БЕЗ проверки ProgramNum < ProgramLen. ProgramNum уже стоит на ProgramLen (2),
  // поэтому num = 3, а num - 1 = 2 = ProgramLen - строка, НЕ входящая в текущую
  // программу. program[2] намеренно захламлён "хвостом" от старой, более длинной
  // программы - ёмкость/напряжение переключаться на него не должны.
  program[2].WType = 'T'; program[2].capacity_num = 7; program[2].Power = 99.0f;
  ProgramNum = ProgramLen;
  reset_mocks();
  run_dist_program(ProgramLen + 1);
  check(capacityCalls == 0, "повторное нажатие после конца программы не должно переключать ёмкость на чужую строку");
  check(powerCalls == 0, "повторное нажатие после конца программы не должно применять чужое напряжение");
  check(ProgramNum == ProgramLen, "ProgramNum должен остаться на ProgramLen");

  // [defect] program_commit() должен обнулять удаляемые строки ЦЕЛИКОМ, а не
  // только WType. Коммитим "старую" программу из 5 строк, затем укорачиваем её
  // до 2 строк - удалённые строки не должны хранить старые capacity_num/Power.
  {
    ProgramDraft longDraft;
    longDraft.rows[0].WType = 'T'; longDraft.rows[0].capacity_num = 1; longDraft.rows[0].Power = 10.0f;
    longDraft.rows[1].WType = 'T'; longDraft.rows[1].capacity_num = 2; longDraft.rows[1].Power = 20.0f;
    longDraft.rows[2].WType = 'T'; longDraft.rows[2].capacity_num = 7; longDraft.rows[2].Power = 99.0f;
    longDraft.rows[3].WType = 'T'; longDraft.rows[3].capacity_num = 8; longDraft.rows[3].Power = 55.0f;
    longDraft.rows[4].WType = 'T'; longDraft.rows[4].capacity_num = 9; longDraft.rows[4].Power = 44.0f;
    longDraft.len = 5;
    program_commit(longDraft);
    check(program[4].capacity_num == 9, "sanity: пятая строка старой программы должна закоммититься");

    ProgramDraft shortDraft;
    shortDraft.rows[0].WType = 'T'; shortDraft.rows[0].capacity_num = 1; shortDraft.rows[0].Power = 10.0f;
    shortDraft.rows[1].WType = 'T'; shortDraft.rows[1].capacity_num = 2; shortDraft.rows[1].Power = 20.0f;
    shortDraft.len = 2;
    program_commit(shortDraft);

    check(program_type_empty(program[2].WType), "удалённая строка 2 должна стать пустой (WType == NONE)");
    check(program[2].capacity_num == 0, "удалённая строка 2 не должна хранить старую ёмкость (7) от прошлой программы");
    check(program[2].Power == 0.0f, "удалённая строка 2 не должна хранить старое напряжение (99) от прошлой программы");
    check(program[4].capacity_num == 0, "удалённая строка 4 не должна хранить старую ёмкость (9) от прошлой программы");
    check(program[4].Power == 0.0f, "удалённая строка 4 не должна хранить старое напряжение (44) от прошлой программы");
    check(ProgramLen == 2, "ProgramLen должен стать 2 после укорачивания программы");
  }

  if (failures != 0) return 1;
  std::cout << "run_dist_program last-row capacity/power checks passed\n";
  return 0;
}
'''


def build_harness(dist_source: str, program_io_source: str) -> str:
    body = extract_function_body(dist_source, SIGNATURE)
    commit_body = extract_function_body(program_io_source, COMMIT_SIGNATURE)
    harness = HARNESS_TEMPLATE.replace(
        "@RUN_DIST_PROGRAM_BODY@", "void run_dist_program(uint8_t num) {" + body + "}"
    )
    return harness.replace(
        "@PROGRAM_COMMIT_BODY@",
        "void program_commit(const ProgramDraft& draft) {" + commit_body + "}",
    )


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-dist-last-row-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "dist_last_row_test.cpp"
        binary = temp / "dist_last_row_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write("compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    dist_source = (ROOT / "distiller.h").read_text(encoding="utf-8")
    program_io_source = (ROOT / "program_io.h").read_text(encoding="utf-8")
    try:
        harness = build_harness(dist_source, program_io_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return compile_and_run(harness)


if __name__ == "__main__":
    raise SystemExit(main())
