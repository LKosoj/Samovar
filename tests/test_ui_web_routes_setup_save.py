import unittest
from pathlib import Path


class TestUiWebRoutesSetupSave(unittest.TestCase):
    def test_new_route_setup_headers_exist(self) -> None:
        self.assertTrue(Path("ui/web/routes_setup_wifi.h").exists())
        self.assertTrue(Path("ui/web/routes_setup_process.h").exists())

    def test_wifi_helper_contains_network_setting_fields(self) -> None:
        text = Path("ui/web/routes_setup_wifi.h").read_text(encoding="utf-8")
        self.assertIn("void handleSaveWifiSettings(AsyncWebServerRequest *request)", text)
        for expected in [
            'request->hasArg("videourl")',
            'SamSetup.videourl',
            'request->hasArg("blynkauth")',
            'SamSetup.blynkauth',
            'request->hasArg("tgtoken")',
            'SamSetup.tg_token',
            'request->hasArg("tgchatid")',
            'SamSetup.tg_chat_id',
        ]:
            self.assertIn(expected, text)

    def test_process_helper_contains_mode_switch_flow(self) -> None:
        text = Path("ui/web/routes_setup_process.h").read_text(encoding="utf-8")
        self.assertIn("void handleSaveProcessSettings(AsyncWebServerRequest *request)", text)
        for expected in [
            'request->hasArg("mode")',
            'distiller_finish();',
            'beer_finish();',
            'bk_finish();',
            'nbk_finish();',
            'set_power(false);',
            'samovar_reset();',
            'load_default_program_for_mode();',
            'save_profile_nvs();',
            'load_profile_nvs();',
            'change_samovar_mode();',
        ]:
            self.assertIn(expected, text)

    def test_routes_save_module_exists_and_includes_helpers(self) -> None:
        # Проверяем, что routes_save.h существует и включает helper модули
        routes_save_path = Path("ui/web/routes_save.h")
        self.assertTrue(routes_save_path.exists(), "ui/web/routes_save.h must exist")
        text = routes_save_path.read_text(encoding="utf-8")
        self.assertIn('#include "ui/web/routes_setup_wifi.h"', text)
        self.assertIn('#include "ui/web/routes_setup_process.h"', text)
        self.assertIn('inline void handleSave(AsyncWebServerRequest *request)', text)

    def test_routes_save_contains_all_settings(self) -> None:
        # Проверяем, что handleSave содержит все настройки
        text = Path("ui/web/routes_save.h").read_text(encoding="utf-8")
        for expected in [
            'request->hasArg("SteamDelay")',
            'request->hasArg("DeltaSteamTemp")',
            'request->hasArg("SetSteamTemp")',
            'request->hasArg("Kp")',
            'request->hasArg("UseBuzzer")',
            'request->hasArg("rele1")',
            'handleSaveWifiSettings(request);',
            'handleSaveProcessSettings(request);',
            'save_profile_nvs();',
            'read_config();',
        ]:
            self.assertIn(expected, text)

    def test_server_init_includes_routes_save_module(self) -> None:
        # Проверяем, что server_init.h включает routes_save.h
        server_init_text = Path("ui/web/server_init.h").read_text(encoding="utf-8")
        self.assertIn('#include "ui/web/routes_save.h"', server_init_text)

    def test_routes_save_includes_required_headers(self) -> None:
        # Проверяем, что routes_save.h включает необходимые заголовки
        text = Path("ui/web/routes_save.h").read_text(encoding="utf-8")
        required_headers = [
            "#include <Arduino.h>",
            '#include "Samovar.h"',
            '#include "state/globals.h"',
            '#include "modes/bk/bk_water_control.h"',
        ]
        for header in required_headers:
            self.assertIn(header, text)


if __name__ == "__main__":
    unittest.main()
