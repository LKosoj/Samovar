import unittest
from pathlib import Path


class WebServerInitModuleTests(unittest.TestCase):
    def setUp(self):
        self.server_init_path = Path("ui/web/server_init.h")
        self.server_init_text = self.server_init_path.read_text(encoding="utf-8")
        self.webserver_path = Path("WebServer.ino")
        self.webserver_text = self.webserver_path.read_text(encoding="utf-8")

    def test_server_init_module_exists_with_route_registration(self):
        self.assertTrue(self.server_init_path.exists(), "ui/web/server_init.h must exist")
        expected_snippets = [
            "void WebServerInit(void)",
            'server.on("/", HTTP_GET | HTTP_POST',
            'server.on("/ajax", HTTP_GET',
            'server.on("/command", HTTP_GET, [](AsyncWebServerRequest *request) {',
            "web_command(request);",
            'server.on("/program", HTTP_POST, [](AsyncWebServerRequest *request) {',
            "web_program(request);",
            'server.on("/save", HTTP_POST, [](AsyncWebServerRequest *request) {',
            "handleSave(request);",
            'server.on("/wifi/save", HTTP_POST',
            'change_samovar_mode();',
            'load_profile();',
            'DefaultHeaders::Instance().addHeader("Access-Control-Allow-Origin", "*");',
            'server.begin();',
        ]
        for snippet in expected_snippets:
            self.assertIn(snippet, self.server_init_text)

    def test_webserver_ino_includes_new_server_init_module(self):
        self.assertIn('#include "ui/web/server_init.h"', self.webserver_text)

    def test_webserver_ino_no_longer_defines_webserverinit_locally(self):
        self.assertNotIn("void WebServerInit(void) {", self.webserver_text)


if __name__ == "__main__":
    unittest.main()
