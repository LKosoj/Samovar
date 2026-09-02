#!/usr/bin/env python3
"""[9b] Проверка выполнения программы БК: run_bk_program()/bk_apply_work_power()
переносят мощность/ёмкость ЗАВЕРШИВШЕЙСЯ строки и взводят уставку воды из
НОВОЙ строки (по образцу run_dist_program/distiller.h), а bk_proc() отказывает
старту, если программа требует датчик пара, а он невалиден.

Харнесс компилирует РЕАЛЬНЫЕ тела bk_program_requires_steam_sensor(),
bk_proc(), bk_apply_work_power(), run_bk_program() (BK.h) и общий хелпер
program_threshold_row_done() (distiller.h) - каждый как отдельный кусок
текста, чтобы мутации применялись к ОДНОМУ извлечённому телу и не задевали
одноимённую подстроку в определении другой функции (например,
"bk_program_requires_steam_sensor()" встречается и в сигнатуре её же
определения, и в единственном вызове внутри bk_proc()).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS_PREFIX = r'''
#include <cstdint>
#include <iostream>
#include <string>

#define SAMOVAR_USE_POWER 1
#define USE_WATER_PUMP 1

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
String operator+(const char* lhs, const String& rhs) { return String(lhs) + rhs; }

static const int SAMOVAR_STATUS_IDLE = 0;
static const int SAMOVAR_STATUS_BK = 4000;
static int SamovarStatusInt = SAMOVAR_STATUS_IDLE;

static const int SAMOVAR_STARTVAL_IDLE = 0;
static int startval = SAMOVAR_STARTVAL_IDLE;

static bool PowerOn = false;

struct Sensor { float avgTemp = 0; float StartProgTemp = 0; };
static Sensor TankSensor, SteamSensor, WaterSensor;

static bool tankSensorValid = true;
static bool steamSensorValid = true;
static bool sensor_valid(const Sensor& sensor) {
  if (&sensor == &SteamSensor) return steamSensorValid;
  return tankSensorValid;
}

static int processSensorFailedCalls = 0;
static bool process_sensor_failed(const char*, const char*) {
  processSensorFailedCalls++;
  return true;
}

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

static bool heaterSafetyLatchedStub = false;
bool heater_safety_latched() { return heaterSafetyLatchedStub; }

enum ModeHeatingStartResult { MODE_HEATING_START_FAILED = 0, MODE_HEATING_START_SUCCEEDED = 1 };
static int runHeatingStartCalls = 0;
static ModeHeatingStartResult mode_run_heating_start(
    int, const char*, const char*, const String&, const char*, bool) {
  runHeatingStartCalls++;
  return MODE_HEATING_START_FAILED;
}

static bool plateauFinishDueStub = false;
static bool dist_plateau_finish_due() { return plateauFinishDueStub; }

static bool bk_work_power_pending = false;

static int bkFinishCalls = 0;
static void bk_finish() { bkFinishCalls++; }

struct Setup { float DistTemp = 98.0f; float BKPower = 180.0f; };
static Setup SamSetup;

using ProgramType = char;
static const ProgramType PROGRAM_TYPE_NONE = 0;
struct WProgram {
  ProgramType WType = PROGRAM_TYPE_NONE;
  float Speed = 0;
  uint8_t capacity_num = 0;
  float Temp = 0;
  float Power = 0;
};
static const uint8_t PROGRAM_END = 8;
static WProgram program[PROGRAM_END];
static uint8_t ProgramNum = 0;
static uint8_t ProgramLen = 0;
static bool program_type_empty(ProgramType value) { return value == PROGRAM_TYPE_NONE; }

static float get_alcohol(float t) { return 100.0f - t; }
static float get_steam_alcohol(float t) { return 100.0f - t; }

static int sendMsgCalls = 0;
static std::string lastSendMsgText;
static void SendMsg(const String& message, MESSAGE_TYPE) {
  sendMsgCalls++;
  lastSendMsgText = message.text();
}

static int setCurrentPowerCalls = 0;
static float lastSetCurrentPowerArg = -1.0f;
static void set_current_power(float volt) {
  setCurrentPowerCalls++;
  lastSetCurrentPowerArg = volt;
}

static int applyProgramPowerRowCalls = 0;
static float lastApplyProgramPowerRowArg = -999.0f;
static void apply_program_power_row(float power) {
  applyProgramPowerRowCalls++;
  lastApplyProgramPowerRowArg = power;
}

static int setCapacityCalls = 0;
static uint8_t lastSetCapacityArg = 255;
static void set_capacity(uint8_t cap) {
  setCapacityCalls++;
  lastSetCapacityArg = cap;
}

static bool bk_water_auto = false;
static float bk_steam_setpoint = 0.0f;
static uint32_t bk_water_last_adjust_ms = 0;
static int bk_pwm = 0;   // [9b] нужен только чтобы проверить "без скачка" - resume его не трогает
static unsigned long fakeMillis = 0;
static unsigned long millis() { return fakeMillis; }

#define vTaskDelay(x) do { (void)(x); } while (0)
#define portTICK_PERIOD_MS 1

'''

HARNESS_SUFFIX = r'''
static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}

static void reset_common() {
  SamovarStatusInt = SAMOVAR_STATUS_BK;
  startval = 7;
  PowerOn = false;
  tankSensorValid = true;
  steamSensorValid = true;
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
  SteamSensor = Sensor();
  WaterSensor = Sensor();
  SamSetup = Setup();
  ProgramNum = 0;
  ProgramLen = 0;
  for (uint8_t i = 0; i < PROGRAM_END; i++) program[i] = WProgram();
  sendMsgCalls = 0;
  lastSendMsgText.clear();
  setCurrentPowerCalls = 0;
  lastSetCurrentPowerArg = -1.0f;
  applyProgramPowerRowCalls = 0;
  lastApplyProgramPowerRowArg = -999.0f;
  setCapacityCalls = 0;
  lastSetCapacityArg = 255;
  bk_water_auto = false;
  bk_steam_setpoint = 0.0f;
  bk_water_last_adjust_ms = 0;
  bk_pwm = 0;
  fakeMillis = 0;
}

int main() {
  // Сценарий 1: штатный старт с программой - строка 0 задаёт Power=220,
  // перекрывающий SamSetup.BKPower=180 (дефолт Setup выше), взводит
  // ProgramNum/уставку воды через run_bk_program(0) внутри bk_apply_work_power().
  reset_common();
  ProgramLen = 2;
  program[0].WType = 'T'; program[0].Speed = 80.0f; program[0].capacity_num = 1;
  program[0].Temp = 65.0f; program[0].Power = 220.0f;
  program[1].WType = 'T'; program[1].Speed = 90.0f; program[1].capacity_num = 2;
  program[1].Temp = 78.0f; program[1].Power = 0.0f;
  bk_apply_work_power();
  check(setCurrentPowerCalls == 1 && lastSetCurrentPowerArg == 180.0f,
        "сценарий 1: set_current_power должен быть вызван с BKPower (180)");
  check(applyProgramPowerRowCalls == 1 && lastApplyProgramPowerRowArg == 220.0f,
        "сценарий 1: apply_program_power_row должен перекрыть BKPower мощностью строки 0 (220)");
  check(!bk_work_power_pending, "сценарий 1: bk_work_power_pending должен быть снят");
  check(ProgramNum == 0, "сценарий 1: run_bk_program(0) должен взвести ProgramNum == 0");
  check(bk_water_auto, "сценарий 1: авторежим воды должен включиться (Temp строки 0 > 0)");
  check(bk_steam_setpoint == 65.0f, "сценарий 1: уставка пара должна быть взята из строки 0 (65)");

  // Сценарий 2: переход строки - порог строки 0 достигнут (TankSensor.avgTemp
  // дошёл до 80), run_bk_program(1) переносит мощность/ёмкость строки 0 и
  // взводит уставку из строки 1. apply_program_power_row вызывается ВТОРОЙ раз
  // тем же значением 220 - идемпотентность (см. семантику decision 1 плана).
  TankSensor.avgTemp = 80.0f;
  check(program_threshold_row_done(program[0]),
        "сценарий 2: строка 0 (T, порог 80) должна считаться завершённой при avgTemp == 80");
  run_bk_program(1);
  check(setCapacityCalls == 1 && lastSetCapacityArg == 1,
        "сценарий 2: set_capacity должен получить capacity_num завершившейся строки 0");
  check(applyProgramPowerRowCalls == 2 && lastApplyProgramPowerRowArg == 220.0f,
        "сценарий 2: apply_program_power_row должен применить мощность завершившейся строки 0 повторно тем же значением (220)");
  check(ProgramNum == 1, "сценарий 2: ProgramNum должен перейти на 1");
  check(bk_water_auto, "сценарий 2: авторежим воды должен остаться включённым (Temp строки 1 > 0)");
  check(bk_steam_setpoint == 78.0f, "сценарий 2: уставка пара должна обновиться из строки 1 (78)");

  // Сценарий 3: конец программы - run_bk_program(ProgramLen) должен только
  // отметить исчерпание программы сообщением, НЕ трогая авторежим/уставку
  // воды (программа не содержит новой строки, значит взводить нечего).
  run_bk_program(2);
  check(ProgramNum == 2, "сценарий 3: ProgramNum должен стать равным ProgramLen");
  check(lastSendMsgText.find("продолжение отбора") != std::string::npos,
        "сценарий 3: должно быть отправлено сообщение об исчерпании программы");
  check(bk_water_auto, "сценарий 3: авторежим воды НЕ должен измениться при исчерпании программы");
  check(bk_steam_setpoint == 78.0f, "сценарий 3: уставка пара НЕ должна измениться при исчерпании программы");

  // Сценарий 4: пустая программа - bk_apply_work_power() не должен трогать
  // program[0] (ProgramLen == 0), а run_bk_program(0) внутри неё не должен
  // слать ни "Переход к строке", ни "продолжение отбора" (антиспам через
  // ProgramNum < ProgramLen, изначально 0 < 0 ложно).
  reset_common();
  ProgramLen = 0;
  bk_apply_work_power();
  check(applyProgramPowerRowCalls == 0,
        "сценарий 4: apply_program_power_row не должен вызываться при пустой программе");
  check(sendMsgCalls == 0,
        "сценарий 4: run_bk_program(0) не должен слать сообщения при пустой программе (антиспам)");

  // Сценарий 5: программа требует датчик пара (program[0].Temp > 0), датчик
  // пара невалиден, PowerOn == false, защёлка не взведена - старт БК должен
  // отказать ДО mode_run_heating_start.
  reset_common();
  ProgramLen = 1;
  program[0].WType = 'T'; program[0].Speed = 80.0f; program[0].capacity_num = 1;
  program[0].Temp = 65.0f; program[0].Power = 0.0f;
  steamSensorValid = false;
  bk_proc();
  check(cancelProcessStartCalls == 1,
        "сценарий 5: mode_cancel_process_start должен быть вызван ровно один раз");
  check(lastCancelMessage.text() == "БК не запущена: программа требует датчик пара",
        "сценарий 5: сообщение должно быть про требование датчика пара");
  check(runHeatingStartCalls == 0,
        "сценарий 5: mode_run_heating_start не должен вызываться");
  bk_proc();
  check(cancelProcessStartCalls == 1,
        "сценарий 5: повторный тик не должен спамить (антиспам через сброс статуса)");

  // Сценарий 6: программа НЕ задаёт уставок пара (Temp == 0 у всех строк) -
  // датчик пара не нужен, исполнение обязано дойти до mode_run_heating_start.
  reset_common();
  ProgramLen = 1;
  program[0].WType = 'T'; program[0].Speed = 80.0f; program[0].capacity_num = 1;
  program[0].Temp = 0.0f; program[0].Power = 0.0f;
  steamSensorValid = false;
  bk_proc();
  check(cancelProcessStartCalls == 0,
        "сценарий 6: mode_cancel_process_start НЕ должен вызываться без уставок пара в программе");
  check(runHeatingStartCalls == 1,
        "сценарий 6: исполнение обязано дойти до mode_run_heating_start");

  // Сценарий 7: аварийная защёлка уже взведена - ветка датчика пара не должна
  // перехватывать отказ (симметрично сценарию C smoke_bk_start_refusal.py).
  reset_common();
  ProgramLen = 1;
  program[0].WType = 'T'; program[0].Speed = 80.0f; program[0].capacity_num = 1;
  program[0].Temp = 65.0f; program[0].Power = 0.0f;
  steamSensorValid = false;
  heaterSafetyLatchedStub = true;
  bk_proc();
  check(runHeatingStartCalls == 1,
        "сценарий 7: защёлка взведена - исполнение обязано дойти до mode_run_heating_start, а не остановиться на ветке датчика пара");

  // Сценарий 8: программа требует датчик пара (Temp > 0), но датчик ВАЛИДЕН -
  // старт не должен отказывать по этой ветке. Без этого сценария мутация,
  // убирающая !sensor_valid(SteamSensor) из условия, не ловится: сценарий 5
  // не различает "сенсор невалиден" от "сенсор вообще не проверяется", раз
  // bk_program_requires_steam_sensor() у него и так true.
  reset_common();
  ProgramLen = 1;
  program[0].WType = 'T'; program[0].Speed = 80.0f; program[0].capacity_num = 1;
  program[0].Temp = 65.0f; program[0].Power = 0.0f;
  steamSensorValid = true;
  bk_proc();
  check(cancelProcessStartCalls == 0,
        "сценарий 8: валидный датчик пара - mode_cancel_process_start НЕ должен вызываться");
  check(runHeatingStartCalls == 1,
        "сценарий 8: валидный датчик пара - исполнение обязано дойти до mode_run_heating_start");

  // Сценарий 9 (ревью, CRITICAL): процесс уже завершён через bk_finish()
  // (PowerOn=false, статус IDLE, ProgramNum сброшен в 0), а ProgramLen ЕЩЁ НЕ
  // обнулён - именно так выглядит состояние после реального bk_finish().
  // Отложенный bk_water_auto_resume(), пришедший из web_command() ПОСЛЕ
  // финиша, не должен включать авторежим воды на выбеге.
  reset_common();
  PowerOn = false;
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  ProgramNum = 0;
  ProgramLen = 2;
  program[0].Temp = 65.0f;
  bk_pwm = 777;
  bk_water_auto_resume();
  check(!bk_water_auto, "сценарий 9: resume после завершения процесса не должен включать авторежим воды");
  check(bk_pwm == 777, "сценарий 9: resume не должен трогать bk_pwm даже при отказе");

  // Сценарий 10 (ревью): штатный resume - PowerOn, статус БК, текущая строка
  // с Temp > 0. bk_pwm не трогается ("без скачка" - следующий шаг регулятора
  // в check_alarm_bk() отталкивается от факта, а не от нового стартового значения).
  reset_common();
  PowerOn = true;
  SamovarStatusInt = SAMOVAR_STATUS_BK;
  ProgramNum = 0;
  ProgramLen = 1;
  program[0].Temp = 65.0f;
  bk_pwm = 777;
  fakeMillis = 12345;
  bk_water_auto_resume();
  check(bk_water_auto, "сценарий 10: штатный resume должен включить авторежим воды");
  check(bk_steam_setpoint == 65.0f, "сценарий 10: уставка должна быть взята из текущей строки программы");
  check(bk_water_last_adjust_ms == 12345, "сценарий 10: таймер должен взводиться текущим millis()");
  check(bk_pwm == 777, "сценарий 10: bk_pwm не должен меняться - resume взводит только auto/уставку/таймер");

  // Сценарий 11 (ревью): текущая строка без уставки пара (Temp == 0) - resume
  // не включает авторежим (симметрично guard'у в run_bk_program/bk_apply_work_power).
  reset_common();
  PowerOn = true;
  SamovarStatusInt = SAMOVAR_STATUS_BK;
  ProgramNum = 0;
  ProgramLen = 1;
  program[0].Temp = 0.0f;
  bk_water_auto_resume();
  check(!bk_water_auto, "сценарий 11: resume не должен включать авторежим при Temp == 0 у текущей строки");

  // Сценарий 12 (ревью): bk_reset_water_auto() обнуляет все три поля.
  reset_common();
  bk_water_auto = true;
  bk_steam_setpoint = 65.0f;
  bk_water_last_adjust_ms = 999;
  bk_reset_water_auto();
  check(!bk_water_auto, "сценарий 12: bk_reset_water_auto должен выключить авторежим");
  check(bk_steam_setpoint == 0.0f, "сценарий 12: bk_reset_water_auto должен обнулить уставку");
  check(bk_water_last_adjust_ms == 0, "сценарий 12: bk_reset_water_auto должен обнулить таймер");

  // Сценарий 13 (ревью, CRITICAL): разгон до кипения (bk_work_power_pending
  // == true), куб уже прошёл порог строки 0 - bk_proc() НЕ должен переходить
  // на строку 1: иначе run_bk_program(0) из bk_apply_work_power() по факту
  // кипения откатит ProgramNum и задвоит переключение ёмкости. После
  // применения рабочей мощности тот же тик переводит на строку 1.
  reset_common();
  PowerOn = true;
  bk_work_power_pending = true;
  ProgramLen = 2;
  program[0].WType = 'T'; program[0].Speed = 78.0f; program[0].capacity_num = 1;
  program[0].Temp = 65.0f; program[0].Power = 0.0f;
  program[1].WType = 'T'; program[1].Speed = 90.0f; program[1].capacity_num = 2;
  program[1].Temp = 78.0f; program[1].Power = 0.0f;
  TankSensor.avgTemp = 80.0f;
  bk_proc();
  check(ProgramNum == 0,
        "сценарий 13: во время разгона (bk_work_power_pending) строки программы не должны переходить");
  check(setCapacityCalls == 0,
        "сценарий 13: во время разгона ёмкость не должна переключаться");
  bk_apply_work_power();
  check(ProgramNum == 0, "сценарий 13: bk_apply_work_power взводит строку 0");
  bk_proc();
  check(ProgramNum == 1,
        "сценарий 13: после применения рабочей мощности порог строки 0 должен перевести на строку 1");
  check(setCapacityCalls == 1 && lastSetCapacityArg == 1,
        "сценарий 13: переход должен переключить ёмкость строки 0");

  if (failures != 0) return 1;
  std::cout << "BK program run passed\n";
  return 0;
}
'''


def load_pieces() -> dict:
    bk_source = (ROOT / "BK.h").read_text(encoding="utf-8")
    distiller_source = (ROOT / "distiller.h").read_text(encoding="utf-8")
    return {
        "steam_sensor_requires": (
            "static bool bk_program_requires_steam_sensor() {"
            + extract_function_body(bk_source, "static bool bk_program_requires_steam_sensor()")
            + "}"
        ),
        "bk_proc": "void bk_proc() {" + extract_function_body(bk_source, "void bk_proc()") + "}",
        "bk_apply_work_power": (
            "static void bk_apply_work_power() {"
            + extract_function_body(bk_source, "static void bk_apply_work_power()")
            + "}"
        ),
        "run_bk_program": (
            "void run_bk_program(uint8_t num) {"
            + extract_function_body(bk_source, "void run_bk_program(uint8_t num)")
            + "}"
        ),
        "row_done": (
            "static bool program_threshold_row_done(const WProgram& row) {"
            + extract_function_body(distiller_source, "inline bool program_threshold_row_done")
            + "}"
        ),
        "water_auto_resume": (
            "void bk_water_auto_resume() {"
            + extract_function_body(bk_source, "void bk_water_auto_resume()")
            + "}"
        ),
        "reset_water_auto": (
            "void bk_reset_water_auto() {"
            + extract_function_body(bk_source, "void bk_reset_water_auto()")
            + "}"
        ),
    }


def assemble(pieces: dict) -> str:
    order = [
        "row_done",
        "steam_sensor_requires",
        "run_bk_program",
        "bk_apply_work_power",
        "bk_proc",
        "water_auto_resume",
        "reset_water_auto",
    ]
    body = "\n".join(pieces[key] for key in order)
    return HARNESS_PREFIX + body + HARNESS_SUFFIX


def compile_and_run(source: str, name: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="samovar-bk-program-run-") as temp_dir:
        temp = Path(temp_dir)
        source_path = temp / f"{name}.cpp"
        binary_path = temp / name
        source_path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source_path), "-o", str(binary_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return result
        return subprocess.run([str(binary_path)], capture_output=True, text=True, check=False)


def main() -> int:
    try:
        pieces = load_pieces()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    harness = assemble(pieces)
    result = compile_and_run(harness, "bk_program_run")
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        return result.returncode

    def check_mutant(name: str, piece_key: str, old: str, new: str, expect_message: str) -> int:
        mutated_pieces = dict(pieces)
        mutated_text = pieces[piece_key].replace(old, new, 1)
        if mutated_text == pieces[piece_key]:
            print(f"FAIL: не удалось построить мутацию {name}", file=sys.stderr)
            return 1
        mutated_pieces[piece_key] = mutated_text
        mutant_result = compile_and_run(assemble(mutated_pieces), name)
        if mutant_result.returncode == 0:
            print(f"FAIL: мутация {name} ({expect_message}) пережила тест", file=sys.stderr)
            return 1
        return 0

    # Убрать ProgramLen > 0 перед apply_program_power_row(program[0].Power) -
    # сценарий 4 (пустая программа) не должен обращаться к program[0].
    status = check_mutant(
        "bk_apply_work_power_program_len_guard",
        "bk_apply_work_power",
        "if (ProgramLen > 0) apply_program_power_row(program[0].Power);",
        "apply_program_power_row(program[0].Power);",
        "apply_program_power_row вызывается при пустой программе",
    )
    if status != 0:
        return status

    # Заменить num - 1 на num в применении capacity/power внутри run_bk_program -
    # сценарий 2 должен упасть (применённое значение окажется от строки 1, а не 0).
    status = check_mutant(
        "run_bk_program_off_by_one",
        "run_bk_program",
        "program[num - 1].capacity_num",
        "program[num].capacity_num",
        "capacity строки num вместо завершившейся num-1",
    )
    if status != 0:
        return status

    # Убрать !sensor_valid(SteamSensor) && из проверки старта - сценарий 5
    # перестаёт отказывать.
    status = check_mutant(
        "bk_proc_steam_sensor_guard",
        "bk_proc",
        "!sensor_valid(SteamSensor) &&",
        "",
        "отказ старта по датчику пара перестаёт срабатывать",
    )
    if status != 0:
        return status

    # Заменить bk_program_requires_steam_sensor() на true - сценарий 6 должен
    # упасть (отказ происходит даже без уставок пара в программе).
    status = check_mutant(
        "bk_proc_requires_steam_sensor_always_true",
        "bk_proc",
        "bk_program_requires_steam_sensor()",
        "true",
        "отказ по датчику пара срабатывает даже без уставок пара в программе",
    )
    if status != 0:
        return status

    # [9b, CRITICAL-фикс ревью] Вернуть старый guard bk_water_auto_resume() -
    # без проверки PowerOn/SamovarStatusInt сценарий 9 (resume после
    # bk_finish()) должен упасть: авторежим включится на выбеге.
    status = check_mutant(
        "bk_water_auto_resume_old_guard",
        "water_auto_resume",
        "!PowerOn || SamovarStatusInt != SAMOVAR_STATUS_BK || ",
        "",
        "resume включает авторежим воды после завершения процесса (bk_finish)",
    )
    if status != 0:
        return status

    # Убрать проверку Temp == 0 у текущей строки - сценарий 11 должен упасть.
    status = check_mutant(
        "bk_water_auto_resume_no_setpoint_guard",
        "water_auto_resume",
        "if (program[ProgramNum].Temp == 0) return;",
        "",
        "resume включает авторежим даже при Temp == 0 у текущей строки",
    )
    if status != 0:
        return status

    # [ревью 02.09.2026, CRITICAL] Разрешить переход строк во время разгона -
    # сценарий 13 должен упасть (ProgramNum уйдёт на 1 до применения BKPower).
    status = check_mutant(
        "bk_proc_rows_advance_during_ramp",
        "bk_proc",
        "PowerOn && !bk_work_power_pending &&",
        "PowerOn &&",
        "строки программы переходят во время разгона до кипения",
    )
    if status != 0:
        return status

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
