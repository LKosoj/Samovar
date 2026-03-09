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
            'save_profile();',
            'load_profile();',
            'change_samovar_mode();',
        ]:
            self.assertIn(expected, text)

    def test_webserver_uses_new_helpers(self) -> None:
        text = Path("WebServer.ino").read_text(encoding="utf-8")
        self.assertIn('#include "ui/web/routes_setup_wifi.h"', text)
        self.assertIn('#include "ui/web/routes_setup_process.h"', text)
        self.assertIn('handleSaveWifiSettings(request);', text)
        self.assertIn('handleSaveProcessSettings(request);', text)
        self.assertNotIn('copyStringSafe(SamSetup.videourl, request->arg("videourl"));', text)
        self.assertNotIn('SamSetup.Mode != request->arg("mode").toInt()', text)


if __name__ == "__main__":
    unittest.main()
