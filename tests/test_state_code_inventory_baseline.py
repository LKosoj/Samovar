from pathlib import Path
import unittest

from tools import state_inventory


STATE_CODES_DOC = Path("docs/result/delivery/state_codes_inventory.md")
GREP_LOG_DOC = Path("docs/result/delivery/state_inventory_grep_log.md")


class StateCodeInventoryBaselineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = state_inventory.build_inventory()
        cls.rendered_state_doc = state_inventory.render_state_codes_inventory(cls.inventory)
        cls.rendered_grep_log = state_inventory.render_state_inventory_grep_log(cls.inventory)

    def test_delivery_docs_exist(self) -> None:
        self.assertTrue(STATE_CODES_DOC.exists(), "state_codes_inventory.md must exist")
        self.assertTrue(GREP_LOG_DOC.exists(), "state_inventory_grep_log.md must exist")

    def test_state_doc_matches_generated_inventory(self) -> None:
        self.assertEqual(STATE_CODES_DOC.read_text(encoding="utf-8"), self.rendered_state_doc)

    def test_grep_log_matches_generated_inventory(self) -> None:
        self.assertEqual(GREP_LOG_DOC.read_text(encoding="utf-8"), self.rendered_grep_log)

    def test_status_and_startval_baseline_values_are_fixed(self) -> None:
        self.assertEqual(
            list(self.inventory["status_values"]),
            [0, 10, 15, 20, 30, 40, 50, 51, 52, 1000, 2000, 3000, 4000],
        )
        self.assertEqual(
            list(self.inventory["start_values"]),
            [0, 1, 2, 3, 100, 1000, 2000, 2001, 2002, 3000, 4000, 4001],
        )

    def test_command_and_mode_numeric_contracts_are_fixed(self) -> None:
        self.assertEqual(
            self.inventory["command_enum"],
            {
                "SAMOVAR_NONE": 0,
                "SAMOVAR_START": 1,
                "SAMOVAR_POWER": 2,
                "SAMOVAR_RESET": 3,
                "CALIBRATE_START": 4,
                "CALIBRATE_STOP": 5,
                "SAMOVAR_PAUSE": 6,
                "SAMOVAR_CONTINUE": 7,
                "SAMOVAR_SETBODYTEMP": 8,
                "SAMOVAR_DISTILLATION": 9,
                "SAMOVAR_BEER": 10,
                "SAMOVAR_BEER_NEXT": 11,
                "SAMOVAR_BK": 12,
                "SAMOVAR_NBK": 13,
                "SAMOVAR_SELF_TEST": 14,
                "SAMOVAR_DIST_NEXT": 15,
                "SAMOVAR_NBK_NEXT": 16,
            },
        )
        self.assertEqual(
            self.inventory["mode_enum"],
            {
                "SAMOVAR_RECTIFICATION_MODE": 0,
                "SAMOVAR_DISTILLATION_MODE": 1,
                "SAMOVAR_BEER_MODE": 2,
                "SAMOVAR_BK_MODE": 3,
                "SAMOVAR_NBK_MODE": 4,
                "SAMOVAR_SUVID_MODE": 5,
                "SAMOVAR_LUA_MODE": 6,
            },
        )

    def test_docs_cover_required_tokens(self) -> None:
        state_doc = STATE_CODES_DOC.read_text(encoding="utf-8")
        grep_doc = GREP_LOG_DOC.read_text(encoding="utf-8")
        for token in [
            "# Шаг 2.1. Инвентаризация state-кодов Samovar",
            "## SamovarStatusInt",
            "## startval",
            "## sam_command_sync",
            "## Samovar_Mode",
            "## Samovar_CR_Mode",
            "## Связанные флаги",
            "`4001`",
            "`SAMOVAR_NBK_NEXT`",
            "`SAMOVAR_LUA_MODE`",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, state_doc)
        for token in [
            "## SamovarStatusInt",
            "## sam_command_sync",
            "## Samovar_CR_Mode",
            "## program_Pause",
            "## SAMOVAR_RESET",
            "## SAMOVAR_SUVID_MODE",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, grep_doc)


if __name__ == "__main__":
    unittest.main()
