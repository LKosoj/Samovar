import unittest
from pathlib import Path


class WebRoutesProgramModuleTests(unittest.TestCase):
    def setUp(self):
        self.routes_program_path = Path("ui/web/routes_program.h")
        self.routes_program_text = self.routes_program_path.read_text(encoding="utf-8")
        self.webserver_path = Path("WebServer.ino")
        self.webserver_text = self.webserver_path.read_text(encoding="utf-8")

    def test_routes_program_module_exists_with_web_program(self):
        self.assertTrue(self.routes_program_path.exists(), "ui/web/routes_program.h must exist")
        expected_snippets = [
            "inline void web_program(AsyncWebServerRequest *request)",
            'request->hasArg("WProgram")',
            'set_beer_program(request->arg("WProgram"));',
            'set_dist_program(request->arg("WProgram"));',
            'set_nbk_program(request->arg("WProgram"));',
            'set_program(request->arg("WProgram"));',
            'BoilerVolume = request->arg("vless").toFloat();',
            "if (BoilerVolume <= 0) BoilerVolume = 30.0f;",
            "heatLossCalculated = false;",
            "heatStartMillis = 0;",
            'SessionDescription = request->arg("Descr");',
            'SessionDescription.replace("%", "&#37;");',
        ]
        for snippet in expected_snippets:
            self.assertIn(snippet, self.routes_program_text)

    def test_webserver_includes_routes_program_module_before_server_init(self):
        include = '#include "ui/web/routes_program.h"'
        server_init_include = '#include "ui/web/server_init.h"'
        self.assertIn(include, self.webserver_text)
        self.assertIn(server_init_include, self.webserver_text)
        self.assertLess(
            self.webserver_text.index(include),
            self.webserver_text.index(server_init_include),
        )

    def test_webserver_no_longer_defines_web_program_locally(self):
        self.assertNotIn("void web_program(AsyncWebServerRequest *request) {", self.webserver_text)


if __name__ == "__main__":
    unittest.main()
