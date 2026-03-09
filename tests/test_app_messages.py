import unittest
from pathlib import Path


MESSAGES_HEADER = Path("app/messages.h")
SAMOVAR_INO = Path("Samovar.ino")


class MessagesHeaderTest(unittest.TestCase):
    def test_messages_header_exists(self) -> None:
        self.assertTrue(MESSAGES_HEADER.exists())

    def test_messages_header_contains_moved_functions(self) -> None:
        text = MESSAGES_HEADER.read_text(encoding="utf-8")
        self.assertIn("void SendMsg(const String& m, MESSAGE_TYPE msg_type)", text)
        self.assertIn("void WriteConsoleLog(String StringLogMsg)", text)

    def test_samovar_includes_messages_header(self) -> None:
        text = SAMOVAR_INO.read_text(encoding="utf-8")
        self.assertIn('#include "app/messages.h"', text)

    def test_samovar_no_longer_defines_messages(self) -> None:
        text = SAMOVAR_INO.read_text(encoding="utf-8")
        self.assertNotIn("void SendMsg(const String& m, MESSAGE_TYPE msg_type) {", text)
        self.assertNotIn("void WriteConsoleLog(String StringLogMsg) {", text)


if __name__ == "__main__":
    unittest.main()
