#!/usr/bin/env python3
"""T08: реальная модель -> снимок -> AJAX/V27 и алкогольные поля V34."""

import json
import re
import subprocess
import tempfile
from pathlib import Path

from smoke_a05_state_owners import HARNESS_PREFIX, production_section
from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]


def replace_function(source, signature, replacement):
    body = extract_function_body(source, signature)
    start = source.index(signature)
    brace = source.index("{", start)
    return source[:start] + replacement + source[brace + len(body) + 2:]


def harness(sketch, blynk, logic, sensor):
    prefix = HARNESS_PREFIX
    prefix = prefix.replace(
        " private:\n  std::string value_;",
        "  String& operator+=(const String& value) { value_ += value.str(); return *this; }\n"
        " private:\n  std::string value_;", 1)
    table = re.search(
        r"struct AlcoholTablePoint \{.*?\n\};\s*static const AlcoholTablePoint ALCOHOL_TABLE\[\] = \{.*?\n\};",
        logic, re.S)
    if not table:
        raise AssertionError("actual alcohol table missing")
    model = "bool boil_started = true;\nusing std::isfinite;\n" + table.group(0)
    for signature in ("inline float get_alcohol_from_table(float t, bool steam)",
                      "float get_alcohol(float t)", "float get_steam_alcohol(float t)"):
        model += signature + " {" + extract_function_body(logic, signature) + "}\n"
    prefix = replace_function(prefix, "float get_alcohol(float temperature)", model)
    prefix = replace_function(prefix, "float get_steam_alcohol(float temperature)", "")
    formatter = extract_function_body(sensor, "inline String format_float(float v, int d)")
    prefix = replace_function(prefix, "String format_float(float value, int digits)",
        "using std::isnan; using std::isinf;\n"
        "char* dtostrf(double v, int, int d, char* out) { std::sprintf(out, \"%.*f\", d, v); return out; }\n"
        "String format_float(float v, int d) {" + formatter + "}\n")
    section = production_section(sketch, (ROOT / "string_utils.h").read_text())
    writer_signature = "static void write_blynk_mode_json(Print& out, const AjaxTelemetrySnapshot& s)"
    section += "constexpr int DETECTOR_IDLE_STEAM_WAIT = 5;\n"
    section += writer_signature + " {" + extract_function_body(blynk, writer_signature) + "}\n"
    # Остальные поля V34 закреплены отдельным smoke_blynk_v34_v35_format.py.
    # Здесь исполняются без переписывания два реальных алкогольных поля.
    tail = extract_function_body(sketch, "static String format_v34_tail_fields()")
    begin = tail.index('  s += ",";\n  s += format_float(get_alcohol(')
    end = tail.index('  s += format_float(pressure_value, 2);', begin)
    section += "static String alcohol_v34_fragment() { String s;\n" + tail[begin:end] + "return s; }\n"
    return prefix + section + r'''
int main() {
  struct Sample { bool boiling; float tank; float steam; };
  const Sample samples[] = {
    {false, 96.12f, 83.51f}, {true, 96.12f, 83.51f},
    {true, 86.64f, 92.46f}, {true, 106.0f, 78.15f},
    {true, 100.0f, 100.0f}, {true, 96.12f, 106.0f}
  };
  const SAMOVAR_MODE modes[] = {SAMOVAR_RECTIFICATION_MODE,
    SAMOVAR_DISTILLATION_MODE, SAMOVAR_BK_MODE, SAMOVAR_NBK_MODE};
  for (auto mode : modes) {
    Samovar_Mode = mode;
    for (const auto& sample : samples) {
      boil_started = sample.boiling;
      TankSensor.avgTemp = sample.tank;
      SteamSensor.avgTemp = sample.steam;
      s_uiStateCache = build_ui_state_from_loop();
      AjaxTelemetrySnapshot snapshot{};
      if (captureAjaxTelemetrySnapshot(0, snapshot) != RUNTIME_AJAX_SNAPSHOT_OK) return 1;
      Print ajax;
      writeAjaxTelemetryFields(ajax, snapshot);
      ajax.print('}'); // send_ajax_json закрывает объект после полей событий.
      Print v27;
      write_blynk_mode_json(v27, snapshot);
      std::cout << ajax.bytes << '\n' << v27.bytes << '\n'
                << alcohol_v34_fragment().c_str() << '\n';
    }
  }
}
'''


def execute(code):
    with tempfile.TemporaryDirectory(prefix="samovar-t08-wire-") as directory:
        source = Path(directory) / "test.cpp"
        binary = Path(directory) / "test"
        source.write_text(code)
        # Ошибка компиляции, включая мутант, не считается успешной проверкой.
        subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                        str(source), "-o", str(binary)], check=True, capture_output=True, text=True)
        return subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout


def verify(output):
    lines = output.splitlines()
    assert len(lines) == 4 * 6 * 3, "wire sample count mismatch"
    for mode in range(4):
        steam = [(-1, -1), (80.33, 35.36), (55.28, 73.72),
                 (-1, -1), (0, 0), (-1, 35.36)]
        for sample, tank in enumerate((-1, 4.71, 27.07, -1, 0, 4.71)):
            expected_steam = steam[sample][0 if mode == 0 else 1]
            offset = (mode * 6 + sample) * 3
            ajax, v27 = map(json.loads, lines[offset:offset + 2])
            csv = lines[offset + 2].split(",")
            assert len(csv) == 4 and csv[0] == csv[-1] == "", "V34 fragment field count"
            for label, value, expected in (
                ("AJAX cube", ajax["alc"], tank),
                ("AJAX steam", ajax["stm_alc"], expected_steam),
                ("V27 cube", v27["alc"], tank),
                ("V27 steam", v27["salc"], expected_steam),
                ("V34 cube", float(csv[1]), tank),
                ("V34 steam", float(csv[2]), expected_steam),
            ):
                assert type(value) in (int, float) and abs(value - expected) < 0.015, (
                    f"{label} value mismatch: mode={mode}, sample={sample}, {value} != {expected}")


def main():
    sketch = (ROOT / "Samovar.ino").read_text()
    blynk = (ROOT / "Blynk.ino").read_text()
    logic = (ROOT / "logic.h").read_text()
    sensor = (ROOT / "sensorinit.h").read_text()
    verify(execute(harness(sketch, blynk, logic, sensor)))
    for old, new, expected in (
        ('"alc", snapshot.alcohol, 2', '"alc", 0.0f, 2', "AJAX cube value mismatch"),
        ("get_steam_alcohol(Samovar_Mode == SAMOVAR_RECTIFICATION_MODE ? SteamSensor.avgTemp : TankSensor.avgTemp)",
         "get_steam_alcohol(TankSensor.avgTemp)", "V34 steam value mismatch"),
    ):
        assert old in sketch, "wire mutation anchor missing"
        output = execute(harness(sketch.replace(old, new, 1), blynk, logic, sensor))
        try:
            verify(output)
        except AssertionError as error:
            assert expected in str(error), f"wrong wire mutation failure: {error}"
        else:
            raise AssertionError(f"wire mutation survived: {expected}")
    print("T08 alcohol wire: AJAX/V27/V34 samples and exact mutations passed")


if __name__ == "__main__":
    main()
