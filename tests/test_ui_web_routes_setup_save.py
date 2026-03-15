import unittest
from pathlib import Path


class TestUiWebRoutesSetupSave(unittest.TestCase):
    def test_routes_setup_header_exists(self) -> None:
        self.assertTrue(Path("ui/web/routes_setup.h").exists())

    def test_routes_setup_contains_network_setting_helper(self) -> None:
        text = Path("ui/web/routes_setup.h").read_text(encoding="utf-8")
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

    def test_routes_setup_contains_process_switch_flow(self) -> None:
        text = Path("ui/web/routes_setup.h").read_text(encoding="utf-8")
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

    def test_routes_setup_contains_handle_save(self) -> None:
        text = Path("ui/web/routes_setup.h").read_text(encoding="utf-8")
        self.assertIn('inline void handleSave(AsyncWebServerRequest *request)', text)

    def test_routes_setup_contains_all_settings(self) -> None:
        text = Path("ui/web/routes_setup.h").read_text(encoding="utf-8")
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

    def test_server_init_includes_routes_setup_module(self) -> None:
        server_init_text = Path("ui/web/server_init.h").read_text(encoding="utf-8")
        self.assertIn('#include "ui/web/routes_setup.h"', server_init_text)

    def test_routes_setup_includes_required_headers(self) -> None:
        text = Path("ui/web/routes_setup.h").read_text(encoding="utf-8")
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
