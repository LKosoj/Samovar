import unittest
from pathlib import Path


class WebRoutesServiceModuleTests(unittest.TestCase):
    def setUp(self):
        self.routes_service_path = Path("ui/web/routes_service.h")
        self.routes_service_text = self.routes_service_path.read_text(encoding="utf-8")
        self.server_init_path = Path("ui/web/server_init.h")
        self.server_init_text = self.server_init_path.read_text(encoding="utf-8")

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

    def test_server_init_includes_routes_service_module(self):
        include = '#include "ui/web/routes_service.h"'
        self.assertIn(include, self.server_init_text)

    def test_server_init_calls_service_handlers(self):
        # Проверяем, что server_init.h вызывает сервисные обработчики
        self.assertIn('calibrate_command(request)', self.server_init_text)
        self.assertIn('get_data_log(request, "data.csv")', self.server_init_text)
        self.assertIn('get_data_log(request, "data_old.csv")', self.server_init_text)


if __name__ == "__main__":
    unittest.main()
