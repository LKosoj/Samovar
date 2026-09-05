#!/usr/bin/env python3
"""Поведенческая проверка [T1-2026-09-03]: рабочий потолок давления в НБК как
регулируемая величина (п.1 отчёта) + обучение потолка по факту реального
захлёба (п.2 отчёта).

Тест вытаскивает РЕАЛЬНЫЕ тела/блоки из nbk.h без переписывания логики:
  A) nbk_pressure_above_ceiling() + nbk_pressure_stale() (extract_function_body)
     - предикат "давление >= рабочего потолка".
  B) nbk_learn_pressure_ceiling() (extract_function_body) - обучение потолка
     по факту захлёба (min с нижней границей = половина стартового потолка).
  C) handle_nbk_stage_work() - блок "пауза на инерцию вышла" целиком
     (extract_braced_block_after), как в smoke_nbk_po_floor.py - новая ветка
     (б) "давление >= потолка" между веткой недогрева (а) и веткой перегрева (в).
  D) handle_nbk_stage_optimization() - ядро "if (nbk_opt_in_progress) {...}"
     (extract_braced_block_after), как в smoke_nbk_opt_found.py - новый блок
     предзахлёба по давлению (автовход в Работу при уже найденном оптимуме).
  E) Текстовые пины мест сброса/инициализации nbk_pressure_ceiling и
     nbk_high_pressure_ticks (run_nbk_program, tick_nbk_actuator_command) -
     без компиляции, по образцу check_reset_sites_pin из
     smoke_nbk_manual_overflow_latch.py.

Плюс 4 мутации (после strip_cpp_comments, каждая обязана провалить харнесс):
  - W: удержание 3 тиков в ветке давления -> 1 (ломает "2 тика без изменений").
  - O: "nbk_opt_found &&" убран из условия предзахлёба (ломает !found-сценарий).
  - Обучение: убрана нижняя граница floorCeiling (ломает floor-сценарий).
  - W: убран сброс nbk_high_temp_ticks в ветке pressureHigh (ломает
    сценарий "давление + перегрев одновременно").
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

STALE_SIGNATURE = "inline bool nbk_pressure_stale() {"
PREDICATE_SIGNATURE = "inline bool nbk_pressure_above_ceiling() {"
LEARN_SIGNATURE = "inline void nbk_learn_pressure_ceiling() {"
WORK_ANCHOR = "if (safety_deadline_expired(millis(), nbk_work_next_time))  {"
OPT_ANCHOR = "if (nbk_opt_in_progress) {"

# Мутация 1 (W): удержание 3 тиков в НОВОЙ ветке давления -> 1 тик.
# Якорь включает следующую строку (nbk_Po -= ...), т.к. точно такое же условие
# "nbk_high_pressure_ticks >= NBK_HIGH_TB_HOLD_TICKS" есть и в ядре
# Оптимизации (мутация 2 её не трогает, но replace(..., 1) без второй строки
# мог бы попасть не туда).
WORK_HOLD_MUTATION_ANCHOR = (
    "if (nbk_high_pressure_ticks >= NBK_HIGH_TB_HOLD_TICKS) {\n"
    "        nbk_Po -= nbk_dP / 10.0;"
)

# Мутация 2 (O): предзахлёб срабатывает БЕЗ учёта nbk_opt_found.
OPT_FOUND_MUTATION_ANCHOR = "if (nbk_opt_found && nbk_pressure_above_ceiling())"

# Мутация 3 (обучение): нижняя граница потолка (floorCeiling) убрана.
LEARN_FLOOR_MUTATION_ANCHOR = (
    "if (candidate < floorCeiling) candidate = floorCeiling; "
    "// нижняя граница — половина стартового потолка\n"
)

# Мутация 4 (W): сброс nbk_high_temp_ticks в ветке pressureHigh убран.
WORK_RESET_MUTATION_ANCHOR = (
    "nbk_high_temp_ticks = 0; // [T1-2026-09-03] давление приоритетнее "
    "— не даём веткам смешаться\n"
)

HEADER = r'''
#include <cmath>
#include <cstdint>
#include <iostream>
#include <string>

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
// Не static: харнесс A (предикат) не делает сравнений с допуском, поэтому
// не вызывает close() - со static неиспользованный экземпляр падал бы на
// -Wunused-function (см. тот же приём в smoke_nbk_power_floor.py).
bool close(float a, float b) { return std::fabs(a - b) < 0.001f; }
'''

STRING_CLASS = r'''
class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(int value) : value_(std::to_string(value)) {}
  String(float value, int) : value_(std::to_string(value)) {}
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
String operator+(const char* lhs, const String& rhs) {
  return String(lhs) + rhs;
}
'''


def build_predicate_harness(nbk_source: str) -> str:
    stale_body = extract_function_body(nbk_source, STALE_SIGNATURE)
    predicate_body = extract_function_body(nbk_source, PREDICATE_SIGNATURE)
    funcs = (
        "bool nbk_pressure_stale() {" + stale_body + "}\n"
        "bool nbk_pressure_above_ceiling() {" + predicate_body + "}\n"
    )
    return HEADER + r'''
bool use_pressure_sensor = false;
float pressure_value = 0.0f;
int pressure_err_count = 0;
float nbk_pressure_ceiling = 0.0f;

''' + funcs + r'''
int main() {
  // A1: все условия истинны -> true.
  use_pressure_sensor = true; pressure_value = 25.0f; pressure_err_count = 0; nbk_pressure_ceiling = 20.0f;
  check(nbk_pressure_above_ceiling(), "A1: все условия истинны, предикат обязан вернуть true");

  // A2: датчика нет -> false.
  use_pressure_sensor = false;
  check(!nbk_pressure_above_ceiling(), "A2: без use_pressure_sensor предикат обязан вернуть false");
  use_pressure_sensor = true;

  // A3: нет показания (-1) -> false.
  pressure_value = -1.0f;
  check(!nbk_pressure_above_ceiling(), "A3: pressure_value < 0 обязано вернуть false");
  pressure_value = 25.0f;

  // A4: несвежие показания ДД -> false.
  pressure_err_count = 11;
  check(!nbk_pressure_above_ceiling(), "A4: nbk_pressure_stale()==true обязано вернуть false");
  pressure_err_count = 0;

  // A5: потолок ещё не выставлен -> false.
  nbk_pressure_ceiling = 0.0f;
  check(!nbk_pressure_above_ceiling(), "A5: nbk_pressure_ceiling<=0 обязано вернуть false");
  nbk_pressure_ceiling = 20.0f;

  // A6: давление ниже потолка -> false.
  pressure_value = 19.0f;
  check(!nbk_pressure_above_ceiling(), "A6: давление ниже потолка обязано вернуть false");

  // A7: граница - давление ровно на потолке (>=) -> true.
  pressure_value = 20.0f;
  check(nbk_pressure_above_ceiling(), "A7: давление ровно на потолке (>=) обязано вернуть true");

  if (failures != 0) return 1;
  std::cout << "nbk_pressure_above_ceiling predicate checks passed\n";
  return 0;
}
'''


def build_learn_harness(nbk_source: str) -> str:
    body = extract_function_body(nbk_source, LEARN_SIGNATURE)
    func = "void nbk_learn_pressure_ceiling() {" + body + "}\n"
    return HEADER + STRING_CLASS + r'''
#define NBK_WORK_PRESSURE_RATIO 0.5f
#define NBK_PRESSURE_MARGIN 5

struct NbkSessionConfig { float overflowPressure; };
NbkSessionConfig nbkSessionConfig{40.0f};

bool use_pressure_sensor = true;
float pressure_value = 0.0f;
int pressure_err_count = 0;
float nbk_pressure_ceiling = 20.0f;
// Зеркало реальной семантики nbk_pressure_stale() - сам предикат уже
// отдельно пропиннен реальным телом в build_predicate_harness (блок A).
bool nbk_pressure_stale() { return pressure_err_count > 10; }

static int sendMsgCalls = 0;
void SendMsg(const String&, MESSAGE_TYPE) { sendMsgCalls++; }

''' + func + r'''
int main() {
  // B1: захлёб при 22, потолок 20 -> опускается до 17 (22-5), одно сообщение.
  nbk_pressure_ceiling = 20.0f; pressure_value = 22.0f; pressure_err_count = 0; sendMsgCalls = 0;
  nbk_learn_pressure_ceiling();
  check(nbk_pressure_ceiling == 17.0f, "B1: потолок обязан опуститься до pressure-MARGIN (22-5=17)");
  check(sendMsgCalls == 1, "B1: снижение потолка обязано отправить одно сообщение");

  // B2: захлёб при 45 (намного выше потолка) -> без изменений.
  nbk_pressure_ceiling = 20.0f; pressure_value = 45.0f; sendMsgCalls = 0;
  nbk_learn_pressure_ceiling();
  check(nbk_pressure_ceiling == 20.0f, "B2: захлёб выше текущего потолка не должен его поднимать");
  check(sendMsgCalls == 0, "B2: без изменения потолка сообщение не отправляется");

  // B3: захлёб при 12, потолок тоже 12 -> зажим на нижней границе 10 (=40*0.5/2).
  nbk_pressure_ceiling = 12.0f; pressure_value = 12.0f; sendMsgCalls = 0;
  nbk_learn_pressure_ceiling();
  check(nbk_pressure_ceiling == 10.0f, "B3: кандидат ниже нижней границы обязан зажаться на floorCeiling (10)");
  check(sendMsgCalls == 1, "B3: зажатое снижение потолка тоже обязано отправить сообщение");

  // B4: повтор при 11, потолок уже на floor (10) -> без изменений (идемпотентность).
  nbk_pressure_ceiling = 10.0f; pressure_value = 11.0f; sendMsgCalls = 0;
  nbk_learn_pressure_ceiling();
  check(nbk_pressure_ceiling == 10.0f, "B4: повтор на floor не должен ничего менять");
  check(sendMsgCalls == 0, "B4: без изменения потолка сообщение не отправляется");

  // B5: несвежие показания ДД -> без изменений.
  nbk_pressure_ceiling = 20.0f; pressure_value = 5.0f; pressure_err_count = 11; sendMsgCalls = 0;
  nbk_learn_pressure_ceiling();
  check(nbk_pressure_ceiling == 20.0f, "B5: при несвежем ДД потолок не должен меняться");
  check(sendMsgCalls == 0, "B5: при несвежем ДД сообщение не отправляется");
  pressure_err_count = 0;

  // B6: датчика нет -> без изменений.
  nbk_pressure_ceiling = 20.0f; pressure_value = 5.0f; use_pressure_sensor = false; sendMsgCalls = 0;
  nbk_learn_pressure_ceiling();
  check(nbk_pressure_ceiling == 20.0f, "B6: без ДД потолок не должен меняться");
  check(sendMsgCalls == 0, "B6: без ДД сообщение не отправляется");
  use_pressure_sensor = true;

  // B7: нет показания (-1) -> без изменений.
  nbk_pressure_ceiling = 20.0f; pressure_value = -1.0f; sendMsgCalls = 0;
  nbk_learn_pressure_ceiling();
  check(nbk_pressure_ceiling == 20.0f, "B7: при pressure_value<0 потолок не должен меняться");
  check(sendMsgCalls == 0, "B7: при pressure_value<0 сообщение не отправляется");

  if (failures != 0) return 1;
  std::cout << "nbk_learn_pressure_ceiling behaviour checks passed\n";
  return 0;
}
'''


def build_work_harness(nbk_source: str) -> str:
    body, _ = extract_braced_block_after(nbk_source, WORK_ANCHOR)
    wrapped = "static void work_tick() {" + body + "}"
    return HEADER + STRING_CLASS + r'''
enum NbkActuatorDeadlineTarget { NBK_ACTUATOR_NO_DEADLINE, NBK_ACTUATOR_OPTIMIZATION_DEADLINE, NBK_ACTUATOR_WORK_DEADLINE };
#define NBK_HIGH_TB_HOLD_TICKS 3
#define NBK_SPILL_DT_MULT 3

uint8_t nbk_high_temp_ticks = 0;
uint8_t nbk_high_pressure_ticks = 0;
float nbk_Po_ceiling = 1000.0f;

float pressure_value = 0.0f;
float nbk_pressure_ceiling = 20.0f;
static bool pressureAboveCeilingFlag = false;
bool nbk_pressure_above_ceiling() { return pressureAboveCeilingFlag; }

float nbk_Tb = 0;
float nbk_Tn = 98.5f;
float nbk_dT = 0.5f;
float nbk_dD = 0;
float nbk_Tp = 100.0f;
float nbk_Tp_lim = 81.0f;
float nbk_P = 0;
float nbk_Po = 0;
float nbk_M = 0;
float nbk_Mo = 100.0f;
float nbk_dP = 0.5f;
uint16_t nbk_column_inertia = 180;
uint16_t nbk_opt_iter = 0;

struct SensorProbe { float avgTemp; };
static SensorProbe TankSensor = {0.0f};
static SensorProbe SteamSensor = {100.0f};

static uint32_t fakeMillis = 1000;
uint32_t millis() { return fakeMillis; }
uint32_t nbk_work_next_time = 0;
uint32_t safety_deadline_after(uint32_t now, uint32_t ms) { return now + ms; }

static int scheduleCalls = 0;
static float lastSpeed = 0;
static float lastPower = -1.0f;
bool nbk_schedule_actuator_command(float m, float p, NbkActuatorDeadlineTarget, uint32_t, uint16_t) {
  scheduleCalls++;
  lastPower = m;
  lastSpeed = p;
  nbk_M = m;
  nbk_P = p;
  return true;
}
void nbk_enter_safe_wait(const String&) {}

static int sendMsgCalls = 0;
static String lastMsg;
void SendMsg(const String& msg, MESSAGE_TYPE) {
  sendMsgCalls++;
  lastMsg = msg;
}

''' + wrapped + r'''

static void reset_work_fixture() {
  fakeMillis = 1000;
  nbk_high_temp_ticks = 0;
  nbk_high_pressure_ticks = 0;
  nbk_Po_ceiling = 1000.0f;
  pressure_value = 25.0f;
  nbk_pressure_ceiling = 20.0f;
  pressureAboveCeilingFlag = false;
  nbk_Tn = 98.5f; nbk_dT = 0.5f; nbk_dD = 0.0f;
  nbk_Tp_lim = 81.0f;
  nbk_dP = 0.5f;
  nbk_column_inertia = 180;
  nbk_opt_iter = 0;
  scheduleCalls = 0; lastSpeed = 0; lastPower = -1.0f;
  sendMsgCalls = 0; lastMsg = String("");
  nbk_work_next_time = 0;
}

int main() {
  // C1: 3 тика подряд с давлением выше потолка, Тб/Тп нейтральны - на 3-м
  // тике По снижается на dП/10 и сброс счётчика, сообщение про потолок.
  reset_work_fixture();
  TankSensor.avgTemp = 98.5f;   // == nbk_Tn: обе температурные ветки ложны
  SteamSensor.avgTemp = 100.0f; // >= nbk_Tp_lim
  pressureAboveCeilingFlag = true;
  nbk_Po = 10.0f; nbk_M = 100.0f; nbk_Mo = 100.0f; nbk_P = 10.0f;

  work_tick();
  check(nbk_high_pressure_ticks == 1, "C1: 1-й тик обязан взвести счётчик в 1");
  check(nbk_Po == 10.0f, "C1: на 1-м тике По не должна меняться (удержание не набрано)");
  check(sendMsgCalls == 0, "C1: на 1-м тике сообщения быть не должно");

  work_tick();
  check(nbk_high_pressure_ticks == 2, "C1: 2-й тик подряд обязан довести счётчик до 2");
  check(nbk_Po == 10.0f, "C1: на 2-м тике По по-прежнему не должна меняться");
  check(sendMsgCalls == 0, "C1: на 2-м тике сообщения по-прежнему быть не должно");

  work_tick();
  check(nbk_high_pressure_ticks == 0, "C1: на 3-м тике счётчик обязан сброситься после срабатывания");
  check(close(nbk_Po, 9.95f), "C1: на 3-м тике По обязана снизиться ровно на dП/10 (10.0-0.05)");
  check(sendMsgCalls == 1, "C1: на 3-м тике обязано уйти ровно одно сообщение");
  check(lastMsg.contains("потолка"), "C1: сообщение обязано упомянуть потолок давления");

  // C2: перегрев (Тб>Тн+dT) одновременно с высоким давлением - По НЕ растёт
  // (ветка pressureHigh стоит раньше ветки перегрева), nbk_high_temp_ticks
  // обязан обнулиться.
  reset_work_fixture();
  TankSensor.avgTemp = 100.0f; // > nbk_Tn+dT (99.0) - без давления пошёл бы рост По
  SteamSensor.avgTemp = 100.0f;
  pressureAboveCeilingFlag = true;
  nbk_high_temp_ticks = 5; // ненулевое значение, чтобы проверить обнуление
  nbk_Po = 10.0f; nbk_M = 100.0f; nbk_Mo = 100.0f; nbk_P = 10.0f;
  work_tick();
  check(nbk_Po == 10.0f, "C2: По не должна расти, пока давление выше потолка");
  check(nbk_high_temp_ticks == 0, "C2: ветка pressureHigh обязана сбрасывать nbk_high_temp_ticks");

  // C3: недогрев (Тб < Тн-dT) важнее давления - ветка (а) срабатывает
  // немедленно, без 3-тикового удержания.
  reset_work_fixture();
  TankSensor.avgTemp = 97.5f; // [Пролив] < Тн(98.5)-dT(0.5)=98.0, но НЕ ниже порога пролива 97.0 (Тн-3dT)
  SteamSensor.avgTemp = 100.0f;
  pressureAboveCeilingFlag = true; // не должно помешать ветке (а)
  nbk_Po = 10.0f; nbk_M = 100.0f; nbk_Mo = 100.0f; nbk_P = 10.0f;
  work_tick();
  check(close(nbk_Po, 9.95f), "C3: недогрев обязан снизить По на dП/10 немедленно, невзирая на давление");
  check(lastMsg.contains("Тб < Тн-dT"), "C3: сообщение обязано быть про недогрев, а не про давление");

  // C4: По не должна уходить в минус при долгой серии срабатываний.
  reset_work_fixture();
  TankSensor.avgTemp = 98.5f;
  SteamSensor.avgTemp = 100.0f;
  pressureAboveCeilingFlag = true;
  nbk_Po = 0.1f; nbk_M = 100.0f; nbk_Mo = 100.0f; nbk_P = 0.1f;
  for (int i = 0; i < 30; i++) {
    work_tick();
    check(nbk_Po >= 0.0f, "C4: По не должна уходить в минус ни на одном тике");
  }
  check(nbk_Po == 0.0f, "C4: после долгой серии По обязана зафиксироваться на нуле");

  // C5 [Ревью итог 03.09]: счётчик давления считает тики ПОДРЯД - любая
  // другая ветка (пролив, просадка, перегрев) обязана обнулить его, иначе
  // «3 подряд» превращаются в «3 когда-нибудь» с застывшим счётчиком.
  // Пролив.
  reset_work_fixture();
  TankSensor.avgTemp = 96.0f; // < Тн-3dT (97.0) - ветка пролива
  SteamSensor.avgTemp = 100.0f;
  pressureAboveCeilingFlag = true;
  nbk_high_pressure_ticks = 2;
  nbk_Po = 10.0f; nbk_M = 100.0f; nbk_Mo = 100.0f; nbk_P = 10.0f;
  work_tick();
  check(nbk_high_pressure_ticks == 0, "C5: ветка пролива обязана обнулять nbk_high_pressure_ticks");
  // Обычная просадка.
  reset_work_fixture();
  TankSensor.avgTemp = 97.5f; // ветка просадки (Тн-dT > Тб > Тн-3dT)
  SteamSensor.avgTemp = 100.0f;
  pressureAboveCeilingFlag = true;
  nbk_high_pressure_ticks = 2;
  nbk_Po = 10.0f; nbk_M = 100.0f; nbk_Mo = 100.0f; nbk_P = 10.0f;
  work_tick();
  check(nbk_high_pressure_ticks == 0, "C5: ветка просадки обязана обнулять nbk_high_pressure_ticks");
  // Перегрев (давление уже НЕ высокое, иначе ветка pressureHigh перехватит).
  reset_work_fixture();
  TankSensor.avgTemp = 100.0f; // > Тн+dT (99.0)
  SteamSensor.avgTemp = 100.0f;
  pressureAboveCeilingFlag = false;
  nbk_high_pressure_ticks = 2;
  nbk_Po = 10.0f; nbk_M = 100.0f; nbk_Mo = 100.0f; nbk_P = 10.0f;
  work_tick();
  check(nbk_high_pressure_ticks == 0, "C5: ветка перегрева обязана обнулять nbk_high_pressure_ticks");

  if (failures != 0) return 1;
  std::cout << "nbk_pressure_ceiling handle_nbk_stage_work checks passed\n";
  return 0;
}
'''


def build_opt_harness(nbk_source: str) -> str:
    body, _ = extract_braced_block_after(nbk_source, OPT_ANCHOR)
    wrapped = "static void core_tick() {" + body + "}"
    return HEADER + STRING_CLASS + r'''
#define SAMOVAR_USE_POWER
#define PWR_MSG "Мощность"
#define PWR_SIGN "Вт"
#define NBK_PUMP_LIMIT 30
#define NBK_HIGH_TB_HOLD_TICKS 3
enum NbkActuatorDeadlineTarget { NBK_ACTUATOR_NO_DEADLINE, NBK_ACTUATOR_OPTIMIZATION_DEADLINE, NBK_ACTUATOR_WORK_DEADLINE };

struct SensorProbe { float avgTemp; };
static SensorProbe TankSensor{0};
static SensorProbe SteamSensor{0};

static bool overflowFlag = false;
bool overflow() { return overflowFlag; }
static int handleOverflowCalls = 0;
void handle_overflow(const String&, bool = true, uint32_t = 0, bool = false) { handleOverflowCalls++; }

static uint32_t fakeMillis = 1000;
uint32_t millis() { return fakeMillis; }
static uint32_t nbk_opt_next_time = 0;
bool safety_deadline_expired(uint32_t now, uint32_t deadline) {
  return (int32_t)(now - deadline) >= 0;
}

static uint16_t nbk_opt_iter = 0;
static uint8_t ProgramNum = 5;
static bool nbk_opt_found = false;
static float nbk_Tb = 0, nbk_Tn = 95.0f, nbk_dD = 0.0f;
static float nbk_Tp = 0, nbk_Tp_lim = 100.0f;
static float nbk_M = 0, nbk_P = 0;
static float nbk_dP = 1.0f, nbk_dM = 50.0f, nbk_M_max = 3000.0f;
static float nbk_Mo = -1, nbk_Po = -1;
static uint16_t nbk_column_inertia = 180;
float fromPower(float value) { return value; }
template <typename T> T max(T a, T b) { return a > b ? a : b; }

// [Тарировка Тн] не предмет этого теста - в D1-D3 nbk_Tb=0 (см. reset_opt_fixture),
// автотарировка объективно молчит, но флаг всё равно взводим заранее для ясности.
#define NBK_TN_AUTOCAL_MAX 102.0f
static bool nbk_tn_autocal_done = true;
struct NbkSessionConfig { float tankTemp; };
static NbkSessionConfig nbkSessionConfig{200.0f};

static uint8_t nbk_high_pressure_ticks = 0;
static float pressure_value = 0.0f;
static float nbk_pressure_ceiling = 20.0f;
static bool nbk_opt_entry_by_pressure = false;
static bool pressureAboveCeilingFlag = false;
bool nbk_pressure_above_ceiling() { return pressureAboveCeilingFlag; }
static int dirtyStreamCalls = 0;
void nbk_set_stream_dirty() { dirtyStreamCalls++; }

static int runNbkProgramCalls = 0;
static uint8_t lastRunNum = 255;
static bool lastWorkConfirmed = true;
static bool lastOptimumEntry = true;
void run_nbk_program(uint8_t num, bool workConfirmed = false, bool optimumEntry = false) {
  runNbkProgramCalls++;
  lastRunNum = num;
  lastWorkConfirmed = workConfirmed;
  lastOptimumEntry = optimumEntry;
}

static int sendMsgCalls = 0;
static String lastMsg;
void SendMsg(const String& msg, MESSAGE_TYPE) {
  sendMsgCalls++;
  lastMsg = msg;
}

static bool scheduleShouldSucceed = true;
static int scheduleCalls = 0;
static float scheduleLastM = -1, scheduleLastP = -1;
static uint16_t scheduleLastIter = 65535;
bool nbk_schedule_actuator_command(float candidateM, float candidateP, NbkActuatorDeadlineTarget, uint32_t, uint16_t nextIteration) {
  scheduleCalls++;
  scheduleLastM = candidateM;
  scheduleLastP = candidateP;
  scheduleLastIter = nextIteration;
  return scheduleShouldSucceed;
}

static int enterSafeWaitCalls = 0;
void nbk_enter_safe_wait(const String&) { enterSafeWaitCalls++; }

''' + wrapped + r'''

static void reset_opt_fixture() {
  nbk_opt_iter = 10;
  ProgramNum = 5;
  overflowFlag = false;
  handleOverflowCalls = 0;
  fakeMillis = 1000;
  nbk_opt_next_time = 500; // дедлайн уже прошёл - ядро выполняется
  nbk_Tb = 0; nbk_Tp = 0;
  TankSensor.avgTemp = 0; SteamSensor.avgTemp = 0;
  nbk_M = 0; nbk_P = 0;
  nbk_Mo = -1; nbk_Po = -1;
  nbk_column_inertia = 180;
  nbk_opt_found = false;
  runNbkProgramCalls = 0;
  lastRunNum = 255;
  lastWorkConfirmed = true;
  lastOptimumEntry = true;
  sendMsgCalls = 0;
  lastMsg = String("");
  scheduleShouldSucceed = true;
  scheduleCalls = 0;
  scheduleLastM = -1; scheduleLastP = -1; scheduleLastIter = 65535;
  enterSafeWaitCalls = 0;
  nbk_high_pressure_ticks = 0;
  pressure_value = 25.0f;
  nbk_pressure_ceiling = 20.0f;
  pressureAboveCeilingFlag = false;
  nbk_tn_autocal_done = true;
  nbk_opt_entry_by_pressure = false;
  dirtyStreamCalls = 0;
}

int main() {
  // D1: оптимум уже найден, давление выше потолка 3 итерации подряд -
  // на 3-й итерации автовход в Работу; до этого обычная логика (schedule
  // вызывается, итерация не "теряется").
  reset_opt_fixture();
  nbk_opt_found = true;
  pressureAboveCeilingFlag = true;
  TankSensor.avgTemp = 80.0f; SteamSensor.avgTemp = 50.0f; // обычная (не оптимум) точка
  nbk_M = 1000.0f; nbk_P = 5.0f;

  core_tick();
  check(nbk_high_pressure_ticks == 1, "D1: 1-я итерация обязана взвести счётчик в 1");
  check(runNbkProgramCalls == 0, "D1: на 1-й итерации автовход ещё не должен сработать");
  check(scheduleCalls == 1, "D1: на 1-й итерации обычная логика планирования обязана выполниться");

  core_tick();
  check(nbk_high_pressure_ticks == 2, "D1: 2-я итерация обязана довести счётчик до 2");
  check(runNbkProgramCalls == 0, "D1: на 2-й итерации автовход ещё не должен сработать");
  check(scheduleCalls == 2, "D1: на 2-й итерации обычная логика планирования обязана выполниться");

  const int msgsBeforeEntry = sendMsgCalls; // на итерациях 1-2 обычная логика могла слать свои сообщения
  core_tick();
  check(runNbkProgramCalls == 1, "D1: на 3-й итерации автовход обязан сработать ровно один раз");
  check(lastRunNum == ProgramNum + 1 && !lastWorkConfirmed && lastOptimumEntry,
        "D1: автовход обязан перейти на следующую строку с флагом optimumEntry");
  check(scheduleCalls == 2, "D1: на 3-й итерации schedule НЕ должен вызываться (ранний return)");
  // Единственное сообщение шлёт optimumEntry-ветка run_nbk_program (здесь заглушка);
  // ядро O лишь передаёт ей причину флагом и обнуляет счётчик.
  check(sendMsgCalls == msgsBeforeEntry, "D1: ядро O не должно слать собственное сообщение (иначе их будет два подряд)");
  check(nbk_opt_entry_by_pressure, "D1: причина автовхода обязана передаться флагом nbk_opt_entry_by_pressure");
  check(nbk_high_pressure_ticks == 0, "D1: после срабатывания счётчик обязан обнулиться");
  check(dirtyStreamCalls == 0, "D1: вход по давлению без overflow не должен переключать поток");

  // D2: оптимум ещё не найден - автовход по давлению не срабатывает,
  // счётчик каждый раз обнуляется, обычная логика выполняется всегда.
  reset_opt_fixture();
  nbk_opt_found = false;
  pressureAboveCeilingFlag = true;
  TankSensor.avgTemp = 80.0f; SteamSensor.avgTemp = 50.0f;
  nbk_M = 1000.0f; nbk_P = 5.0f;
  core_tick();
  core_tick();
  core_tick();
  check(runNbkProgramCalls == 0, "D2: без найденного оптимума автовход по давлению не должен сработать");
  check(nbk_high_pressure_ticks == 0, "D2: без found счётчик каждый тик обнуляется в else-ветке");
  check(scheduleCalls == 3, "D2: обычная логика планирования выполняется на каждой итерации");

  // D3: давление не выше потолка - счётчик держится на нуле, даже если
  // оптимум уже найден.
  reset_opt_fixture();
  nbk_opt_found = true;
  pressureAboveCeilingFlag = false;
  TankSensor.avgTemp = 80.0f; SteamSensor.avgTemp = 50.0f;
  nbk_M = 1000.0f; nbk_P = 5.0f;
  core_tick();
  check(nbk_high_pressure_ticks == 0, "D3: без давления выше потолка счётчик держится на нуле (1-я итерация)");
  core_tick();
  check(nbk_high_pressure_ticks == 0, "D3: без давления выше потолка счётчик держится на нуле (2-я итерация)");

  if (failures != 0) return 1;
  std::cout << "nbk_pressure_ceiling handle_nbk_stage_optimization checks passed\n";
  return 0;
}
'''


def check_reset_and_init_pins(nbk_source: str) -> list:
    """[Пин без компиляции, блок E плана] Три места, которые обязаны
    оставаться синхронными с логикой T1: инициализация рабочего потолка на
    старте сессии (после nbk_Po=0, там же где остальной сброс сессии),
    сброс счётчика nbk_high_pressure_ticks при новом заходе на строку O и
    при коммите строки актуатором (симметрично nbk_high_temp_ticks)."""
    stripped = strip_cpp_comments(nbk_source)
    errors: list = []

    try:
        num0_block, _ = extract_braced_block_after(stripped, "if (ProgramNum == 0) {")
    except ValueError as error:
        errors.append(f"ProgramNum==0 session-start block not found: {error}")
        num0_block = ""
    po_idx = num0_block.find("nbk_Po = 0;")
    ceiling_idx = num0_block.find("nbk_pressure_ceiling = nbkSessionConfig.overflowPressure * NBK_WORK_PRESSURE_RATIO;")
    if po_idx < 0:
        errors.append("ProgramNum==0 session start does not reset nbk_Po (anchor missing)")
    elif ceiling_idx < 0:
        errors.append("ProgramNum==0 session start does not initialize nbk_pressure_ceiling")
    elif ceiling_idx < po_idx:
        errors.append("nbk_pressure_ceiling init must come AFTER nbk_Po = 0 in session-start block")

    try:
        o_block, _ = extract_braced_block_after(stripped, "if (program[ProgramNum].WType == 'O') {")
    except ValueError as error:
        errors.append(f"O-row entry block not found: {error}")
        o_block = ""
    if "nbk_high_pressure_ticks = 0;" not in o_block:
        errors.append("entry to O row does not reset nbk_high_pressure_ticks")

    try:
        commit_block, _ = extract_braced_block_after(stripped, "if (nbkActuatorCommand.commitProgram) {")
    except ValueError as error:
        errors.append(f"commitProgram block not found: {error}")
        commit_block = ""
    temp_idx = commit_block.find("nbk_high_temp_ticks = 0;")
    pressure_idx = commit_block.find("nbk_high_pressure_ticks = 0;")
    if temp_idx < 0:
        errors.append("commitProgram block does not reset nbk_high_temp_ticks (anchor missing)")
    elif pressure_idx < 0:
        errors.append("commitProgram block does not reset nbk_high_pressure_ticks")
    elif pressure_idx < temp_idx:
        errors.append("nbk_high_pressure_ticks reset must come AFTER nbk_high_temp_ticks in commitProgram block")

    return errors


def mutate_work_hold_ticks(nbk_source: str) -> str:
    if WORK_HOLD_MUTATION_ANCHOR not in nbk_source:
        raise ValueError("mutation anchor missing: Work pressure hold-ticks threshold")
    mutated_anchor = WORK_HOLD_MUTATION_ANCHOR.replace("NBK_HIGH_TB_HOLD_TICKS", "1", 1)
    return nbk_source.replace(WORK_HOLD_MUTATION_ANCHOR, mutated_anchor, 1)


def mutate_opt_found_guard(nbk_source: str) -> str:
    if OPT_FOUND_MUTATION_ANCHOR not in nbk_source:
        raise ValueError("mutation anchor missing: Optimization nbk_opt_found guard")
    return nbk_source.replace(OPT_FOUND_MUTATION_ANCHOR, "if (nbk_pressure_above_ceiling())", 1)


def mutate_learn_floor(nbk_source: str) -> str:
    if LEARN_FLOOR_MUTATION_ANCHOR not in nbk_source:
        raise ValueError("mutation anchor missing: learn floorCeiling clamp")
    # "&& false" вместо полного удаления строки: floorCeiling остаётся
    # синтаксически использованной (иначе g++ убивает мутанта на
    # -Werror=unused-variable, а не на ассерте B3 - см. smoke_helpers-правило
    # "мутация if(x) -> if(x && false)").
    mutated_anchor = LEARN_FLOOR_MUTATION_ANCHOR.replace(
        "if (candidate < floorCeiling) candidate = floorCeiling;",
        "if (candidate < floorCeiling && false) candidate = floorCeiling;",
        1,
    )
    return nbk_source.replace(LEARN_FLOOR_MUTATION_ANCHOR, mutated_anchor, 1)


def mutate_work_temp_reset(nbk_source: str) -> str:
    if WORK_RESET_MUTATION_ANCHOR not in nbk_source:
        raise ValueError("mutation anchor missing: Work pressureHigh nbk_high_temp_ticks reset")
    return nbk_source.replace(WORK_RESET_MUTATION_ANCHOR, "", 1)


def compile_and_run(harness: str, label: str, emit: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-pressure-ceiling-") as temp_dir:
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


def main() -> int:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")

    try:
        rc = compile_and_run(build_predicate_harness(nbk_source), "A: nbk_pressure_above_ceiling", True)
        if rc != 0:
            return rc
        rc = compile_and_run(build_learn_harness(nbk_source), "B: nbk_learn_pressure_ceiling", True)
        if rc != 0:
            return rc
        rc = compile_and_run(build_work_harness(nbk_source), "C: handle_nbk_stage_work", True)
        if rc != 0:
            return rc
        rc = compile_and_run(build_opt_harness(nbk_source), "D: handle_nbk_stage_optimization", True)
        if rc != 0:
            return rc
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    pin_errors = check_reset_and_init_pins(nbk_source)
    if pin_errors:
        for error in pin_errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    # --- Мутации: каждая обязана провалить СВОЙ харнесс. ---
    mutations = [
        ("W: hold-ticks threshold -> 1", mutate_work_hold_ticks, build_work_harness),
        ("O: nbk_opt_found guard removed", mutate_opt_found_guard, build_opt_harness),
        ("learn: floorCeiling clamp removed", mutate_learn_floor, build_learn_harness),
        ("W: pressureHigh nbk_high_temp_ticks reset removed", mutate_work_temp_reset, build_work_harness),
    ]
    for name, mutate_fn, build_fn in mutations:
        try:
            mutated = mutate_fn(nbk_source)
        except ValueError as error:
            print(f"FAIL: {error}", file=sys.stderr)
            return 1
        if mutated == nbk_source:
            print(f"FAIL: mutation had no effect: {name}", file=sys.stderr)
            return 1
        mutated_harness = build_fn(mutated)
        if compile_and_run(mutated_harness, f"mutation [{name}]", False) == 0:
            print(f"FAIL: mutation survived (expected failure): {name}", file=sys.stderr)
            return 1

    print("nbk pressure ceiling checks (A/B/C/D behaviour + E reset-site pins + 4 mutations) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
