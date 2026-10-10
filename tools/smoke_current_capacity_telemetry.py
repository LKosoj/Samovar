#!/usr/bin/env python3
"""Фактическая ёмкость попадает в общий снимок, /ajax и V27."""
import json
import re
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]


def check(samovar, blynk):
    capture = extract_function_body(samovar, "static RuntimeAjaxSnapshotResult captureAjaxTelemetrySnapshot(")
    ajax = extract_function_body(samovar, "static void writeAjaxTelemetryFields(")
    mode = extract_function_body(blynk, "static void write_blynk_mode_json(Print& out, const AjaxTelemetrySnapshot& s)")
    assignment = re.search(r"snapshot\.currentCapacity\s*=\s*[^;]+;", capture)
    assert assignment, "снимок должен получать фактическую ёмкость"
    lines = []
    for body, key in [(ajax, "currentCapacity"), (mode, "cap")]:
        line = re.search(r'jsonFieldRaw\(out, first, "' + key + r'", [^;]+;', body)
        assert line, f"телеметрия должна содержать {key}"
        lines.append(line.group())
    # Исполняем строки настоящих функций, а не их копии в тесте.
    source = '''
    #include <iostream>
    struct Snapshot { int currentCapacity = -1; int programIndex = 0; };
    void jsonFieldRaw(std::ostream& out, bool&, const char* key, int value) {
      out << "{\\\"" << key << "\\\":" << value << "}\\n";
    }
    int main() {
      for (int capacity_num : {2, 7}) {
        int ProgramNum = 0;
        (void)ProgramNum;
        Snapshot snapshot;
        bool first = true;
        auto& out = std::cout;
        ''' + assignment.group() + '\n' + lines[0] + '''
        const auto& s = snapshot;
        ''' + lines[1] + '''
      }
    }
    '''
    with tempfile.TemporaryDirectory() as directory:
        cpp = Path(directory) / "test.cpp"
        binary = Path(directory) / "test"
        cpp.write_text(source)
        subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(binary)], check=True)
        values = [json.loads(line) for line in subprocess.check_output([str(binary)], text=True).splitlines()]
    assert values == [{"currentCapacity": 2}, {"cap": 2}, {"currentCapacity": 7}, {"cap": 7}], "снимок и оба ответа должны передавать фактическую ёмкость"


if __name__ == "__main__":
    samovar = (ROOT / "Samovar.ino").read_text()
    blynk = (ROOT / "Blynk.ino").read_text()
    check(samovar, blynk)
    for a, b in [
        (samovar.replace("snapshot.currentCapacity = capacity_num;", "snapshot.currentCapacity = ProgramNum;"), blynk),
        (samovar.replace('"currentCapacity", snapshot.currentCapacity', '"currentCapacity", snapshot.programIndex'), blynk),
        (samovar, blynk.replace('"cap", s.currentCapacity', '"cap", s.programIndex')),
    ]:
        try:
            check(a, b)
        except AssertionError as error:
            assert "фактическую ёмкость" in str(error)
        else:
            raise AssertionError("мутация фактической ёмкости осталась незамеченной")
    print("current capacity telemetry and mutations passed")
