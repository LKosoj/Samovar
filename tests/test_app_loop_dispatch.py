import unittest
from pathlib import Path


LOOP_DISPATCH_HEADER = Path("app/loop_dispatch.h")
ORCHESTRATION_HEADER = Path("app/orchestration.h")
SAMOVAR_INO = Path("Samovar.ino")


class LoopDispatchHeaderTest(unittest.TestCase):
    def test_loop_dispatch_header_exists(self) -> None:
        self.assertTrue(LOOP_DISPATCH_HEADER.exists())

    def test_loop_dispatch_header_contains_moved_functions(self) -> None:
        text = LOOP_DISPATCH_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline void process_sam_command_sync()", text)
        self.assertIn("inline void dispatch_samovar_mode_runtime()", text)

    def test_samovar_includes_loop_dispatch_header(self) -> None:
        text = SAMOVAR_INO.read_text(encoding="utf-8")
        self.assertIn('#include "app/loop_dispatch.h"', text)
        self.assertIn('#include "app/orchestration.h"', text)

    def test_orchestration_uses_loop_dispatch_functions(self) -> None:
        text = ORCHESTRATION_HEADER.read_text(encoding="utf-8")
        self.assertIn("process_sam_command_sync();", text)
        self.assertIn("dispatch_samovar_mode_runtime();", text)

    def test_samovar_no_longer_contains_legacy_dispatch_blocks(self) -> None:
        text = SAMOVAR_INO.read_text(encoding="utf-8")
        self.assertNotIn("switch (sam_command_sync) {", text)
        self.assertNotIn("if (SamovarStatusInt > 0 && SamovarStatusInt < 1000) {", text)
        self.assertNotIn("process_sam_command_sync();", text)
        self.assertNotIn("dispatch_samovar_mode_runtime();", text)


if __name__ == "__main__":
    unittest.main()
