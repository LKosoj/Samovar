#!/usr/bin/env python3
"""[Б6.4] Фиксация кипения при ректификации - периодическая, привязана к двум
статусам и температурному порогу, а не к разовому вызову на кнопке "Старт".

История: раньше (Б6.3) разовая проверка жила в Menu.ino::menu_samovar_start() и
срабатывала только в момент нажатия "Старт отбора". Если оператор стартовал
отбор ДО того, как пар прогрелся выше CHANGE_POWER_MODE_STEAM_TEMP (браузер это
не запрещает - только предупреждает и просит подтверждение), разовая проверка
была ложна (и правильно, что ложна - фиксировать кипение по холодной колонне
нельзя), а статус ниже сразу становился RECT_WITHDRAWAL. Переход
RECT_ACCEL -> RECT_STABILIZING и ветка в alarm.h, которая обычно фиксирует
кипение, требуют статус RECT_STABILIZING - при раннем старте он проскакивается
НАВСЕГДА, boil_started оставался false до конца перегона, а get_alcohol()/
get_steam_alcohol() (logic.h) всю дорогу отдавали заглушку 100% вместо
реальной крепости.

Правка переносит фиксацию в check_alarm() (alarm.h) - функцию, которая уже
вызывается периодически (mode_registry.h) все время работы режима, включая
статус отбора. Условие расширено до ДВУХ статусов (RECT_STABILIZING и
RECT_WITHDRAWAL) и ОБЯЗАТЕЛЬНО требует SteamSensor.avgTemp >=
CHANGE_POWER_MODE_STEAM_TEMP - без порога кипение зафиксировалось бы по
холодной колонне сразу на первом тике после входа в RECT_WITHDRAWAL.

Тест вытаскивает РЕАЛЬНЫЙ if-блок (условие + тело) из alarm.h - находит
"if (" после собственного маркерного комментария [Б6.4] и балансирует скобки
условия сам, а тело блока - через extract_braced_block_after (общий помощник).
Так мутации в условии (не только в теле) реально меняют скомпилированный код,
а не переписанную в тесте копию.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]

ANCHOR_COMMENT = "[Б6.4] Фиксация кипения периодическая"


def extract_if_statement(source: str, anchor_comment: str) -> str:
    """Возвращает "if (COND) { BODY }" как есть в alarm.h: ищет "if (" после
    anchor_comment, сам балансирует скобки УСЛОВИЯ (в нём же есть вложенные
    скобки), а тело блока берёт через extract_braced_block_after - тем же
    способом, что и остальные тесты в tools/.

    ВАЖНО: source обязан быть НЕ прогнан через strip_cpp_comments() целиком -
    anchor_comment сам является комментарием и был бы вырезан. Комментарии
    внутри извлекаемых условия/тела extract_braced_block_after снимает сама
    (она комментарии/строки отслеживает по ходу сканирования, не требуя
    предварительной зачистки всего файла)."""
    anchor_idx = source.find(anchor_comment)
    if anchor_idx < 0:
        raise ValueError(f"anchor comment not found: {anchor_comment}")
    if_idx = source.find("if (", anchor_idx)
    if if_idx < 0:
        raise ValueError("if( not found after anchor comment")
    paren_start = if_idx + len("if (") - 1  # индекс открывающей '('
    depth = 0
    cond_end = -1
    for index in range(paren_start, len(source)):
        if source[index] == "(":
            depth += 1
        elif source[index] == ")":
            depth -= 1
            if depth == 0:
                cond_end = index
                break
    if cond_end < 0:
        raise ValueError("if condition is not closed")
    condition = source[if_idx + len("if ("):cond_end]
    body, _ = extract_braced_block_after(source, "{", offset=cond_end)
    return f"if ({condition}) {{\n{body}\n}}"


PRELUDE = r'''
#include <cstdint>
#include <iostream>
#include <string>

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}
  String(float value) : value_(std::to_string(value)) {}
  String(int value) : value_(std::to_string(value)) {}

  String& operator+=(const String& other) { value_ += other.value_; return *this; }
  friend String operator+(String left, const String& right) { left += right; return left; }
  const std::string& raw() const { return value_; }

 private:
  std::string value_;
};

enum { WARNING_MSG = 1 };

// Значения статусов произвольны (реальные - в Samovar.h) - важно только, что
// они различны и что RECT_ACCEL не входит ни в одну из проверяемых веток.
constexpr int SAMOVAR_STATUS_RECT_ACCEL = 50;
constexpr int SAMOVAR_STATUS_RECT_STABILIZING = 51;
constexpr int SAMOVAR_STATUS_RECT_WITHDRAWAL = 52;
constexpr float CHANGE_POWER_MODE_STEAM_TEMP = 39.0f;

static int SamovarStatusInt = 0;
static bool boil_started = false;
static float alcohol_s = 0.0f;

struct SteamSensorType { float avgTemp = 0; };
static SteamSensorType SteamSensor;

static String format_float(float value, int) { return String(value); }

static int setBoilingCalls = 0;
static void set_boiling() {
  setBoilingCalls++;
  boil_started = true;  // как в logic.h::set_boiling() - реально фиксирует флаг
}

static int sendMsgCalls = 0;
static void SendMsg(const String&, int) { sendMsgCalls++; }

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
'''

MAIN_TEMPLATE = r'''
static void boiling_capture_check() {
@BLOCK@
}

static void reset_state(int status, bool started, float steamTemp) {
  SamovarStatusInt = status;
  boil_started = started;
  SteamSensor.avgTemp = steamTemp;
  setBoilingCalls = 0;
  sendMsgCalls = 0;
}

int main() {
  // 1. Ранний старт: статус уже RECT_WITHDRAWAL (оператор нажал "Старт" до
  //    конца стабилизации), но пар ещё холодный - кипение НЕ фиксируем,
  //    иначе температура куба будет запомнена неверно.
  reset_state(SAMOVAR_STATUS_RECT_WITHDRAWAL, false, CHANGE_POWER_MODE_STEAM_TEMP - 1.0f);
  boiling_capture_check();
  check(!boil_started, "холодный пар в RECT_WITHDRAWAL не должен фиксировать кипение");
  check(setBoilingCalls == 0, "set_boiling() не должен вызываться при холодном паре");

  // 2. Ранний старт: тот же статус RECT_WITHDRAWAL, но пар прогрелся выше
  //    порога уже ПОСЛЕ входа в отбор - это и есть закрытие дыры Б6:
  //    периодическая проверка обязана поймать момент прогрева, раз
  //    RECT_STABILIZING был проскочен.
  reset_state(SAMOVAR_STATUS_RECT_WITHDRAWAL, false, CHANGE_POWER_MODE_STEAM_TEMP);
  boiling_capture_check();
  check(boil_started, "прогретый пар в RECT_WITHDRAWAL обязан зафиксировать кипение");
  check(setBoilingCalls == 1, "set_boiling() обязан вызваться ровно 1 раз");
  check(sendMsgCalls == 1, "фиксация кипения должна сопровождаться сообщением о спиртуозности");

  // 3. Штатный путь: статус RECT_STABILIZING (обычный вход, без раннего
  //    старта), пар уже прогрет - поведение как раньше, кипение фиксируется.
  reset_state(SAMOVAR_STATUS_RECT_STABILIZING, false, CHANGE_POWER_MODE_STEAM_TEMP);
  boiling_capture_check();
  check(boil_started, "RECT_STABILIZING с прогретым паром обязан зафиксировать кипение");
  check(setBoilingCalls == 1, "set_boiling() обязан вызваться ровно 1 раз");

  // 4. Защитный случай (гипотетический для штатного пути, но проверяет, что
  //    порог теперь общий для обеих веток): RECT_STABILIZING с холодным паром
  //    кипение фиксировать не должен.
  reset_state(SAMOVAR_STATUS_RECT_STABILIZING, false, CHANGE_POWER_MODE_STEAM_TEMP - 1.0f);
  boiling_capture_check();
  check(!boil_started, "RECT_STABILIZING с холодным паром не должен фиксировать кипение");
  check(setBoilingCalls == 0, "set_boiling() не должен вызываться при холодном паре");

  // 5. Статус вне двух разрешённых (например, RECT_ACCEL, разгон) - даже с
  //    прогретым паром кипение фиксировать не должен: не его ветка.
  reset_state(SAMOVAR_STATUS_RECT_ACCEL, false, CHANGE_POWER_MODE_STEAM_TEMP);
  boiling_capture_check();
  check(!boil_started, "RECT_ACCEL не должен фиксировать кипение через эту ветку");
  check(setBoilingCalls == 0, "set_boiling() не должен вызываться вне RECT_STABILIZING/RECT_WITHDRAWAL");

  // 6. Кипение уже зафиксировано раньше - повторный вызов/сообщение не нужны
  //    (идемпотентность, как и до правки).
  reset_state(SAMOVAR_STATUS_RECT_WITHDRAWAL, true, CHANGE_POWER_MODE_STEAM_TEMP);
  boiling_capture_check();
  check(setBoilingCalls == 0, "уже зафиксированное кипение не должно вызывать set_boiling() повторно");
  check(sendMsgCalls == 0, "уже зафиксированное кипение не должно повторно слать сообщение");

  if (failures != 0) return 1;
  std::cout << "PASS: alarm.h boiling capture (RECT_STABILIZING/RECT_WITHDRAWAL + steam threshold) checks passed\n";
  return 0;
}
'''


def build_harness(block: str) -> str:
    return PRELUDE + MAIN_TEMPLATE.replace("@BLOCK@", block)


def compile_and_run(name: str, harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix=f"samovar-{name}-") as temp_dir:
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
            sys.stderr.write(f"compile failed ({name}):\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    try:
        alarm_source = (ROOT / "alarm.h").read_text(encoding="utf-8")
        block = extract_if_statement(alarm_source, ANCHOR_COMMENT)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    return compile_and_run("early-start-boiling", build_harness(block))


if __name__ == "__main__":
    raise SystemExit(main())
