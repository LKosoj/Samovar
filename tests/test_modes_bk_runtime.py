from pathlib import Path
import unittest


BK_RUNTIME_HEADER = Path("modes/bk/bk_runtime.h")
BK_HEADER = Path("BK.h")
DIRECT_INCLUDE_USERS = (
    Path("Samovar.ino"),
    Path("app/loop_dispatch.h"),
)


class BkRuntimeExtractionTest(unittest.TestCase):
    def test_bk_runtime_header_exists(self) -> None:
        self.assertTrue(BK_RUNTIME_HEADER.exists(), "modes/bk/bk_runtime.h must exist")

    def test_bk_runtime_header_contains_extracted_runtime(self) -> None:
        text = BK_RUNTIME_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline void bk_proc()", text)

    def test_direct_users_include_bk_runtime_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/bk/bk_runtime.h"', text)

    def test_bk_header_no_longer_contains_runtime(self) -> None:
        text = BK_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("void bk_proc() {", text)


if __name__ == "__main__":
    unittest.main()
