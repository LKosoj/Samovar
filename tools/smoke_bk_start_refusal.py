#!/usr/bin/env python3
"""[A1 п.2] До первого включения нагрева (PowerOn == false) невалидный или не
назначенный датчик куба должен ОТКАЗАТЬ команде старта БК штатным путём
(mode_cancel_process_start -> SendMsg(ALARM_MSG) + SamovarStatusInt = IDLE), а не
взводить аварийную защёлку через process_sensor_failed()/request_emergency_stop()
(она снимается только перезагрузкой, а нагрев ещё ни разу не включался). При
PowerOn == true (процесс уже идёт) поведение обязано остаться прежним -
process_sensor_failed(). Калька tools/smoke_dist_start_refusal.py, адаптированная
под упрощённое тело bk_proc() (нет программы отбора/предиктора времени БК.

Этот тест компилирует РЕАЛЬНОЕ тело bk_proc() (BK.h) в изолированном харнессе и
проверяет фактическое поведение в обоих состояниях PowerOn, включая антиспам
(mode_cancel_process_start своим побочным эффектом - сбросом SamovarStatusInt в
IDLE - гасит повторные вызовы на следующем тике).

[A1 п.6] После правки пункта 6 bk_proc() безусловно зовёт dist_plateau_finish_due()
(хелпер из distiller.h) - харнесс заводит для него заглушку, иначе компиляция
вклеенного тела упадёт с "was not declared in this scope".
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "void bk_proc()"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

#define SAMOVAR_USE_POWER 1

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };

class String {
 public:
  String() {}
  String(const char* value) : value_(value) {}
  String(int value) : value_(std::to_string(value)) {}
  String operator+(const String& other) const { String r; r.value_ = value_ + other.value_; return r; }
  const std::string& text() const { return value_; }
 private:
  std::string value_;
};

static const int SAMOVAR_STATUS_IDLE = 0;
static const int SAMOVAR_STATUS_BK = 4000;
static int SamovarStatusInt = SAMOVAR_STATUS_IDLE;

static const int SAMOVAR_STARTVAL_IDLE = 0;
static int startval = SAMOVAR_STARTVAL_IDLE;

static bool PowerOn = false;

struct Sensor { float avgTemp = 0; };
static Sensor TankSensor;

// Заглушка моделирует реальную зависимость от состояния (минимум два значения -
// см. AGENTS.md): управляется тестом через tankSensorValid, а не константа.
static bool tankSensorValid = true;
static bool sensor_valid(const Sensor&) { return tankSensorValid; }

static int processSensorFailedCalls = 0;
static bool process_sensor_failed(const char*, const char*) {
  processSensorFailedCalls++;
  return true;
}

// mode_cancel_process_start моделирует РЕАЛЬНЫЙ побочный эффект (mode_common.h):
// сброс SamovarStatusInt/startval в IDLE - это и обеспечивает антиспам на
// следующем тике (первая строка bk_proc() остановит выполнение по несовпадению
// статуса), без отдельного флага.
static int cancelProcessStartCalls = 0;
static String lastCancelMessage;
static void mode_cancel_process_start(const String& message) {
  cancelProcessStartCalls++;
  lastCancelMessage = message;
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  startval = SAMOVAR_STARTVAL_IDLE;
}

static bool headingStartPendingStub = false;
static bool mode_heating_start_pending(int) { return headingStartPendingStub; }

// [ревью, П3-аналог] Управляется тестом (минимум два значения). Моделирует
// реальную heater_safety_latched() (power_regulator.h), видимую из BK.h через
// forward-декларацию в samovar_api.h.
// Заглушка НЕ static: единственный вызов лежит внутри вклеенного тела bk_proc()
// ниже. Со static мутация, убирающая этот единственный вызов, уводила бы
// диагностику в unused-function/-Werror вместо содержательного assert-а по
// сценарию C.
static bool heaterSafetyLatchedStub = false;
bool heater_safety_latched() { return heaterSafetyLatchedStub; }

enum ModeHeatingStartResult { MODE_HEATING_START_FAILED = 0, MODE_HEATING_START_SUCCEEDED = 1 };
static int runHeatingStartCalls = 0;
static ModeHeatingStartResult mode_run_heating_start(
    int activeStatus, const char*, const char*, const String&, const char*, bool) {
  runHeatingStartCalls++;
  // Моделирует реальный mode_begin_heating_session (mode_common.h, [PKG-B п.7]):
  // при взведённой защёлке штатный отказ идёт через mode_cancel_process_start с
  // сообщением про защёлку, а не про датчик.
  if (heaterSafetyLatchedStub && SamovarStatusInt == activeStatus) {
    mode_cancel_process_start("Нагрев заблокирован аварийной защитой, требуется перезагрузка");
  }
  return MODE_HEATING_START_FAILED;
}

// [A1 п.6] bk_proc() безусловно зовёт хелпер плато из distiller.h - без заглушки
// вклеенное тело не скомпилируется. Значение не важно для сценариев A-D (все они
// возвращаются раньше, до этой строки), но функция обязана быть объявлена.
static bool plateauFinishDueStub = false;
static bool dist_plateau_finish_due() { return plateauFinishDueStub; }

static bool bk_work_power_pending = false;

static int bkFinishCalls = 0;
static void bk_finish() { bkFinishCalls++; }

struct Setup { float DistTemp = 98.0f; };
static Setup SamSetup;

// [9b] bk_proc() теперь безусловно (без #ifdef USE_WATER_PUMP - он в этом
// харнессе не определён) зовёт переход по строкам программы БК в конце тела -
// без этих заглушек вклеенное тело не скомпилируется. Все сценарии A-D
// возвращаются раньше (см. заголовок файла), поэтому конкретные значения не
// важны для поведения теста, важна только компилируемость.
using ProgramType = char;
static const ProgramType PROGRAM_TYPE_NONE = 0;
struct WProgram { ProgramType WType = PROGRAM_TYPE_NONE; float Speed = 0; float Power = 0; int capacity_num = 0; };
static const uint8_t PROGRAM_END = 8;
static WProgram program[PROGRAM_END];
static uint8_t ProgramNum = 0;
static uint8_t ProgramLen = 0;
static bool program_type_empty(ProgramType value) { return value == PROGRAM_TYPE_NONE; }
static bool program_threshold_row_done(const WProgram&) { return false; }
static int runBkProgramCalls = 0;
static void run_bk_program(uint8_t) { runBkProgramCalls++; }

#define vTaskDelay(x) do { (void)(x); } while (0)
#define portTICK_PERIOD_MS 1

@BK_PROC_BODY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}

static void reset_all() {
  SamovarStatusInt = SAMOVAR_STATUS_BK;
  startval = 7;
  PowerOn = false;
  tankSensorValid = true;
  processSensorFailedCalls = 0;
  cancelProcessStartCalls = 0;
  lastCancelMessage = String("");
  headingStartPendingStub = false;
  heaterSafetyLatchedStub = false;
  runHeatingStartCalls = 0;
  plateauFinishDueStub = false;
  bk_work_power_pending = false;
  bkFinishCalls = 0;
  TankSensor = Sensor();
  SamSetup = Setup();
  ProgramNum = 0;
  ProgramLen = 0;
  runBkProgramCalls = 0;
}

int main() {
  // Сценарий A: PowerOn == false, датчик куба невалиден - отказ команды старта,
  // а не авария процесса. Два тика подряд (эмуляция loop()) - второй не должен
  // спамить: первая строка bk_proc() остановит выполнение по несовпадению
  // статуса, выставленного mode_cancel_process_start на первом тике.
  reset_all();
  PowerOn = false;
  tankSensorValid = false;
  bk_proc();
  check(cancelProcessStartCalls == 1,
        "PowerOn==false, датчик невалиден: mode_cancel_process_start должен быть вызван ровно один раз");
  check(processSensorFailedCalls == 0,
        "PowerOn==false, датчик невалиден: process_sensor_failed НЕ должен вызываться (это не авария процесса)");
  check(runHeatingStartCalls == 0,
        "PowerOn==false, датчик невалиден: mode_run_heating_start не должен вызываться");
  check(SamovarStatusInt == SAMOVAR_STATUS_IDLE,
        "после отказа старта SamovarStatusInt должен вернуться в IDLE");

  bk_proc();
  check(cancelProcessStartCalls == 1,
        "повторный тик после отказа не должен спамить mode_cancel_process_start (антиспам через сброс статуса)");
  check(processSensorFailedCalls == 0,
        "повторный тик после отказа всё ещё не должен взводить аварийную защёлку");

  // Сценарий B: PowerOn == true (процесс уже идёт) - поведение прежнее:
  // невалидный датчик - это авария процесса (process_sensor_failed).
  reset_all();
  PowerOn = true;
  tankSensorValid = false;
  bk_proc();
  check(processSensorFailedCalls == 1,
        "PowerOn==true, датчик невалиден: process_sensor_failed должен быть вызван (авария процесса)");
  check(cancelProcessStartCalls == 0,
        "PowerOn==true, датчик невалиден: mode_cancel_process_start не должен вызываться");

  // Сценарий C: PowerOn == false, датчик невалиден, НО аварийная защёлка уже
  // взведена (heater_safety_latched()) - настоящая причина отказа не датчик, а
  // защёлка (снимается только перезагрузкой). Ветка датчика не должна
  // перехватывать это своим сообщением - исполнение обязано дойти до
  // mode_run_heating_start, который штатно откажет через mode_cancel_process_start
  // с сообщением про защёлку.
  reset_all();
  PowerOn = false;
  tankSensorValid = false;
  heaterSafetyLatchedStub = true;
  bk_proc();
  check(runHeatingStartCalls == 1,
        "защёлка взведена: исполнение обязано дойти до mode_run_heating_start, а не остановиться на ветке датчика");
  check(cancelProcessStartCalls == 1,
        "защёлка взведена: mode_cancel_process_start должен быть вызван ровно один раз (из штатного отказа mode_run_heating_start)");
  check(lastCancelMessage.text() == "Нагрев заблокирован аварийной защитой, требуется перезагрузка",
        "защёлка взведена: пользователь должен увидеть сообщение про защёлку, а не про датчик куба");
  check(processSensorFailedCalls == 0,
        "защёлка взведена, PowerOn==false: process_sensor_failed всё ещё не должен вызываться");

  // Сценарий D: PowerOn == false, датчик куба ВАЛИДЕН, защёлка не взведена -
  // штатный путь запуска. Ветка датчика не должна перехватывать старт (сенсор в
  // порядке), исполнение обязано дойти до mode_run_heating_start. Без этого
  // сценария мутация, убирающая проверку датчика из else-if (оставляющая только
  // "!heater_safety_latched()"), проходит тест: сценарии A/B/C её не ловят - они
  // все стартуют с невалидным датчиком.
  reset_all();
  PowerOn = false;
  tankSensorValid = true;
  heaterSafetyLatchedStub = false;
  bk_proc();
  check(cancelProcessStartCalls == 0,
        "PowerOn==false, датчик валиден: mode_cancel_process_start не должен вызываться");
  check(runHeatingStartCalls == 1,
        "PowerOn==false, датчик валиден: исполнение обязано дойти до mode_run_heating_start");
  check(processSensorFailedCalls == 0,
        "PowerOn==false, датчик валиден: process_sensor_failed не должен вызываться");

  if (failures != 0) return 1;
  std::cout << "bk_proc start-refusal (PowerOn-gated sensor guard) checks passed\n";
  return 0;
}
'''


def build_harness(bk_source: str) -> str:
    body = extract_function_body(bk_source, SIGNATURE)
    return HARNESS_TEMPLATE.replace(
        "@BK_PROC_BODY@", "static void bk_proc() {" + body + "}"
    )


def compile_and_run(harness: str, name: str = "bk_start_refusal_test") -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-bk-start-refusal-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / f"{name}.cpp"
        binary = temp / name
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
    bk_source = (ROOT / "BK.h").read_text(encoding="utf-8")
    try:
        harness = build_harness(bk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    result = compile_and_run(harness)
    if result != 0:
        return result

    # Мутация: `if (PowerOn)` -> `if (true)` - гейт всегда берёт "старую" ветку
    # (process_sensor_failed), даже при PowerOn == false. Это откат: невалидный
    # датчик до первого включения нагрева снова взводит аварийную защёлку вместо
    # отказа старта; ветка else-if с mode_cancel_process_start становится мёртвым
    # кодом (компилируется, но недостижима).
    mutant = harness.replace("if (PowerOn) {", "if (true) {", 1)
    if mutant == harness:
        print("FAIL: не удалось построить мутацию start-refusal gate", file=sys.stderr)
        return 1
    if compile_and_run(mutant, name="bk_start_refusal_mutant") == 0:
        print("FAIL: мутация start-refusal gate (откат к безусловному process_sensor_failed) пережила тест", file=sys.stderr)
        return 1

    # Мутация: убираем `&& !heater_safety_latched()` - ветка датчика снова
    # перехватывает отказ, даже когда настоящая причина - уже взведённая
    # аварийная защёлка. Сценарий C должен упасть.
    mutant2 = harness.replace(
        "!sensor_valid(TankSensor) && !heater_safety_latched()",
        "!sensor_valid(TankSensor)",
        1,
    )
    if mutant2 == harness:
        print("FAIL: не удалось построить мутацию heater_safety_latched() gate", file=sys.stderr)
        return 1
    if compile_and_run(mutant2, name="bk_start_refusal_latch_mutant") == 0:
        print("FAIL: мутация heater_safety_latched() gate (ветка датчика снова маскирует защёлку) пережила тест", file=sys.stderr)
        return 1

    # Мутация: убираем `!sensor_valid(TankSensor) &&` из else-if - ветка отказа
    # старта срабатывает по одной лишь защёлке, не глядя на датчик. sensor_valid()
    # остаётся вызванной в ветке if (PowerOn) выше, поэтому мутация не превращает
    # функцию-заглушку в неиспользуемую - падать должен содержательный assert
    # сценария D, а не компилятор.
    mutant3 = harness.replace(
        "!sensor_valid(TankSensor) && !heater_safety_latched()",
        "!heater_safety_latched()",
        1,
    )
    if mutant3 == harness:
        print("FAIL: не удалось построить мутацию sensor_valid() gate", file=sys.stderr)
        return 1
    if compile_and_run(mutant3, name="bk_start_refusal_sensor_mutant") == 0:
        print("FAIL: мутация sensor_valid() gate (отказ старта по одной защёлке, без учёта валидного датчика) пережила тест", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
