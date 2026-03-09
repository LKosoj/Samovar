import unittest
from pathlib import Path


RUNTIME_TASKS_HEADER = Path("app/runtime_tasks.h")
SAMOVAR_INO = Path("Samovar.ino")


class RuntimeTasksHeaderTest(unittest.TestCase):
    def test_runtime_tasks_header_exists(self) -> None:
        self.assertTrue(RUNTIME_TASKS_HEADER.exists())

    def test_runtime_tasks_header_contains_moved_functions(self) -> None:
        text = RUNTIME_TASKS_HEADER.read_text(encoding="utf-8")
        for signature in [
            "void stopService(void)",
            "void startService(void)",
            "void IRAM_ATTR StepperTicker(void)",
            "void IRAM_ATTR WFpulseCounter()",
            "void IRAM_ATTR isrWHLS_TICK()",
            "void triggerGetClock(void *parameter)",
            "void triggerSysTicker(void *parameter)",
        ]:
            self.assertIn(signature, text)

    def test_samovar_includes_runtime_tasks_header(self) -> None:
        text = SAMOVAR_INO.read_text(encoding="utf-8")
        self.assertIn('#include "app/runtime_tasks.h"', text)

    def test_samovar_no_longer_defines_runtime_tasks(self) -> None:
        text = SAMOVAR_INO.read_text(encoding="utf-8")
        for signature in [
            "void stopService(void) {",
            "void startService(void) {",
            "void IRAM_ATTR StepperTicker(void) {",
            "void IRAM_ATTR WFpulseCounter() {",
            "void IRAM_ATTR isrWHLS_TICK() {",
            "void triggerGetClock(void *parameter) {",
            "void triggerSysTicker(void *parameter) {",
        ]:
            self.assertNotIn(signature, text)


if __name__ == "__main__":
    unittest.main()
