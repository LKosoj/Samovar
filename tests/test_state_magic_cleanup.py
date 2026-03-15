from pathlib import Path
import unittest

from tools import state_magic_cleanup


MAGIC_CLEANUP_LOG = Path("docs/result/delivery/magic_cleanup_log.md")
STATUS_CODES_HEADER = Path("src/core/state/status_codes.h")
MODE_CODES_HEADER = Path("src/core/state/mode_codes.h")


class StateMagicCleanupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.audit = state_magic_cleanup.build_audit()
        cls.rendered_log = state_magic_cleanup.render_magic_cleanup_log(cls.audit)

    def test_delivery_log_matches_generated_audit(self) -> None:
        self.assertTrue(MAGIC_CLEANUP_LOG.exists(), "magic_cleanup_log.md must exist")
        self.assertEqual(MAGIC_CLEANUP_LOG.read_text(encoding="utf-8"), self.rendered_log)

    def test_raw_numeric_literal_matches_are_absent(self) -> None:
        for variable, matches in self.audit["raw_matches"].items():
            with self.subTest(variable=variable):
                self.assertEqual(matches, [])

    def test_state_headers_define_semantic_helper_predicates(self) -> None:
        status_text = STATUS_CODES_HEADER.read_text(encoding="utf-8")
        mode_text = MODE_CODES_HEADER.read_text(encoding="utf-8")
        for token in [
            "samovar_status_is_rectification",
            "samovar_status_allows_rectification_withdrawal",
            "samovar_status_has_rectification_program_progress",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, status_text)
        for token in [
            "startval_is_rect_program_state",
            "startval_is_active_non_calibration",
            "startval_is_beer_program_started",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, mode_text)

    def test_critical_transition_logic_uses_semantic_helpers(self) -> None:
        expectations = {
            "app/loop_dispatch.h": ["samovar_status_is_rectification(SamovarStatusInt)"],
            "app/orchestration.h": ["samovar_status_is_rectification(SamovarStatusInt)"],
            "io/actuators.h": ["samovar_status_allows_rectification_withdrawal(SamovarStatusInt)"],
            "modes/rect/rect_runtime.h": ["samovar_status_allows_rectification_withdrawal(SamovarStatusInt)"],
            "ui/menu/actions.h": ["startval_is_active_non_calibration(startval)"],
            "Blynk.ino": ["startval_is_rect_program_state(startval)"],
            "modes/beer/beer_runtime.h": ["startval_is_beer_program_started(startval)"],
        }
        for raw_path, tokens in expectations.items():
            text = Path(raw_path).read_text(encoding="utf-8")
            for token in tokens:
                with self.subTest(path=raw_path, token=token):
                    self.assertIn(token, text)

    def test_log_mentions_helper_call_sites_and_clean_result(self) -> None:
        text = MAGIC_CLEANUP_LOG.read_text(encoding="utf-8")
        for token in [
            "# Step 2.5 magic number cleanup audit",
            "## Raw numeric literal matches for SamovarStatusInt",
            "## Raw numeric literal matches for startval",
            "## Named semantic helper call sites",
            "## samovar_status_is_rectification",
            "## samovar_status_allows_rectification_withdrawal",
            "## samovar_status_has_rectification_program_progress",
            "## startval_is_rect_program_state",
            "## startval_is_active_non_calibration",
            "## startval_is_beer_program_started",
            "_No raw numeric literal matches found._",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
