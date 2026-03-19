import unittest
from pathlib import Path


class WebRoutesProgramModuleTests(unittest.TestCase):
    def setUp(self):
        self.routes_program_path = Path("ui/web/routes_program.h")
        self.routes_program_text = self.routes_program_path.read_text(encoding="utf-8")
        self.server_init_path = Path("ui/web/server_init.h")
        self.server_init_text = self.server_init_path.read_text(encoding="utf-8")

    def test_routes_program_module_exists_with_web_program(self):
        self.assertTrue(self.routes_program_path.exists(), "ui/web/routes_program.h must exist")
        expected_snippets = [
            "inline void web_program(AsyncWebServerRequest *request)",
            'request->hasArg("WProgram")',
            'set_program_for_mode(Samovar_Mode, request->arg("WProgram"));',
            'get_program_for_mode(Samovar_Mode)',
            'BoilerVolume = request->arg("vless").toFloat();',
            "if (BoilerVolume <= 0) BoilerVolume = 30.0f;",
            "heatLossCalculated = false;",
            "heatStartMillis = 0;",
            'SessionDescription = request->arg("Descr");',
            'SessionDescription.replace("%", "&#37;");',
        ]
        for snippet in expected_snippets:
            self.assertIn(snippet, self.routes_program_text)

    def test_server_init_includes_routes_program_module(self):
        include = '#include "ui/web/routes_program.h"'
        self.assertIn(include, self.server_init_text)
        self.assertIn("web_program(request);", self.server_init_text)

    def test_legacy_webserver_file_removed(self):
        self.assertFalse(Path("WebServer.ino").exists())


if __name__ == "__main__":
    unittest.main()
