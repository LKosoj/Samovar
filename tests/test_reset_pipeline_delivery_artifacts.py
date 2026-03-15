from pathlib import Path
import unittest


RESET_SPEC = Path("docs/result/delivery/reset_pipeline_spec.md")
REGRESSION_LOG = Path("docs/result/delivery/step2_regression_log.md")
BUILD_LOG = Path("docs/result/delivery/step2_builds.md")
RESET_TEST = Path("tools/tests/test_reset_pipeline_invariant.py")


class ResetPipelineDeliveryArtifactsTest(unittest.TestCase):
    def test_delivery_artifacts_exist(self) -> None:
        for path in [RESET_SPEC, REGRESSION_LOG, BUILD_LOG, RESET_TEST]:
            with self.subTest(path=path.as_posix()):
                self.assertTrue(path.exists(), f"{path} must exist")

    def test_reset_pipeline_spec_covers_full_pipeline(self) -> None:
        text = RESET_SPEC.read_text(encoding="utf-8")
        required_tokens = [
            "# Шаг 2.4. Reset Pipeline Spec",
            "Runtime reset",
            "Menu/UI reset",
            "Full mode-switch reset",
            "Command-triggered reset",
            "Power / stepper / I2C pump cleanup",
            "Lua state reset",
            "Profile save/load sequence",
            "Route rebinding",
            "handleSaveProcessSettings()",
            "samovar_reset()",
            "reset_sensor_counter()",
            "change_samovar_mode()",
            "save_profile_nvs()",
            "load_profile_nvs()",
        ]
        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_regression_log_contains_explicit_pass_and_scenarios(self) -> None:
        text = REGRESSION_LOG.read_text(encoding="utf-8")
        required_tokens = [
            "Reset pipeline invariant test",
            "dist_to_beer|ok|target=/beer.htm|save_load=1/1|route_rebind=1/1",
            "beer_to_bk|ok|target=/bk.htm|save_load=1/1|route_rebind=1/1",
            "bk_to_nbk|ok|target=/nbk.htm|save_load=1/1|route_rebind=1/1",
            "nbk_to_rect|ok|target=/index.htm|save_load=1/1|route_rebind=1/1",
            "rect_to_dist|ok|target=/distiller.htm|save_load=1/1|route_rebind=1/1",
            "same_mode_noop|ok|route_unchanged=1",
            "reset_pipeline_invariant|ok",
            "Reset pipeline invariant: PASS",
        ]
        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_build_log_contains_subtask_2_4_success_evidence(self) -> None:
        text = BUILD_LOG.read_text(encoding="utf-8")
        required_tokens = [
            "## Подзадача 2.4",
            "- Команда: `pio run -e Samovar`",
            "- Результат: `SUCCESS`",
            "- Длительность: `00:00:23.020`",
            "- RAM: `18.3% (59904 / 327680 bytes)`",
            "- Flash: `70.1% (1148721 / 1638400 bytes)`",
            "### Raw build excerpt",
            "[SUCCESS] Took 23.02 seconds",
            "Samovar        SUCCESS   00:00:23.020",
            "1 succeeded in 00:00:23.020",
        ]
        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_reset_pipeline_test_file_has_explicit_invariant_checks(self) -> None:
        text = RESET_TEST.read_text(encoding="utf-8")
        required_tokens = [
            "state_inventory.parse_enum(\"SAMOVAR_MODE\")",
            "state_inventory.parse_enum(\"SamovarCommands\")",
            "Verifying explicit web mode-switch reset order",
            "Verifying reset_sensor_counter() runtime cleanup set",
            "dist_to_beer",
            "beer_to_bk",
            "bk_to_nbk",
            "nbk_to_rect",
            "rect_to_dist",
            "same_mode_noop",
            "reset_pipeline_invariant|ok",
        ]
        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
