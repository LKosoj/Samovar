from pathlib import Path
import unittest


SENSORINIT_FILE = Path("sensorinit.h")
TASK_STACK_USAGE_HEADER = Path("support/task_stack_usage.h")
SEARCH_ROOTS = [
    Path("Samovar.ino"),
    Path("Blynk.ino"),
    Path("Samovar.h"),
    Path("app"),
    Path("io"),
    Path("modes"),
    Path("state"),
    Path("storage"),
    Path("support"),
    Path("ui"),
    Path("file_list.param"),
    Path("mkdocs.yml"),
]
ALLOWED_SUFFIXES = {"", ".h", ".ino", ".cpp", ".c", ".py", ".yml", ".param"}


class SensorinitRemovedTests(unittest.TestCase):
    def test_sensorinit_file_removed(self) -> None:
        self.assertFalse(SENSORINIT_FILE.exists(), "sensorinit.h must be removed")

    def test_task_stack_usage_module_exists_and_owns_debug_helper(self) -> None:
        self.assertTrue(TASK_STACK_USAGE_HEADER.exists(), "support/task_stack_usage.h must exist")
        text = TASK_STACK_USAGE_HEADER.read_text(encoding="utf-8")
        for snippet in [
            "inline void get_task_stack_usage()",
            'Serial.println(F("=== Task Stack Usage ==="));',
            'Serial.printf("SysTicker:        %u words free (of 3200)\\n", uxTaskGetStackHighWaterMark(SysTickerTask1));',
            'Serial.printf("GetClock:         %u words free (of 3400)\\n", uxTaskGetStackHighWaterMark(GetClockTask1));',
            'Serial.println(F("========================"));',
        ]:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, text)

    def test_repo_has_no_remaining_sensorinit_references(self) -> None:
        for root in SEARCH_ROOTS:
            if root.is_dir():
                files = [
                    path
                    for path in root.rglob("*")
                    if path.is_file() and path.suffix in ALLOWED_SUFFIXES
                ]
            else:
                files = [root]
            for path in files:
                with self.subTest(path=path.as_posix()):
                    text = path.read_text(encoding="utf-8")
                    self.assertNotIn("sensorinit.h", text)


if __name__ == "__main__":
    unittest.main()
