#!/usr/bin/env python3
"""Регресс-проверка [P7 п.3a] mode_common.h: явный запрос старта нагрева.

Раньше mode_begin_heating_session стартовало сессию нагрева всегда, как только
предусловия (PowerOn/SamovarStatusInt/heater_safety_latched/power_transition_active)
были в порядке - в т.ч. и в тике сразу после отказа регулятора, который сам
сбросил SamovarStatusInt в IDLE, а вышестоящий код (proc()) тут же выставил его
обратно в активный статус. Получался молчаливый авто-рестарт нагрева без нового
действия пользователя.

Теперь mode_begin_heating_session требует ОДНОРАЗОВЫЙ флаг
modeHeatingStartRequested (взводится ТОЛЬКО mode_request_heating_start(status), см.
mode_registry.h::mode_apply_power_on_command) - без него сессия не начинается,
с явным сообщением через mode_cancel_process_start. Флаг потребляется
(consume) при первой же проверке - следующий вызов снова требует явного взвода.

[P7 F1] Флаг взводится generic-веткой mode_apply_power_on_command для ЛЮБОГО
табличного режима (в т.ч. BEER/NBK, которые mode_begin_heating_session не
вызывают и потому флаг не потребляют). Чтобы чужой (для другого activeStatus)
или устаревший взвод не мог быть ошибочно потреблён другим режимом,
mode_request_heating_start(activeStatus) хранит вместе с флагом целевой
статус, а mode_consume_heating_start_request(activeStatus) сверяет его с
запрошенным - несовпадение даёт false и флаг НЕ снимается.

Тест вытаскивает РЕАЛЬНЫЕ тела mode_request_heating_start,
mode_consume_heating_start_request, mode_cancel_process_start,
mode_warn_log_close_failed, mode_clear_heating_start, mode_fail_heating_start,
mode_begin_heating_session из mode_common.h, реальный SafetyTransition/enum из
safety_transition.h (через -I ROOT), и компилирует их в харнесс с
не-static-моками истинно внешних зависимостей (heater_safety_latched,
power_transition_active, create_data, reset_heat_loss_calculation,
request_data_log_close, set_power, SendMsg).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

FUNCTIONS = [
    "inline void mode_request_heating_start(int16_t activeStatus)",
    "inline bool mode_consume_heating_start_request(int16_t activeStatus)",
    "inline void mode_cancel_process_start(const String& message)",
    "inline void mode_warn_log_close_failed()",
    "inline void mode_clear_heating_start()",
    "inline ModeHeatingStartResult mode_fail_heating_start()",
    "inline ModeHeatingStartResult mode_begin_heating_session(\n"
    "  int16_t activeStatus,\n"
    "  const char* createLogError,\n"
    "  const char* sessionBusyError,\n"
    "  const String& mqttProgram,\n"
    "  const char* heatingMessage,\n"
    "  bool resetHeatLoss\n"
    ")",
]

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

using TickType_t = int;

#include "safety_transition.h"

enum MESSAGE_TYPE {ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, NONE_MSG = 100};

constexpr int16_t SAMOVAR_STATUS_IDLE = 0;
constexpr int16_t SAMOVAR_STARTVAL_IDLE = 0;
constexpr int16_t TEST_ACTIVE_STATUS = 1000;
constexpr int16_t OTHER_ACTIVE_STATUS = 2000;

// Минимальный совместимый с Arduino String: только то, что реально нужно
// извлечённым телам (конструирование из const char*, чтение как std::string
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
bool PowerOn = false;
int16_t SamovarStatusInt = SAMOVAR_STATUS_IDLE;
int16_t startval = SAMOVAR_STARTVAL_IDLE;

@ENUM@

@STRUCT@

static ModeHeatingStartState modeHeatingStart;
static bool modeHeatingStartRequested = false;
static int16_t modeHeatingStartRequestedStatus = 0;

// --- Моки истинно внешних зависимостей (не-static) ---
static bool heaterSafetyLatchedReturn = false;
bool heater_safety_latched() { return heaterSafetyLatchedReturn; }

static bool powerTransitionActiveReturn = false;
bool power_transition_active() { return powerTransitionActiveReturn; }

static bool createDataReturn = true;
static int createDataCalls = 0;
bool create_data() { createDataCalls++; return createDataReturn; }

static int resetHeatLossCalls = 0;
void reset_heat_loss_calculation() { resetHeatLossCalls++; }

static bool requestDataLogCloseReturn = true;
bool request_data_log_close() { return requestDataLogCloseReturn; }

static int setPowerCalls = 0;
static bool lastSetPowerOn = false;
void set_power(bool On, bool enqueueResetCommand = true) {
  (void)enqueueResetCommand;
  setPowerCalls++;
  lastSetPowerOn = On;
  PowerOn = On;
}

static int sendMsgCalls = 0;
static std::string lastSendMsgText;
static int lastSendMsgType = -1;
void SendMsg(const String& msg, int type) {
  sendMsgCalls++;
  lastSendMsgText = msg.str();
  lastSendMsgType = type;
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
  PowerOn = false;
  SamovarStatusInt = TEST_ACTIVE_STATUS;
  startval = SAMOVAR_STARTVAL_IDLE;
  modeHeatingStart = ModeHeatingStartState();
  modeHeatingStartRequested = false;
  modeHeatingStartRequestedStatus = 0;
  heaterSafetyLatchedReturn = false;
  powerTransitionActiveReturn = false;
  createDataReturn = true;
  createDataCalls = 0;
  resetHeatLossCalls = 0;
  requestDataLogCloseReturn = true;
  setPowerCalls = 0;
  lastSetPowerOn = false;
  sendMsgCalls = 0;
  lastSendMsgText.clear();
  lastSendMsgType = -1;
}

int main() {
  // Сценарий 1: флаг НЕ взведён -> отказ до create_data()/set_power(), явное
  // сообщение через mode_cancel_process_start, статус/startval сброшены в IDLE.
  reset_fixture();
  {
    ModeHeatingStartResult result = mode_begin_heating_session(
      TEST_ACTIVE_STATUS, "log error", "busy error", String("prog"), "started", true
    );
    check(result == MODE_HEATING_START_FAILED, "1: без взведённого флага должен быть отказ");
    check(createDataCalls == 0, "1: create_data не должен вызываться без взведённого флага");
    check(setPowerCalls == 0, "1: set_power не должен вызываться без взведённого флага");
    check(sendMsgCalls == 1, "1: должно быть отправлено ровно одно сообщение");
    check(
      lastSendMsgText == "Нагрев не возобновлён автоматически. Требуется повторная команда старта.",
      "1: сообщение об отказе должно быть точным (без взведённого флага)"
    );
    check(lastSendMsgType == ALARM_MSG, "1: сообщение об отказе должно быть ALARM_MSG");
    check(SamovarStatusInt == SAMOVAR_STATUS_IDLE, "1: SamovarStatusInt должен быть сброшен в IDLE");
    check(startval == SAMOVAR_STARTVAL_IDLE, "1: startval должен быть сброшен в IDLE");
  }

  // Сценарий 2: флаг взведён для ТОГО ЖЕ activeStatus -> проверка проходит,
  // выполнение идёт дальше (create_data вызван, дошло до set_power(true),
  // результат PENDING).
  reset_fixture();
  mode_request_heating_start(TEST_ACTIVE_STATUS);
  {
    ModeHeatingStartResult result = mode_begin_heating_session(
      TEST_ACTIVE_STATUS, "log error", "busy error", String("prog"), "started", true
    );
    check(result == MODE_HEATING_START_PENDING, "2: со взведённым флагом сессия должна успешно начаться (PENDING)");
    check(createDataCalls == 1, "2: create_data должен быть вызван - проверка флага пройдена");
    check(resetHeatLossCalls == 1, "2: resetHeatLoss должен быть применён");
    check(setPowerCalls == 1 && lastSetPowerOn == true, "2: set_power(true) должен быть вызван в конце");
    check(PowerOn == true, "2: PowerOn должен стать true после успешного старта");
  }

  // Сценарий 3: одноразовость - после успешного потребления в сценарии 2
  // повторный прямой вызов mode_consume_heating_start_request(TEST_ACTIVE_STATUS)
  // должен вернуть false (флаг уже снят и не взводился заново).
  check(
    mode_consume_heating_start_request(TEST_ACTIVE_STATUS) == false,
    "3: флаг должен быть одноразовым - повторное потребление даёт false"
  );

  // Сценарий 4: сброс сессии (как после отказа регулятора/выключения) и
  // повторный вызов mode_begin_heating_session БЕЗ повторного взвода флага ->
  // снова отказ (флаг не сохранился/не взвёлся сам по себе).
  reset_fixture();
  {
    ModeHeatingStartResult result = mode_begin_heating_session(
      TEST_ACTIVE_STATUS, "log error", "busy error", String("prog"), "started", true
    );
    check(result == MODE_HEATING_START_FAILED, "4: без повторного взвода флага новая попытка должна снова быть отклонена");
    check(createDataCalls == 0, "4: create_data не должен вызываться без повторного взвода флага");
  }

  // Сценарий 5 [P7 F1]: взвод для ОДНОГО activeStatus (например, взведён
  // generic-веткой для BEER/NBK) не должен потребляться ПРОВЕРКОЙ ДРУГОГО
  // статуса (например, DISTILLATION/BK через mode_begin_heating_session) -
  // чужой взвод не проходит, и флаг остаётся взведённым для своего статуса.
  reset_fixture();
  mode_request_heating_start(OTHER_ACTIVE_STATUS);
  check(
    mode_consume_heating_start_request(TEST_ACTIVE_STATUS) == false,
    "5: взвод для чужого activeStatus не должен потребляться проверкой другого статуса"
  );
  check(
    mode_consume_heating_start_request(OTHER_ACTIVE_STATUS) == true,
    "5: тот же статус, для которого был взведён флаг, должен успешно потребить его"
  );
  check(
    mode_consume_heating_start_request(OTHER_ACTIVE_STATUS) == false,
    "5: после потребления повторная проверка того же статуса должна снова дать false (одноразовость сохранена)"
  );

  // Сценарий 6 [P7 F1]: та же ситуация сквозь mode_begin_heating_session -
  // флаг взведён для ЧУЖОГО статуса (BEER/NBK), попытка начать сессию СВОЕГО
  // статуса (activeStatus == SamovarStatusInt == TEST_ACTIVE_STATUS) должна
  // быть отклонена, как будто флаг вовсе не взводился.
  reset_fixture();
  mode_request_heating_start(OTHER_ACTIVE_STATUS);
  {
    ModeHeatingStartResult result = mode_begin_heating_session(
      TEST_ACTIVE_STATUS, "log error", "busy error", String("prog"), "started", true
    );
    check(result == MODE_HEATING_START_FAILED, "6: взвод для чужого статуса не должен запускать сессию текущего статуса");
    check(createDataCalls == 0, "6: create_data не должен вызываться при чужом взводе флага");
    check(setPowerCalls == 0, "6: set_power не должен вызываться при чужом взводе флага");
  }

  if (failures != 0) return 1;
  std::cout << "mode heating start flag smoke checks passed\n";
  return 0;
}
'''


def build_harness(source: str) -> str:
    code = strip_cpp_comments(source)
    enum_body, _ = extract_braced_block_after(code, "enum ModeHeatingStartResult : uint8_t {")
    struct_body, _ = extract_braced_block_after(code, "struct ModeHeatingStartState {")
    enum_text = f"enum ModeHeatingStartResult : uint8_t {{{enum_body}}};"
    struct_text = f"struct ModeHeatingStartState {{{struct_body}}};"

    bodies = []
    for signature in FUNCTIONS:
        body = extract_function_body(code, signature)
        bodies.append(f"{signature} {{{body}}}")

    harness = HARNESS_TEMPLATE.replace("@ENUM@", enum_text)
    harness = harness.replace("@STRUCT@", struct_text)
    harness = harness.replace("@FUNCTIONS@", "\n\n".join(bodies))
    return harness


def main() -> int:
    source = (ROOT / "mode_common.h").read_text(encoding="utf-8")

    try:
        harness = build_harness(source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-mode-heating-start-flag-") as temp_dir:
        temp = Path(temp_dir)
        cpp_source = temp / "mode_heating_start_flag_test.cpp"
        binary = temp / "mode_heating_start_flag_test"
        cpp_source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-I", str(ROOT), str(cpp_source), "-o", str(binary),
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


if __name__ == "__main__":
    raise SystemExit(main())
