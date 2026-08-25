#!/usr/bin/env python3
"""[T26.1] /command?action=power больше не слепой переключатель.

Раньше action == "power" вообще не читал значение параметра: если PowerOn
было true, всегда ставилась команда-переключатель SAMOVAR_POWER (set_power(
!PowerOn)). Если веб-страница показывала устаревшее состояние (нагрев уже
выключился, а страница ещё думает, что он включён), клик "Выключить" на
самом деле ВКЛЮЧАЛ нагрев.

Теперь значение параметра читается (parse_exact_bool), и голое power (без
значения - так дёргают URL внешние интеграции) сохраняет старое поведение-
переключатель, а
power=0/power=1 всегда ставят явную команду:
  - power=0 -> SAMOVAR_POWER_OFF (идемпотентное выключение, НЕ переключатель);
  - power=1 при выключенном нагреве -> mode_power_on_command(Samovar_Mode)
    (та же команда включения, что и для start/distiller/... для этого режима);
  - power=1 при уже включённом нагреве -> команда НЕ ставится вовсе (иначе
    mode_power_on_command для ректификации/Сувида/Lua возвращает тот же
    SAMOVAR_POWER-переключатель и выключила бы нагрев - тот же баг наоборот).

Тест вытаскивает РЕАЛЬНЫЕ тела обеих веток action == "power" из WebServer.ino
(парсинг значения и диспетчеризацию команды) через extract_braced_block_after
и компилирует их в харнесс с реальным parse_exact_bool (numeric_parse.h) и
немутируемыми (не static) моками остальных зависимостей.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

TOKEN = 'else if (action == "power") {'


def check_power_off_case(errors: list[str]) -> None:
    """Текстовый пин на case SAMOVAR_POWER_OFF: в Samovar.ino.

    У этой ветки нет фигурных скобок (case-метка + два оператора + break;),
    поэтому extract_braced_block_after не подходит - вырезаем текст вручную
    от метки до следующего case. Ветка обязана звать set_power(false) и НЕ
    обязана (и не должна) звать переключатель set_power(!PowerOn) - иначе
    SAMOVAR_POWER_OFF ничем не отличался бы от старого SAMOVAR_POWER.
    """
    code = strip_cpp_comments((ROOT / "Samovar.ino").read_text(encoding="utf-8"))
    label = "case SAMOVAR_POWER_OFF:"
    start = code.find(label)
    if start < 0:
        errors.append("Samovar.ino: case SAMOVAR_POWER_OFF: не найден")
        return
    end = code.find("case ", start + len(label))
    if end < 0:
        errors.append("Samovar.ino: не найден следующий case после SAMOVAR_POWER_OFF")
        return
    branch = code[start:end]
    if "set_power(false);" not in branch:
        errors.append("Samovar.ino: case SAMOVAR_POWER_OFF не вызывает set_power(false)")
    if "set_power(!PowerOn)" in branch:
        errors.append(
            "Samovar.ino: case SAMOVAR_POWER_OFF всё ещё содержит переключатель set_power(!PowerOn)"
        )

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstddef>
#include <string>
#include <iostream>

#include "numeric_parse.h"

enum SamovarCommands {SAMOVAR_NONE, SAMOVAR_START, SAMOVAR_POWER, SAMOVAR_RESET, CALIBRATE_START, CALIBRATE_STOP, SAMOVAR_PAUSE, SAMOVAR_CONTINUE, SAMOVAR_SETBODYTEMP, SAMOVAR_DISTILLATION, SAMOVAR_BEER, SAMOVAR_BEER_NEXT, SAMOVAR_BK, SAMOVAR_NBK, SAMOVAR_SELF_TEST, SAMOVAR_DIST_NEXT, SAMOVAR_NBK_NEXT, SAMOVAR_POWER_OFF};
enum SAMOVAR_MODE {SAMOVAR_RECTIFICATION_MODE, SAMOVAR_DISTILLATION_MODE, SAMOVAR_BEER_MODE, SAMOVAR_BK_MODE, SAMOVAR_NBK_MODE, SAMOVAR_SUVID_MODE, SAMOVAR_LUA_MODE};

// Мини-строка вместо Arduino String - извлечённая ветка использует только
// .length()/.c_str(), которые тут и реализованы.
struct FakeString {
  std::string data;
  FakeString() = default;
  FakeString(const char* s) : data(s ? s : "") {}
  size_t length() const { return data.size(); }
  const char* c_str() const { return data.c_str(); }
  FakeString& operator=(const char* s) { data = s ? s : ""; return *this; }
};

struct FakeParam {
  FakeString val;
  FakeString value() const { return val; }
};

struct FakeRequest {};

// --- состояние, которым управляют сценарии ---
bool PowerOn = false;
SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
FakeParam paramStorage;
FakeParam* actionParam = &paramStorage;
FakeRequest requestStorage;
FakeRequest* request = &requestStorage;

// --- моки внешних зависимостей (не static: единственные вызовы лежат во
// вклеенных реальных телах ниже; со static мутация, убравшая вызов, роняла бы
// компилятор по unused-function вместо содержательного assert-а) ---
int modePowerOnCommandCalls = 0;
SamovarCommands mode_power_on_command(SAMOVAR_MODE) {
  modePowerOnCommandCalls++;
  // Произвольный, но легко узнаваемый маркер "команда включения режима" -
  // отличим от SAMOVAR_POWER/SAMOVAR_POWER_OFF/SAMOVAR_NONE.
  return SAMOVAR_DISTILLATION;
}

int queueCalls = 0;
SamovarCommands lastQueuedCommand = SAMOVAR_NONE;
bool queueReturnValue = true;
bool queue_samovar_command(SamovarCommands command) {
  queueCalls++;
  lastQueuedCommand = command;
  // Реальный инвариант (samovar_command_queue.h): для SAMOVAR_NONE функция
  // ВСЕГДА возвращает false, до захвата мьютекса и очереди. Мок обязан его
  // повторять - иначе мутация, стирающая guard "command != SAMOVAR_NONE",
  // не будет ничем отличаться от исходного кода в сценарии F.
  if (command == SAMOVAR_NONE) return false;
  return queueReturnValue;
}

int responseCalls = 0;
int lastResponseStatus = -1;
std::string lastResponseText;
void send_web_command_response(FakeRequest*, int status, const char* text) {
  responseCalls++;
  lastResponseStatus = status;
  lastResponseText = text;
}

// --- тестируемая функция: реальный порядок операций web_command() для
// action == "power" (парсинг -> проверка parseResult -> диспетчеризация ->
// общий хвост 200 OK). Тела ОБЕИХ веток (парсинг и диспетчеризация) -
// подставлены целиком, как они есть в WebServer.ino. Проверка parseResult и
// хвост markAccepted()/200 - это общий код ПОСЛЕ if/else-if цепочки действий,
// одинаковый для всех action; здесь он воспроизведён как в оригинале (без
// throttle-бухгалтерии markAccepted - она не влияет на выбор команды).
void run_power_action(const char* rawValue) {
  bool boolValue = false;
  bool powerValueGiven = false;
  NumericParseResult parseResult = numeric_parse_result(NUMERIC_PARSE_OK);
  std::string commandKeySuffix;
  paramStorage.val = rawValue;

  queueCalls = 0;
  lastQueuedCommand = SAMOVAR_NONE;
  responseCalls = 0;
  lastResponseStatus = -1;
  lastResponseText.clear();
  modePowerOnCommandCalls = 0;

@PARSE_BODY@

  if (!parseResult.ok()) {
    send_web_command_response(request, 400, "BAD_REQUEST");
    return;
  }

@DISPATCH_BODY@

  send_web_command_response(request, 200, "OK");
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // A: голый power ("" - так шлют Blynk/MQTT) при PowerOn=true ->
  // старое поведение-переключатель SAMOVAR_POWER.
  PowerOn = true;
  run_power_action("");
  check(lastQueuedCommand == SAMOVAR_POWER, "A: голый power при PowerOn=true должен поставить SAMOVAR_POWER");
  check(queueCalls == 1, "A: команда должна быть поставлена ровно один раз");
  check(modePowerOnCommandCalls == 0, "A: mode_power_on_command не должен вызываться");
  check(responseCalls == 1 && lastResponseStatus == 200, "A: ответ должен быть 200 OK");

  // B: голый power при PowerOn=false -> mode_power_on_command(Samovar_Mode).
  PowerOn = false;
  run_power_action("");
  check(lastQueuedCommand == SAMOVAR_DISTILLATION, "B: голый power при PowerOn=false должен поставить mode_power_on_command()");
  check(modePowerOnCommandCalls == 1, "B: mode_power_on_command должен быть вызван ровно один раз");
  check(queueCalls == 1, "B: команда должна быть поставлена ровно один раз");

  // C: power=0 при PowerOn=true -> SAMOVAR_POWER_OFF (не переключатель).
  PowerOn = true;
  run_power_action("0");
  check(lastQueuedCommand == SAMOVAR_POWER_OFF, "C: power=0 при PowerOn=true должен поставить SAMOVAR_POWER_OFF");
  check(modePowerOnCommandCalls == 0, "C: mode_power_on_command не должен вызываться при явном выключении");

  // D: power=0 при PowerOn=false -> тоже SAMOVAR_POWER_OFF (идемпотентно).
  PowerOn = false;
  run_power_action("0");
  check(lastQueuedCommand == SAMOVAR_POWER_OFF, "D: power=0 при PowerOn=false тоже должен поставить SAMOVAR_POWER_OFF");
  check(modePowerOnCommandCalls == 0, "D: mode_power_on_command не должен вызываться");

  // E: power=1 при PowerOn=false -> mode_power_on_command(Samovar_Mode).
  PowerOn = false;
  run_power_action("1");
  check(lastQueuedCommand == SAMOVAR_DISTILLATION, "E: power=1 при PowerOn=false должен поставить mode_power_on_command()");
  check(modePowerOnCommandCalls == 1, "E: mode_power_on_command должен быть вызван ровно один раз");

  // F (ключевой): power=1 при PowerOn=true -> команда НЕ ставится вовсе
  // (иначе mode_power_on_command для ректификации/Сувида/Lua вернула бы тот
  // же переключатель SAMOVAR_POWER и выключила бы уже включённый нагрев).
  // Ответ должен остаться честными 200, а НЕ 503 - это и проверяет guard
  // "command != SAMOVAR_NONE" перед queue_samovar_command().
  PowerOn = true;
  run_power_action("1");
  check(queueCalls == 0, "F: power=1 при уже включённом нагреве не должен ставить никакую команду в очередь");
  check(modePowerOnCommandCalls == 0, "F: mode_power_on_command не должен вызываться, нагрев уже включён");
  check(responseCalls == 1 && lastResponseStatus == 200,
        "F: ответ должен быть честным 200 (нет-оп), а НЕ 503 BUSY");

  if (failures != 0) return 1;
  std::cout << "web_command power action smoke checks passed\n";
  return 0;
}
'''


def build_harness(source: str) -> str:
    code = strip_cpp_comments(source)
    parse_body, end1 = extract_braced_block_after(code, TOKEN, 0)
    dispatch_body, _end2 = extract_braced_block_after(code, TOKEN, end1)
    harness = HARNESS_TEMPLATE.replace("@PARSE_BODY@", parse_body)
    harness = harness.replace("@DISPATCH_BODY@", dispatch_body)
    return harness


def main() -> int:
    errors: list[str] = []
    check_power_off_case(errors)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    source = (ROOT / "WebServer.ino").read_text(encoding="utf-8")

    try:
        harness = build_harness(source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-web-command-power-") as temp_dir:
        temp = Path(temp_dir)
        cpp_source = temp / "web_command_power_test.cpp"
        binary = temp / "web_command_power_test"
        cpp_source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT),
             str(cpp_source), "-o", str(binary)],
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
