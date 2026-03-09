import unittest
from pathlib import Path


class WebRoutesCommandModuleTests(unittest.TestCase):
    def setUp(self):
        self.routes_command_path = Path("ui/web/routes_command.h")
        self.routes_command_text = self.routes_command_path.read_text(encoding="utf-8")
        self.webserver_path = Path("WebServer.ino")
        self.webserver_text = self.webserver_path.read_text(encoding="utf-8")

    def test_routes_command_module_exists_with_web_command(self):
        self.assertTrue(self.routes_command_path.exists(), "ui/web/routes_command.h must exist")
        expected_snippets = [
            "inline void web_command(AsyncWebServerRequest *request)",
            "static uint32_t last_command_time = 0;",
            "if (millis() - last_command_time < 1500) {",
            'if (request->hasArg("start") && PowerOn) {',
            'request->hasArg("power")',
            'request->hasArg("setbodytemp")',
            'request->hasArg("mixer")',
            'request->hasArg("pnbk") && PowerOn',
            'request->hasArg("nbkopt") && PowerOn',
            'request->hasArg("watert")',
            'request->hasArg("pumpspeed")',
            'request->hasArg("pause")',
            'request->send(200, "text/plain", "OK");',
        ]
        for snippet in expected_snippets:
            self.assertIn(snippet, self.routes_command_text)

    def test_webserver_includes_routes_command_module(self):
        self.assertIn('#include "ui/web/routes_command.h"', self.webserver_text)

    def test_webserver_no_longer_defines_web_command_locally(self):
        self.assertNotIn("void web_command(AsyncWebServerRequest *request) {", self.webserver_text)


if __name__ == "__main__":
    unittest.main()
