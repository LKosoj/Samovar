import re
import unittest
from pathlib import Path


ORCHESTRATION_HEADER = Path("app/orchestration.h")
SAMOVAR_INO = Path("Samovar.ino")


class AppOrchestrationHeaderTest(unittest.TestCase):
    def test_orchestration_header_exists(self) -> None:
        self.assertTrue(ORCHESTRATION_HEADER.exists())

    def test_orchestration_header_contains_setup_and_loop_helpers(self) -> None:
        text = ORCHESTRATION_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline void samovar_app_setup()", text)
        self.assertIn("inline void samovar_app_loop()", text)

    def test_setup_helper_keeps_critical_initialization_steps(self) -> None:
        text = ORCHESTRATION_HEADER.read_text(encoding="utf-8")
        for marker in [
            'esp_log_level_set("i2c.master", ESP_LOG_NONE);',
            "migrate_from_eeprom();",
            "read_config();",
            "setupMenu();",
            "sensor_init();",
            "startService();",
            "samovar_reset();",
            "WebServerInit();",
            "triggerSysTicker",
            "triggerGetClock",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_loop_helper_keeps_mode_switching_and_runtime_dispatch(self) -> None:
        text = ORCHESTRATION_HEADER.read_text(encoding="utf-8")
        for marker in [
            "if (mode_is_rect_runtime(Samovar_Mode))",
            "mode_is_distillation_runtime(Samovar_Mode)",
            "mode_is_bk_runtime(Samovar_Mode)",
            "mode_is_nbk_runtime(Samovar_Mode)",
            "mode_is_beer_runtime(Samovar_Mode)",
            "sam_command_sync = SAMOVAR_DISTILLATION;",
            "sam_command_sync = SAMOVAR_BK;",
            "sam_command_sync = SAMOVAR_NBK;",
            "sam_command_sync = SAMOVAR_BEER;",
            "process_sam_command_sync();",
            "dispatch_samovar_mode_runtime();",
            "alarm_btn.tick();",
            "btn.tick();",
            "encoder.tick();",
            "process_buzzer();",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_samovar_setup_and_loop_are_minimal_wrappers(self) -> None:
        text = SAMOVAR_INO.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            re.compile(
                r"void setup\(\)\s*\{\s*samovar_app_setup\(\);\s*\}\s*"
                r"void loop\(\)\s*\{\s*samovar_app_loop\(\);\s*\}",
                re.MULTILINE | re.DOTALL,
            ),
        )
        self.assertNotIn('esp_log_level_set("i2c.master", ESP_LOG_NONE);', text)
        self.assertNotIn("process_sam_command_sync();", text)
        self.assertNotIn("dispatch_samovar_mode_runtime();", text)


if __name__ == "__main__":
    unittest.main()
