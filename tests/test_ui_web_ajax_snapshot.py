import unittest
from pathlib import Path


AJAX_SNAPSHOT_HEADER = Path("ui/web/ajax_snapshot.h")
SAMOVAR_INO = Path("Samovar.ino")
SERVER_INIT = Path("ui/web/server_init.h")


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

    def test_server_init_includes_ajax_snapshot_header(self) -> None:
        text = SERVER_INIT.read_text(encoding="utf-8")
        self.assertIn('#include "ui/web/ajax_snapshot.h"', text)

    def test_samovar_no_longer_defines_ajax_snapshot_functions(self) -> None:
        text = SAMOVAR_INO.read_text(encoding="utf-8")
        for signature in [
            "static inline void jsonAddKey(Print &out, bool &first, const char *key) {",
            "static void jsonPrintEscaped(Print &out, const String &value) {",
            "void send_ajax_json(AsyncWebServerRequest *request) {",
        ]:
            self.assertNotIn(signature, text)

    def test_legacy_webserver_file_removed(self) -> None:
        self.assertFalse(Path("WebServer.ino").exists())


if __name__ == "__main__":
    unittest.main()
