from pathlib import Path
import unittest


PROCESS_COMMON_HEADER = Path("app/process_common.h")
LOGIC_HEADER = Path("logic.h")
PROCESS_COMMON_USERS = [
    Path("logic.h"),
    Path("Samovar.ino"),
    Path("WebServer.ino"),
    Path("beer.h"),
    Path("distiller.h"),
    Path("BK.h"),
]


class ProcessCommonStructureTest(unittest.TestCase):
    def test_process_common_header_exists_and_defines_functions(self) -> None:
        self.assertTrue(PROCESS_COMMON_HEADER.exists(), "app/process_common.h must exist")
        text = PROCESS_COMMON_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline void stop_process(String reason)", text)
        self.assertIn("inline void start_self_test(void)", text)
        self.assertIn("inline void stop_self_test(void)", text)

    def test_logic_header_includes_process_common_header(self) -> None:
        text = LOGIC_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "app/process_common.h"', text)

    def test_process_common_definitions_removed_from_logic_header(self) -> None:
        text = LOGIC_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("void stop_process(String reason) {", text)
        self.assertNotIn("void start_self_test(void) {", text)
        self.assertNotIn("void stop_self_test(void) {", text)

    def test_process_common_users_include_header_directly(self) -> None:
        for path in PROCESS_COMMON_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "app/process_common.h"', text)


if __name__ == "__main__":
    unittest.main()
