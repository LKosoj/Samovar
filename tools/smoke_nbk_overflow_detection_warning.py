#!/usr/bin/env python3
"""Поведенческая проверка [Ремонт-2026-09-02 П12 + П9]:

П12: nbk_overflow_detection_available() - есть ли хоть один работающий
детектор захлёба (ДЗ по уровню ИЛИ ДД по давлению). Если нет - старт НБК
теперь НЕ блокируется, но оператор получает явное предупреждение (раньше
об этом факте вообще не сообщалось - процесс тихо стартовал без защиты).

П9: старый текст "Автоматический переход к Работе" в сообщении про
отсутствие датчика уровня в Оптимизации был неточен (переход НЕ
автоматический - нужно вручную задать параметры и нажать кнопку) и заменён
на явное "Через 10 минут процесс перейдёт в безопасное ожидание".

Три независимых проверки:
A) РЕАЛЬНАЯ nbk_overflow_detection_available() - таблица истинности по
   макросу USE_HEAD_LEVEL_SENSOR (два отдельных компилята) x
   use_pressure_sensor x pressure_value(-1/0/5).
B) РЕАЛЬНЫЙ фрагмент run_nbk_program (num==0, после create_data()) -
   предупреждение шлётся/не шлётся по результату (A), и НЕ блокирует старт.
C) Текстовый пин (без компиляции) фрагмента handle_nbk_stage_optimization
   про отсутствие ДЗ (П9) - новый текст есть, старой фразы нет.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

AVAILABLE_SIGNATURE = "inline bool nbk_overflow_detection_available() {"
AVAILABLE_MUTATION_ANCHOR = (
    "return hasLevelSensor || (use_pressure_sensor && pressure_value >= 0);"
)

WARNING_START_ANCHOR = "manual_overflow = false; // [Ремонт-2026-09-02 П6] сброс латча Ручной настройки на новом старте сессии"
WARNING_END_ANCHOR = "#ifdef USE_MQTT"
WARNING_MUTATION_ANCHOR = "if (!nbk_overflow_detection_available()) {"

P9_START_ANCHOR = "#ifndef USE_HEAD_LEVEL_SENSOR"
P9_NEW_TEXT = "Через 10 минут процесс перейдёт в безопасное ожидание (нагрев и подача выключены)."
P9_OLD_TEXT = "Автоматический переход к Работе"

COMMON = r'''
#include <cstdint>
#include <iostream>
#include <string>

class String {
 public:
  String(const char* value = "") : value_(value ? value : "") {}
  bool contains(const char* needle) const { return value_.find(needle) != std::string::npos; }
 private:
  std::string value_;
};

static int failures = 0;
static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
'''

AVAILABLE_HARNESS = r'''
static bool use_pressure_sensor = false;
static float pressure_value = -1;

@BODY@

int main() {
  // --- use_pressure_sensor=false: ДД в принципе не участвует, результат
  // зависит ТОЛЬКО от макроса USE_HEAD_LEVEL_SENSOR. ---
  use_pressure_sensor = false;
  pressure_value = 5;
#ifdef USE_HEAD_LEVEL_SENSOR
  check(nbk_overflow_detection_available(), "ДЗ включён макросом - обязан считаться доступным даже без ДД");
#else
  check(!nbk_overflow_detection_available(), "нет ни ДЗ, ни ДД - недоступно");
#endif

  // --- use_pressure_sensor=true, pressure_value=-1 ("нет данных" код) - ДД
  // формально включён, но данных ещё не было - недоступен, если нет ДЗ. ---
  use_pressure_sensor = true;
  pressure_value = -1;
#ifdef USE_HEAD_LEVEL_SENSOR
  check(nbk_overflow_detection_available(), "ДЗ включён - доступность не зависит от кода 'нет данных' ДД");
#else
  check(!nbk_overflow_detection_available(), "ДД без данных (-1) не должен считаться доступным");
#endif

  // --- use_pressure_sensor=true, pressure_value=0 - валидные данные ДД
  // (0 - реальное показание, не код отсутствия). ---
  use_pressure_sensor = true;
  pressure_value = 0;
  check(nbk_overflow_detection_available(), "ДД с валидным показанием 0 обязан считаться доступным");

  // --- use_pressure_sensor=true, pressure_value=5 - обычные валидные данные. ---
  use_pressure_sensor = true;
  pressure_value = 5;
  check(nbk_overflow_detection_available(), "ДД с валидным показанием >0 обязан считаться доступным");

  if (failures != 0) return 1;
  std::cout << "nbk_overflow_detection_available truth table passed\n";
  return 0;
}
'''

WARNING_HARNESS = r'''
enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };

static bool createDataShouldSucceed = true;
bool create_data() { return createDataShouldSucceed; }

// [Ремонт-2026-09-02] сбросы состояния прошлой сессии в начале блока num==0.
bool manual_overflow = true;
uint32_t nbk_manual_overflow_until = 1;
float nbk_Mo = 0;
float nbk_Po = 0;

// [T1-2026-09-03] инициализация рабочего потолка давления - не предмет этого
// теста, но входит в извлекаемый сегмент num==0.
#define NBK_WORK_PRESSURE_RATIO 0.5f
struct NbkSessionConfig { float overflowPressure; };
NbkSessionConfig nbkSessionConfig{40.0f};
float nbk_pressure_ceiling = 0;

// [Тарировка Тн] сброс флага автотарировки на старте сессии - не предмет
// этого теста, но входит в извлекаемый сегмент num==0.
bool nbk_tn_autocal_done = true;

static int cancelCalls = 0;
void nbk_cancel_program_start(const String&) {
  cancelCalls++;
}

static int sendMsgCalls = 0;
static int lastMsgType = -1;
static bool lastMsgWasWarningText = false;
void SendMsg(const String& msg, int type) {
  sendMsgCalls++;
  lastMsgType = type;
  lastMsgWasWarningText = msg.contains("Внимание: нет ни одного датчика захлёба");
}

static bool detectionAvailable = true;
static int detectionCalls = 0;
bool nbk_overflow_detection_available() {
  detectionCalls++;
  return detectionAvailable;
}

static bool reachedAfterSegment = false;

void fake_session_start_prefix() {
@BODY@
  reachedAfterSegment = true;
}

static void reset_fixture() {
  createDataShouldSucceed = true;
  cancelCalls = 0;
  sendMsgCalls = 0;
  lastMsgType = -1;
  lastMsgWasWarningText = false;
  detectionAvailable = true;
  detectionCalls = 0;
  reachedAfterSegment = false;
  manual_overflow = true;
  nbk_manual_overflow_until = 1;
  nbkSessionConfig.overflowPressure = 40.0f;
  nbk_pressure_ceiling = 0;
  nbk_tn_autocal_done = true;
}

// B4 (ревью R2): Мо/По прошлой сессии обязаны обнуляться на старте новой,
// иначе fallback явной строки W подставит протухший оптимум без ослабления.
static void test_stale_optimum_reset(float staleMo, float stalePo) {
  reset_fixture();
  nbk_Mo = staleMo;
  nbk_Po = stalePo;
  fake_session_start_prefix();
  check(nbk_Mo == 0.0f, "B4: старт сессии обязан обнулить nbk_Mo прошлой сессии");
  check(nbk_Po == 0.0f, "B4: старт сессии обязан обнулить nbk_Po прошлой сессии");
  check(!manual_overflow, "B4: старт сессии обязан сбросить латч захлёба Ручной настройки");
  check(nbk_manual_overflow_until == 0, "B4: старт сессии обязан обнулить дедлайн латча");
  check(reachedAfterSegment, "B4: сброс не должен мешать продолжению старта");
  check(nbk_pressure_ceiling == nbkSessionConfig.overflowPressure * NBK_WORK_PRESSURE_RATIO,
        "[T1-2026-09-03] старт сессии обязан инициализировать потолок давления как overflowPressure * RATIO");
}

// B1: детектора нет - предупреждение уходит, старт НЕ блокируется.
static void test_warning_sent_when_unavailable() {
  reset_fixture();
  detectionAvailable = false;
  fake_session_start_prefix();
  check(detectionCalls == 1, "B1: доступность обязана проверяться ровно один раз");
  check(sendMsgCalls == 2, "B1: обязаны уйти оба сообщения - старт И предупреждение");
  check(lastMsgWasWarningText, "B1: последним обязано быть именно предупреждение про отсутствие ДЗ/ДД");
  check(lastMsgType == WARNING_MSG, "B1: тип последнего сообщения обязан быть WARNING_MSG");
  check(cancelCalls == 0, "B1: отсутствие детектора НЕ обязано отменять старт (П12: не блокирует)");
  check(reachedAfterSegment, "B1: выполнение обязано продолжиться дальше (нет блокирующего return)");
}

// B2: детектор есть - предупреждения быть не должно, только сообщение о старте.
static void test_no_warning_when_available() {
  reset_fixture();
  detectionAvailable = true;
  fake_session_start_prefix();
  check(sendMsgCalls == 1, "B2: при доступном детекторе лишнего предупреждения быть не должно");
  check(!lastMsgWasWarningText, "B2: единственное сообщение - не предупреждение про отсутствие детектора");
  check(reachedAfterSegment, "B2: выполнение обязано продолжиться дальше");
}

// B3: create_data() провалился - отмена старта РАНЬШЕ проверки детектора,
// проверка доступности вообще не должна вызываться.
static void test_create_data_failure_short_circuits() {
  reset_fixture();
  createDataShouldSucceed = false;
  detectionAvailable = false; // не важно - до проверки дело не дойдёт
  fake_session_start_prefix();
  check(cancelCalls == 1, "B3: ошибка создания лога обязана отменить старт");
  check(sendMsgCalls == 0, "B3: при отмене старта ни одно из последующих сообщений уйти не должно");
  check(detectionCalls == 0, "B3: до проверки детектора при ошибке лога дело не должно доходить");
  check(!reachedAfterSegment, "B3: при отмене старта выполнение НЕ должно провалиться дальше");
}

int main() {
  test_warning_sent_when_unavailable();
  test_no_warning_when_available();
  test_create_data_failure_short_circuits();
  test_stale_optimum_reset(1200.0f, 8.0f);
  test_stale_optimum_reset(700.0f, 3.0f);
  if (failures != 0) return 1;
  std::cout << "nbk num==0 overflow-detection warning behaviour passed\n";
  return 0;
}
'''


def build_available_harness(nbk_source: str, define_hls: bool) -> str:
    body = extract_function_body(nbk_source, AVAILABLE_SIGNATURE)
    wrapped = f"bool nbk_overflow_detection_available() {{{body}}}"
    prelude = "#define USE_HEAD_LEVEL_SENSOR\n" if define_hls else ""
    return prelude + COMMON + AVAILABLE_HARNESS.replace("@BODY@", wrapped)


def build_warning_harness(nbk_source: str, warning_anchor: str = WARNING_MUTATION_ANCHOR) -> str:
    start = nbk_source.index(WARNING_START_ANCHOR)
    end = nbk_source.index(WARNING_END_ANCHOR, start)
    segment = nbk_source[start:end]
    if warning_anchor not in segment:
        raise ValueError(f"warning anchor missing from extracted segment: {warning_anchor}")
    return COMMON + WARNING_HARNESS.replace("@BODY@", segment)


def compile_and_run(harness: str, tag: str, emit: bool) -> int:
    with tempfile.TemporaryDirectory(prefix=f"samovar-nbk-overflow-warning-{tag}-") as temp_dir:
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
                sys.stderr.write("compile failed:\n")
                sys.stderr.write(compile_result.stdout)
                sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if emit:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode


def check_p9_text_pin(nbk_source: str) -> list:
    errors: list = []
    start = nbk_source.find(P9_START_ANCHOR)
    if start < 0:
        errors.append("П9 anchor not found: #ifndef USE_HEAD_LEVEL_SENSOR")
        return errors
    end = nbk_source.find("#endif", start)
    if end < 0:
        errors.append("П9 segment #endif not found")
        return errors
    segment = strip_cpp_comments(nbk_source[start:end])
    if P9_NEW_TEXT not in segment:
        errors.append(f"П9: новый текст не найден в сегменте: {P9_NEW_TEXT!r}")
    if P9_OLD_TEXT in segment:
        errors.append(f"П9: старая фраза всё ещё присутствует в сегменте: {P9_OLD_TEXT!r}")
    return errors


def mutate_available_and_instead_of_or(source: str) -> str:
    # П12: заменяет ИЛИ на И между ДЗ и ДД - должно сломать сценарий "есть
    # ДЗ, но ДД не отвечает" (перестанет считаться доступным при живом ДЗ).
    if AVAILABLE_MUTATION_ANCHOR not in source:
        raise ValueError("mutation anchor missing: hasLevelSensor || (...) ")
    mutated = AVAILABLE_MUTATION_ANCHOR.replace(
        "hasLevelSensor || (use_pressure_sensor && pressure_value >= 0)",
        "hasLevelSensor && (use_pressure_sensor && pressure_value >= 0)",
    )
    return source.replace(AVAILABLE_MUTATION_ANCHOR, mutated, 1)


def mutate_drop_warning_branch(source: str) -> str:
    # П12: отключает саму ветку предупреждения - должно сломать B1
    # (предупреждение перестанет уходить при недоступном детекторе).
    if WARNING_MUTATION_ANCHOR not in source:
        raise ValueError("mutation anchor missing: nbk_overflow_detection_available warning branch")
    return source.replace(
        WARNING_MUTATION_ANCHOR, "if (false && !nbk_overflow_detection_available()) {", 1
    )


def main() -> int:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")

    try:
        harness_no_hls = build_available_harness(nbk_source, define_hls=False)
        harness_hls = build_available_harness(nbk_source, define_hls=True)
        warning_harness = build_warning_harness(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if compile_and_run(harness_no_hls, "avail-no-hls", True) != 0:
        return 1
    if compile_and_run(harness_hls, "avail-hls", True) != 0:
        return 1
    if compile_and_run(warning_harness, "warning", True) != 0:
        return 1

    p9_errors = check_p9_text_pin(nbk_source)
    if p9_errors:
        for error in p9_errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    try:
        mutated_available = mutate_available_and_instead_of_or(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if mutated_available == nbk_source:
        print("FAIL: availability mutation had no effect", file=sys.stderr)
        return 1
    mutated_harness = build_available_harness(mutated_available, define_hls=True)
    if compile_and_run(mutated_harness, "avail-mut", False) == 0:
        print("FAIL: availability mutation survived (expected failure): || -> && ", file=sys.stderr)
        return 1

    try:
        mutated_warning = mutate_drop_warning_branch(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if mutated_warning == nbk_source:
        print("FAIL: warning mutation had no effect", file=sys.stderr)
        return 1
    mutated_warning_harness = build_warning_harness(
        mutated_warning, warning_anchor="if (false && !nbk_overflow_detection_available()) {"
    )
    if compile_and_run(mutated_warning_harness, "warning-mut", False) == 0:
        print("FAIL: warning mutation survived (expected failure): warning branch disabled", file=sys.stderr)
        return 1

    print("nbk overflow-detection warning checks (П12 + П9, behaviour + mutations) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
