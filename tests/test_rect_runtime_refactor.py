"""Tests for rect_runtime.h refactoring: WType helpers, check_alarm decomposition,
named constants, and globals.h grouping."""

from pathlib import Path
import re
import unittest


RECT_RUNTIME = Path("modes/rect/rect_runtime.h")
GLOBALS_H = Path("state/globals.h")


class WTypeHelpersTest(unittest.TestCase):
    """Verify WType inline helpers exist and replaced raw string comparisons."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = RECT_RUNTIME.read_text(encoding="utf-8")

    def test_helpers_defined(self) -> None:
        self.assertIn("inline bool is_body_or_prechoke(const String& wtype)", self.text)
        self.assertIn("inline bool is_active_withdrawal(const String& wtype)", self.text)
        self.assertIn("inline bool is_heads_or_tails(const String& wtype)", self.text)

    def test_helpers_used_in_withdrawal(self) -> None:
        # withdrawal() should call check_sensor_temp_pause, not raw WType checks
        self.assertIn("check_sensor_temp_pause(SteamSensor,", self.text)
        self.assertIn("check_sensor_temp_pause(PipeSensor,", self.text)

    def test_helpers_used_in_run_program(self) -> None:
        self.assertIn("is_body_or_prechoke(currentType)", self.text)
        self.assertIn("is_body_or_prechoke(prevType)", self.text)
        self.assertIn("is_active_withdrawal(program[num].WType)", self.text)
        self.assertIn("is_heads_or_tails(program[num].WType)", self.text)

    def test_no_raw_body_prechoke_pattern_outside_helpers(self) -> None:
        """Ensure (WType == "B" || WType == "C") pattern is not used outside helper definitions."""
        # Find all raw patterns, excluding the helper definition lines
        raw_pattern = re.compile(r'WType\s*==\s*"B"\s*\|\|\s*\w+\.?WType\s*==\s*"C"')
        lines = self.text.split('\n')
        violations = []
        for i, line in enumerate(lines, 1):
            if raw_pattern.search(line):
                # Allow in helper definition
                if 'inline bool is_body_or_prechoke' in line:
                    continue
                violations.append(f"line {i}: {line.strip()}")
        self.assertEqual(violations, [], f"Raw B||C pattern found:\n" + "\n".join(violations))


class CheckSensorTempPauseTest(unittest.TestCase):
    """Verify the extracted check_sensor_temp_pause function."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = RECT_RUNTIME.read_text(encoding="utf-8")

    def test_function_exists(self) -> None:
        self.assertIn("inline void check_sensor_temp_pause(DSSensor& sensor,", self.text)

    def test_withdrawal_uses_it_for_both_sensors(self) -> None:
        # Inside withdrawal(), there should be exactly two calls
        withdrawal_start = self.text.index("inline void withdrawal(void)")
        withdrawal_end = self.text.index("inline void pause_withdrawal(")
        withdrawal_body = self.text[withdrawal_start:withdrawal_end]
        calls = withdrawal_body.count("check_sensor_temp_pause(")
        self.assertEqual(calls, 2, "withdrawal() must call check_sensor_temp_pause exactly twice")


class CheckAlarmDecompositionTest(unittest.TestCase):
    """Verify check_alarm() is decomposed into subfunctions."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = RECT_RUNTIME.read_text(encoding="utf-8")

    def test_subfunctions_exist(self) -> None:
        self.assertIn("inline void check_acceleration_heater()", self.text)
        self.assertIn("inline void check_head_level_sensor()", self.text)
        self.assertIn("inline void check_valve_and_cooling()", self.text)
        self.assertIn("inline void check_temperature_limits()", self.text)
        self.assertIn("inline void check_warmup_and_stabilization()", self.text)

    def test_check_alarm_delegates_to_subfunctions(self) -> None:
        # Find check_alarm body
        idx = self.text.rindex("inline void check_alarm()")
        body = self.text[idx:]
        self.assertIn("check_acceleration_heater()", body)
        self.assertIn("check_head_level_sensor()", body)
        self.assertIn("check_power_error()", body)
        self.assertIn("check_valve_and_cooling()", body)
        self.assertIn("check_temperature_limits()", body)
        self.assertIn("check_warmup_and_stabilization()", body)

    def test_check_alarm_body_is_short(self) -> None:
        """check_alarm() should be a dispatcher, not a monolith."""
        idx = self.text.rindex("inline void check_alarm()")
        # Find closing brace
        body_start = self.text.index("{", idx)
        depth = 0
        body_end = body_start
        for i, ch in enumerate(self.text[body_start:], body_start):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    body_end = i
                    break
        body = self.text[body_start:body_end]
        line_count = body.count('\n')
        self.assertLess(line_count, 25, f"check_alarm() body has {line_count} lines, should be <25 (dispatcher)")


class NamedConstantsTest(unittest.TestCase):
    """Verify magic numbers are replaced with named constants."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = RECT_RUNTIME.read_text(encoding="utf-8")

    def test_constants_defined(self) -> None:
        self.assertIn("HLS_REACTION_DELAY_MS", self.text)
        self.assertIn("ALARM_WATER_REACTION_MS", self.text)
        self.assertIn("EMERGENCY_COMMAND_DELAY_MS", self.text)
        self.assertIn("STABILIZATION_TICKS", self.text)
        self.assertIn("STABILIZATION_THRESHOLD", self.text)
        self.assertIn("RELATIVE_TEMP_THRESHOLD", self.text)
        self.assertIn("PRECHOKE_TIMER_MS", self.text)
        self.assertIn("PRECHOKE_FAST_TIMER_MS", self.text)

    def test_no_raw_40sec_delay(self) -> None:
        """1000 * 40 should not appear raw (replaced by HLS_REACTION_DELAY_MS)."""
        self.assertNotIn("1000 * 40", self.text)

    def test_no_raw_30sec_delay(self) -> None:
        """1000 * 30 should not appear raw (replaced by ALARM_WATER_REACTION_MS)."""
        self.assertNotIn("1000 * 30", self.text)

    def test_no_raw_time_c_pattern(self) -> None:
        """1000 * 60 * TIME_C should not appear raw."""
        self.assertNotIn("1000 * 60 * TIME_C", self.text)


class GlobalsGroupingTest(unittest.TestCase):
    """Verify globals.h has semantic section comments."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = GLOBALS_H.read_text(encoding="utf-8")

    def test_section_headers_exist(self) -> None:
        expected_sections = [
            "FreeRTOS",
            "Периферия",
            "Сеть и веб-сервер",
            "Конфигурация и state-модель",
            "Датчики температуры",
            "Давление и BME",
            "Программа режима и отбор",
            "Степпер и привод отбора",
            "Управление нагревом и мощностью",
            "Алармы и таймеры безопасности",
            "Клапаны, насосы, вода",
            "PID-регулятор",
            "Звуковые оповещения",
            "UI: дисплей и меню",
            "Сообщения и логирование",
            "Lua",
        ]
        for section in expected_sections:
            with self.subTest(section=section):
                self.assertIn(section, self.text, f"Section '{section}' not found in globals.h")

    def test_all_original_externs_preserved(self) -> None:
        """All extern declarations must still be present."""
        required_externs = [
            "extern DSSensor SteamSensor;",
            "extern DSSensor PipeSensor;",
            "extern WProgram program[30];",
            "extern volatile bool PowerOn;",
            "extern SetupEEPROM SamSetup;",
            "extern volatile SAMOVAR_MODE Samovar_Mode;",
            "extern volatile int16_t SamovarStatusInt;",
            "extern AsyncWebServer server;",
            "extern GStepper2< STEPPER2WIRE> stepper;",
        ]
        for ext in required_externs:
            with self.subTest(extern=ext):
                self.assertIn(ext, self.text)


if __name__ == "__main__":
    unittest.main()
