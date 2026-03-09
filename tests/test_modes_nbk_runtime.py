from pathlib import Path
import unittest


NBK_RUNTIME_HEADER = Path("modes/nbk/nbk_runtime.h")
DIRECT_INCLUDE_USERS = (
    Path("app/loop_dispatch.h"),
)


class NbkRuntimeExtractionTest(unittest.TestCase):
    def test_nbk_runtime_header_exists(self) -> None:
        self.assertTrue(NBK_RUNTIME_HEADER.exists(), "modes/nbk/nbk_runtime.h must exist")

    def test_nbk_runtime_header_contains_extracted_runtime(self) -> None:
        text = NBK_RUNTIME_HEADER.read_text(encoding="utf-8")
        for signature in [
            "inline void nbk_proc()",
            "inline void handle_nbk_stage_heatup()",
            "inline void handle_nbk_stage_manual()",
            "inline void handle_nbk_stage_optimization()",
            "inline void handle_nbk_stage_work()",
            "inline void run_nbk_program(uint8_t num)",
            "inline bool check_nbk_critical_alarms()",
            "inline void handle_overflow(const String& msg, bool finish, uint32_t pause_ms)",
        ]:
            with self.subTest(signature=signature):
                self.assertIn(signature, text)

    def test_direct_users_include_nbk_runtime_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/nbk/nbk_runtime.h"', text)

    def test_legacy_nbk_header_removed(self) -> None:
        self.assertFalse(Path("nbk.h").exists())


if __name__ == "__main__":
    unittest.main()
