import unittest
from pathlib import Path


class WebRoutesServiceModuleTests(unittest.TestCase):
    def setUp(self):
        self.routes_service_path = Path("ui/web/routes_service.h")
        self.routes_service_text = self.routes_service_path.read_text(encoding="utf-8")
        self.webserver_path = Path("WebServer.ino")
        self.webserver_text = self.webserver_path.read_text(encoding="utf-8")

    def test_routes_service_module_exists_with_service_handlers(self):
        self.assertTrue(self.routes_service_path.exists(), "ui/web/routes_service.h must exist")
        expected_snippets = [
            "inline void calibrate_command(AsyncWebServerRequest *request)",
            'request->hasArg("pump")',
            'request->hasArg("stpstep")',
            'sam_command_sync = CALIBRATE_START;',
            'sam_command_sync = CALIBRATE_STOP;',
            "SamSetup.StepperStepMlI2C = (uint16_t)round((float)done / 100.0f);",
            'request->send(200, "text/plain", "OK");',
            "inline void get_data_log(AsyncWebServerRequest *request, String fn)",
            'response = request->beginResponse(SPIFFS, "/" + fn, String(), true);',
            'response->addHeader(F("Content-Disposition"), "attachment; filename=\\"" + fn + "\\"");',
        ]
        for snippet in expected_snippets:
            self.assertIn(snippet, self.routes_service_text)

    def test_webserver_includes_routes_service_module_before_server_init(self):
        include = '#include "ui/web/routes_service.h"'
        server_init_include = '#include "ui/web/server_init.h"'
        self.assertIn(include, self.webserver_text)
        self.assertIn(server_init_include, self.webserver_text)
        self.assertLess(
            self.webserver_text.index(include),
            self.webserver_text.index(server_init_include),
        )

    def test_webserver_no_longer_defines_service_handlers_locally(self):
        self.assertNotIn("void calibrate_command(AsyncWebServerRequest *request) {", self.webserver_text)
        self.assertNotIn("void get_data_log(AsyncWebServerRequest *request, String fn) {", self.webserver_text)


if __name__ == "__main__":
    unittest.main()
