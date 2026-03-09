import unittest
from pathlib import Path


class WebTemplateKeysModuleTests(unittest.TestCase):
    def setUp(self):
        self.template_keys_path = Path("ui/web/template_keys.h")
        self.template_keys_text = self.template_keys_path.read_text(encoding="utf-8")
        self.webserver_path = Path("WebServer.ino")
        self.webserver_text = self.webserver_path.read_text(encoding="utf-8")

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

    def test_webserver_ino_includes_template_keys_module(self):
        self.assertIn('#include "ui/web/template_keys.h"', self.webserver_text)

    def test_webserver_ino_no_longer_defines_template_processors_locally(self):
        forbidden_snippets = [
            "String indexKeyProcessor(const String &var) {",
            "String setupKeyProcessor(const String &var) {",
            "String wifiKeyProcessor(const String &var) {",
            "String calibrateKeyProcessor(const String &var) {",
        ]
        for snippet in forbidden_snippets:
            self.assertNotIn(snippet, self.webserver_text)


if __name__ == "__main__":
    unittest.main()
