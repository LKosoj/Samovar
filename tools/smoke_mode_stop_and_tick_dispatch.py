#!/usr/bin/env python3
"""[WP17 п.40] Регресс-проверка: два оставшихся рукописных switch(Samovar_Mode) /
switch(ops->mode), перечислявших режимы заново, переведены на данные реестра.

Было:
  - mode_registry.h::mode_dispatch_loop() - switch(ops->mode) с веткой на каждый
    режим (withdrawal/distiller_proc/bk_proc/nbk_proc/beer-branch), SUVID/LUA
    падали в `default: break;`.
  - WebServer.ino::stop_active_process_for_mode() - switch(Samovar_Mode) с веткой
    на каждый режим (run_program(PROGRAM_END)/distiller_finish/beer_finish/
    bk_finish/nbk_finish), SUVID/LUA/default - общий сброс статуса и питания.

Стало: оба switch удалены, поведение выбирается через новые поля ModeOps -
`tick` (mode_dispatch_loop) и `stopProcess` (stop_active_process_for_mode).

Тест проверяет:
  a) в телах обеих функций больше нет ключевого слова `switch` (конструкция
     реально переведена на реестр, а не просто переименована);
  b) строки mode_registry_table() несут правильные tick/stopProcess для всех
     все режимы, включая nullptr у SUVID/LUA;
  c) сами тела функций, извлечённые из исходников (а не переписанные в тесте),
     ведут себя по контракту в харнессах на g++ с мокнутыми зависимостями;
  d) мутации тел обеих функций обязаны валить содержательные assert'ы харнесса,
     а не компиляцию.

[T40 А3] mode_dispatch_loop() дополнительно переведён с mode_ops_by_status()
(строка реестра по SamovarStatusInt - второй, независимый от mode_dispatch_alarm()
источник выбора режима) на mode_ops_current() (по Samovar_Mode - тот же источник,
что и у alarm) + mode_status_belongs(ops, status) (принадлежит ли статус диапазону
ЭТОГО режима). Если не принадлежит, но статус активен для какого-то ДРУГОГО режима
(mode_status_session_active) - это рассогласование, и харнесс ниже (сценарии 5-7)
отдельно проверяет, что WARNING_MSG уходит РОВНО один раз на устойчивое
рассогласование (не на каждый такт) и сбрасывается/шлётся заново после разрешения -
мутация (г) ниже нарочно снимает именно guard "уже предупредили", чтобы поймать
регресс "предупреждение шлётся на каждом такте".
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "mode_registry.h"
WEBSERVER_PATH = ROOT / "mode_switch.h"

TICK_SIGNATURE = "inline void mode_dispatch_loop()"
STOP_SIGNATURE = "void stop_active_process_for_mode()"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --- (a) не осталось switch в телах обеих функций -----------------------------------------
def check_no_switch(name: str, body: str, errors: list[str]) -> None:
    if re.search(r"\bswitch\b", body):
        errors.append(f"{name}: тело всё ещё содержит switch - конструкция не переведена на реестр")


# --- (b) строки таблицы: tick/stopProcess по всем режимам --------------------------------
EXPECTED_TICK_STOP = {
    "SAMOVAR_RECTIFICATION_MODE": ("withdrawal", "mode_stop_process_rectification"),
    "SAMOVAR_DISTILLATION_MODE": ("distiller_proc", "distiller_finish"),
    "SAMOVAR_BEER_MODE": ("mode_tick_beer", "beer_finish"),
    "SAMOVAR_BK_MODE": ("bk_proc", "bk_finish"),
    "SAMOVAR_NBK_MODE": ("nbk_proc", "nbk_finish"),
    "SAMOVAR_SUVID_MODE": ("nullptr", "nullptr"),
    "SAMOVAR_LUA_MODE": ("nullptr", "nullptr"),
    "SAMOVAR_CHEESE_MODE": ("mode_tick_cheese", "cheese_finish"),
}


def check_table_rows(source: str, errors: list[str]) -> None:
    code = strip_cpp_comments(source)
    try:
        table_body = extract_function_body(
            code, "inline const ModeOps* mode_registry_table(size_t& count)"
        )
    except ValueError as exc:
        errors.append(str(exc))
        return
    rows = dict(re.findall(r"\{\s*(SAMOVAR_[A-Z_]+_MODE)\s*,([^{}]*)\}", table_body))
    if len(rows) != len(EXPECTED_TICK_STOP):
        errors.append(
            f"mode_registry table: ожидалось {len(EXPECTED_TICK_STOP)} строк, найдено {len(rows)} "
            f"({sorted(rows)})"
        )
    for mode, (expected_tick, expected_stop) in EXPECTED_TICK_STOP.items():
        rest = rows.get(mode)
        if rest is None:
            errors.append(f"mode_registry table: row for {mode} not found")
            continue
        fields = [f.strip() for f in rest.split(",")]
        if len(fields) < 4:
            errors.append(f"mode_registry table: row for {mode} has too few fields: {rest}")
            continue
        tick_fn, stop_fn = fields[-4], fields[-3]
        if tick_fn != expected_tick:
            errors.append(f"mode_registry table: {mode} tick = {tick_fn!r}, expected {expected_tick!r}")
        if stop_fn != expected_stop:
            errors.append(
                f"mode_registry table: {mode} stopProcess = {stop_fn!r}, expected {expected_stop!r}"
            )


# --- (c)/(d) харнесс А: mode_dispatch_loop() ------------------------------------------------
TICK_HARNESS_TEMPLATE = r'''
#include <iostream>

enum SAMOVAR_MODE { MODE_ALPHA, MODE_BETA };
using ModeVoidFn = void (*)();

struct ModeOps {
  SAMOVAR_MODE mode;
  ModeVoidFn tick;
};

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1 };

static bool switchInProgress = false;
bool mode_switch_in_progress() { return switchInProgress; }

// mode_ops_current()/mode_status_belongs()/mode_status_session_active() -
// заменили mode_ops_by_status() (единственная зависимость старого
// mode_dispatch_loop()) после [T40 А3]: реальные тела этих трёх функций
// проверяются ОТДЕЛЬНЫМИ тестами (smoke_mode_registry_session_guard.py и
// косвенно smoke_mode_command_table_single_source.py/smoke_mode_registry_*),
// здесь они мокнуты управляемыми возвратами - как statusOps/mode_ops_by_status
// мокался раньше.
static const ModeOps* currentOps = nullptr;
const ModeOps* mode_ops_current() { return currentOps; }

static bool statusBelongsReturn = false;
bool mode_status_belongs(const ModeOps*, int) { return statusBelongsReturn; }

static bool statusSessionActiveReturn = false;
bool mode_status_session_active(int) { return statusSessionActiveReturn; }

static int sendMsgCalls = 0;
void SendMsg(const char*, MESSAGE_TYPE) { sendMsgCalls++; }

int SamovarStatusInt = 0;

static int tickCalls = 0;
void tickFn() { tickCalls++; }

static ModeOps rowWithTick = {MODE_ALPHA, tickFn};
static ModeOps rowWithoutTick = {MODE_BETA, nullptr};

void mode_dispatch_loop() {
@TICK_BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  switchInProgress = false;
  currentOps = nullptr;
  statusBelongsReturn = false;
  statusSessionActiveReturn = false;
  sendMsgCalls = 0;
  tickCalls = 0;
  SamovarStatusInt = 0;
}

int main() {
  // 1. mode_switch_in_progress() == true -> ничего не вызывается вообще
  //    (ни tick, ни предупреждение), даже если формально было бы рассогласование.
  reset_fixture();
  switchInProgress = true;
  currentOps = &rowWithTick;
  statusBelongsReturn = false;
  statusSessionActiveReturn = true;
  mode_dispatch_loop();
  check(tickCalls == 0, "1: смена режима в процессе - tick не должен вызываться");
  check(sendMsgCalls == 0, "1: смена режима в процессе - SendMsg не должен вызываться");

  // 2. ops == nullptr (mode_ops_current не нашёл строку), статус ни для кого не
  //    активен -> тишина, это не рассогласование.
  reset_fixture();
  currentOps = nullptr;
  mode_dispatch_loop();
  check(tickCalls == 0, "2: неизвестный режим, статус неактивен - tick не должен вызываться");
  check(sendMsgCalls == 0, "2: неизвестный режим, статус неактивен - предупреждения быть не должно");

  // 3. Статус принадлежит режиму, но ops->tick == nullptr (эмуляция SUVID/LUA) ->
  //    тишина, tick не вызывается, предупреждения нет.
  reset_fixture();
  currentOps = &rowWithoutTick;
  statusBelongsReturn = true;
  mode_dispatch_loop();
  check(tickCalls == 0, "3: режим без tick в реестре - ничего не должно вызываться");
  check(sendMsgCalls == 0, "3: статус принадлежит режиму - предупреждения нет");

  // 4. Обычный случай -> tick вызывается ровно один раз, предупреждения нет.
  reset_fixture();
  currentOps = &rowWithTick;
  statusBelongsReturn = true;
  mode_dispatch_loop();
  check(tickCalls == 1, "4: обычный случай - tick должен быть вызван ровно один раз");
  check(sendMsgCalls == 0, "4: обычный случай - предупреждения нет");

  // 5. Простой (idle): статус не принадлежит текущему режиму, но и ни для кого
  //    не активен -> тишина без предупреждения (простой - не рассогласование).
  reset_fixture();
  currentOps = &rowWithTick;
  statusBelongsReturn = false;
  statusSessionActiveReturn = false;
  mode_dispatch_loop();
  check(tickCalls == 0, "5: простой - tick не вызывается");
  check(sendMsgCalls == 0, "5: простой (не рассогласование) - предупреждения быть не должно");

  // 6. Рассогласование (статус активен, но для другого режима) -> предупреждение
  //    ОДИН раз, даже если тикнуть несколько тактов подряд без изменений (иначе
  //    WARNING_MSG в цикле забьёт очередь и вытеснит настоящие аварии).
  reset_fixture();
  currentOps = &rowWithTick;
  statusBelongsReturn = false;
  statusSessionActiveReturn = true;
  mode_dispatch_loop();
  check(sendMsgCalls == 1, "6a: рассогласование - предупреждение должно быть отправлено");
  mode_dispatch_loop();
  mode_dispatch_loop();
  check(sendMsgCalls == 1,
        "6b: повторные такты с тем же рассогласованием НЕ должны слать предупреждение снова");
  check(tickCalls == 0, "6c: во время рассогласования тик не идёт ни разу");

  // 7. После разрешения (статус снова принадлежит режиму) флаг однократности
  //    сбрасывается - следующее НОВОЕ рассогласование обязано предупредить снова
  //    (приём "один раз, сброс когда разрешилось" - как noDZ_message_sent в nbk.h
  //    / pressure_alarm_sent в Samovar.ino).
  statusBelongsReturn = true;
  mode_dispatch_loop();
  check(tickCalls == 1, "7a: рассогласование разрешилось - тик пошёл");
  statusBelongsReturn = false;
  statusSessionActiveReturn = true;
  mode_dispatch_loop();
  check(sendMsgCalls == 2, "7b: новое рассогласование после разрешения предыдущего должно предупредить снова");

  if (failures) return 1;
  std::cout << "mode dispatch loop smoke checks passed\n";
  return 0;
}
'''

# --- харнесс Б: stop_active_process_for_mode() -----------------------------------------------
STOP_HARNESS_TEMPLATE = r'''
#include <iostream>

enum SAMOVAR_MODE { MODE_ALPHA };
using ModeVoidFn = void (*)();

struct ModeOps {
  SAMOVAR_MODE mode;
  ModeVoidFn stopProcess;
};

const int SAMOVAR_STATUS_IDLE = 0;
const int SAMOVAR_STARTVAL_IDLE = 0;

bool heaterPowerOnValue = false;
bool heater_power_on() { return heaterPowerOnValue; }

int SamovarStatusInt = SAMOVAR_STATUS_IDLE;
int startval = SAMOVAR_STARTVAL_IDLE;
int ProgramNum = 0;
SAMOVAR_MODE Samovar_Mode = MODE_ALPHA;

static bool selfTestActiveValue = false;
bool self_test_active() { return selfTestActiveValue; }
static int stopSelfTestCalls = 0;
void stop_self_test() { stopSelfTestCalls++; }

static int setPowerCalls = 0;
static bool lastSetPowerArg = true;
void set_power(bool on) {
  setPowerCalls++;
  lastSetPowerArg = on;
}

static const ModeOps* opsForMode = nullptr;
const ModeOps* mode_ops_by_mode(SAMOVAR_MODE) { return opsForMode; }

static int stopProcessCalls = 0;
void stopProcessFn() { stopProcessCalls++; }
static ModeOps rowWithStop = {MODE_ALPHA, stopProcessFn};
static ModeOps rowWithoutStop = {MODE_ALPHA, nullptr};

void stop_active_process_for_mode() {
@STOP_BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  heaterPowerOnValue = false;
  SamovarStatusInt = 7;      // "активен" - не IDLE
  startval = 7;
  ProgramNum = 3;
  selfTestActiveValue = false;
  stopSelfTestCalls = 0;
  setPowerCalls = 0;
  stopProcessCalls = 0;
  opsForMode = &rowWithStop;
}

int main() {
  // 1. Процесс не активен (ownerActive == false) -> общий сброс без stopProcess/set_power.
  reset_fixture();
  heaterPowerOnValue = false;
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  startval = SAMOVAR_STARTVAL_IDLE;
  ProgramNum = 0;
  stop_active_process_for_mode();
  check(SamovarStatusInt == SAMOVAR_STATUS_IDLE, "1: статус должен остаться IDLE");
  check(startval == SAMOVAR_STARTVAL_IDLE, "1: startval должен остаться IDLE");
  check(ProgramNum == 0, "1: ProgramNum должен остаться 0");
  check(stopProcessCalls == 0, "1: stopProcess не должен вызываться, когда процесс не активен");
  check(setPowerCalls == 0, "1: set_power не должен вызываться, когда процесс не активен");

  // 2. Процесс активен, у режима есть stopProcess -> вызван РОВНО один раз, общий сброс/set_power не идут следом.
  reset_fixture();
  opsForMode = &rowWithStop;
  stop_active_process_for_mode();
  check(stopProcessCalls == 1, "2: stopProcess должен быть вызван ровно один раз");
  check(setPowerCalls == 0, "2: после stopProcess() общий фолбэк (set_power) не должен выполняться следом");

  // 3. Процесс активен, но ops == nullptr (эмуляция несуществующего режима) -> общий фолбэк.
  reset_fixture();
  opsForMode = nullptr;
  stop_active_process_for_mode();
  check(SamovarStatusInt == SAMOVAR_STATUS_IDLE, "3: общий фолбэк должен сбросить статус");
  check(startval == SAMOVAR_STARTVAL_IDLE, "3: общий фолбэк должен сбросить startval");
  check(ProgramNum == 0, "3: общий фолбэк должен сбросить ProgramNum");
  check(setPowerCalls == 1 && lastSetPowerArg == false, "3: общий фолбэк должен звать set_power(false)");

  // 4. Процесс активен, stopProcess == nullptr (эмуляция SUVID/LUA) -> общий фолбэк.
  reset_fixture();
  opsForMode = &rowWithoutStop;
  stop_active_process_for_mode();
  check(setPowerCalls == 1 && lastSetPowerArg == false, "4: SUVID/LUA - общий фолбэк с set_power(false)");
  check(stopProcessCalls == 0, "4: stopProcess не должен вызываться, если он nullptr");

  // 5. self_test_active() всегда останавливается, независимо от остальной логики.
  reset_fixture();
  selfTestActiveValue = true;
  stop_active_process_for_mode();
  check(stopSelfTestCalls == 1, "5: активный самотест должен быть остановлен");

  if (failures) return 1;
  std::cout << "stop active process for mode smoke checks passed\n";
  return 0;
}
'''


def compile_and_run(harness_source: str, prefix: str) -> tuple[bool, int, str, str]:
    """Возвращает (скомпилировалось_ли, код_возврата, stdout, stderr).

    `скомпилировалось_ли` разделяет две принципиально разные причины ненулевого
    кода возврата: ошибка СБОРКИ (мутация превратила код в невалидный C++ -
    это НЕ значит, что мы поймали содержательную мутацию поведения) и падение
    УЖЕ СКОМПИЛИРОВАННОГО бинарника (assert через check() ИЛИ настоящий crash
    из-за вызова через nullptr - оба варианта означают, что мутация поймана).
    """
    with tempfile.TemporaryDirectory(prefix=prefix) as temp_dir:
        temp = Path(temp_dir)
        cpp_path = temp / "test.cpp"
        binary_path = temp / "test_bin"
        cpp_path.write_text(harness_source, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp_path), "-o", str(binary_path)],
            capture_output=True, text=True, check=False,
        )
        if compile_result.returncode != 0:
            return False, compile_result.returncode, compile_result.stdout, compile_result.stderr
        run_result = subprocess.run([str(binary_path)], capture_output=True, text=True, check=False)
        return True, run_result.returncode, run_result.stdout, run_result.stderr


def extract_tick_body(source: str) -> str:
    return extract_function_body(strip_cpp_comments(source), TICK_SIGNATURE)


def extract_stop_body(source: str) -> str:
    return extract_function_body(strip_cpp_comments(source), STOP_SIGNATURE)


# needle/replacement применяются только к тексту НАЧИНАЯ с сигнатуры функции,
# чтобы случайно не задеть текстуально идентичный фрагмент в соседней функции
# (например, mode_dispatch_alarm() выше mode_dispatch_loop() несёт точно такой
# же охранник "if (mode_switch_in_progress()) return;").
TICK_MUTATIONS = {
    "инверсия условия mode_switch_in_progress (смена режима больше не блокирует tick)": (
        "if (mode_switch_in_progress()) return;",
        "if (!mode_switch_in_progress()) return;",
    ),
    "снят guard ops->tick != nullptr (для SUVID/LUA вызов пойдёт через nullptr)": (
        "if (ops->tick != nullptr) ops->tick();", "ops->tick();",
    ),
    "снят сброс dispatchMismatchWarned при разрешении рассогласования (после resolve флаг не сбрасывается - новое рассогласование не предупредит)": (
        "\n    dispatchMismatchWarned = false;\n    if (ops->tick",
        "\n    if (ops->tick",
    ),
    "не взводится dispatchMismatchWarned после отправки (предупреждение будет слаться на КАЖДОМ такте, пока держится рассогласование)": (
        "dispatchMismatchWarned = true;", "",
    ),
}

STOP_MUTATIONS = {
    "убран return после ops->stopProcess() (двойной сброс питания следом)": (
        "ops->stopProcess();\n    return;\n  }",
        "ops->stopProcess();\n  }",
    ),
    "снят guard ops->stopProcess != nullptr (для SUVID/LUA вызов пойдёт через nullptr)": (
        " && ops->stopProcess != nullptr", ""
    ),
}


def run_mutations(
    label: str,
    source: str,
    signature: str,
    baseline_body: str,
    extractor,
    harness_template: str,
    body_placeholder: str,
    mutations: dict,
    prefix: str,
) -> list[str]:
    problems: list[str] = []
    anchor = source.find(signature)
    if anchor < 0:
        problems.append(f"{label}: не найдена сигнатура {signature!r} для якоря мутаций")
        return problems
    prefix_text, scoped_text = source[:anchor], source[anchor:]
    for name, (needle, replacement) in mutations.items():
        if needle not in scoped_text:
            problems.append(f"{label}: не удалось построить мутацию ({name}): токен не найден")
            continue
        mutant_scoped = scoped_text.replace(needle, replacement, 1)
        if mutant_scoped == scoped_text:
            problems.append(f"{label}: не удалось построить мутацию ({name}): текст не изменился")
            continue
        mutant_source = prefix_text + mutant_scoped
        try:
            mutant_body = extractor(mutant_source)
        except ValueError as exc:
            problems.append(f"{label}: не удалось построить мутацию ({name}): {exc}")
            continue
        if mutant_body == baseline_body:
            problems.append(f"{label}: мутация ({name}) не изменила тело функции")
            continue
        mutant_harness = harness_template.replace(body_placeholder, mutant_body)
        compiled, returncode, _stdout, stderr = compile_and_run(mutant_harness, prefix)
        if not compiled:
            problems.append(
                f"{label}: мутация ({name}) не скомпилировалась - это не считается пойманной мутацией "
                f"поведения:\n{stderr}"
            )
            continue
        if returncode == 0:
            problems.append(f"{label}: mutation survived: {name}")
            continue
        # returncode != 0 при УСПЕШНОЙ сборке - мутация поймана: либо содержательным
        # assert'ом check() ("FAIL: ..." в stderr), либо настоящим падением из-за
        # вызова через nullptr (пустой stderr, ненулевой код) - для guard'ов от
        # разыменования nullptr это тоже валидное доказательство, что охранник нужен.
    return problems


def main() -> int:
    registry_source = read(REGISTRY_PATH)
    webserver_source = read(WEBSERVER_PATH)

    errors: list[str] = []

    try:
        tick_body = extract_tick_body(registry_source)
    except ValueError as exc:
        errors.append(str(exc))
        tick_body = ""
    try:
        stop_body = extract_stop_body(webserver_source)
    except ValueError as exc:
        errors.append(str(exc))
        stop_body = ""

    if tick_body:
        check_no_switch("mode_dispatch_loop", tick_body, errors)
    if stop_body:
        check_no_switch("stop_active_process_for_mode", stop_body, errors)

    check_table_rows(registry_source, errors)

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    tick_harness = TICK_HARNESS_TEMPLATE.replace("@TICK_BODY@", tick_body)
    compiled, returncode, stdout, stderr = compile_and_run(tick_harness, "samovar-mode-tick-")
    if not compiled or returncode != 0:
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
        print("FAIL: baseline mode_dispatch_loop() harness did not pass", file=sys.stderr)
        return 1

    stop_harness = STOP_HARNESS_TEMPLATE.replace("@STOP_BODY@", stop_body)
    compiled2, returncode2, stdout2, stderr2 = compile_and_run(stop_harness, "samovar-mode-stop-")
    if not compiled2 or returncode2 != 0:
        sys.stdout.write(stdout2)
        sys.stderr.write(stderr2)
        print("FAIL: baseline stop_active_process_for_mode() harness did not pass", file=sys.stderr)
        return 1

    problems = run_mutations(
        "mode_dispatch_loop", registry_source, TICK_SIGNATURE, tick_body, extract_tick_body,
        TICK_HARNESS_TEMPLATE, "@TICK_BODY@", TICK_MUTATIONS, "samovar-mode-tick-mut-",
    )
    problems += run_mutations(
        "stop_active_process_for_mode", webserver_source, STOP_SIGNATURE, stop_body, extract_stop_body,
        STOP_HARNESS_TEMPLATE, "@STOP_BODY@", STOP_MUTATIONS, "samovar-mode-stop-mut-",
    )
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1

    sys.stdout.write(stdout)
    sys.stdout.write(stdout2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
