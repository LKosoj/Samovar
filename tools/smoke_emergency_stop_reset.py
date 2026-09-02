#!/usr/bin/env python3
"""Проверка T09: разделение reset_sensor_counter(), снятие мешалки и сброс
состояния в perform_emergency_stop(), пост-аварийные гейты withdrawal()/pause_withdrawal().

(а) Текстовые проверки (extract_function_body/require_ordered_tokens):
    - reset_process_state() НЕ трогает файловую систему и барометр - эти две
      операции остаются исключительно в reset_sensor_counter(), которая теперь
      сначала полностью сбрасывает состояние процесса, а потом делает файловый
      и барометрический шаги.
    - samovar_reset() (Menu.ino) завершает активный процесс ШТАТНОЙ командой
      режима stop_active_process_for_mode(), добивает Lua, уведомляет, если
      завершение не подтвердилось, и только потом идёт на reset_sensor_counter().
    - reset_process_state() приводит состояние варки к завершённому тем же самым
      хвостом, что и штатный beer_finish() - общей beer_reset_stage_state()
      (beer.h). Доделать его после сброса статуса некому: тик режима больше не
      вызывается, см. (в). Тест пинит и состав этой функции (заявка на повтор
      finish, фаза Lua-этапа, детектор кипения, ручная пауза, накопители простоя
      строки и разгона до кипения, метка простоя мешалки, ожидание подтверждения
      пропуска охлаждения), и оба её вызова.
    - perform_emergency_stop() принудительно снимает мешалку (в обход
      heater_safety_latched(), которым гейтятся обе штатные точки выключения
      в beer.h) и сбрасывает состояние процесса.

(б) Поведенческий харнесс на РЕАЛЬНЫХ телах withdrawal() и pause_withdrawal()
    (logic.h): после аварии (PowerOn=false и/или alarm_event=true) обе функции
    должны становиться no-op в соответствующих ветках - withdrawal() целиком,
    pause_withdrawal(false) (возобновление) - до присваивания PauseOn = Pause;
    [код-ревью]: гейт возобновления стоит ДО присваивания PauseOn, а не в ветке
    else после него, иначе PauseOn и SamovarStatusInt рассинхронизируются -
    проверяем, что при блокировке PauseOn НЕ меняется и startService() не
    вызывается. Постановка на паузу (Pause=true) гейтом не блокируется и
    работает даже при выключенном питании/аварии.

(в) Поведенческий харнесс на реальных телах mode_tick_beer()/mode_dispatch_loop()
    (check_dispatch_reachability): после сброса статуса в IDLE тик режима пива не
    вызывается вовсе - это и есть доказательство, что недоделанный хвост
    beer_finish() после сброса подхватить некому, и потому его обязана доводить
    сама reset_process_state().
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def forbid_token(name: str, body: str, token: str) -> None:
    if token in body:
        errors.append(f"{name} must not contain: {token}")


# [Решение владельца 25.08] Сброс обязан завершать процесс ШТАТНОЙ командой режима.
# Раньше samovar_reset() шла сразу на reset_sensor_counter(), минуя завершение: мешалка
# (её выключают только beer_stage_tick()/check_mixer_state()) и Lua-job варки (его
# останавливает beer_finish()) переживали команду SAMOVAR_RESET и продолжали работать
# при статусе "простой" - ни одно из этих мест после сброса статуса не вызывается
# (см. check_dispatch_reachability ниже - оно доказывает это поведением).
# Порядок обязателен: завершение процесса ДО reset_sensor_counter(), иначе сброс статуса
# в IDLE отберёт у finish'а право на повторный тик.
RESET_REQUIRED_CALLS = [
    ("stop_active_process_for_mode();", "штатное завершение процесса текущего режима"),
    ("request_lua_mode_stop()", "добить Lua, если штатный finish вышел раньше времени"),
    ('SendMsg("Процесс остановлен сбросом',
     "уведомить, если штатный finish не дошёл до собственного сообщения"),
    ("reset_sensor_counter();", "общий сброс счётчиков после завершения"),
]


def missing_reset_calls(body: str) -> list[tuple[str, str]]:
    """Обязательные вызовы, которых нет в теле samovar_reset().

    Комментарии из тела уже вырезаны extract_function_body, поэтому
    закомментированный вызов проверку не пройдёт.
    """
    return [(call, what) for call, what in RESET_REQUIRED_CALLS if call not in body]


def beer_stage_state_reset(body: str) -> bool:
    """Тело reset_process_state() приводит состояние варки к завершённому.

    Тем же хвостом, что и штатный beer_finish() - общей beer_reset_stage_state()
    (beer.h), состав которой проверяется отдельно ниже. Комментарии из тела уже
    вырезаны extract_function_body, поэтому закомментированный вызов проверку не
    пройдёт.
    """
    return "beer_reset_stage_state();" in body


# ---- (а) Текстовые проверки ----

sensorinit_text = read_text("sensorinit.h")
alarm_text = read_text("alarm.h")

if sensorinit_text:
    try:
        process_state_body = extract_function_body(sensorinit_text, "void reset_process_state(void)")
    except ValueError as exc:
        errors.append(str(exc))
        process_state_body = ""

    if process_state_body:
        forbid_token("reset_process_state", process_state_body, "request_data_log_close(")
        forbid_token("reset_process_state", process_state_body, "BME_getvalue(")
        # [Решение владельца 25.08] Состояние варки обязано сбрасываться здесь же,
        # и ровно тем хвостом, который выполняет штатный beer_finish(). Почему его
        # больше некому доделать после сброса статуса - доказывает поведенческая
        # проверка check_dispatch_reachability() ниже: тик режима не вызывается.
        if not beer_stage_state_reset(process_state_body):
            errors.append(
                "reset_process_state должна звать beer_reset_stage_state(): иначе "
                "заявка beerFinishPending залипает навсегда и съедает следующий запуск "
                "варки, фаза beerLuaStage остаётся в EXIT_QUEUED (программа с первой "
                "строкой 'L' не стартует до перезагрузки платы), а ручная пауза "
                "beerManualPause переживает сброс и вешает следующую варку на гейте "
                "строк M/P/B/C/F")

    try:
        reset_counter_body = extract_function_body(sensorinit_text, "void reset_sensor_counter(void)")
    except ValueError as exc:
        errors.append(str(exc))
        reset_counter_body = ""

    if reset_counter_body:
        require_ordered_tokens(
            "reset_sensor_counter calls reset_process_state before FS/barometer ops",
            reset_counter_body,
            [
                "reset_process_state();",
                "request_data_log_close(",
                "BME_getvalue(",
            ],
            errors,
        )

menu_text = read_text("Menu.ino")

if menu_text:
    try:
        samovar_reset_body = extract_function_body(menu_text, "void samovar_reset()")
    except ValueError as exc:
        errors.append(str(exc))
        samovar_reset_body = ""

    if samovar_reset_body:
        for missing, why in missing_reset_calls(samovar_reset_body):
            errors.append(
                f"samovar_reset должна звать {missing} - {why}: без этого привод "
                "переживает команду сброса, а подхватить его больше некому")
        # Порядок всех трёх - тот же, что у смены режима (mode_switch.h::switch_samovar_mode):
        # сначала штатное завершение процесса, потом добить Lua, и только потом общий
        # сброс счётчиков. Наоборот нельзя: сброс статуса в IDLE отберёт у finish право
        # на повторный тик (см. check_dispatch_reachability() ниже).
        RESET_ORDER = [call for call, _ in RESET_REQUIRED_CALLS]
        require_ordered_tokens(
            "samovar_reset finishes the active process and stops Lua before resetting counters",
            samovar_reset_body,
            RESET_ORDER,
            errors,
        )
        # Самопроверка: на каждой перестановке соседних вызовов проверка обязана падать.
        for first in range(len(RESET_ORDER) - 1):
            swapped = list(RESET_ORDER)
            swapped[first], swapped[first + 1] = swapped[first + 1], swapped[first]
            swapped_errors: list[str] = []
            require_ordered_tokens("self-check", "\n".join(swapped), RESET_ORDER, swapped_errors)
            if not swapped_errors:
                errors.append(
                    f"проверка порядка не ловит перестановку {RESET_ORDER[first]} и "
                    f"{RESET_ORDER[first + 1]}")

        # Уведомление обязано стоять ПОД условием "процесс всё ещё активен". Без
        # условия оно уходило бы при каждом сбросе - включая setup() и смену профиля,
        # где процесса не было вовсе, и дублировало бы собственное сообщение finish'а
        # ("Программа затирания завершена" и т.п.). Признак - именно эти два поля:
        # хвост любого finish ставит оба в IDLE.
        for field in ("SamovarStatusInt != SAMOVAR_STATUS_IDLE", "startval != SAMOVAR_STARTVAL_IDLE"):
            if field not in samovar_reset_body:
                errors.append(
                    f"samovar_reset должна слать уведомление только при {field}: иначе "
                    "сообщение уходит и когда процесса не было, и дублирует уведомление finish'а")

# [Решение владельца 25.08] Хвост состояния варки живёт в ОДНОЙ функции beer.h -
# её зовут и штатное завершение, и сброс процесса. Разъехаться они не могут по
# построению; тест пинит и состав функции, и оба вызова.
BEER_STAGE_STATE_FIELDS = [
    ("beerFinishPending = false;", "заявка на повтор зависшего beer_finish()"),
    ("beer_reset_lua_stage();", "фаза, тикет и nextProgram Lua-этапа варки"),
    ("resetBoilingDetector();", "история и стабильность детектора кипения"),
    ("beerBoilActiveAccumMs = 0;", "накопитель активного времени разгона до кипения"),
    ("beerManualPause = false;", "ручная пауза варки"),
    ("beerStageIdleAccumMs = 0;", "накопитель простоя текущей строки"),
    ("beerStageIdleSinceMs = 0;", "метка начала простоя текущей строки"),
    ("beerMixerPauseSinceMs = 0;", "метка начала простоя мешалки"),
    ("beerSkipConfirmProgramNum = 0xFF;", "ожидание подтверждения пропуска охлаждения"),
]

beer_text = read_text("beer.h")

if beer_text:
    try:
        stage_state_body = extract_function_body(beer_text, "inline void beer_reset_stage_state()")
    except ValueError as exc:
        errors.append(str(exc))
        stage_state_body = ""

    if stage_state_body:
        for token, what in BEER_STAGE_STATE_FIELDS:
            if token not in stage_state_body:
                errors.append(
                    f"beer_reset_stage_state должна сбрасывать {token} ({what}): "
                    "иначе поле переживает сброс процесса и приходит в новую варку "
                    "с чужим значением")
        # Приводов, локов и I2C здесь быть не должно: функция зовётся из
        # reset_process_state(), куда блокирующим операциям хода нет.
        for token in ("set_mixer_state(", "beer_safe_lua_outputs(", "request_lua_mode_stop(",
                      "request_beer_lua_stop(", "set_power(", "stop_process("):
            forbid_token("beer_reset_stage_state", stage_state_body, token)

    try:
        beer_finish_body = extract_function_body(beer_text, "void beer_finish()")
    except ValueError as exc:
        errors.append(str(exc))
        beer_finish_body = ""

    if beer_finish_body and "beer_reset_stage_state();" not in beer_finish_body:
        errors.append(
            "beer_finish должна звать beer_reset_stage_state(): иначе хвост штатного "
            "завершения и хвост сброса разъедутся")

if alarm_text:
    try:
        emergency_stop_body = extract_function_body(alarm_text, "void perform_emergency_stop")
    except ValueError as exc:
        errors.append(str(exc))
        emergency_stop_body = ""

    if emergency_stop_body:
        require_ordered_tokens(
            "perform_emergency_stop forces mixer relay off and resets process state",
            emergency_stop_body,
            [
                "digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);",
                "mixer_status = false;",
                "reset_process_state();",
            ],
            errors,
        )
        forbid_token("perform_emergency_stop", emergency_stop_body, "heater_safety_latched()")

if errors:
    print("emergency stop / reset smoke FAILED (text checks):", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)
    sys.exit(1)


# ---- (б) Поведенческий харнесс на реальных телах withdrawal()/pause_withdrawal() ----

SIGNATURES = {
    "withdrawal": ("void withdrawal(void)", "logic.h"),
    "pause_withdrawal": ("void pause_withdrawal(bool Pause)", "logic.h"),
}

HARNESS_TEMPLATE = r'''
#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>

#define USE_BODY_TEMP_AUTOSET

using std::abs;
using std::max;

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}
  String& operator+=(const String& other) { value_ += other.value_; return *this; }
  friend String operator+(String left, const String& right) { left += right; return left; }

 private:
  std::string value_;
};

using ProgramType = char;
constexpr ProgramType PROGRAM_TYPE_NONE = '\0';
constexpr uint8_t PROGRAM_MAX = 10;

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
};

struct ImpurityDetector {
  float correctionFactor = 1.0f;
  unsigned long lastCorrectionTime = 0;
};

enum ProgramWaitType : uint8_t { PROGRAM_WAIT_NONE = 0, PROGRAM_WAIT_STEAM, PROGRAM_WAIT_PIPE, PROGRAM_WAIT_DETECTOR };
enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum SAMOVAR_MODE { SAMOVAR_RECTIFICATION_MODE, SAMOVAR_OTHER_MODE };

constexpr int16_t SAMOVAR_STATUS_RECT_WITHDRAWAL = 10;
constexpr int16_t SAMOVAR_STATUS_RECT_AUTOPAUSE = 15;
constexpr int16_t SAMOVAR_STATUS_PAUSED = 40;
constexpr int16_t SAMOVAR_STARTVAL_RECT_RUNNING = 1;
constexpr int16_t SAMOVAR_STARTVAL_RECT_DONE = 2;
constexpr uint8_t PROGRAM_END = PROGRAM_MAX;
constexpr int PROGRAM_DONE_AUTO_POWEROFF_MIN = 0;
constexpr float PAUSE_RESUME_HYSTERESIS_DELTA = 0.07f;
using TickType_t = unsigned long;
#define pdMS_TO_TICKS(x) (x)
#define portTICK_PERIOD_MS 1
static void vTaskDelay(int) {}

// ---- Глобальное состояние (общее для withdrawal() и pause_withdrawal()) ----
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
static unsigned long t_min = 0;
static uint8_t RowStopPauseCount = 0;
static unsigned long program_done_hold_since = 0;
static SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;

// [T09] Пост-аварийные гейты withdrawal() и pause_withdrawal() читают эти флаги.
static bool PowerOn = true;
static bool alarm_event = false;

static unsigned long fake_millis_value = 100000;
static unsigned long millis() { return fake_millis_value; }

// ---- Моки внешних примитивов (не относятся к проверяемой логике гейтов) ----
static void SendMsg(const String&, MESSAGE_TYPE) {}
static void set_buzzer(bool) {}
static bool set_program_wait_type(ProgramWaitType, TickType_t) { return true; }
static bool copy_program_wait_type(ProgramWaitType& out) { out = PROGRAM_WAIT_NONE; return true; }
static void reset_impurity_detector() {}
static void detector_on_auto_resume() {}
static bool detector_trend_settled() { return false; }
static void apply_row_stop_pause_policy() {}
static void set_body_temp() {}
static bool is_steam_stable() { return false; }
static uint32_t body_temp_capture_deadline = 0;
static bool body_temp_autoset_allowed() { return false; }
static bool is_first_body_program_after_heads(uint8_t, ProgramType) { return false; }
static bool program_type_one_of(ProgramType, const char*) { return false; }
static void set_pump_speed(float, bool, bool = true) {}
static void run_program(uint8_t) {}

static ProgramType program_type_at(uint8_t index) {
  return index < ProgramLen ? program[index].WType : PROGRAM_TYPE_NONE;
}

static bool rectTransitionRequestedFixture = false;
static bool rect_row_transition_requested(const WProgram&, uint32_t, uint32_t, int16_t, float, float) {
  return rectTransitionRequestedFixture;
}

static int processImpurityDetectorCalls = 0;
static void process_impurity_detector() { processImpurityDetectorCalls++; }

static int menuSamovarStartCalls = 0;
static void menu_samovar_start() { menuSamovarStartCalls++; }

// Стэппер: общий набор для withdrawal() (только чтение) и pause_withdrawal()
// (чтение + запись).
static bool stepperState = false;
static bool stepper_safe_get_state() { return stepperState; }
static uint32_t stepper_safe_get_current() { return CurrrentStepps; }
static uint32_t stepper_safe_get_target() { return TargetStepps; }
static float stepper_safe_get_speed() { return 100.0f; }
static void stopService() {}

static int stepperSetMaxSpeedCalls = 0;
static void stepper_safe_set_max_speed(uint16_t) { stepperSetMaxSpeedCalls++; }
static int stepperSetCurrentCalls = 0;
static void stepper_safe_set_current(int32_t) { stepperSetCurrentCalls++; }
static int stepperSetTargetCalls = 0;
static void stepper_safe_set_target(uint32_t) { stepperSetTargetCalls++; }
static int stepperStopCalls = 0;
static void stepper_safe_stop() { stepperStopCalls++; }

static int startServiceCalls = 0;
static void startService() { startServiceCalls++; }

// ---- Реальный код под тестом (extract_function_body) ----
// withdrawal() вызывает pause_withdrawal() до её определения ниже - нужен прототип.
static void pause_withdrawal(bool Pause);

@WITHDRAWAL_BODY@
@PAUSE_WITHDRAWAL_BODY@

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
  ProgramLen = 2;
  program[0].WType = 'B';
  program[1].WType = 'T';
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
  TargetStepps = 999999;
  CurrrentStepperSpeed = 100;
  t_min = 0;
  RowStopPauseCount = 0;
  program_done_hold_since = 0;
  fake_millis_value = 100000;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  PowerOn = true;
  alarm_event = false;
  rectTransitionRequestedFixture = false;
  processImpurityDetectorCalls = 0;
  menuSamovarStartCalls = 0;
  stepperState = false;
  stepperSetMaxSpeedCalls = 0;
  stepperSetCurrentCalls = 0;
  stepperSetTargetCalls = 0;
  stepperStopCalls = 0;
  startServiceCalls = 0;
}

// Положительный контроль: без аварии withdrawal() доходит хотя бы до
// process_impurity_detector() - это доказывает, что харнесс не блокирует
// её вызов сам по себе (иначе отрицательные проверки ниже были бы бессмысленны).
static void test_withdrawal_normal_reaches_detector() {
  reset_fixture();
  withdrawal();
  check(processImpurityDetectorCalls == 1, "withdrawal() в норме должна дойти до process_impurity_detector()");
}

// [T09] withdrawal() в аварии (PowerOn=false и/или alarm_event=true) - no-op:
// код не должен доходить даже до process_impurity_detector().
static void test_withdrawal_noop_during_emergency() {
  reset_fixture();
  PowerOn = false;
  alarm_event = true;
  withdrawal();
  check(processImpurityDetectorCalls == 0, "withdrawal() при PowerOn=false,alarm_event=true должна быть no-op");

  reset_fixture();
  PowerOn = false;
  withdrawal();
  check(processImpurityDetectorCalls == 0, "withdrawal() при PowerOn=false должна быть no-op");

  reset_fixture();
  alarm_event = true;
  withdrawal();
  check(processImpurityDetectorCalls == 0, "withdrawal() при alarm_event=true должна быть no-op");
}

// [T09] pause_withdrawal(false) в норме доводит возобновление до startService().
static void test_pause_withdrawal_resume_normal() {
  reset_fixture();
  PauseOn = true;  // отбор был на паузе
  CurrrentStepperSpeed = 250;
  CurrrentStepps = 10;
  TargetStepps = 500;

  pause_withdrawal(false);

  check(!PauseOn, "pause_withdrawal(false) должна снять PauseOn");
  check(startServiceCalls == 1, "pause_withdrawal(false) в норме должна вызвать startService()");
  check(stepperSetMaxSpeedCalls == 1 && stepperSetCurrentCalls == 1 && stepperSetTargetCalls == 1,
        "pause_withdrawal(false) в норме должна восстановить скорость/позицию/цель стэппера");
}

// [T09][код-ревью] pause_withdrawal(false) в аварии не должна возобновлять сервис
// И НЕ ДОЛЖНА МЕНЯТЬ PauseOn - иначе PauseOn рассинхронизируется с SamovarStatusInt
// (снаружи статус остаётся "Пауза", а PauseOn уже false). Гейт стоит ДО присваивания
// PauseOn = Pause, поэтому оно вообще не должно выполняться при блокировке.
static void test_pause_withdrawal_resume_blocked_by_emergency() {
  reset_fixture();
  PauseOn = true;
  PowerOn = false;
  alarm_event = true;
  pause_withdrawal(false);
  check(startServiceCalls == 0, "pause_withdrawal(false) при PowerOn=false,alarm_event=true не должна звать startService()");
  check(stepperSetMaxSpeedCalls == 0, "pause_withdrawal(false) в аварии не должна трогать стэппер");
  check(PauseOn, "pause_withdrawal(false) при PowerOn=false,alarm_event=true НЕ должна менять PauseOn");

  reset_fixture();
  PauseOn = true;
  PowerOn = false;
  pause_withdrawal(false);
  check(startServiceCalls == 0, "pause_withdrawal(false) при PowerOn=false не должна звать startService()");
  check(PauseOn, "pause_withdrawal(false) при PowerOn=false НЕ должна менять PauseOn");

  reset_fixture();
  PauseOn = true;
  alarm_event = true;
  pause_withdrawal(false);
  check(startServiceCalls == 0, "pause_withdrawal(false) при alarm_event=true не должна звать startService()");
  check(PauseOn, "pause_withdrawal(false) при alarm_event=true НЕ должна менять PauseOn");
}

// [T09][код-ревью] Постановка на паузу (Pause=true) по-прежнему разрешена всегда -
// гейт `!Pause && (...)` на неё не действует, движение к остановке не блокируем
// даже при выключенном питании/аварии.
static void test_pause_withdrawal_pause_allowed_during_emergency() {
  reset_fixture();
  stepperState = true;  // отбор активен - без этого сработает более ранний guard "нечего ставить на паузу"
  PauseOn = false;
  PowerOn = false;
  alarm_event = true;
  pause_withdrawal(true);
  check(PauseOn, "pause_withdrawal(true) должна ставить PauseOn даже при PowerOn=false,alarm_event=true");
  check(stepperStopCalls == 1, "pause_withdrawal(true) должна останавливать стэппер даже при PowerOn=false,alarm_event=true");

  reset_fixture();
  stepperState = true;
  PauseOn = false;
  PowerOn = false;
  pause_withdrawal(true);
  check(PauseOn, "pause_withdrawal(true) должна ставить PauseOn при PowerOn=false");
  check(stepperStopCalls == 1, "pause_withdrawal(true) должна останавливать стэппер при PowerOn=false");
}

int main() {
  test_withdrawal_normal_reaches_detector();
  test_withdrawal_noop_during_emergency();
  test_pause_withdrawal_resume_normal();
  test_pause_withdrawal_resume_blocked_by_emergency();
  test_pause_withdrawal_pause_allowed_during_emergency();

  if (failures != 0) return 1;
  std::cout << "emergency stop post-alarm gate behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    bodies = {}
    files_cache: dict[str, str] = {}
    for key, (signature, filename) in SIGNATURES.items():
        if filename not in files_cache:
            files_cache[filename] = (ROOT / filename).read_text(encoding="utf-8")
        bodies[key] = extract_function_body(files_cache[filename], signature)

    harness = HARNESS_TEMPLATE
    harness = harness.replace(
        "@WITHDRAWAL_BODY@",
        "static void withdrawal(void) {" + bodies["withdrawal"] + "}",
    )
    harness = harness.replace(
        "@PAUSE_WITHDRAWAL_BODY@",
        "static void pause_withdrawal(bool Pause) {" + bodies["pause_withdrawal"] + "}",
    )
    return harness


def compile_and_run(harness: str, show_output: bool = True) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-emergency-stop-reset-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "emergency_stop_reset_test.cpp"
        binary = temp / "emergency_stop_reset_test"
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
        if show_output:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode



# --- [Ревью 25.08] Почему beerFinishPending обязан сниматься в reset_process_state ---
#
# mode_dispatch_loop() зовёт тик режима ТОЛЬКО когда SamovarStatusInt попадает в
# диапазон статусов текущего режима. reset_process_state() ставит статус в IDLE,
# а у пива диапазон [SAMOVAR_STATUS_BEER, +1) - после аварии тик пива больше не
# вызывается, и оба места, повторяющие зависший beer_finish() (beer_proc() и
# beer_stage_tick()), недостижимы. Харнесс берёт РЕАЛЬНЫЕ тела обеих функций
# диспетчеризации и показывает это поведением, а не текстом.

DISPATCH_HARNESS = r"""
#include <iostream>

typedef int SAMOVAR_MODE;
#define SAMOVAR_BEER_MODE 2

static const int SAMOVAR_STATUS_IDLE = 0;
static const int SAMOVAR_STATUS_BEER = 2000;
static const int SAMOVAR_STARTVAL_IDLE = 0;
static const int SAMOVAR_STARTVAL_BEER_START = 2000;

static int SamovarStatusInt = SAMOVAR_STATUS_IDLE;
static int startval = SAMOVAR_STARTVAL_IDLE;
static bool switchInProgress = false;

static int beerProcCalls = 0;
static int beerStageTickCalls = 0;
static int warnings = 0;

enum { WARNING_MSG = 1 };
static void SendMsg(const char*, int) { warnings++; }
static void beer_proc() { beerProcCalls++; }
static void beer_stage_tick() { beerStageTickCalls++; }
static bool mode_switch_in_progress() { return switchInProgress; }

struct ModeOps {
  int mode;
  int statusRangeLow;
  int statusRangeHigh;
  void (*tick)();
};

@MODE_TICK_BEER_BODY@

static int beerTickCalls = 0;
static void mode_tick_beer_counted() { beerTickCalls++; mode_tick_beer(); }

static const ModeOps beerOps = {
    SAMOVAR_BEER_MODE, SAMOVAR_STATUS_BEER, SAMOVAR_STATUS_BEER + 1, mode_tick_beer_counted};

static const ModeOps* mode_ops_current() { return &beerOps; }

static bool mode_status_belongs(const ModeOps* ops, int status) {
  if (ops == nullptr) return false;
  if (ops->statusRangeLow >= ops->statusRangeHigh) return false;
  return status >= ops->statusRangeLow && status < ops->statusRangeHigh;
}

static bool mode_status_session_active(int status) { return status != SAMOVAR_STATUS_IDLE; }

@MODE_DISPATCH_LOOP_BODY@

static int failures = 0;
static void expect(bool condition, const char* what) {
  if (!condition) { std::cout << "ASSERT: " << what << std::endl; failures++; }
}

int main() {
  // Штатная варка: статус принадлежит режиму - тик доходит до beer_proc().
  SamovarStatusInt = SAMOVAR_STATUS_BEER;
  startval = SAMOVAR_STARTVAL_BEER_START;
  beerProcCalls = beerStageTickCalls = beerTickCalls = warnings = 0;
  mode_dispatch_loop();
  expect(beerProcCalls == 1, "штатная варка: beer_proc() вызывается");

  // Штатная варка на поздней стадии - тик доходит до beer_stage_tick().
  startval = SAMOVAR_STARTVAL_BEER_START + 1;
  beerProcCalls = beerStageTickCalls = 0;
  mode_dispatch_loop();
  expect(beerStageTickCalls == 1, "поздняя стадия: beer_stage_tick() вызывается");

  // Статус пива, но стадия сброшена: внутренний гейт mode_tick_beer() не пускает
  // ни к beer_proc(), ни к beer_stage_tick().
  startval = SAMOVAR_STARTVAL_IDLE;
  beerProcCalls = beerStageTickCalls = 0;
  mode_dispatch_loop();
  expect(beerProcCalls == 0 && beerStageTickCalls == 0,
         "стадия IDLE: гейт по startval не пускает к телу варки");

  // После reset_process_state() (авария/стоп): статус IDLE - тик режима НЕ вызывается
  // вовсе. Значит залипшую заявку beerFinishPending подхватить некому.
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  startval = SAMOVAR_STARTVAL_IDLE;
  beerProcCalls = beerStageTickCalls = beerTickCalls = warnings = 0;
  mode_dispatch_loop();
  expect(beerTickCalls == 0,
         "после сброса процесса тик пива не вызывается - заявку подхватить некому");
  expect(warnings == 0, "простой (IDLE) не считается рассогласованием и не шлёт предупреждение");

  if (failures) { std::cout << "FAILURES: " << failures << std::endl; return 1; }
  std::cout << "dispatch reachability checks passed" << std::endl;
  return 0;
}
"""


def build_dispatch_harness() -> str:
    registry_text = read_text("mode_registry.h")
    if not registry_text:
        raise ValueError("mode_registry.h not found")
    tick_body = extract_function_body(registry_text, "inline void mode_tick_beer()")
    dispatch_body = extract_function_body(registry_text, "inline void mode_dispatch_loop()")
    harness = DISPATCH_HARNESS
    harness = harness.replace(
        "@MODE_TICK_BEER_BODY@", "static void mode_tick_beer() {" + tick_body + "}")
    harness = harness.replace(
        "@MODE_DISPATCH_LOOP_BODY@", "static void mode_dispatch_loop() {" + dispatch_body + "}")
    return harness


def check_dispatch_reachability() -> int:
    try:
        harness = build_dispatch_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if compile_and_run(harness) != 0:
        return 1
    # Мутации валят ASSERT, а не компилятор: подменяется тело заглушки/гейта,
    # все функции остаются используемыми (харнесс собирается с -Werror).
    mutants = [
        # Гейт принадлежности статуса снят - тик режима пошёл бы и при IDLE,
        # то есть проверка перестала бы пинить причину сброса флага.
        ("status_belongs_gate",
         "  if (ops->statusRangeLow >= ops->statusRangeHigh) return false;\n"
         "  return status >= ops->statusRangeLow && status < ops->statusRangeHigh;",
         "  (void)status;\n  return ops->statusRangeLow <= ops->statusRangeHigh;"),
        # Внутренний гейт mode_tick_beer() по стадии снят.
        ("beer_startval_gate",
         "if (startval == SAMOVAR_STARTVAL_BEER_START) beer_proc();",
         "if (startval != -1) beer_proc();"),
    ]
    for name, original, replacement in mutants:
        mutant = harness.replace(original, replacement, 1)
        if mutant == harness:
            print(f"FAIL: не удалось построить мутацию {name}", file=sys.stderr)
            return 1
        if compile_and_run(mutant, show_output=False) == 0:
            print(f"FAIL: мутация {name} пережила тест", file=sys.stderr)
            return 1
    return 0


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if compile_and_run(harness) != 0:
        return 1
    if check_dispatch_reachability() != 0:
        return 1

    mutants = [
        (
            "withdrawal_gate",
            "static void withdrawal(void) {\n  if (!PowerOn || alarm_event) return;",
            "static void withdrawal(void) {\n  if (false) return;",
        ),
        (
            # [код-ревью] Гейт возобновления должен стоять ДО PauseOn = Pause;.
            # Если его случайно вернуть ПОСЛЕ присваивания (старый баг), PauseOn
            # успевает стать false ещё до выхода - мутация имитирует этот откат.
            "pause_withdrawal_resume_gate_after_assignment",
            "if (!Pause && (!PowerOn || alarm_event)) return;\n  PauseOn = Pause;",
            "PauseOn = Pause;\n  if (!Pause && (!PowerOn || alarm_event)) return;",
        ),
        (
            "pause_withdrawal_resume_gate_removed",
            "if (!Pause && (!PowerOn || alarm_event)) return;\n  PauseOn = Pause;",
            "PauseOn = Pause;",
        ),
    ]
    for name, original, replacement in mutants:
        mutant = harness.replace(original, replacement, 1)
        if mutant == harness:
            print(f"FAIL: не удалось построить мутацию {name}", file=sys.stderr)
            return 1
        if compile_and_run(mutant, show_output=False) == 0:
            print(f"FAIL: мутация {name} пережила тест", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
