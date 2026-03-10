from pathlib import Path
import unittest


class WebServerLegacyRemovalTest(unittest.TestCase):
    def test_legacy_webserver_file_removed(self) -> None:
        self.assertFalse(Path("WebServer.ino").exists())

    def test_server_init_module_is_present(self) -> None:
        text = Path("ui/web/server_init.h").read_text(encoding="utf-8")
        self.assertIn("void WebServerInit(void)", text)


if __name__ == "__main__":
    unittest.main()
