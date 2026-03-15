from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


RUNTIME_HEADER = Path("ui/lua/runtime.h")


def _extract_function(text: str, signature: str) -> str:
    pattern = re.compile(rf"(?:inline\s+)?{re.escape(signature)}\s*\{{", re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Function signature not found: {signature}")

    brace_start = text.find("{", match.start())
    if brace_start == -1:
        raise AssertionError(f"Function body start not found: {signature}")

    depth = 0
    for index in range(brace_start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[match.start():index + 1]

    raise AssertionError(f"Function body end not found: {signature}")


class LuaGlobalVariablesBehaviorTest(unittest.TestCase):
    def test_debug_harness_executes_extracted_get_global_variables(self) -> None:
        compiler = shutil.which("g++") or shutil.which("c++")
        self.assertIsNotNone(
            compiler,
            "C++ compiler is required for get_global_variables harness test",
        )

        header_text = RUNTIME_HEADER.read_text(encoding="utf-8")
        extracted_function = _extract_function(
            header_text,
            "String get_global_variables()",
        )

        harness = textwrap.dedent(
            f"""
            #include <cstring>
            #include <iostream>
            #include <sstream>
            #include <string>

            class String {{
             public:
              String() = default;
              String(const char* text) : value_(text == nullptr ? "" : text) {{}}
              String(const std::string& text) : value_(text) {{}}
              String(int number) : value_(std::to_string(number)) {{}}
              String(unsigned int number) : value_(std::to_string(number)) {{}}
              String(long number) : value_(std::to_string(number)) {{}}
              String(unsigned long number) : value_(std::to_string(number)) {{}}
              String(float number) : value_(format_number(number)) {{}}
              String(double number) : value_(format_number(number)) {{}}
              String(bool value) : value_(value ? "1" : "0") {{}}
              String(const String&) = default;
              String& operator=(const String&) = default;

              String& operator+=(const String& other) {{
                value_ += other.value_;
                return *this;
              }}

              String& operator+=(const char* other) {{
                value_ += other == nullptr ? "" : other;
                return *this;
              }}

              const char* c_str() const {{
                return value_.c_str();
              }}

              std::size_t length() const {{
                return value_.size();
              }}

              friend String operator+(const String& left, const String& right) {{
                return String(left.value_ + right.value_);
              }}

              friend String operator+(const String& left, const char* right) {{
                return String(left.value_ + (right == nullptr ? "" : right));
              }}

              friend String operator+(const char* left, const String& right) {{
                return String(std::string(left == nullptr ? "" : left) + right.value_);
              }}

             private:
              static std::string format_number(double value) {{
                std::ostringstream stream;
                stream << value;
                return stream.str();
              }}

              std::string value_;
            }};

            struct ProgramLine {{
              String WType;
              float Volume = 0;
              float Speed = 0;
              float Temp = 0;
              float Power = 0;
              float Time = 0;
              int capacity_num = 0;
            }};

            struct SamSetupStruct {{
              int Mode = 0;
            }};

            struct SensorState {{
              float avgTemp = 0;
            }};

            float bme_pressure = 752.6f;
            int capacity_num = 2;
            int SamovarStatusInt = 50;
            int ProgramNum = 0;
            int ProgramLen = 3;
            float ActualVolumePerHour = 1.5f;
            int WthdrwlProgress = 11;
            bool PowerOn = true;
            bool PauseOn = false;
            bool StepperMoving = true;
            bool program_Pause = false;
            bool program_Wait = true;
            String program_Wait_Type = "steam";
            unsigned long WthdrwTimeAll = 120;
            unsigned long WthdrwTime = 15;
            String WthdrwTimeAllS = "02:00";
            String WthdrwTimeS = "00:15";
            bool pump_started = false;
            bool heater_state = true;
            bool mixer_status = true;
            bool alarm_event = false;
            bool acceleration_heater = true;
            bool valve_status = false;
            ProgramLine program[3];
            SamSetupStruct SamSetup;
            int test_num_val = 7;
            String test_str_val = "abc";
            SensorState SteamSensor;
            SensorState PipeSensor;
            SensorState WaterSensor;
            SensorState TankSensor;
            SensorState ACPSensor;
            String current_power_mode = "voltage";
            float target_power_volt = 220.0f;

            {extracted_function}

            int main() {{
              program[0].WType = "body";
              program[0].Volume = 3.2f;
              program[0].Speed = 1.1f;
              program[0].Temp = 78.3f;
              program[0].Power = 1.4f;
              program[0].Time = 42.0f;
              program[0].capacity_num = 1;

              SteamSensor.avgTemp = 78.1f;
              PipeSensor.avgTemp = 77.4f;
              WaterSensor.avgTemp = 19.8f;
              TankSensor.avgTemp = 25.5f;
              ACPSensor.avgTemp = 18.2f;

              String result = get_global_variables();
              if (std::strcmp(result.c_str(), "") != 0) {{
                std::cerr << "expected empty Phase 0 result, got: " << result.c_str() << std::endl;
                return 1;
              }}

              PowerOn = false;
              PauseOn = true;
              result = get_global_variables();
              if (result.length() != 0) {{
                std::cerr << "expected stable empty result after state change" << std::endl;
                return 1;
              }}

              return 0;
            }}
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            harness_path = tmp_path / "lua_global_variables_harness.cpp"
            binary_path = tmp_path / "lua_global_variables_harness"
            harness_path.write_text(harness, encoding="utf-8")

            compile_result = subprocess.run(
                [compiler, "-std=c++17", str(harness_path), "-o", str(binary_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                compile_result.returncode,
                0,
                msg=compile_result.stderr or compile_result.stdout,
            )

            run_result = subprocess.run(
                [str(binary_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                run_result.returncode,
                0,
                msg=run_result.stderr or run_result.stdout,
            )


if __name__ == "__main__":
    unittest.main()
