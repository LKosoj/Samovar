#!/usr/bin/env python3
"""Проверка антиспама сообщений детектора примесей (impurity_detector.h).

Жалоба с форума на 6.27: на отборе хвостов детектор слал сообщение каждые 5-25 секунд
до конца строки. Причина - correctionFactor упирался в нижний предел 0.7, скорость
насоса больше не менялась, а SendMsg уходил при каждом срабатывании.

Часть (а): вытаскивает РЕАЛЬНОЕ тело ветки снижения скорости
(if (now - impurityDetector.lastCorrectionTime > correctionInterval)) через
extract_braced_block_after и проверяет на моках, что сообщение и команда насосу
уходят только когда коэффициент действительно изменился.

Часть (б): статическая проверка выключателя. SamSetup.useDetector должен гасить
детектор целиком (общий ранний выход в process_impurity_detector), а не отдельный
тип строки программы - иначе возвращается прежнее поведение useDetectorOnHeads,
когда галочка влияла только на головы.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

CORRECTION_BLOCK_TOKEN = "if (now - impurityDetector.lastCorrectionTime > correctionInterval)"
PROCESS_SIGNATURE = "void process_impurity_detector()"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, NONE_MSG = 100 };

// Минимальная замена Arduino String: нужна только конкатенация текста сообщения.
struct String {
  std::string s;
  String() {}
  String(const char* value) : s(value) {}
  String(float value, int) : s(std::to_string(value)) {}
  String operator+(const String& other) const { String result; result.s = s + other.s; return result; }
};

static String operator+(const char* left, const String& right) {
  String result;
  result.s = std::string(left) + right.s;
  return result;
}

struct ImpurityDetector {
  float correctionFactor = 1.0f;
  unsigned long lastCorrectionTime = 0;
  float currentTrend = 0;
  float tempVariance = 0;
};

static ImpurityDetector impurityDetector;
static float CurrentBaseSpeedRate = 0;
static unsigned long correctionIntervalFixture = 25000;

// ---- Моки внешних примитивов ----
static float correctionStepFixture = 0.05f;
static float get_detector_correction_step() { return correctionStepFixture; }

static float get_speed_from_rate(float rate) { return rate * 10.0f; }

static int setPumpSpeedCalls = 0;
static float lastPumpSpeed = 0;
static void set_pump_speed(float speed, bool, bool) { setPumpSpeedCalls++; lastPumpSpeed = speed; }

static int sendMsgCalls = 0;
static void SendMsg(const String& message, MESSAGE_TYPE) { sendMsgCalls++; (void)message; }

// ---- Реальный код под тестом (extract_braced_block_after) ----
static void apply_speed_correction(unsigned long now, float warningThreshold) {
@CORRECTION_BLOCK@
}

// ---- Тесты ----
static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static bool nearly_equal(float a, float b) {
  float diff = a - b;
  if (diff < 0) diff = -diff;
  return diff < 0.0001f;
}

static void reset_counters() {
  setPumpSpeedCalls = 0;
  sendMsgCalls = 0;
  lastPumpSpeed = 0;
}

int main() {
  CurrentBaseSpeedRate = 5.0f;
  correctionStepFixture = 0.05f;

  // Обычная коррекция: коэффициент снизился - шлём и команду насосу, и сообщение.
  reset_counters();
  impurityDetector.correctionFactor = 1.0f;
  impurityDetector.lastCorrectionTime = 0;
  apply_speed_correction(100000, 0.02f);
  check(nearly_equal(impurityDetector.correctionFactor, 0.95f), "коэффициент должен упасть до 0.95");
  check(setPumpSpeedCalls == 1, "скорость насоса должна быть пересчитана");
  check(nearly_equal(lastPumpSpeed, 47.5f), "новая скорость = базовая * коэффициент");
  check(sendMsgCalls == 1, "о снижении скорости нужно сообщить один раз");
  check(impurityDetector.lastCorrectionTime == 100000, "время коррекции должно обновиться");

  // Коэффициент уже на нижнем пределе: скорость не меняется - молчим (это и был спам).
  reset_counters();
  impurityDetector.correctionFactor = 0.7f;
  impurityDetector.lastCorrectionTime = 0;
  apply_speed_correction(200000, 0.02f);
  check(nearly_equal(impurityDetector.correctionFactor, 0.7f), "коэффициент должен остаться 0.7");
  check(setPumpSpeedCalls == 0, "на пределе насосу команда не нужна");
  check(sendMsgCalls == 0, "на пределе сообщение слать не нужно");
  check(impurityDetector.lastCorrectionTime == 200000, "время коррекции обновляется в любом случае");

  // Последний шаг перед пределом: коэффициент клампится до 0.7, но он ИЗМЕНИЛСЯ -
  // об этом сообщаем, и это последнее сообщение до конца строки программы.
  reset_counters();
  impurityDetector.correctionFactor = 0.72f;
  impurityDetector.lastCorrectionTime = 0;
  apply_speed_correction(300000, 0.02f);
  check(nearly_equal(impurityDetector.correctionFactor, 0.7f), "коэффициент должен склампиться до 0.7");
  check(setPumpSpeedCalls == 1, "на последнем шаге скорость меняется");
  check(sendMsgCalls == 1, "о последнем шаге нужно сообщить");

  // Интервал ещё не вышел - блок вообще ничего не делает.
  reset_counters();
  impurityDetector.correctionFactor = 1.0f;
  impurityDetector.lastCorrectionTime = 300000;
  apply_speed_correction(300001, 0.02f);
  check(nearly_equal(impurityDetector.correctionFactor, 1.0f), "до истечения интервала коэффициент не трогаем");
  check(setPumpSpeedCalls == 0, "до истечения интервала насос не трогаем");
  check(sendMsgCalls == 0, "до истечения интервала сообщений нет");

  if (failures != 0) return 1;
  std::cout << "detector message anti-spam behaviour checks passed\n";
  return 0;
}
'''


def build_harness(detector_source: str) -> str:
    block, _ = extract_braced_block_after(detector_source, CORRECTION_BLOCK_TOKEN)
    wrapped = (
        "  const unsigned long correctionInterval = correctionIntervalFixture;\n"
        "  if (now - impurityDetector.lastCorrectionTime > correctionInterval) {" + block + "}"
    )
    return HARNESS_TEMPLATE.replace("@CORRECTION_BLOCK@", wrapped)


def check_detector_switch(detector_source: str, web_source: str) -> list[str]:
    errors: list[str] = []
    if "useDetectorOnHeads" in detector_source:
        errors.append("impurity_detector.h: осталось прежнее имя настройки useDetectorOnHeads")
    if "useDetectorOnHeads" in web_source:
        errors.append("WebServer.ino: поддержка прежнего имени useDetectorOnHeads снята намеренно")

    body = strip_cpp_comments(extract_function_body(detector_source, PROCESS_SIGNATURE))
    if "!SamSetup.useautospeed || !SamSetup.useDetector" not in body:
        errors.append(
            "process_impurity_detector: общий ранний выход должен смотреть и на useautospeed, и на useDetector"
        )
    mentions = body.count("SamSetup.useDetector")
    if mentions != 1:
        errors.append(
            "process_impurity_detector: SamSetup.useDetector должен проверяться ровно один раз "
            f"(общий выключатель), найдено {mentions}"
        )
    return errors


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-detector-message-spam-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "detector_message_spam_test.cpp"
        binary = temp / "detector_message_spam_test"
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
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    detector_source = (ROOT / "impurity_detector.h").read_text(encoding="utf-8")
    web_source = (ROOT / "WebServer.ino").read_text(encoding="utf-8")
    try:
        harness = build_harness(detector_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    exit_code = compile_and_run(harness)

    errors = check_detector_switch(detector_source, web_source)
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    if errors:
        return 1
    if exit_code == 0:
        print("detector switch static checks passed")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
