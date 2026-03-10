import unittest
from pathlib import Path


class WebTemplateKeysModuleTests(unittest.TestCase):
    def setUp(self):
        self.template_keys_path = Path("ui/web/template_keys.h")
        self.template_keys_text = self.template_keys_path.read_text(encoding="utf-8")
        self.server_init_path = Path("ui/web/server_init.h")
        self.server_init_text = self.server_init_path.read_text(encoding="utf-8")

    def test_template_keys_module_exists_with_processors(self):
        self.assertTrue(self.template_keys_path.exists(), "ui/web/template_keys.h must exist")
        expected_snippets = [
            "String indexKeyProcessor(const String &var)",
            "String setupKeyProcessor(const String &var)",
            "String wifiKeyProcessor(const String &var)",
            "String calibrateKeyProcessor(const String &var)",
            'if (var == "WProgram") {',
            'if (var == "wifi_ssid") {',
            'if (var == "StepperStep") return (String)STEPPER_MAX_SPEED;',
        ]
        for snippet in expected_snippets:
            self.assertIn(snippet, self.template_keys_text)

    def test_server_init_includes_template_keys_module(self):
        self.assertIn('#include "ui/web/template_keys.h"', self.server_init_text)

    def test_legacy_webserver_file_removed(self):
        self.assertFalse(Path("WebServer.ino").exists())


if __name__ == "__main__":
    unittest.main()
