import unittest
from pathlib import Path


class WebRoutesCommandModuleTests(unittest.TestCase):
    def setUp(self):
        self.routes_command_path = Path("ui/web/routes_command.h")
        self.routes_command_text = self.routes_command_path.read_text(encoding="utf-8")
        self.server_init_path = Path("ui/web/server_init.h")
        self.server_init_text = self.server_init_path.read_text(encoding="utf-8")

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

    def test_server_init_includes_routes_command_module(self):
        self.assertIn('#include "ui/web/routes_command.h"', self.server_init_text)

    def test_routes_command_includes_required_headers(self):
        # Проверяем, что все необходимые заголовки включены
        required_headers = [
            "#include <Arduino.h>",
            '#include "Samovar.h"',
            '#include "state/globals.h"',
            '#include "modes/bk/bk_water_control.h"',
            '#include "io/actuators.h"',
            '#include "io/sensors.h"',
        ]
        for header in required_headers:
            self.assertIn(header, self.routes_command_text)

    def test_routes_command_has_forward_declarations(self):
        # Проверяем, что есть forward declarations для функций
        required_declarations = [
            "void menu_reset_wifi();",
            "void set_mixer(bool On);",
            "uint16_t get_stepper_speed(void);",
            "uint32_t get_stepper_status(void);",
            "bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target);",
            "float i2c_get_speed_from_rate(float volume_per_hour);",
            "void set_pump_speed(float pumpspeed, bool continue_process);",
        ]
        for decl in required_declarations:
            self.assertIn(decl, self.routes_command_text)

        self.assertNotIn("void scan_ds_adress();", self.routes_command_text)

    def test_routes_command_calls_web_command_from_server_init(self):
        # Проверяем, что server_init.h вызывает web_command
        self.assertIn('web_command(request)', self.server_init_text)


if __name__ == "__main__":
    unittest.main()
