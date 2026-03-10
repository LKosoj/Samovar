from pathlib import Path
import unittest


DIST_RUNTIME_HEADER = Path("modes/dist/dist_runtime.h")
DIRECT_INCLUDE_USERS = (
    Path("app/runtime_tasks.h"),
    Path("app/loop_dispatch.h"),
    Path("app/orchestration.h"),
    Path("ui/web/ajax_snapshot.h"),
    Path("ui/web/routes_setup_process.h"),
)


class DistRuntimeExtractionTest(unittest.TestCase):
    def test_dist_runtime_header_exists(self) -> None:
        self.assertTrue(DIST_RUNTIME_HEADER.exists(), "modes/dist/dist_runtime.h must exist")

    def test_dist_runtime_header_contains_extracted_runtime(self) -> None:
        text = DIST_RUNTIME_HEADER.read_text(encoding="utf-8")
        for signature in [
            "inline void distiller_proc()",
            "inline void distiller_finish()",
            "inline void run_dist_program(uint8_t num)",
        ]:
            with self.subTest(signature=signature):
                self.assertIn(signature, text)

    def test_distiller_header_deleted(self) -> None:
        self.assertFalse(Path("distiller.h").exists())

    def test_direct_users_include_dist_runtime_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/dist/dist_runtime.h"', text)

    def test_runtime_header_no_longer_contains_alarm_or_predictor_logic(self) -> None:
        text = DIST_RUNTIME_HEADER.read_text(encoding="utf-8")
        for signature in [
            "inline void check_alarm_distiller()",
            "struct TimePredictor {",
            "inline void resetTimePredictor()",
            "inline void updateTimePredictor()",
            "inline float get_dist_remaining_time()",
            "inline float get_dist_predicted_total_time()",
        ]:
            with self.subTest(signature=signature):
                self.assertNotIn(signature, text)


if __name__ == "__main__":
    unittest.main()
