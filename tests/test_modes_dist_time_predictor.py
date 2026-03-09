from pathlib import Path
import unittest


DIST_TIME_PREDICTOR_HEADER = Path("modes/dist/dist_time_predictor.h")
DIST_RUNTIME_HEADER = Path("modes/dist/dist_runtime.h")
DIRECT_INCLUDE_USERS = (
    Path("modes/dist/dist_runtime.h"),
    Path("ui/web/ajax_snapshot.h"),
    Path("distiller.h"),
)


class DistTimePredictorExtractionTest(unittest.TestCase):
    def test_dist_time_predictor_header_exists(self) -> None:
        self.assertTrue(DIST_TIME_PREDICTOR_HEADER.exists(), "modes/dist/dist_time_predictor.h must exist")

    def test_dist_time_predictor_header_contains_extracted_predictor(self) -> None:
        text = DIST_TIME_PREDICTOR_HEADER.read_text(encoding="utf-8")
        for signature in [
            "struct TimePredictor {",
            "extern TimePredictor timePredictor;",
            "inline void resetTimePredictor()",
            "inline void updateTimePredictor()",
            "inline float get_dist_remaining_time()",
            "inline float get_dist_predicted_total_time()",
        ]:
            with self.subTest(signature=signature):
                self.assertIn(signature, text)

    def test_direct_users_include_dist_time_predictor_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/dist/dist_time_predictor.h"', text)

    def test_dist_runtime_header_no_longer_defines_predictor_logic(self) -> None:
        text = DIST_RUNTIME_HEADER.read_text(encoding="utf-8")
        for signature in [
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
