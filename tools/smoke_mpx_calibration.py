#!/usr/bin/env python3
"""MPX pressure conversion uses the persisted zero and scale calibration."""

from __future__ import annotations

import pathlib
import subprocess
import tempfile
import textwrap

from smoke_helpers import extract_function_body


ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "sensorinit.h").read_text(encoding="utf-8")
BODY = extract_function_body(SOURCE, "void pressure_sensor_get()", strip_comments=False)

HARNESS = textwrap.dedent(
    f"""
    #include <assert.h>
    #include <math.h>

    #define USE_PRESSURE_MPX
    #define LUA_PIN 32

    struct SetupEEPROM {{
      float MpxZeroAdc;
      float MpxCountsPerMmHg;
    }};

    static SetupEEPROM SamSetup{{}};
    static bool use_pressure_sensor = true;
    static float pressure_value = 0.0f;
    static float old_pressure_value = 0.0f;
    static int raw_adc = 0;

    static int analogRead(int pin) {{
      assert(pin == LUA_PIN);
      return raw_adc;
    }}

    static void pressure_sensor_get() {{
    {BODY}
      (void)t;
    }}

    static void expect_close(float actual, float expected) {{
      assert(fabsf(actual - expected) < 0.0001f);
    }}

    int main() {{
      SamSetup.MpxZeroAdc = 36.7f;
      SamSetup.MpxCountsPerMmHg = 12.0f;
      old_pressure_value = 2.0f;
      raw_adc = 157;
      pressure_sensor_get();
      expect_close(pressure_value, (((157.0f - 36.7f) / 12.0f) + 2.0f) / 2.0f);

      SamSetup.MpxZeroAdc = 100.0f;
      SamSetup.MpxCountsPerMmHg = 4.0f;
      old_pressure_value = -2.0f;
      raw_adc = 140;
      pressure_sensor_get();
      expect_close(pressure_value, 4.0f);

      use_pressure_sensor = false;
      pressure_sensor_get();
      expect_close(pressure_value, -1.0f);
      return 0;
    }}
    """
)

with tempfile.TemporaryDirectory() as tmp:
    source = pathlib.Path(tmp) / "mpx_calibration.cpp"
    binary = pathlib.Path(tmp) / "mpx_calibration"
    source.write_text(HARNESS, encoding="utf-8")
    subprocess.run(
        ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
        check=True,
    )
    subprocess.run([str(binary)], check=True)

print("OK: MPX conversion uses profile zero and counts-per-mmHg calibration")
