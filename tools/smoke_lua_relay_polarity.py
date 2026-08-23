#!/usr/bin/env python3
"""Фиксация сырого контракта lua.h::lua_wrapper_digitalWrite для реле.

Во всём C++-тракте инвариант такой: ВКЛ реле пишет SamSetup.releN, ВЫКЛ пишет
!SamSetup.releN (см. Samovar.ino, beer.h, valve_buzzer.h и т.д.). Lua-обёртка
digitalWrite этому инварианту НАМЕРЕННО не следует: она повторяет семантику
одноимённого примитива Arduino и пишет на пин сырое значение.

Это решение владельца, а не упущение. Все существующие пользовательские скрипты
написаны под сырой проход и уже учитывают полярность своей платы сами. Добавление
инверсии по SamSetup.releN молча перевернуло бы миксер (RELE_CHANNEL2) и клапан
(RELE_CHANNEL3) у всех на конфигурации по умолчанию (releN=false): скрипт,
включавший реле через digitalWrite(pin, LOW), начал бы его выключать. Полярность-
зависимое управление реле — это отдельная новая функция, а не смена смысла
digitalWrite.

Тест вытаскивает РЕАЛЬНЫЙ блок обработки пинов из lua_wrapper_digitalWrite через
extract_braced_block_after (без переписывания логики) и проверяет поведение записи
на пин, а не наличие конкретной строки в исходнике.

Тест также покрывает lua_wrapper_pinMode (R10): при взведённой аварийной защёлке
heater_safety_latched() pinMode() на RELE_CHANNEL1/RELE_CHANNEL4 обязан быть
молчаливым no-op (иначе pinMode(INPUT) отдал бы пин подтяжке платы в обход
защёлки, вернув нагрев мимо C++-тракта), а на RELE_CHANNEL2/RELE_CHANNEL3/LUA_PIN
защёлка ничего не меняет — блок вытаскивается тем же способом, без копирования
логики.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

HARNESS_TEMPLATE = r'''
#include <iostream>

#define LOW 0
#define HIGH 1
#define WATER_PUMP_PIN 11
#define RELE_CHANNEL1 2
#define RELE_CHANNEL2 42
#define RELE_CHANNEL3 41
#define RELE_CHANNEL4 40
#define LUA_PIN 4
#define INPUT 0
#define OUTPUT 1

struct SamSetupType { bool rele1; bool rele2; bool rele3; bool rele4; };
static SamSetupType SamSetup;

static int lastPin = -1;
static int lastVal = -1;
static int writeCalls = 0;

static void digitalWrite(int pin, int val) {
  lastPin = pin;
  lastVal = val;
  writeCalls++;
}

static int lastPinModePin = -1;
static int lastPinModeMode = -1;
static int pinModeCalls = 0;

// Не static по той же причине, что и предикат ниже: pinMode() из этого харнесса
// вызывается только из тела, вытащенного extract_braced_block_after из реального
// lua_wrapper_pinMode, и если бы pinMode() была static, потерянный мутацией вызов
// ловился бы как -Wunused-function, а не как содержательный assert-провал.
inline void pinMode(int pin, int mode) {
  lastPinModePin = pin;
  lastPinModeMode = mode;
  pinModeCalls++;
}

static bool g_heaterSafetyLatched = false;
// Не static: в lua.h обе функции объявлены inline (внешняя связность), поэтому
// -Wunused-function на них не распространяется. Если бы они были static, мутация
// «убрать вызов предиката из тела digitalWrite/pinMode» ловилась бы как ошибка
// компилятора об unused-function, а не как содержательный assert-провал — это
// маскирует смысл мутационной проверки.
inline bool heater_safety_latched() { return g_heaterSafetyLatched; }

inline bool lua_pin_is_heater_channel(int pin) {
@HEATER_PREDICATE_BODY@
}

// [П3] Реальные тела учёта "поднят ли heater-канал сырым digitalWrite мимо
// PowerOn" — та же extract_function_body, что и остальной харнесс, а не
// переписанная логика.
static bool luaHeaterChannel1Raised = false;
static bool luaHeaterChannel4Raised = false;

inline bool lua_heater_channel_raised() {
@HEATER_RAISED_BODY@
}

inline void lua_set_heater_channel_raised(int pin, bool raised) {
@SET_HEATER_RAISED_BODY@
}

inline void lua_track_heater_channel_write(int pin, int level) {
@TRACK_HEATER_WRITE_BODY@
}

static void run_digital_write(int a, int b) {
@BODY@
}

static void run_pin_mode(int a, int b) {
@PINMODE_BODY@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

// Сырой проход: что скрипт передал, то и уходит на пин — при ЛЮБОЙ настройке полярности.
static void expect_raw(int pin, bool relePolarity, const char* what) {
  writeCalls = 0;
  run_digital_write(pin, HIGH);
  check(writeCalls == 1, "digitalWrite не вызван");
  check(lastPin == pin, "запись ушла не на тот пин");
  if (lastVal != 1) {
    std::cerr << "FAIL: " << what << " (releN=" << (relePolarity ? "true" : "false")
              << "): HIGH от скрипта обязан уходить на пин сырым HIGH; инверсия по "
                 "SamSetup.releN здесь перевернула бы существующие скрипты\n";
    failures++;
  }
  run_digital_write(pin, LOW);
  if (lastVal != 0) {
    std::cerr << "FAIL: " << what << " (releN=" << (relePolarity ? "true" : "false")
              << "): LOW от скрипта обязан уходить на пин сырым LOW; инверсия по "
                 "SamSetup.releN здесь перевернула бы существующие скрипты\n";
    failures++;
  }
}

// Защёлка взведена: heater-канал не должен уйти на пин ни в HIGH, ни в LOW.
static void expect_suppressed(int pin, const char* what) {
  g_heaterSafetyLatched = true;
  writeCalls = 0;
  lastPin = -1;
  run_digital_write(pin, HIGH);
  run_digital_write(pin, LOW);
  if (writeCalls != 0 || lastPin != -1) {
    std::cerr << "FAIL: " << what
              << ": защёлка взведена, запись на heater-канал обязана быть "
                 "подавлена молча (C++-тракт уже погасил канал)\n";
    failures++;
  }
  g_heaterSafetyLatched = false;
}

// pinMode: сырой проход — вызов должен дойти до пина с тем же режимом, что передал скрипт.
static void expect_pinmode_raw(int pin, int mode, const char* what) {
  pinModeCalls = 0;
  lastPinModePin = -1;
  lastPinModeMode = -1;
  run_pin_mode(pin, mode);
  if (pinModeCalls != 1 || lastPinModePin != pin || lastPinModeMode != mode) {
    std::cerr << "FAIL: " << what << ": pinMode обязан быть вызван на пине " << pin
              << " с режимом " << mode << "\n";
    failures++;
  }
}

// pinMode: heater-канал при взведённой защёлке не должен дойти до пина ни в каком режиме.
static void expect_pinmode_suppressed(int pin, int mode, const char* what) {
  pinModeCalls = 0;
  lastPinModePin = -1;
  run_pin_mode(pin, mode);
  if (pinModeCalls != 0 || lastPinModePin != -1) {
    std::cerr << "FAIL: " << what
              << ": защёлка взведена, pinMode на heater-канале обязан быть подавлен молча "
                 "(pinMode(INPUT) отдал бы пин подтяжке платы в обход защёлки)\n";
    failures++;
  }
}

int main() {
  // Миксер: сырой проход независимо от настроенной полярности.
  SamSetup.rele2 = true;
  expect_raw(RELE_CHANNEL2, true, "RELE_CHANNEL2 (миксер)");
  SamSetup.rele2 = false;
  expect_raw(RELE_CHANNEL2, false, "RELE_CHANNEL2 (миксер)");

  // Клапан: то же самое.
  SamSetup.rele3 = true;
  expect_raw(RELE_CHANNEL3, true, "RELE_CHANNEL3 (клапан)");
  SamSetup.rele3 = false;
  expect_raw(RELE_CHANNEL3, false, "RELE_CHANNEL3 (клапан)");

  // Не-реле пин (на LUA_PIN полагаются штатные скрипты вроде dist_autofill.lua) —
  // тоже сырой проход, никакой полярности тут нет в принципе.
  run_digital_write(LUA_PIN, HIGH);
  check(lastVal == 1, "LUA_PIN должен оставаться сырым проходом (HIGH -> HIGH)");
  run_digital_write(LUA_PIN, LOW);
  check(lastVal == 0, "LUA_PIN должен оставаться сырым проходом (LOW -> LOW)");

  // R7: защёлка НЕ взведена — нагревательные каналы всё ещё проходят сырым
  // значением (владелец восстановил эту работоспособность явно).
  g_heaterSafetyLatched = false;
  expect_raw(RELE_CHANNEL1, false, "RELE_CHANNEL1 (нагреватель 1, защёлка снята)");
  expect_raw(RELE_CHANNEL4, false, "RELE_CHANNEL4 (нагреватель 4, защёлка снята)");

  // R7: защёлка взведена — Lua больше не может снова подать нагрев в обход
  // heater_safety_latched(), запись молча подавляется.
  expect_suppressed(RELE_CHANNEL1, "RELE_CHANNEL1 (нагреватель 1, защёлка взведена)");
  expect_suppressed(RELE_CHANNEL4, "RELE_CHANNEL4 (нагреватель 4, защёлка взведена)");

  // R7: защёлка взведена, но не должна цеплять не-нагревательные пины — миксер,
  // клапан и LUA_PIN по-прежнему проходят сырым значением.
  g_heaterSafetyLatched = true;
  expect_raw(RELE_CHANNEL2, true, "RELE_CHANNEL2 (миксер, защёлка взведена)");
  expect_raw(RELE_CHANNEL3, true, "RELE_CHANNEL3 (клапан, защёлка взведена)");
  expect_raw(LUA_PIN, true, "LUA_PIN (защёлка взведена)");
  // Насос охлаждения — самый тяжёлый случай: авария по перегреву это ровно тот момент,
  // когда он нужнее всего, а подавить его защёлкой достаточно ошибочно причислить
  // WATER_PUMP_PIN к нагревательным каналам. Здесь (сборка без USE_WATER_PUMP) помпа
  // уходит в digitalWrite веткой #else, поэтому сырой проход виден харнессу.
  expect_raw(WATER_PUMP_PIN, true, "WATER_PUMP_PIN (насос охлаждения, защёлка взведена)");
  g_heaterSafetyLatched = false;

  // R10: pinMode, защёлка снята — нагревательные каналы всё ещё доступны для смены режима пина.
  g_heaterSafetyLatched = false;
  expect_pinmode_raw(RELE_CHANNEL1, INPUT, "pinMode RELE_CHANNEL1 (нагреватель 1, защёлка снята)");
  expect_pinmode_raw(RELE_CHANNEL4, INPUT, "pinMode RELE_CHANNEL4 (нагреватель 4, защёлка снята)");

  // R10: pinMode, защёлка взведена — pinMode(RELE_CHANNEL1/4, INPUT) отдал бы пин
  // подтяжке платы в обход защёлки, поэтому вызов молча подавляется. Каналы проверяются
  // РАЗДЕЛЬНО: мутация, забывшая один из двух каналов, не должна прятаться за общим assert-ом.
  g_heaterSafetyLatched = true;
  expect_pinmode_suppressed(RELE_CHANNEL1, INPUT, "pinMode RELE_CHANNEL1 (нагреватель 1, защёлка взведена)");
  expect_pinmode_suppressed(RELE_CHANNEL4, INPUT, "pinMode RELE_CHANNEL4 (нагреватель 4, защёлка взведена)");
  g_heaterSafetyLatched = false;

  // R10: pinMode, защёлка взведена, но не должна цеплять не-нагревательные пины — миксер,
  // клапан и LUA_PIN по-прежнему проходят сырым режимом.
  g_heaterSafetyLatched = true;
  expect_pinmode_raw(RELE_CHANNEL2, OUTPUT, "pinMode RELE_CHANNEL2 (миксер, защёлка взведена)");
  expect_pinmode_raw(RELE_CHANNEL3, OUTPUT, "pinMode RELE_CHANNEL3 (клапан, защёлка взведена)");
  expect_pinmode_raw(LUA_PIN, OUTPUT, "pinMode LUA_PIN (защёлка взведена)");
  g_heaterSafetyLatched = false;

  // [П3] digitalWrite на heater-канал мимо PowerOn обязан поднимать флаг учёта
  // (lua_heater_channel_raised()), чтобы аварийный надзор не остался слепым.
  // Проверяем ОБЕ полярности releN — флаг должен ориентироваться на реальный
  // уровень "включено" (SamSetup.releN), а не на сырое HIGH/LOW.
  g_heaterSafetyLatched = false;
  SamSetup.rele1 = true;
  luaHeaterChannel1Raised = false;
  luaHeaterChannel4Raised = false;
  run_digital_write(RELE_CHANNEL1, HIGH);
  check(lua_heater_channel_raised(), "RELE_CHANNEL1 releN=true: HIGH обязан поднять флаг raised");
  run_digital_write(RELE_CHANNEL1, LOW);
  check(!lua_heater_channel_raised(), "RELE_CHANNEL1 releN=true: LOW обязан снять флаг raised");

  SamSetup.rele1 = false;
  run_digital_write(RELE_CHANNEL1, LOW);
  check(lua_heater_channel_raised(), "RELE_CHANNEL1 releN=false: LOW - это ВКЛ, флаг обязан подняться");
  run_digital_write(RELE_CHANNEL1, HIGH);
  check(!lua_heater_channel_raised(), "RELE_CHANNEL1 releN=false: HIGH - это ВЫКЛ, флаг обязан снятья");

  // Два канала независимы, но lua_heater_channel_raised() - это ИЛИ по обоим:
  // пока поднят хотя бы один, надзор обязан быть включён.
  SamSetup.rele1 = true;
  SamSetup.rele4 = true;
  run_digital_write(RELE_CHANNEL1, HIGH);
  run_digital_write(RELE_CHANNEL4, HIGH);
  check(lua_heater_channel_raised(), "оба канала подняты: флаг обязан быть true");
  run_digital_write(RELE_CHANNEL1, LOW);
  check(lua_heater_channel_raised(), "RELE_CHANNEL4 всё ещё поднят: флаг не должен упасть");
  run_digital_write(RELE_CHANNEL4, LOW);
  check(!lua_heater_channel_raised(), "оба канала сняты: флаг обязан стать false");

  // Защёлка аварийного отключения: C++-тракт уже погасил канал физически -
  // запись подавляется, и учёт обязан это отразить (иначе надзор продолжит
  // думать, что канал ещё поднят, хотя пин молчит).
  SamSetup.rele1 = true;
  run_digital_write(RELE_CHANNEL1, HIGH);
  check(lua_heater_channel_raised(), "подготовка: RELE_CHANNEL1 должен быть поднят перед проверкой защёлки");
  g_heaterSafetyLatched = true;
  writeCalls = 0;
  run_digital_write(RELE_CHANNEL1, HIGH);
  check(writeCalls == 0, "защёлка взведена: запись на пин обязана быть подавлена (проверено выше, дублируем инвариант)");
  check(!lua_heater_channel_raised(), "защёлка взведена: учёт обязан сброситься в false вместе с реальным пином");
  g_heaterSafetyLatched = false;

  if (failures != 0) return 1;
  std::cout << "lua_wrapper_digitalWrite/lua_wrapper_pinMode raw relay contract checks passed\n";
  return 0;
}
'''


def extract_gated_whitelist(code: str, anchor: str, wrapper: str) -> str:
    """Достаёт тело белого списка пинов, называя цену промаха по якорю.

    Якорь требует открывающую скобку, поэтому откат гейта защёлки к
    до-фиксовому однострочнику (`if (...) pinMode(a, b);`) рушит экстракцию, а
    не проваливает assert. Достоверно при промахе одно: гейт не проверен. Сам
    промах бывает и безобидным (список пинов переставили), поэтому причину
    сообщение называет гипотезой, а не приговором.
    """
    try:
        body, _ = extract_braced_block_after(code, anchor)
    except ValueError as error:
        raise ValueError(
            f"{wrapper}: белый список пинов не извлекается ({error}), поэтому гейт"
            " heater_safety_latched() на этой обёртке НЕ проверен. Причина бывает"
            " безобидной (пины в списке переставили или дополнили — тогда поправьте"
            " якорь), но точно так же якорь промахивается, если гейт свернули обратно"
            " в однострочник. Сверьте тело обёртки в lua.h ПЕРЕД тем, как править"
            " якорь: без гейта Lua снова подаёт нагрев после аварийной защёлки"
            " (R7 для digitalWrite, R10 для pinMode)."
        ) from error
    return body.replace("\r\n", "\n")


def build_harness() -> str:
    source = (ROOT / "lua.h").read_text(encoding="utf-8")
    code = strip_cpp_comments(source)
    predicate_anchor = "inline bool lua_pin_is_heater_channel(int pin)"
    predicate_body, _ = extract_braced_block_after(code, predicate_anchor)
    predicate_body = predicate_body.replace("\r\n", "\n")
    heater_raised_body = extract_function_body(code, "inline bool lua_heater_channel_raised()")
    set_heater_raised_body = extract_function_body(
        code, "inline void lua_set_heater_channel_raised(int pin, bool raised)"
    )
    track_heater_write_body = extract_function_body(
        code, "inline void lua_track_heater_channel_write(int pin, int level)"
    )
    body = extract_gated_whitelist(
        code,
        "if (a == RELE_CHANNEL1 || a == WATER_PUMP_PIN || a == RELE_CHANNEL4 || a == RELE_CHANNEL3 || a == RELE_CHANNEL2 || a == LUA_PIN",
        "lua_wrapper_digitalWrite",
    )
    pinmode_body = extract_gated_whitelist(
        code,
        "if (a == RELE_CHANNEL1 || a == RELE_CHANNEL4 || a == RELE_CHANNEL3 || a == RELE_CHANNEL2 || a == LUA_PIN) {",
        "lua_wrapper_pinMode",
    )
    harness = HARNESS_TEMPLATE.replace("@HEATER_PREDICATE_BODY@", predicate_body)
    harness = harness.replace("@HEATER_RAISED_BODY@", heater_raised_body)
    harness = harness.replace("@SET_HEATER_RAISED_BODY@", set_heater_raised_body)
    harness = harness.replace("@TRACK_HEATER_WRITE_BODY@", track_heater_write_body)
    harness = harness.replace("@BODY@", body)
    harness = harness.replace("@PINMODE_BODY@", pinmode_body)
    return harness


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-lua-relay-polarity-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "lua_relay_polarity_test.cpp"
        binary = temp / "lua_relay_polarity_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
