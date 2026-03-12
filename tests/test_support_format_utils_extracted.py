from pathlib import Path
import unittest


FORMAT_UTILS_HEADER = Path("support/format_utils.h")
SENSORINIT_FILE = Path("sensorinit.h")

FORMER_DECLARATION_FILES = [
    Path("app/status_text.h"),
    Path("storage/session_logs.h"),
    Path("io/actuators.h"),
    Path("ui/web/ajax_snapshot.h"),
    Path("modes/rect/rect_runtime.h"),
]


class FormatUtilsExtractionTests(unittest.TestCase):
    def test_format_utils_module_exists_and_owns_format_float(self) -> None:
        self.assertTrue(FORMAT_UTILS_HEADER.exists(), "support/format_utils.h must exist")

        header_text = FORMAT_UTILS_HEADER.read_text(encoding="utf-8")
        for snippet in [
            "inline String format_float(float v, int d)",
            "char outstr[15];",
            "dtostrf(v, 1, d, outstr);",
            "return outstr;",
        ]:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, header_text)

    def test_sensorinit_legacy_file_is_removed(self) -> None:
        self.assertFalse(SENSORINIT_FILE.exists(), "sensorinit.h must be removed")

    def test_former_consumers_no_longer_keep_local_declarations(self) -> None:
        for path in FORMER_DECLARATION_FILES:
            with self.subTest(path=str(path)):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("String format_float(float v, int d);", text)
                self.assertNotIn("inline String format_float(float v, int d);", text)


if __name__ == "__main__":
    unittest.main()
