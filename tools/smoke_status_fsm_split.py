#!/usr/bin/env python3
"""[WP14 п.43] Поведенческая проверка разделения tick_status_fsm() (logic.h) на
"решение" (переходы SamovarStatusInt) и "отрисовку" (текст статуса для веба).

До разделения tick_status_fsm() одновременно шесть раз меняла SamovarStatusInt
и строила текст статуса в одной ветке if/elseif. Разделение обязано быть
чисто структурным - ни один текст, ни одно условие перехода не меняются.

Этот тест вытаскивает РЕАЛЬНОЕ тело tick_status_fsm() (и, если они уже
появились после рефакторинга, decide_status_fsm()/format_status_fsm_text())
из logic.h, компилирует их с набором фиктивных runtime-переменных и прогоняет
через набор входных состояний, покрывающий все шесть точек перехода плюс
пограничные ветки (пустой текст, дедупликация SendMsg, catch-all
mode_status_by_status, зависимость append-блока "Осталось" от НОВОГО состояния).

Печатает по одной строке на сценарий - (текст статуса, итоговое SamovarStatusInt,
счётчики важных побочных эффектов). Скрипт можно запускать как на старом
(нерасщеплённом), так и на новом (расщеплённом) logic.h - в обоих случаях
sivnature "String tick_status_fsm()" присутствует, а decide/format вытаскиваются
"best effort" (если не найдены - просто не подставляются, тело tick_status_fsm
тогда самодостаточно).

Использование:
  python3 smoke_status_fsm_split.py                  # берёт живой logic.h
  python3 smoke_status_fsm_split.py /tmp/snapshot.h   # берёт указанный файл
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <string>
#include <iostream>

// ---- Заглушка Arduino String (см. smoke_withdrawal_pause_resume.py) ----
class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}
  String(int value) : value_(std::to_string(value)) {}
  String(unsigned int value) : value_(std::to_string(value)) {}
  String(float value) : value_(std::to_string(value)) {}
  String(unsigned long value) : value_(std::to_string(value)) {}

  String& operator+=(const String& other) { value_ += other.value_; return *this; }
  friend String operator+(String left, const String& right) { left += right; return left; }
  const std::string& raw() const { return value_; }

 private:
  std::string value_;
};

#define F(x) (x)
#define pdMS_TO_TICKS(x) (x)

using MessageType = int;
constexpr MessageType WARNING_MSG = 1;
constexpr MessageType NOTIFY_MSG = 2;

enum SAMOVAR_MODE_T {
  SAMOVAR_RECTIFICATION_MODE, SAMOVAR_DISTILLATION_MODE, SAMOVAR_BEER_MODE,
  SAMOVAR_BK_MODE, SAMOVAR_NBK_MODE, SAMOVAR_SUVID_MODE, SAMOVAR_LUA_MODE
};

// Значения - как в Samovar.h (реальные константы контракта, не менять).
constexpr int16_t SAMOVAR_STATUS_IDLE              = 0;
constexpr int16_t SAMOVAR_STATUS_RECT_WITHDRAWAL   = 10;
constexpr int16_t SAMOVAR_STATUS_RECT_AUTOPAUSE    = 15;
constexpr int16_t SAMOVAR_STATUS_RECT_PROGRAM_DONE = 20;
constexpr int16_t SAMOVAR_STATUS_RECT_CALIBRATION  = 30;
constexpr int16_t SAMOVAR_STATUS_PAUSED            = 40;
constexpr int16_t SAMOVAR_STATUS_RECT_ACCEL        = 50;
constexpr int16_t SAMOVAR_STATUS_RECT_STABILIZING  = 51;
constexpr int16_t SAMOVAR_STATUS_RECT_STABLE       = 52;
constexpr int16_t SAMOVAR_STATUS_BEER              = 2000;

constexpr int16_t SAMOVAR_STARTVAL_IDLE          = 0;
constexpr int16_t SAMOVAR_STARTVAL_RECT_RUNNING  = 1;
constexpr int16_t SAMOVAR_STARTVAL_RECT_DONE     = 2;
constexpr int16_t SAMOVAR_STARTVAL_CALIBRATION   = 100;

struct DSSensor { float avgTemp = 0; float BodyTemp = 0; };

// ---- Runtime-переменные (имена и роли - как в Samovar.h) ----
static bool PowerOn = false;
static bool PauseOn = false;
static int16_t SamovarStatusInt = SAMOVAR_STATUS_IDLE;
static int16_t startval = SAMOVAR_STARTVAL_IDLE;
static bool program_Wait = false;
static SAMOVAR_MODE_T Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
static uint8_t ProgramNum = 0;
static unsigned long t_min = 0;
static bool heater_state = false;
static DSSensor TankSensor, SteamSensor, PipeSensor;
static String WthdrwTimeS, WthdrwTimeAllS;
static String SamovarStatus;

static unsigned long fake_millis_value = 100000;
static unsigned long millis() { return fake_millis_value; }

// ---- Моки внешних примитивов (не относятся к проверяемой логике) ----
static bool stepperSafeStateFixture = false;
// Если true - каждый ФАКТИЧЕСКИЙ вызов переключает фикстуру (имитирует ISR степпера,
// который может поменять состояние МЕЖДУ двумя отдельными чтениями за один тик).
// Используется сценарием cascade_coherence, чтобы поймать регресс к двойному чтению.
static bool stepperSafeStateToggleOnRead = false;
static int stepperSafeGetStateCalls = 0;
static bool stepper_safe_get_state() {
  stepperSafeGetStateCalls++;
  bool result = stepperSafeStateFixture;
  if (stepperSafeStateToggleOnRead) stepperSafeStateFixture = !stepperSafeStateFixture;
  return result;
}

static bool nbkTransitionActiveFixture = false;
static bool nbkTransitionActiveToggleOnRead = false;
static int nbkTransitionActiveCalls = 0;
static bool nbk_transition_active() {
  nbkTransitionActiveCalls++;
  bool result = nbkTransitionActiveFixture;
  if (nbkTransitionActiveToggleOnRead) nbkTransitionActiveFixture = !nbkTransitionActiveFixture;
  return result;
}

static bool waitTypeTextOk = true;
static String waitTypeTextFixture = "по пару";
static int copyWaitTypeCalls = 0;
static bool copy_program_wait_type_text(String& out) {
  copyWaitTypeCalls++;
  if (waitTypeTextOk) { out = waitTypeTextFixture; return true; }
  return false;
}

static float suvidTargetTempFixture = 60.0f;
static float suvid_target_temp() { return suvidTargetTempFixture; }

static int32_t suvidHoldRemainingFixture = -1;
static int32_t suvid_hold_remaining_sec() { return suvidHoldRemainingFixture; }

static String format_uptime(unsigned long seconds) { return String("UT:") + String((int)seconds); }
static String format_float(float v, int digits) { (void)digits; return String((int)(v * 100)); }

static String modeStatusTextFixture = "MODE_TEXT";
static int modeStatusByStatusCalls = 0;
static int16_t lastModeStatusArg = -9999;
static bool mode_status_by_status(int16_t status, String& text) {
  modeStatusByStatusCalls++;
  lastModeStatusArg = status;
  text = modeStatusTextFixture;
  return true;
}

static int sendMsgCalls = 0;
static void SendMsg(const String&, MessageType) { sendMsgCalls++; }

static bool runtime_state_lock(int) { return true; }
static void runtime_state_unlock(bool) {}

// ---- Реальный код под тестом ----
@DECIDE_FUNCTION@
@FORMAT_FUNCTION@
@TICK_FUNCTION@

// ---- Обвязка сценариев ----
static void reset_fixture() {
  PowerOn = false;
  PauseOn = false;
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  startval = SAMOVAR_STARTVAL_IDLE;
  program_Wait = false;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  ProgramNum = 0;
  t_min = 0;
  heater_state = false;
  TankSensor = DSSensor{};
  SteamSensor = DSSensor{};
  PipeSensor = DSSensor{};
  WthdrwTimeS = "";
  WthdrwTimeAllS = "";
  SamovarStatus = "";
  fake_millis_value = 100000;
  stepperSafeStateFixture = false;
  stepperSafeStateToggleOnRead = false;
  stepperSafeGetStateCalls = 0;
  nbkTransitionActiveFixture = false;
  nbkTransitionActiveToggleOnRead = false;
  nbkTransitionActiveCalls = 0;
  waitTypeTextOk = true;
  waitTypeTextFixture = "по пару";
  copyWaitTypeCalls = 0;
  suvidTargetTempFixture = 60.0f;
  suvidHoldRemainingFixture = -1;
  modeStatusTextFixture = "MODE_TEXT";
  modeStatusByStatusCalls = 0;
  lastModeStatusArg = -9999;
  sendMsgCalls = 0;
}

// [WP14 п.43, фикс двойного чтения] Раньше эта функция только печатала результат -
// код возврата всегда был 0, поэтому расхождение каскадов format/decide (см. отчёт)
// осталось бы незамеченным. Теперь каждый сценарий сверяет ФАКТИЧЕСКИЙ текст и
// состояние с эталоном, зафиксированным по проверенному (эквивалентному оригиналу)
// выводу - при расхождении failureCount растёт, и main() возвращает ненулевой код.
static int failureCount = 0;

static void fail(const std::string& scenario, const std::string& detail) {
  failureCount++;
  std::cout << "  FAIL[" << scenario << "]: " << detail << "\n";
}

static void expect(const std::string& name, const std::string& expectedText, int16_t expectedState) {
  String result = tick_status_fsm();
  std::cout << name
            << " | text=[" << result.raw() << "]"
            << " | state=" << SamovarStatusInt
            << " | sendMsg=" << sendMsgCalls
            << " | copyWaitType=" << copyWaitTypeCalls
            << " | modeStatusCalls=" << modeStatusByStatusCalls
            << " | modeStatusArg=" << lastModeStatusArg
            << "\n";
  if (result.raw() != expectedText) {
    fail(name, "text expected [" + expectedText + "] got [" + result.raw() + "]");
  }
  if (SamovarStatusInt != expectedState) {
    fail(name, "state expected " + std::to_string(expectedState) + " got " + std::to_string(SamovarStatusInt));
  }
}

// Проверка на расхождение каскадов: format_status_fsm_text()/decide_status_fsm()
// содержат дословно одинаковое ветвление и обязаны видеть ОДНО И ТО ЖЕ значение
// stepper_safe_get_state()/nbk_transition_active() за тик. Фикстуры настроены на
// переключение значения на каждый ФАКТИЧЕСКИЙ вызов (см. stepperSafeStateToggleOnRead) -
// имитация ISR степпера, меняющего состояние между двумя отдельными чтениями. Если
// tick_status_fsm() вернётся к двойному чтению (одно - для текста, другое - для
// перехода), текст и состояние выберут РАЗНЫЕ ветки одного каскада, а счётчики
// вызовов вырастут до 2 - любое из трёх и даст здесь FAIL с понятным сообщением.
static void expect_cascade_coherence_single_read() {
  const std::string name = "cascade_coherence_single_read_under_isr_toggle";
  String result = tick_status_fsm();
  std::cout << name
            << " | text=[" << result.raw() << "]"
            << " | state=" << SamovarStatusInt
            << " | stepperCalls=" << stepperSafeGetStateCalls
            << " | nbkCalls=" << nbkTransitionActiveCalls
            << "\n";
  if (result.raw() != "Разгон колонны") {
    fail(name, "text expected [Разгон колонны] got [" + result.raw() + "]");
  }
  if (SamovarStatusInt != SAMOVAR_STATUS_RECT_ACCEL) {
    fail(name, "state expected " + std::to_string(SAMOVAR_STATUS_RECT_ACCEL) + " got " +
                   std::to_string(SamovarStatusInt) +
                   " - текст и переход состояния разошлись между format_status_fsm_text() "
                   "и decide_status_fsm() (похоже на возврат двойного чтения stepper/nbk state)");
  }
  if (stepperSafeGetStateCalls != 1) {
    fail(name, "stepper_safe_get_state() must be called exactly once per tick, called " +
                   std::to_string(stepperSafeGetStateCalls) + " times");
  }
  if (nbkTransitionActiveCalls != 1) {
    fail(name, "nbk_transition_active() must be called exactly once per tick, called " +
                   std::to_string(nbkTransitionActiveCalls) + " times");
  }
}

int main() {
  // 1) Питание выключено, автомат в простое - ветка без перехода.
  reset_fixture();
  PowerOn = false;
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  SteamSensor.BodyTemp = 55.5f;
  PipeSensor.BodyTemp = 44.4f;
  expect("off_idle_with_body_temps", "Выключено;Т тела пар:5550;Т тела царга:4440", SAMOVAR_STATUS_IDLE);

  // 2) Переход №1: старт отбора -> RECT_WITHDRAWAL. Плюс проверка, что append
  //    "Осталось" в ЭТОМ ЖЕ тике видит УЖЕ НОВОЕ состояние (ключевая зависимость
  //    текста от порядка изменения состояния - см. отчёт).
  reset_fixture();
  PowerOn = true;
  startval = SAMOVAR_STARTVAL_RECT_RUNNING;
  PauseOn = false;
  program_Wait = false;
  ProgramNum = 3;
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;  // старое состояние - не WITHDRAWAL
  WthdrwTimeS = "12:34";
  WthdrwTimeAllS = "56:78";
  expect("withdrawal_start_sees_new_state_in_append", "Прг №4; Осталось:12:34|56:78", SAMOVAR_STATUS_RECT_WITHDRAWAL);

  // 3) Переход №2 (успех): автопауза с валидным типом.
  reset_fixture();
  PowerOn = true;
  startval = SAMOVAR_STARTVAL_RECT_RUNNING;
  program_Wait = true;
  ProgramNum = 1;
  t_min = fake_millis_value + 5000;
  waitTypeTextOk = true;
  waitTypeTextFixture = "по пару";
  WthdrwTimeS = "01:02";
  WthdrwTimeAllS = "03:04";
  expect("autopause_ok", "Прг №2 пауза по пару. Продолжение через 5 сек.; Осталось:01:02|03:04", SAMOVAR_STATUS_RECT_AUTOPAUSE);

  // 4) Переход №2 (отказ чтения типа паузы): SendMsg должен вызваться РОВНО
  //    один раз (не дважды - именно это способен сломать неверный сплит).
  reset_fixture();
  PowerOn = true;
  startval = SAMOVAR_STARTVAL_RECT_RUNNING;
  program_Wait = true;
  ProgramNum = 1;
  t_min = fake_millis_value + 5000;
  waitTypeTextOk = false;
  expect("autopause_wait_type_read_fails", "Прг №2 пауза (ошибка). Продолжение через 5 сек.; Осталось:|", SAMOVAR_STATUS_RECT_AUTOPAUSE);

  // 5) Переход №3: программа завершена.
  reset_fixture();
  PowerOn = true;
  startval = SAMOVAR_STARTVAL_RECT_DONE;
  expect("program_done", "Выполнение программы завершено", SAMOVAR_STATUS_RECT_PROGRAM_DONE);

  // 6) Переход №4: калибровка.
  reset_fixture();
  PowerOn = true;
  startval = SAMOVAR_STARTVAL_CALIBRATION;
  expect("calibration", "Калибровка", SAMOVAR_STATUS_RECT_CALIBRATION);

  // 7) Переход №5: ручная пауза (не зависит от PowerOn).
  reset_fixture();
  PowerOn = false;
  PauseOn = true;
  SamovarStatusInt = SAMOVAR_STATUS_RECT_PROGRAM_DONE;  // не IDLE - иначе решила бы ветка 1
  expect("manual_pause", "Пауза", SAMOVAR_STATUS_PAUSED);

  // 8) Сувид, нагрев, с выдержкой - без перехода (Сувид живёт со статусом 0).
  reset_fixture();
  PowerOn = true;
  Samovar_Mode = SAMOVAR_SUVID_MODE;
  heater_state = true;
  suvidTargetTempFixture = 63.5f;
  TankSensor.avgTemp = 61.2f;
  suvidHoldRemainingFixture = 125;
  SamovarStatusInt = 999;  // произвольный дозор, чтобы явно увидеть отсутствие перехода
  expect("suvid_heating_with_hold", "Сувид; Поддерж. Т=63.500000°; Тек: 61.200001° (Нагрев); Выдержка: UT:125", 999);

  // 9) Сувид, термостатирование, без выдержки.
  reset_fixture();
  PowerOn = true;
  Samovar_Mode = SAMOVAR_SUVID_MODE;
  heater_state = false;
  suvidHoldRemainingFixture = -1;
  SamovarStatusInt = 999;
  expect("suvid_thermostat_no_hold", "Сувид; Поддерж. Т=60.000000°; Тек: 0.000000° (Термостатирование)", 999);

  // 10) Переход №6: разгон колонны.
  reset_fixture();
  PowerOn = true;
  startval = SAMOVAR_STARTVAL_IDLE;
  stepperSafeStateFixture = false;
  nbkTransitionActiveFixture = false;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  expect("accel_start", "Разгон колонны", SAMOVAR_STATUS_RECT_ACCEL);

  // 11) Та же внешняя ветка, но LUA - текст-заглушка, переход не требуется.
  reset_fixture();
  PowerOn = true;
  startval = SAMOVAR_STARTVAL_IDLE;
  stepperSafeStateFixture = false;
  Samovar_Mode = SAMOVAR_LUA_MODE;
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  expect("accel_lua_stub_text_only", "Выполнение Lua скрипта", SAMOVAR_STATUS_IDLE);

  // 12) Тот же диапазон startval/stepper, состояние уже STABILIZING - только текст.
  reset_fixture();
  PowerOn = true;
  startval = SAMOVAR_STARTVAL_IDLE;
  stepperSafeStateFixture = false;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  SamovarStatusInt = SAMOVAR_STATUS_RECT_STABILIZING;
  expect("accel_stabilizing_text_only", "Разгон завершен. Стабилизация/Работа на себя", SAMOVAR_STATUS_RECT_STABILIZING);

  // 13) STABLE - только текст.
  reset_fixture();
  PowerOn = true;
  startval = SAMOVAR_STARTVAL_IDLE;
  stepperSafeStateFixture = false;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  SamovarStatusInt = SAMOVAR_STATUS_RECT_STABLE;
  expect("accel_stable_text_only", "Стабилизация завершена/Работа на себя", SAMOVAR_STATUS_RECT_STABLE);

  // 14) Пограничный случай: активный nbk-переход блокирует "Разгон колонны", но ни
  //     одна из под-веток LUA/STABILIZING/STABLE тоже не подходит - текст пустой
  //     (это существующее поведение оригинала, а не дефект рефакторинга).
  reset_fixture();
  PowerOn = true;
  startval = SAMOVAR_STARTVAL_IDLE;
  stepperSafeStateFixture = false;
  nbkTransitionActiveFixture = true;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  expect("accel_blocked_by_nbk_transition_empty_text", "", SAMOVAR_STATUS_IDLE);

  // 15) catch-all: mode_status_by_status() + append "Осталось" для BEER.
  reset_fixture();
  PowerOn = true;
  startval = SAMOVAR_STARTVAL_IDLE;
  stepperSafeStateFixture = true;  // блокирует ветку "Разгон колонны"
  Samovar_Mode = SAMOVAR_BEER_MODE;
  SamovarStatusInt = SAMOVAR_STATUS_BEER;
  WthdrwTimeS = "07:08";
  WthdrwTimeAllS = "09:10";
  expect("catch_all_mode_status_beer_append", "MODE_TEXT; Осталось:07:08|09:10", SAMOVAR_STATUS_BEER);

  // 16) Расхождение каскадов: та же ветка "Разгон колонны", что и в сценарии 10, но
  //     stepper/nbk-фикстуры переключаются на каждый ФАКТИЧЕСКИЙ вызов - имитация ISR
  //     степпера между двумя отдельными чтениями. При правильном одиночном чтении
  //     (см. logic.h: tick_status_fsm() читает оба значения один раз и передаёт их
  //     параметрами) текст и переход остаются на одной ветке, а счётчики вызовов равны 1.
  //     Регресс к двойному чтению (одно - в format, другое - в decide) даст расхождение
  //     текста/состояния и/или счётчик вызовов 2 - expect_cascade_coherence_single_read()
  //     ловит любое из этого.
  reset_fixture();
  PowerOn = true;
  startval = SAMOVAR_STARTVAL_IDLE;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  stepperSafeStateFixture = false;
  stepperSafeStateToggleOnRead = true;
  nbkTransitionActiveFixture = false;
  nbkTransitionActiveToggleOnRead = true;
  expect_cascade_coherence_single_read();

  if (failureCount > 0) {
    std::cout << failureCount << " check(s) FAILED\n";
    return 1;
  }
  std::cout << "all checks passed\n";
  return 0;
}
'''


def read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def build_harness(logic_source: str) -> str:
    tick_body = extract_function_body(logic_source, "String tick_status_fsm")
    tick_function = "String tick_status_fsm() {" + tick_body + "}"

    decide_function = ""
    try:
        decide_body = extract_function_body(logic_source, "void decide_status_fsm")
        decide_function = (
            "void decide_status_fsm(bool stepperState, bool nbkTransitionActive) {" + decide_body + "}"
        )
    except ValueError:
        pass

    format_function = ""
    try:
        format_body = extract_function_body(logic_source, "String format_status_fsm_text")
        format_function = (
            "String format_status_fsm_text(bool stepperState, bool nbkTransitionActive) {" + format_body + "}"
        )
    except ValueError:
        pass

    return (
        HARNESS_TEMPLATE
        .replace("@DECIDE_FUNCTION@", decide_function)
        .replace("@FORMAT_FUNCTION@", format_function)
        .replace("@TICK_FUNCTION@", tick_function)
    )


def compile_and_run(harness: str) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-status-fsm-split-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "status_fsm_split_test.cpp"
        binary = temp / "status_fsm_split_test"
        source.write_text(harness, encoding="utf-8", newline="")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            return compile_result.returncode, compile_result.stdout, compile_result.stderr
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        return run_result.returncode, run_result.stdout, run_result.stderr


def main() -> int:
    if len(sys.argv) > 1:
        logic_path = Path(sys.argv[1])
    else:
        logic_path = ROOT / "logic.h"
    logic_source = read_source(logic_path)

    try:
        harness = build_harness(logic_source)
    except ValueError as exc:
        print(f"status fsm split smoke failed: {exc}")
        return 1

    code, out, err = compile_and_run(harness)
    sys.stdout.write(out)
    if code != 0:
        sys.stderr.write(err)
        print(f"status fsm split smoke failed (exit {code})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
