#!/usr/bin/env python3
"""[PKG-B, П3] До первого включения нагрева (PowerOn == false) невалидный или не
назначенный датчик куба должен ОТКАЗАТЬ команде старта дистилляции штатным путём
(mode_cancel_process_start -> SendMsg(ALARM_MSG) + SamovarStatusInt = IDLE), а не
взводить аварийную защёлку через process_sensor_failed()/request_emergency_stop()
(она снимается только перезагрузкой, а нагрев ещё ни разу не включался). При
PowerOn == true (процесс уже идёт) поведение обязано остаться прежним -
process_sensor_failed().

smoke_heating_sensor_validity.py пинит этот же фрагмент ТОЛЬКО текстовым порядком
токенов (require_ordered_tokens) - это не ловит нейтрализацию условия (например,
`if (PowerOn || true)` формально сохраняет все токены в прежнем порядке). Этот
тест компилирует РЕАЛЬНОЕ тело distiller_proc() (distiller.h) в изолированном
харнессе и проверяет фактическое поведение в обоих состояниях PowerOn, включая
антиспам (mode_cancel_process_start своим побочным эффектом - сбросом
SamovarStatusInt в IDLE - гасит повторные вызовы на следующем тике, т.к. первая
строка функции сама остановит выполнение по несовпадению статуса; отдельного
флага для этого не заводилось).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "void distiller_proc()"

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
static const int SAMOVAR_STATUS_DISTILLATION = 5;
static int SamovarStatusInt = SAMOVAR_STATUS_IDLE;

static const int SAMOVAR_STARTVAL_IDLE = 0;
static int startval = SAMOVAR_STARTVAL_IDLE;

static bool PowerOn = false;

struct Sensor { float avgTemp = 0; float StartProgTemp = 0; };
static Sensor TankSensor, WaterSensor;

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
// следующем тике (первая строка distiller_proc() остановит выполнение по
// несовпадению статуса), без отдельного флага.
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

// [ревью, П3] Управляется тестом (минимум два значения). Моделирует реальную
// heater_safety_latched() (power_regulator.h), видимую из distiller.h через
// forward-декларацию в samovar_api.h (тем же путём ею уже пользуются beer.h/nbk.h
// без прямого #include "power_regulator.h").
// Заглушка НЕ static (как heater_boost_output_off() в smoke_dist_boost_gate.py):
// единственный вызов лежит внутри вклеенного тела distiller_proc() ниже. Со
// static мутация, убирающая этот единственный вызов, уводила бы диагностику в
// unused-function/-Werror вместо содержательного assert-а по сценарию C.
static bool heaterSafetyLatchedStub = false;
bool heater_safety_latched() { return heaterSafetyLatchedStub; }

enum ModeHeatingStartResult { MODE_HEATING_START_FAILED = 0, MODE_HEATING_START_SUCCEEDED = 1 };
static int runHeatingStartCalls = 0;
static ModeHeatingStartResult mode_run_heating_start(
    int activeStatus, const String&, const String&, const String&, const String&, bool) {
  runHeatingStartCalls++;
  // Моделирует реальный mode_begin_heating_session (mode_common.h, [PKG-B п.7]):
  // при взведённой защёлке штатный отказ идёт через mode_cancel_process_start с
  // сообщением про защёлку, а не про датчик.
  if (heaterSafetyLatchedStub && SamovarStatusInt == activeStatus) {
    mode_cancel_process_start("Нагрев заблокирован аварийной защитой, требуется перезагрузка");
  }
  return MODE_HEATING_START_FAILED;
}

static String get_dist_program() { return String(""); }

static int runDistProgramCalls = 0;
static void run_dist_program(uint8_t) { runDistProgramCalls++; }

static float d_s_temp_prev = 0;

static const uint8_t SAFETY_HEATER_OUTPUT_BOOST = 1;
static void heater_enable_outputs(uint8_t) {}
static bool distBoostGated = false;
static bool distBoilStartedPrev = false;

static int resetTimePredictorCalls = 0;
static void resetTimePredictor() { resetTimePredictorCalls++; }

static unsigned long sessionStartTime = 0;
static bool sessionTimerValid = false;
static unsigned long fakeMillis = 0;
static unsigned long millis() { return fakeMillis; }

static bool boil_started = false;

struct Setup { bool UseST = true; float DistTemp = 98.0f; uint8_t DistTimeF = 0; };
static Setup SamSetup;

static void heater_boost_output_off() {}

static int updateTimePredictorCalls = 0;
static void updateTimePredictor() { updateTimePredictorCalls++; }

static int distillerFinishCalls = 0;
static void distiller_finish() { distillerFinishCalls++; }

using ProgramType = char;
static const ProgramType PROGRAM_TYPE_NONE = 0;
struct WProgram { ProgramType WType = PROGRAM_TYPE_NONE; float Speed = 0; };
static const uint8_t PROGRAM_END = 8;
static WProgram program[PROGRAM_END];
static uint8_t ProgramNum = 0;
static uint8_t ProgramLen = 0;
static bool program_type_empty(ProgramType value) { return value == PROGRAM_TYPE_NONE; }

static float get_alcohol(float t) { return 100.0f - t; }
static float get_steam_alcohol(float t) { return 100.0f - t; }

static float d_s_temp_finish = 0;
static unsigned long d_s_time_min = 0;

static int sendMsgCalls = 0;
static void SendMsg(const String&, MESSAGE_TYPE) { sendMsgCalls++; }

#define vTaskDelay(x) do { (void)(x); } while (0)
#define portTICK_PERIOD_MS 1

@DISTILLER_PROC_BODY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}

static void reset_all() {
  SamovarStatusInt = SAMOVAR_STATUS_DISTILLATION;
  startval = 7;
  PowerOn = false;
  tankSensorValid = true;
  processSensorFailedCalls = 0;
  cancelProcessStartCalls = 0;
  lastCancelMessage = String("");
  headingStartPendingStub = false;
  heaterSafetyLatchedStub = false;
  runHeatingStartCalls = 0;
  runDistProgramCalls = 0;
  distBoostGated = false;
  distBoilStartedPrev = false;
  resetTimePredictorCalls = 0;
  sessionStartTime = 0;
  sessionTimerValid = false;
  fakeMillis = 0;
  boil_started = false;
  updateTimePredictorCalls = 0;
  distillerFinishCalls = 0;
  ProgramNum = 0;
  ProgramLen = 0;
  sendMsgCalls = 0;
  TankSensor = Sensor();
  WaterSensor = Sensor();
  SamSetup = Setup();
}

int main() {
  // Сценарий A: PowerOn == false, датчик куба невалиден - отказ команды старта,
  // а не авария процесса. Два тика подряд (эмуляция loop()) - второй не должен
  // спамить: первая строка distiller_proc() остановит выполнение по несовпадению
  // статуса, выставленного mode_cancel_process_start на первом тике.
  reset_all();
  PowerOn = false;
  tankSensorValid = false;
  distiller_proc();
  check(cancelProcessStartCalls == 1,
        "PowerOn==false, датчик невалиден: mode_cancel_process_start должен быть вызван ровно один раз");
  check(processSensorFailedCalls == 0,
        "PowerOn==false, датчик невалиден: process_sensor_failed НЕ должен вызываться (это не авария процесса)");
  check(runHeatingStartCalls == 0,
        "PowerOn==false, датчик невалиден: mode_run_heating_start не должен вызываться");
  check(runDistProgramCalls == 0,
        "PowerOn==false, датчик невалиден: run_dist_program не должен вызываться");
  check(SamovarStatusInt == SAMOVAR_STATUS_IDLE,
        "после отказа старта SamovarStatusInt должен вернуться в IDLE");

  distiller_proc();
  check(cancelProcessStartCalls == 1,
        "повторный тик после отказа не должен спамить mode_cancel_process_start (антиспам через сброс статуса)");
  check(processSensorFailedCalls == 0,
        "повторный тик после отказа всё ещё не должен взводить аварийную защёлку");

  // Сценарий B: PowerOn == true (процесс уже идёт) - поведение прежнее:
  // невалидный датчик - это авария процесса (process_sensor_failed).
  reset_all();
  PowerOn = true;
  tankSensorValid = false;
  distiller_proc();
  check(processSensorFailedCalls == 1,
        "PowerOn==true, датчик невалиден: process_sensor_failed должен быть вызван (авария процесса)");
  check(cancelProcessStartCalls == 0,
        "PowerOn==true, датчик невалиден: mode_cancel_process_start не должен вызываться");

  // Сценарий C [ревью]: PowerOn == false, датчик невалиден, НО аварийная защёлка
  // уже взведена (heater_safety_latched()) - настоящая причина отказа не датчик,
  // а защёлка (снимается только перезагрузкой). Ветка датчика не должна
  // перехватывать это своим сообщением - исполнение обязано дойти до
  // mode_run_heating_start (-> mode_begin_heating_session), который штатно
  // откажет через mode_cancel_process_start с сообщением про защёлку.
  reset_all();
  PowerOn = false;
  tankSensorValid = false;
  heaterSafetyLatchedStub = true;
  distiller_proc();
  check(runHeatingStartCalls == 1,
        "защёлка взведена: исполнение обязано дойти до mode_run_heating_start, а не остановиться на ветке датчика");
  check(cancelProcessStartCalls == 1,
        "защёлка взведена: mode_cancel_process_start должен быть вызван ровно один раз (из штатного отказа mode_run_heating_start)");
  check(lastCancelMessage.text() == "Нагрев заблокирован аварийной защитой, требуется перезагрузка",
        "защёлка взведена: пользователь должен увидеть сообщение про защёлку, а не про датчик куба");
  check(processSensorFailedCalls == 0,
        "защёлка взведена, PowerOn==false: process_sensor_failed всё ещё не должен вызываться");

  // Сценарий D [ревью]: PowerOn == false, датчик куба ВАЛИДЕН, защёлка не
  // взведена - штатный путь запуска. Ветка датчика не должна перехватывать
  // старт (сенсор в порядке), исполнение обязано дойти до
  // mode_run_heating_start. Без этого сценария мутация, убирающая проверку
  // датчика из else-if (оставляющая только "!heater_safety_latched()"),
  // проходит тест: сценарии A/B/C её не ловят - они все стартуют с невалидным
  // датчиком, и условие "!sensor_valid(...)" в них и так истинно.
  reset_all();
  PowerOn = false;
  tankSensorValid = true;
  heaterSafetyLatchedStub = false;
  distiller_proc();
  check(cancelProcessStartCalls == 0,
        "PowerOn==false, датчик валиден: mode_cancel_process_start не должен вызываться");
  check(runHeatingStartCalls == 1,
        "PowerOn==false, датчик валиден: исполнение обязано дойти до mode_run_heating_start");
  check(processSensorFailedCalls == 0,
        "PowerOn==false, датчик валиден: process_sensor_failed не должен вызываться");

  if (failures != 0) return 1;
  std::cout << "distiller_proc start-refusal (PowerOn-gated sensor guard) checks passed\n";
  return 0;
}
'''


def build_harness(dist_source: str) -> str:
    body = extract_function_body(dist_source, SIGNATURE)
    return HARNESS_TEMPLATE.replace(
        "@DISTILLER_PROC_BODY@", "static void distiller_proc() {" + body + "}"
    )


def compile_and_run(harness: str, name: str = "dist_start_refusal_test") -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-dist-start-refusal-") as temp_dir:
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
    dist_source = (ROOT / "distiller.h").read_text(encoding="utf-8")
    try:
        harness = build_harness(dist_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    result = compile_and_run(harness)
    if result != 0:
        return result

    # Мутация: `if (PowerOn)` -> `if (true)` - гейт всегда берёт "старую" ветку
    # (process_sensor_failed), даже при PowerOn == false. Это и есть суть отката
    # П3: невалидный датчик до первого включения нагрева снова взводит аварийную
    # защёлку вместо отказа старта; ветка else-if с mode_cancel_process_start
    # становится мёртвым кодом (компилируется, но недостижима).
    mutant = harness.replace("if (PowerOn) {", "if (true) {", 1)
    if mutant == harness:
        print("FAIL: не удалось построить мутацию start-refusal gate", file=sys.stderr)
        return 1
    if compile_and_run(mutant, name="dist_start_refusal_mutant") == 0:
        print("FAIL: мутация start-refusal gate (откат к безусловному process_sensor_failed) пережила тест", file=sys.stderr)
        return 1

    # [ревью] Мутация: убираем `&& !heater_safety_latched()` - ветка датчика снова
    # перехватывает отказ, даже когда настоящая причина - уже взведённая аварийная
    # защёлка. Сценарий C должен упасть: mode_run_heating_start не будет вызван,
    # cancelProcessStartCalls всё ещё равен 1, но сообщение окажется про датчик,
    # а не про защёлку.
    mutant2 = harness.replace(
        "!sensor_valid(TankSensor) && !heater_safety_latched()",
        "!sensor_valid(TankSensor)",
        1,
    )
    if mutant2 == harness:
        print("FAIL: не удалось построить мутацию heater_safety_latched() gate", file=sys.stderr)
        return 1
    if compile_and_run(mutant2, name="dist_start_refusal_latch_mutant") == 0:
        print("FAIL: мутация heater_safety_latched() gate (ветка датчика снова маскирует защёлку) пережила тест", file=sys.stderr)
        return 1

    # [ревью] Мутация: убираем `!sensor_valid(TankSensor) &&` из else-if - ветка
    # отказа старта срабатывает по одной лишь защёлке, не глядя на датчик.
    # sensor_valid() остаётся вызванной в ветке if (PowerOn) выше, поэтому
    # мутация не превращает функцию-заглушку в неиспользуемую (см. комментарий
    # про heater_safety_latched()/-Werror=unused-function выше) - падать должен
    # содержательный assert сценария D, а не компилятор. При валидном датчике и
    # снятой защёлке (сценарий D) мутант всё равно вызовет
    # mode_cancel_process_start и не дойдёт до mode_run_heating_start.
    mutant3 = harness.replace(
        "!sensor_valid(TankSensor) && !heater_safety_latched()",
        "!heater_safety_latched()",
        1,
    )
    if mutant3 == harness:
        print("FAIL: не удалось построить мутацию sensor_valid() gate", file=sys.stderr)
        return 1
    if compile_and_run(mutant3, name="dist_start_refusal_sensor_mutant") == 0:
        print("FAIL: мутация sensor_valid() gate (отказ старта по одной защёлке, без учёта валидного датчика) пережила тест", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
