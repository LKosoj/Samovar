import unittest
from pathlib import Path


AJAX_SNAPSHOT_HEADER = Path("ui/web/ajax_snapshot.h")
SAMOVAR_INO = Path("Samovar.ino")
WEBSERVER_INO = Path("WebServer.ino")


class AjaxSnapshotHeaderTest(unittest.TestCase):
    def test_ajax_snapshot_header_exists(self) -> None:
        self.assertTrue(AJAX_SNAPSHOT_HEADER.exists())

    def test_ajax_snapshot_header_contains_moved_functions(self) -> None:
        text = AJAX_SNAPSHOT_HEADER.read_text(encoding="utf-8")
        for signature in [
            "static inline void jsonAddKey(Print &out, bool &first, const char *key)",
            "static inline void jsonPrintEscaped(Print &out, const String &value)",
            "void send_ajax_json(AsyncWebServerRequest *request)",
        ]:
            self.assertIn(signature, text)

    def test_samovar_includes_ajax_snapshot_header(self) -> None:
        text = SAMOVAR_INO.read_text(encoding="utf-8")
        self.assertIn('#include "ui/web/ajax_snapshot.h"', text)

    def test_webserver_includes_ajax_snapshot_header(self) -> None:
        text = WEBSERVER_INO.read_text(encoding="utf-8")
        self.assertIn('#include "ui/web/ajax_snapshot.h"', text)

    def test_samovar_no_longer_defines_ajax_snapshot_functions(self) -> None:
        text = SAMOVAR_INO.read_text(encoding="utf-8")
        for signature in [
            "static inline void jsonAddKey(Print &out, bool &first, const char *key) {",
            "static void jsonPrintEscaped(Print &out, const String &value) {",
            "void send_ajax_json(AsyncWebServerRequest *request) {",
        ]:
            self.assertNotIn(signature, text)

    def test_webserver_no_longer_declares_send_ajax_json_manually(self) -> None:
        text = WEBSERVER_INO.read_text(encoding="utf-8")
        self.assertNotIn("void send_ajax_json(AsyncWebServerRequest *request);", text)


if __name__ == "__main__":
    unittest.main()
