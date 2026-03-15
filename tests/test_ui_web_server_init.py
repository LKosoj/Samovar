import unittest
from pathlib import Path


class WebServerInitModuleTests(unittest.TestCase):
    def setUp(self):
        self.server_init_path = Path("ui/web/server_init.h")
        self.server_init_text = self.server_init_path.read_text(encoding="utf-8")
        self.orchestration_path = Path("app/orchestration.h")
        self.orchestration_text = self.orchestration_path.read_text(encoding="utf-8")

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
            'load_profile_nvs();',
            'DefaultHeaders::Instance().addHeader("Access-Control-Allow-Origin", "*");',
            'server.begin();',
        ]
        for snippet in expected_snippets:
            self.assertIn(snippet, self.server_init_text)

    def test_orchestration_includes_server_init_module(self):
        # Проверяем, что orchestration.h включает server_init.h
        self.assertIn('#include "ui/web/server_init.h"', self.orchestration_text)

    def test_legacy_webserver_file_removed(self):
        self.assertFalse(Path("WebServer.ino").exists())

    def test_server_init_includes_all_required_modules(self):
        # Проверяем, что server_init.h включает все необходимые модули
        required_modules = [
            '#include "ui/web/ajax_snapshot.h"',
            '#include "ui/web/page_assets.h"',
            '#include "ui/web/template_keys.h"',
            '#include "ui/web/routes_command.h"',
            '#include "ui/web/routes_program.h"',
            '#include "ui/web/routes_save.h"',
            '#include "ui/web/routes_service.h"',
            '#include "storage/web_assets_sync.h"',
        ]
        for module in required_modules:
            self.assertIn(module, self.server_init_text)

    def test_server_init_includes_FS_h(self):
        # Проверяем, что FS.h включён для доступа к функциям файловой системы
        self.assertIn('#include "FS.h"', self.server_init_text)

    def test_server_init_includes_storage_web_assets_sync_h(self):
        # Проверяем, что storage/web_assets_sync.h включён для доступа к функциям синхронизации
        self.assertIn('#include "storage/web_assets_sync.h"', self.server_init_text)

    def test_server_init_has_forward_declarations(self):
        # Проверяем, что есть необходимая forward declaration для change_samovar_mode
        # (остальные функции FS.ino доступны через Samovar.h и storage/web_assets_sync.h)
        self.assertIn('void change_samovar_mode();', self.server_init_text)

    def test_change_samovar_mode_defined(self):
        # Проверяем, что функция change_samovar_mode определена
        self.assertIn("void change_samovar_mode() {", self.server_init_text)
        self.assertIn('server.serveStatic("/index.htm", SPIFFS, "/beer.htm")', self.server_init_text)


if __name__ == "__main__":
    unittest.main()
