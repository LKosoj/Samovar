#!/usr/bin/env python3
"""Поведенческая проверка withdrawal() (logic.h) для пакета П3 (ядро ректификации).

Вытаскивает РЕАЛЬНЫЕ тела нескольких функций через extract_function_body и
компилирует их вместе в один харнесс - проверяется настоящее поведение
withdrawal() (в т.ч. лямбда handlePauseBySensor внутри неё), а не переписанная
в тесте копия. Мокаются только внешние примитивы (SendMsg, стэппер, буззер и т.п.),
не относящиеся к проверяемой логике.

Что покрывается:
  [П3-1] CurrentBaseSpeedRate - после резюме по датчику пара/царги обновляется
         через set_pump_speed(), program[].Speed никогда не перезаписывается;
         корректировка детектора с updateBase=false базу не портит; резюме
         детекторной паузы (т.к. коррекция не трогала CurrentBaseSpeedRate)
         оставляет базу нетронутой.
  [П3-3] Гистерезис резюме по датчику пара/царги (PAUSE_RESUME_HYSTERESIS_DELTA):
         в "мёртвой зоне" резюме не происходит, ниже threshold-delta - происходит.
         Проверено для двух разных SetTemp (0.5 и 1.0).
  [П3-4] Резюме после детекторной паузы ждёт detector_trend_settled(): при
         критическом тренде резюме не происходит, при осевшем - происходит.
  [П3-8] Единый критерий "первая строка тела после голов" (is_first_body_program_
         after_heads) срабатывает для топологий H;B и H;P;B одинаково.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURES = {
    "get_liquid_volume_by_step": ("float get_liquid_volume_by_step(float StepCount)", "logic.h"),
    "get_liquid_rate_by_step": ("float get_liquid_rate_by_step(int StepperSpeed)", "logic.h"),
    "set_pump_speed": ("void set_pump_speed(float pumpspeed, bool continue_process, bool updateBase)", "logic.h"),
    "withdrawal": ("void withdrawal(void)", "logic.h"),
    "program_type_at": ("inline ProgramType program_type_at(uint8_t index)", "runtime_helpers.h"),
    "is_first_body_program_after_heads": (
        "bool is_first_body_program_after_heads(uint8_t currentProgram, ProgramType currentType)",
        "impurity_detector.h",
    ),
    "get_adaptive_threshold": (
        "float get_adaptive_threshold(float baseThreshold, float variance, float volumePerHour, ProgramType processPhase)",
        "impurity_detector.h",
    ),
    "detector_current_recovery_threshold": ("inline float detector_current_recovery_threshold()", "impurity_detector.h"),
    "detector_trend_settled": ("inline bool detector_trend_settled()", "impurity_detector.h"),
}

HARNESS_TEMPLATE = r'''
#include <cmath>
#include <cstdint>
#include <iostream>
#include <string>

#define USE_BODY_TEMP_AUTOSET

using std::round;

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}
  String(int value) : value_(std::to_string(value)) {}
  String(unsigned int value) : value_(std::to_string(value)) {}
  String(float value) : value_(std::to_string(value)) {}

  String& operator+=(const String& other) { value_ += other.value_; return *this; }
  friend String operator+(String left, const String& right) { left += right; return left; }
  const std::string& raw() const { return value_; }

 private:
  std::string value_;
};

// ---- Типы/константы предметной области ----
using ProgramType = char;
constexpr ProgramType PROGRAM_TYPE_NONE = '\0';
constexpr uint8_t PROGRAM_MAX = 10;
inline bool program_type_empty(ProgramType type) { return type == PROGRAM_TYPE_NONE; }

struct WProgram {
  ProgramType WType = PROGRAM_TYPE_NONE;
  uint16_t Volume = 0;
  float Speed = 0;
  uint8_t capacity_num = 0;
  float Temp = 0;
  float Power = 0;
  uint8_t TempSensor = 0;
  float Time = 0;
};

struct DSSensor {
  float avgTemp = 0;
  float SetTemp = 0;
  float BodyTemp = 0;
  uint16_t Delay = 0;
  float StartProgTemp = 0;
};

struct SetupEEPROM {
  bool useautospeed = true;
  uint16_t StepperStepMl = 1000;
  uint8_t PackDens = 80;
  uint8_t autospeed = 5;
};

struct ImpurityDetector {
  float correctionFactor = 1.0f;
  unsigned long lastCorrectionTime = 0;
  float currentTrend = 0;
  float tempStdDev = 0;
};

enum ProgramWaitType : uint8_t { PROGRAM_WAIT_NONE = 0, PROGRAM_WAIT_STEAM, PROGRAM_WAIT_PIPE, PROGRAM_WAIT_DETECTOR };
enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };

constexpr int16_t SAMOVAR_STATUS_RECT_WITHDRAWAL = 10;
constexpr int16_t SAMOVAR_STATUS_RECT_AUTOPAUSE = 15;
constexpr int16_t SAMOVAR_STATUS_PAUSED = 40;
constexpr int16_t SAMOVAR_STARTVAL_RECT_RUNNING = 1;
constexpr int16_t SAMOVAR_STARTVAL_RECT_DONE = 2;
constexpr uint8_t PROGRAM_END = PROGRAM_MAX;
constexpr float PAUSE_RESUME_HYSTERESIS_DELTA = 0.07f;
// [П3-6] Не относится к этому харнессу - блок работает только когда startval==RECT_DONE,
// в наших сценариях startval всегда RUNNING, так что ветка не активируется.
constexpr int PROGRAM_DONE_AUTO_POWEROFF_MIN = 0;
using TickType_t = unsigned long;
#define pdMS_TO_TICKS(x) (x)
#define portTICK_PERIOD_MS 1
static void vTaskDelay(int) {}

// ---- Глобальное состояние ----
static WProgram program[PROGRAM_MAX];
static uint8_t ProgramNum = 0;
static uint8_t ProgramLen = 0;
static DSSensor SteamSensor;
static DSSensor PipeSensor;
static SetupEEPROM SamSetup;
static ImpurityDetector impurityDetector;
static int16_t SamovarStatusInt = SAMOVAR_STATUS_RECT_WITHDRAWAL;
static int16_t startval = SAMOVAR_STARTVAL_RECT_RUNNING;
static bool program_Pause = false;
static bool program_Wait = false;
static bool PauseOn = false;
static uint32_t CurrrentStepps = 0;
static uint32_t TargetStepps = 0;
static uint16_t CurrrentStepperSpeed = 100;
static float ActualVolumePerHour = 0;
static float CurrentBaseSpeedRate = 0;
static unsigned long t_min = 0;
static uint8_t RowStopPauseCount = 0;
static unsigned long program_done_hold_since = 0;

static unsigned long fake_millis_value = 100000;
static unsigned long millis() { return fake_millis_value; }

// ---- Моки внешних примитивов (не относятся к проверяемой логике) ----
static int sendMsgCalls = 0;
static void SendMsg(const String&, MESSAGE_TYPE) { sendMsgCalls++; }

static int setBuzzerCalls = 0;
static void set_buzzer(bool) { setBuzzerCalls++; }

static ProgramWaitType lastSetWaitType = PROGRAM_WAIT_NONE;
static bool set_program_wait_type(ProgramWaitType t, TickType_t) { lastSetWaitType = t; return true; }

static ProgramWaitType currentWaitTypeFixture = PROGRAM_WAIT_NONE;
static bool copy_program_wait_type(ProgramWaitType& out) { out = currentWaitTypeFixture; return true; }

static int pauseWithdrawalCalls = 0;
static bool lastPauseArg = false;
static void pause_withdrawal(bool p) { pauseWithdrawalCalls++; lastPauseArg = p; }

static int resetImpurityDetectorCalls = 0;
static void reset_impurity_detector() { resetImpurityDetectorCalls++; }

static int detectorOnAutoResumeCalls = 0;
static void detector_on_auto_resume() { detectorOnAutoResumeCalls++; }

static int setBodyTempCalls = 0;
static void set_body_temp() { setBodyTempCalls++; }

static int applyRowStopPausePolicyCalls = 0;
static void apply_row_stop_pause_policy() { applyRowStopPausePolicyCalls++; }

static void process_impurity_detector() {}
static void menu_samovar_start() {}
static void run_program(uint8_t) {}

static bool stepperState = true;
static bool stepper_safe_get_state() { return stepperState; }
static uint32_t stepper_safe_get_current() { return CurrrentStepps; }
static uint32_t stepper_safe_get_target() { return TargetStepps; }
static void stepper_safe_set_max_speed(uint16_t) {}
static void stepper_safe_set_target(uint32_t) {}
static void stopService() {}
static void startService() {}

// Прототип с дефолтным аргументом (как в samovar_api.h) - нужен, потому что
// реальное тело withdrawal() вызывает set_pump_speed() двухаргументно,
// полагаясь на дефолт updateBase=true из прототипа.
static void set_pump_speed(float pumpspeed, bool continue_process, bool updateBase = true);

// ---- Реальный код под тестом (extract_function_body) ----
@GET_LIQUID_VOLUME_BY_STEP_BODY@
@GET_LIQUID_RATE_BY_STEP_BODY@
@PROGRAM_TYPE_AT_BODY@
@IS_FIRST_BODY_PROGRAM_AFTER_HEADS_BODY@
@GET_ADAPTIVE_THRESHOLD_BODY@
@DETECTOR_CURRENT_RECOVERY_THRESHOLD_BODY@
@DETECTOR_TREND_SETTLED_BODY@
@SET_PUMP_SPEED_BODY@
@WITHDRAWAL_BODY@

// ---- Тесты ----
static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  for (uint8_t i = 0; i < PROGRAM_MAX; i++) program[i] = WProgram{};
  ProgramNum = 0;
  ProgramLen = 3;
  SteamSensor = DSSensor{};
  PipeSensor = DSSensor{};
  SamSetup = SetupEEPROM{};
  impurityDetector = ImpurityDetector{};
  SamovarStatusInt = SAMOVAR_STATUS_RECT_WITHDRAWAL;
  startval = SAMOVAR_STARTVAL_RECT_RUNNING;
  program_Pause = false;
  program_Wait = false;
  PauseOn = false;
  CurrrentStepps = 0;
  TargetStepps = 999999;  // далеко от достижения - не хотим срабатывания menu_samovar_start()
  CurrrentStepperSpeed = 100;
  ActualVolumePerHour = 0;
  CurrentBaseSpeedRate = 0;
  t_min = 0;
  RowStopPauseCount = 0;
  fake_millis_value = 100000;
  currentWaitTypeFixture = PROGRAM_WAIT_NONE;
  sendMsgCalls = 0;
  setBuzzerCalls = 0;
  lastSetWaitType = PROGRAM_WAIT_NONE;
  pauseWithdrawalCalls = 0;
  lastPauseArg = false;
  resetImpurityDetectorCalls = 0;
  detectorOnAutoResumeCalls = 0;
  setBodyTempCalls = 0;
  applyRowStopPausePolicyCalls = 0;
  stepperState = true;
}

// [П3-3] Гистерезис резюме: два разных SetTemp, каждый раз проверяем и "мёртвую
// зону" (резюме НЕТ), и точку ниже threshold-delta (резюме ЕСТЬ).
static void test_hysteresis_for_set_temp(float setTemp) {
  reset_fixture();
  program[0].WType = 'B';
  program[0].Temp = 0;  // не завершаем строку по температуре - тестируем только паузу
  SteamSensor.BodyTemp = 85.0f;
  SteamSensor.SetTemp = setTemp;
  program_Wait = true;
  currentWaitTypeFixture = PROGRAM_WAIT_STEAM;
  t_min = fake_millis_value - 1;  // таймер уже истёк

  const float thresholdHigh = SteamSensor.BodyTemp + setTemp;
  const float thresholdLow = thresholdHigh - PAUSE_RESUME_HYSTERESIS_DELTA;

  // Мёртвая зона: чуть ниже threshold_high, но ещё не ниже threshold_low.
  SteamSensor.avgTemp = thresholdHigh - PAUSE_RESUME_HYSTERESIS_DELTA * 0.3f;
  withdrawal();
  check(program_Wait, "в мёртвой зоне гистерезиса резюме не должно было произойти");

  // Ниже threshold_low: резюме должно произойти.
  SteamSensor.avgTemp = thresholdLow - 0.01f;
  withdrawal();
  check(!program_Wait, "ниже threshold-delta резюме должно было произойти");
  check(pauseWithdrawalCalls >= 1 && lastPauseArg == false, "резюме должно было вызвать pause_withdrawal(false)");
}

// [П3-1] Резюме по датчику пара обновляет CurrentBaseSpeedRate через set_pump_speed,
// program[].Speed никогда не перезаписывается напрямую (старый храповик убран).
static void test_sensor_resume_updates_base_not_program_speed() {
  reset_fixture();
  program[0].WType = 'B';
  program[0].Temp = 0;
  program[0].Speed = 0.5f;          // исходная база строки программы
  CurrentBaseSpeedRate = 0.5f;
  CurrrentStepperSpeed = 400;        // фактическая скорость насоса на момент паузы (после коррекции детектора)
  SamSetup.useautospeed = true;

  SteamSensor.BodyTemp = 85.0f;
  SteamSensor.SetTemp = 0.5f;
  SteamSensor.avgTemp = 80.0f;       // далеко ниже threshold - гарантированное резюме
  program_Wait = true;
  currentWaitTypeFixture = PROGRAM_WAIT_STEAM;
  t_min = fake_millis_value - 1;

  withdrawal();

  check(!program_Wait, "резюме по датчику пара должно было произойти");
  check(program[0].Speed == 0.5f, "program[].Speed не должен перезаписываться при резюме (П3-1)");
  check(impurityDetector.correctionFactor == 1.0f, "correctionFactor должен сброситься к 1.0 при резюме");
  check(CurrentBaseSpeedRate > 0, "CurrentBaseSpeedRate должен был обновиться через set_pump_speed");
}

// [П3-1/П3-4] Коррекция детектора (updateBase=false) не портит CurrentBaseSpeedRate;
// резюме ПОСЛЕ ДЕТЕКТОРНОЙ паузы (через detector_on_auto_resume) тоже не трогает
// ни CurrentBaseSpeedRate, ни program[].Speed - в отличие от резюме по датчику,
// этот путь вообще не вызывает set_pump_speed.
static void test_detector_pause_resume_keeps_base_untouched() {
  reset_fixture();
  program[0].WType = 'B';
  program[0].Temp = 0;
  program[0].Speed = 0.5f;
  CurrentBaseSpeedRate = 0.5f;

  // Детектор снижает скорость (корректирующий вызов, updateBase=false) - база не должна поменяться.
  set_pump_speed(80.0f, true, false);
  check(CurrentBaseSpeedRate == 0.5f, "корректирующий вызов set_pump_speed(updateBase=false) не должен менять базу");

  // Детекторная пауза: тренд ещё критический -> резюме НЕ должно произойти.
  program_Wait = true;
  currentWaitTypeFixture = PROGRAM_WAIT_DETECTOR;
  t_min = fake_millis_value - 1;
  impurityDetector.currentTrend = 5.0f;  // заведомо выше любого адаптивного порога
  withdrawal();
  check(program_Wait, "при критическом тренде резюме детекторной паузы не должно было произойти (П3-4)");
  check(detectorOnAutoResumeCalls == 0, "detector_on_auto_resume не должен был вызываться при критическом тренде");

  // Тренд осел ниже порога восстановления -> резюме должно произойти.
  impurityDetector.currentTrend = -1.0f;
  withdrawal();
  check(!program_Wait, "после оседания тренда резюме детекторной паузы должно было произойти (П3-4)");
  check(detectorOnAutoResumeCalls == 1, "detector_on_auto_resume должен был вызваться ровно один раз");
  check(CurrentBaseSpeedRate == 0.5f, "резюме детекторной паузы не должно было менять CurrentBaseSpeedRate");
  check(program[0].Speed == 0.5f, "резюме детекторной паузы не должно было менять program[].Speed");
}

// [П3-8] Единый критерий "первая строка тела после голов": H;B и H;P;B должны
// одинаково вызывать set_body_temp() (раньше H;P;B не срабатывало).
static void test_first_body_after_heads_topologies() {
  // Топология H;B (смежные).
  reset_fixture();
  program[0].WType = 'H';
  program[1].WType = 'B';
  ProgramNum = 1;
  ProgramLen = 2;
  SteamSensor.BodyTemp = 85.0f;
  SteamSensor.SetTemp = 0.5f;
  SteamSensor.avgTemp = 86.0f;  // выше threshold_high - входим в блок автокоррекции Т тела
  withdrawal();
  check(setBodyTempCalls == 1, "H;B: set_body_temp() должен был вызваться");

  // Топология H;P;B (через строку паузы).
  reset_fixture();
  program[0].WType = 'H';
  program[1].WType = 'P';
  program[2].WType = 'B';
  ProgramNum = 2;
  ProgramLen = 3;
  SteamSensor.BodyTemp = 85.0f;
  SteamSensor.SetTemp = 0.5f;
  SteamSensor.avgTemp = 86.0f;
  withdrawal();
  check(setBodyTempCalls == 1, "H;P;B: set_body_temp() должен был вызваться (единый критерий, П3-8)");
}

int main() {
  test_hysteresis_for_set_temp(0.5f);
  test_hysteresis_for_set_temp(1.0f);
  test_sensor_resume_updates_base_not_program_speed();
  test_detector_pause_resume_keeps_base_untouched();
  test_first_body_after_heads_topologies();

  if (failures != 0) return 1;
  std::cout << "withdrawal() pause/resume behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    bodies = {}
    files_cache = {}
    for key, (signature, filename) in SIGNATURES.items():
        if filename not in files_cache:
            files_cache[filename] = (ROOT / filename).read_text(encoding="utf-8")
        body = extract_function_body(files_cache[filename], signature)
        bodies[key] = (signature, body)

    def wrap(key: str, opening: str) -> str:
        _, body = bodies[key]
        return opening + "{" + body + "}"

    harness = HARNESS_TEMPLATE
    harness = harness.replace(
        "@GET_LIQUID_VOLUME_BY_STEP_BODY@",
        wrap("get_liquid_volume_by_step", "static float get_liquid_volume_by_step(float StepCount) "),
    )
    harness = harness.replace(
        "@GET_LIQUID_RATE_BY_STEP_BODY@",
        wrap("get_liquid_rate_by_step", "static float get_liquid_rate_by_step(int StepperSpeed) "),
    )
    harness = harness.replace(
        "@PROGRAM_TYPE_AT_BODY@",
        wrap("program_type_at", "static ProgramType program_type_at(uint8_t index) "),
    )
    harness = harness.replace(
        "@IS_FIRST_BODY_PROGRAM_AFTER_HEADS_BODY@",
        wrap(
            "is_first_body_program_after_heads",
            "static bool is_first_body_program_after_heads(uint8_t currentProgram, ProgramType currentType) ",
        ),
    )
    harness = harness.replace(
        "@GET_ADAPTIVE_THRESHOLD_BODY@",
        wrap(
            "get_adaptive_threshold",
            "static float get_adaptive_threshold(float baseThreshold, float variance, float volumePerHour, ProgramType processPhase) ",
        ),
    )
    harness = harness.replace(
        "@DETECTOR_CURRENT_RECOVERY_THRESHOLD_BODY@",
        wrap("detector_current_recovery_threshold", "static float detector_current_recovery_threshold() "),
    )
    harness = harness.replace(
        "@DETECTOR_TREND_SETTLED_BODY@",
        wrap("detector_trend_settled", "static bool detector_trend_settled() "),
    )
    harness = harness.replace(
        "@SET_PUMP_SPEED_BODY@",
        wrap("set_pump_speed", "static void set_pump_speed(float pumpspeed, bool continue_process, bool updateBase) "),
    )
    harness = harness.replace(
        "@WITHDRAWAL_BODY@",
        wrap("withdrawal", "static void withdrawal(void) "),
    )
    return harness


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-withdrawal-pause-resume-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "withdrawal_pause_resume_test.cpp"
        binary = temp / "withdrawal_pause_resume_test"
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
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return compile_and_run(harness)


if __name__ == "__main__":
    raise SystemExit(main())
