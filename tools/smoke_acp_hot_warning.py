#!/usr/bin/env python3
"""Предупреждение оператору о горячей ТСА (жалоба с форума 21.09.2026).

Предупреждение о превышении SetACPTemp не зависит от температуры воды.
После охлаждения ниже порога на 2 градуса новый перегрев предупреждает снова.
Усиление насоса дополнительно требует, чтобы ТСА была горячее воды.

Харнесс вытаскивает из исходников РЕАЛЬНЫЕ тела mode_acp_above_boost_threshold(),
mode_warn_acp_hot_once(), mode_update_water_pump_pid() и датчиковых проверок alarm.h.
Заглушки только у SendMsg/set_buzzer/set_pump_speed_pid (запоминают вызовы) и
format_float.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

ALARM_SIGNATURES = [
    "inline bool sensor_configured(const DSSensor& sensor)",
    "inline bool sensor_reading_valid(const DSSensor& sensor)",
    "inline bool sensor_temp_at_least(const DSSensor& sensor, float temp)",
]
MODE_COMMON_SIGNATURES = [
    "inline bool mode_acp_above_boost_threshold(float acpBoostThreshold)",
    "inline void mode_warn_acp_hot_once(bool acpHot, float acpBoostThreshold)",
    "inline bool mode_water_rising_fast()",
    "inline void mode_update_water_pump_pid(float acpBoostThreshold)",
]

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <string>

#define USE_WATER_PUMP
#define WARNING_MSG 1

using String = std::string;
using DeviceAddress = uint8_t[8];
struct DSSensor {
  DeviceAddress Sensor = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
  volatile float avgTemp = 0.0f;
  volatile int ErrCount = 0;
};
struct Setup { float SetWaterTemp = 30.0f; float SetACPTemp = 47.0f; };

static DSSensor WaterSensor;
static DSSensor ACPSensor;
static Setup SamSetup;
static bool PowerOn = false;
static bool valve_status = true;
static uint32_t fakeMillis = 0;
static uint32_t millis() { return fakeMillis; }

static int buzzerCalls = 0;
static int messageCount = 0;
static String lastMessage;
static int lastMessageLevel = -1;
static float lastPumpTemp = 0.0f;
static bool lastPumpSoften = true;

static void set_buzzer(bool on) { if (on) buzzerCalls++; }
static void SendMsg(const String& text, int level) {
  messageCount++;
  lastMessage = text;
  lastMessageLevel = level;
}
static String format_float(float v, int d) {
  char out[32];
  snprintf(out, sizeof(out), "%.*f", d, (double)v);
  return out;
}
static void set_pump_speed_pid(float temp, bool soften = true) {
  lastPumpTemp = temp;
  lastPumpSoften = soften;
}

@BODIES@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static bool contains(const String& text, const char* part) {
  return text.find(part) != String::npos;
}

int main() {
  ACPSensor.Sensor[0] = 0x28;
  WaterSensor.Sensor[0] = 0x28;
  WaterSensor.avgTemp = 25.0f;
  PowerOn = true;

  // Ниже порога: тишина, насос ведётся по температуре воды.
  ACPSensor.avgTemp = 46.0f;
  mode_update_water_pump_pid(47.0f);
  check(messageCount == 0, "ниже порога ТСА предупреждения быть не должно");
  check(lastPumpTemp == 25.0f && lastPumpSoften, "ниже порога насос ведётся по температуре воды");

  // Выше порога: одно предупреждение с температурой и порогом, насос усилен.
  ACPSensor.avgTemp = 47.5f;
  mode_update_water_pump_pid(47.0f);
  check(messageCount == 1, "выше порога ТСА обязано прийти предупреждение");
  check(lastMessageLevel == WARNING_MSG, "предупреждение о ТСА идёт уровнем WARNING_MSG");
  check(buzzerCalls == 1, "предупреждение о ТСА сопровождается гудком");
  check(contains(lastMessage, "ТСА") && contains(lastMessage, "47.5") && contains(lastMessage, "47.0"),
        "в тексте обязаны быть ТСА, её температура 47.5 и порог 47.0");
  check(lastPumpTemp == 33.0f && !lastPumpSoften, "выше порога насос усилен (уставка воды + 3, без смягчения)");

  // Пока эпизод длится - без повторов, в том числе при дрожании у порога.
  mode_update_water_pump_pid(47.0f);
  ACPSensor.avgTemp = 46.5f;
  mode_update_water_pump_pid(47.0f);
  ACPSensor.avgTemp = 48.0f;
  mode_update_water_pump_pid(47.0f);
  check(messageCount == 1, "дрожание у порога не должно плодить предупреждения");

  // Остыла на 2 градуса ниже порога - новый эпизод даёт новое предупреждение.
  ACPSensor.avgTemp = 44.0f;
  mode_update_water_pump_pid(47.0f);
  ACPSensor.avgTemp = 50.0f;
  mode_update_water_pump_pid(47.0f);
  check(messageCount == 2, "после остывания ниже порога - 2 новый перегрев обязан предупредить снова");
  check(contains(lastMessage, "50.0"), "второе предупреждение называет новую температуру 50.0");

  // Другой порог (39): текст берёт порог из аргумента.
  ACPSensor.avgTemp = 30.0f;
  mode_update_water_pump_pid(39.0f);
  ACPSensor.avgTemp = 40.0f;
  mode_update_water_pump_pid(39.0f);
  check(messageCount == 3 && contains(lastMessage, "39.0"), "порог 39.0 обязан попасть в текст");

  // Нагрев выключен: предупреждений нет, выключение взводит предупреждение заново.
  PowerOn = false;
  mode_update_water_pump_pid(39.0f);
  check(messageCount == 3, "без нагрева предупреждений о ТСА нет");
  PowerOn = true;
  mode_update_water_pump_pid(39.0f);
  check(messageCount == 4, "после нового включения нагрева горячая ТСА предупреждает снова");

  // Закрытый клапан воды останавливает только управление насосом, не предупреждение.
  PowerOn = false;
  mode_update_water_pump_pid(39.0f);
  PowerOn = true;
  valve_status = false;
  lastPumpTemp = -1.0f;
  mode_update_water_pump_pid(39.0f);
  check(messageCount == 5, "предупреждение о ТСА не зависит от клапана воды");
  check(lastPumpTemp == -1.0f, "при закрытом клапане насос не трогаем");
  valve_status = true;

  // Предупреждение не зависит от воды; насос продолжает регулирование по воде.
  PowerOn = false;
  mode_update_water_pump_pid(39.0f);
  PowerOn = true;
  WaterSensor.avgTemp = 60.0f;
  ACPSensor.avgTemp = 45.0f;
  mode_update_water_pump_pid(39.0f);
  check(messageCount == 6, "ТСА холоднее воды - предупреждение обязательно");
  check(lastPumpTemp == 60.0f && lastPumpSoften, "ТСА холоднее воды - насос регулируется по воде");
  WaterSensor.avgTemp = 25.0f;

  // Датчик ТСА не назначен - предупреждения нет.
  PowerOn = false;
  mode_update_water_pump_pid(39.0f);
  PowerOn = true;
  ACPSensor.Sensor[0] = 0xFF;
  ACPSensor.avgTemp = 70.0f;
  mode_update_water_pump_pid(39.0f);
  check(messageCount == 6, "без датчика ТСА предупреждения нет");

  ACPSensor.Sensor[0] = 0x28;
  // Вызываем извлечённую из check_alarm() строку с двумя уставками.
  for (float threshold : {47.0f, 55.0f}) {
    SamSetup.SetACPTemp = threshold;
    WaterSensor.avgTemp = 60.0f;
    ACPSensor.avgTemp = 30.0f;
    rectification_pump_tick();
    const int before = messageCount;
    ACPSensor.avgTemp = threshold - 1;
    rectification_pump_tick();
    check(messageCount == before, "ректификация учитывает настроенную уставку");
    ACPSensor.avgTemp = threshold + 5;
    rectification_pump_tick();
    check(messageCount == before + 1, "первый перегрев при горячей воде");
    ACPSensor.avgTemp = 30.0f;
    rectification_pump_tick();
    ACPSensor.avgTemp = threshold + 3;
    rectification_pump_tick();
    check(messageCount == before + 2, "повторный перегрев при горячей воде");
    WaterSensor.avgTemp = 25.0f;
    rectification_pump_tick();
    check(lastPumpTemp == 33.0f && !lastPumpSoften, "насос усиливается по настроенной уставке");
    ACPSensor.avgTemp = threshold - 1;
    rectification_pump_tick();
    check(lastPumpTemp == 25.0f && lastPumpSoften, "насос не усиливается ниже настроенной уставки");
  }

  if (failures == 0) std::cout << "OK\n";
  return failures == 0 ? 0 : 1;
}
'''


def build_harness(mode_common_source: str, alarm_source: str) -> str:
    bodies = []
    for source, signatures in ((alarm_source, ALARM_SIGNATURES), (mode_common_source, MODE_COMMON_SIGNATURES)):
        for signature in signatures:
            bodies.append(signature + " {" + extract_function_body(source, signature) + "}")
    rect = extract_function_body(alarm_source, "void check_alarm()")
    call = re.search(r"mode_update_water_pump_pid\([^;]+;", rect).group(0)
    bodies.append("void rectification_pump_tick() {" + call + "}")
    return HARNESS_TEMPLATE.replace("@BODIES@", "\n\n".join(bodies))


def compile_and_run(harness: str, label: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-acp-hot-warning-") as temp_dir:
        source = Path(temp_dir) / "acp_hot_warning_test.cpp"
        binary = Path(temp_dir) / "acp_hot_warning_test"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if compiled.returncode != 0:
            return compiled.returncode, f"[{label}] compile failed:\n{compiled.stdout}{compiled.stderr}"
        result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        return result.returncode, result.stdout + result.stderr


# Каждая мутация обязана упасть на названном содержательном assert-е, а не на компиляторе.
MUTATIONS = [
    ("предупреждение не отправляется", "  warned = true;\n  set_buzzer(true);\n  SendMsg(",
     "  warned = true;\n  set_buzzer(true);\n  if (false) SendMsg(", "обязано прийти предупреждение"),
    ("нет защиты от повторов", "  if (warned) return;", "  if (warned && false) return;",
     "не должно плодить предупреждения"),
    ("нет гистерезиса 2 градуса", "acpBoostThreshold - 2)) warned = false;", "acpBoostThreshold)) warned = false;",
     "не должно плодить предупреждения"),
    ("предупреждение без нагрева", "  if (!PowerOn) {\n    warned = false;\n    return;\n  }",
     "  if (!PowerOn) {\n    warned = false;\n  }", "без нагрева предупреждений о ТСА нет"),
    ("предупреждение спрятано за клапаном",
     "  mode_warn_acp_hot_once(acpHot, acpBoostThreshold);\n#ifdef USE_WATER_PUMP\n  const bool waterRisingFast = mode_water_rising_fast();\n  if (!valve_status) return;",
     "#ifdef USE_WATER_PUMP\n  const bool waterRisingFast = mode_water_rising_fast();\n  if (!valve_status) return;\n  mode_warn_acp_hot_once(acpHot, acpBoostThreshold);",
     "не зависит от клапана воды"),
    ("насос не сравнивает ТСА с водой", "if (acpHot && ACPSensor.avgTemp > WaterSensor.avgTemp)", "if (acpHot)",
     "ТСА холоднее воды - насос"),
    ("предупреждение зависит от воды", "mode_warn_acp_hot_once(acpHot, acpBoostThreshold);",
     "mode_warn_acp_hot_once(acpHot && ACPSensor.avgTemp > WaterSensor.avgTemp, acpBoostThreshold);",
     "ТСА холоднее воды - предупреждение"),
]


def main() -> int:
    mode_common_source = (ROOT / "mode_common.h").read_text(encoding="utf-8")
    alarm_source = (ROOT / "alarm.h").read_text(encoding="utf-8")
    try:
        rc, output = compile_and_run(build_harness(mode_common_source, alarm_source), "baseline")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if rc != 0:
        print(output, file=sys.stderr)
        return 1

    for label, old, new, expected in MUTATIONS:
        if mode_common_source.count(old) != 1:
            print(f"FAIL: mutation anchor not unique for «{label}»", file=sys.stderr)
            return 1
        rc, output = compile_and_run(build_harness(mode_common_source.replace(old, new), alarm_source), label)
        if rc == 0:
            print(f"FAIL: mutation «{label}» survived", file=sys.stderr)
            return 1
        if expected not in output:
            print(f"FAIL: mutation «{label}» failed for the wrong reason:\n{output}", file=sys.stderr)
            return 1

    mutant_alarm = alarm_source.replace("mode_update_water_pump_pid(SamSetup.SetACPTemp < 45.0f ? 45.0f : SamSetup.SetACPTemp);", "mode_update_water_pump_pid(39.0f);")
    rc, output = compile_and_run(build_harness(mode_common_source, mutant_alarm), "fixed 39")
    if rc == 0 or "ректификация учитывает настроенную уставку" not in output:
        print("FAIL: fixed threshold mutation: " + output, file=sys.stderr)
        return 1
    print("OK: smoke_acp_hot_warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
