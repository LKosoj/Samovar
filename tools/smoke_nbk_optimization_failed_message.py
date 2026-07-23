#!/usr/bin/env python3
"""Поведенческая проверка [T6]/[T8]: сообщения W-ветки run_nbk_program в nbk.h.

Тест вытаскивает РЕАЛЬНЫЙ блок "if (program[ProgramNum].WType == 'W') { ... }"
из run_nbk_program через extract_braced_block_after — без переписывания
логики — и подставляет его в минимальный host-харнесс, замокав только
downstream-вызовы (SendMsg, set_current_power, SetSpeed, toPower, fromPower,
safety_deadline_after, millis).

Регресс, который тест защищает: до задачи 6 переход к строке "Работа" без
пропуска Оптимизации и без найденного оптимума (nbk_Mo/nbk_Po остались 0)
происходил МОЛЧА — оператор не узнавал, что колонна пошла на минимальных,
не оптимизированных параметрах. После задачи 6 два сценария обязаны различаться
текстом сообщения: пропуск Оптимизации ("пропущена") и пустой оптимум
("Оптимум не найден"), причём взаимоисключающе.

Регресс [Ревью П1, находка 1]: пересчёт nbk_M/nbk_P выполнялся БЕЗУСЛОВНО, даже
когда nbk_work_entry_overflow_pending == true (вход в Работу сразу после
захлёба в конце Оптимизации) — то есть когда handle_overflow() уже выставил на
железо СНИЖЕННЫЕ М/П. Пересчёт затирал nbk_M/nbk_P полными значениями, из-за
чего SendMsg врал о фактических параметрах, а последующий API-экшн "nbkopt"
(nbk_Mo = nbk_M; nbk_Po = nbk_P;) молча отменял снижение. Сценарий 3 проверяет,
что при pending == true nbk_M/nbk_P остаются уже сниженными, а НЕ становятся
значениями, которые дал бы пересчёт.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]

ANCHOR = "if (program[ProgramNum].WType == 'W') {"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <string>
#include <vector>

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
using ProgramType = char;

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}
  String(float v, int decimals) : value_(format_float(v, decimals)) {}
  String operator+(const char* text) const { return String(value_ + (text ? text : "")); }
  String operator+(const String& other) const { return String(value_ + other.value_); }
  const std::string& value() const { return value_; }

 private:
  std::string value_;
  static std::string format_float(float v, int decimals) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.*f", decimals, static_cast<double>(v));
    return std::string(buf);
  }
};

static String operator+(const char* lhs, const String& rhs) {
  return String(std::string(lhs ? lhs : "") + rhs.value());
}

struct ProgramRow {
  ProgramType WType = 'W';
  float Power = 0;
  float Speed = 0;
};

static ProgramRow program[4];
static uint8_t ProgramNum = 0;

float nbk_M = 0;
float nbk_P = 0;
float nbk_Mo = 0;
float nbk_Po = 0;
float nbk_Mo_temp = 0;
float nbk_Po_temp = 0;
float nbk_Po_ceiling = 0;
uint8_t nbk_high_temp_ticks = 0;
bool nbk_pause_overflow_repeat_latched = false;
bool nbk_work_entry_overflow_pending = false;
bool nbk_work_in_pause = false;
bool nbk_overflow_happened = false;
uint32_t nbk_work_next_time = 0;
uint16_t nbk_column_inertia = 180;

static std::vector<std::string> sentMessages;
// Заглушка НЕ static: единственный вызов лежит во вклеенном теле блока, и со
// static мутация, убравшая вызов, роняла бы компилятор по unused-function
// вместо содержательного assert-а. Держится это на проверке sentMessages ниже.
void SendMsg(const String& msg, MESSAGE_TYPE) { sentMessages.push_back(msg.value()); }

// toPower/fromPower тождественны: конверсия ватт<->вольт не предмет ЭТОГО
// теста (её защищает smoke_nbk_po_floor.py), а тождество упрощает арифметику
// проверяемых значений nbk_M/nbk_P без побочных искажений.
float toPower(float v) { return v; }
float fromPower(float v) { return v; }

static int powerCalls = 0;
static int setSpeedCalls = 0;
void set_current_power(float) { powerCalls++; }
void SetSpeed(float) { setSpeedCalls++; }

static uint32_t fakeMillis = 1000;
uint32_t millis() { return fakeMillis; }
uint32_t safety_deadline_after(uint32_t now, uint32_t ms) { return now + ms; }

static void run_w_branch_entry() {
@BODY@
}

static bool contains(const std::string& text) {
  for (const auto& msg : sentMessages) {
    if (msg.find(text) != std::string::npos) return true;
  }
  return false;
}

static int count_containing(const std::string& text) {
  int n = 0;
  for (const auto& msg : sentMessages) {
    if (msg.find(text) != std::string::npos) n++;
  }
  return n;
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  ProgramNum = 0;
  program[0] = ProgramRow{};
  nbk_M = 0;
  nbk_P = 0;
  nbk_Mo = 0;
  nbk_Po = 0;
  nbk_Mo_temp = 0;
  nbk_Po_temp = 0;
  nbk_Po_ceiling = 0;
  nbk_high_temp_ticks = 5; // заведомо ненулевое — проверим, что вход в W обнуляет
  nbk_pause_overflow_repeat_latched = true; // заведомо true — проверим сброс
  nbk_work_entry_overflow_pending = false;
  nbk_work_in_pause = true;
  nbk_overflow_happened = true;
  nbk_work_next_time = 0;
  sentMessages.clear();
  powerCalls = 0;
  setSpeedCalls = 0;
}

// Сценарий 1: Оптимизация не пропущена (Mo_temp/Po_temp == 0) и оптимум не
// найден (nbk_Mo <= 0) -> ровно одно "Оптимум не найден", и НИКАКОГО
// "пропущена".
static void test_empty_optimum_message() {
  reset_fixture();
  nbk_Mo = 0;
  nbk_Po = 0;
  nbk_Mo_temp = 0;
  nbk_Po_temp = 0;
  run_w_branch_entry();

  check(count_containing("Оптимум не найден") == 1, "пустой оптимум должен дать РОВНО одно сообщение \"Оптимум не найден\"");
  check(!contains("пропущена"), "при пустом оптимуме сообщение о пропуске Оптимизации не должно отправляться");
  check(nbk_M == 500.0f, "без найденного оптимума и без строки программы М должно стать дефолтным 500");
  check(nbk_P == 1.0f, "без найденного оптимума и без строки программы П должно стать дефолтным 1.0");
  check(nbk_high_temp_ticks == 0, "вход в Работу обязан обнулить счётчик тиков высокой Тб");
  check(!nbk_pause_overflow_repeat_latched, "вход в Работу обязан сбросить латч повторного захлёба паузы");
  check(powerCalls == 1 && setSpeedCalls == 1, "штатный (не pending) вход в Работу обязан выставить мощность и подачу");
}

// Сценарий 2: Оптимизация пропущена (Mo_temp/Po_temp > 0) -> "пропущена", и
// НИКАКОГО "Оптимум не найден", даже если nbk_Mo изначально был <= 0.
static void test_skipped_optimization_message() {
  reset_fixture();
  nbk_Mo = 0; // изначально пусто — важно показать, что ветка "не найден" не сработает
  nbk_Po = 0;
  nbk_Mo_temp = 800.0f;
  nbk_Po_temp = 5.0f;
  run_w_branch_entry();

  check(contains("пропущена"), "пропуск Оптимизации должен дать сообщение с \"пропущена\"");
  check(!contains("Оптимум не найден"), "при пропуске Оптимизации сообщение \"Оптимум не найден\" отправляться не должно");
  check(nbk_Mo == 800.0f && nbk_Po == 5.0f, "переданные из Настройки Mo_temp/Po_temp обязаны стать Mo/По");
  check(nbk_M == 800.0f && nbk_P == 5.0f, "М/П обязаны совпасть с перенесёнными Mo/По");
}

// Сценарий 3 [Ревью П1, находка 1]: вход в Работу сразу после захлёба в конце
// Оптимизации (pending == true) — handle_overflow() уже выставил сниженные
// nbk_M/nbk_P на железо ДО этого вызова. Пересчёт обязан быть подавлен: М/П
// должны остаться сниженными сентинельными значениями, а НЕ стать теми
// (заведомо другими) значениями, которые дал бы безусловный пересчёт из
// nbk_Mo/nbk_Po. Хардварные вызовы (set_current_power/SetSpeed) в pending-ветке
// не выполняются — снижение уже применено handle_overflow() раньше.
static void test_pending_overflow_preserves_reduced_values() {
  reset_fixture();
  nbk_work_entry_overflow_pending = true;
  nbk_M = 123.0f;  // уже сниженное handle_overflow() значение
  nbk_P = 2.5f;    // уже сниженное handle_overflow() значение
  nbk_Mo = 999.0f; // если бы пересчёт произошёл вопреки pending — М стало бы этим
  nbk_Po = 777.0f; // если бы пересчёт произошёл вопреки pending — П стало бы этим
  nbk_Mo_temp = 0;
  nbk_Po_temp = 0;
  run_w_branch_entry();

  check(nbk_M == 123.0f, "РЕГРЕСС: pending overflow не должен затирать уже сниженное nbk_M пересчитанным полным значением");
  check(nbk_P == 2.5f, "РЕГРЕСС: pending overflow не должен затирать уже сниженное nbk_P пересчитанным полным значением");
  check(!nbk_work_entry_overflow_pending, "вход в Работу обязан потребить (сбросить) флаг pending");
  check(powerCalls == 0 && setSpeedCalls == 0, "pending-вход в Работу не должен повторно выставлять мощность/подачу — снижение уже применено handle_overflow()");
}

int main() {
  test_empty_optimum_message();
  test_skipped_optimization_message();
  test_pending_overflow_preserves_reduced_values();
  if (failures != 0) return 1;
  std::cout << "nbk W-branch optimization message behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    body, _ = extract_braced_block_after(source, ANCHOR)
    body = body.replace("\r\n", "\n")
    return HARNESS_TEMPLATE.replace("@BODY@", body)


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-nbk-optimization-failed-message-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "nbk_optimization_failed_message_test.cpp"
        binary = temp / "nbk_optimization_failed_message_test"
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
