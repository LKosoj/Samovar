"""Baseline UI smoke tests for Samovar web interface.

Uses mock server + playwright-cli to verify that all pages render
correctly with expected elements. This is the baseline for Step 4
UI refactoring — any changes must pass these tests.
"""

import json
import subprocess
import time
import unittest
from pathlib import Path

MOCK_PORT = 8033
BASE_URL = f"http://localhost:{MOCK_PORT}"
SCREENSHOT_DIR = Path("docs/result/delivery/baseline_screenshots")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _cli(*args):
    """Run playwright-cli command and return stdout."""
    result = subprocess.run(
        ["playwright-cli", *args],
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout


class MockServerMixin:
    """Start/stop mock server for the test suite."""
    server_proc = None

    @classmethod
    def start_server(cls):
        cls.server_proc = subprocess.Popen(
            ["python3", str(PROJECT_ROOT / "tests/web/mock_server.py"), str(MOCK_PORT)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        # Wait for server to be ready
        for _ in range(20):
            try:
                subprocess.check_output(
                    ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                     f"{BASE_URL}/ajax"],
                    timeout=2,
                )
                return
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                time.sleep(0.3)
        raise RuntimeError("Mock server did not start")

    @classmethod
    def stop_server(cls):
        if cls.server_proc:
            cls.server_proc.terminate()
            cls.server_proc.wait(timeout=5)
            cls.server_proc = None


class SamovarUIBaselineTest(MockServerMixin, unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.start_server()
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        _cli("open", BASE_URL + "/index.htm")
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        _cli("close")
        cls.stop_server()

    def _goto_and_wait(self, page):
        _cli("goto", f"{BASE_URL}/{page}")
        time.sleep(1)

    def _screenshot(self, name):
        _cli("screenshot", f"--filename={SCREENSHOT_DIR}/{name}.png")

    def _has_element(self, element_id):
        out = _cli("eval", f"!!document.getElementById('{element_id}')")
        return "true" in out.lower()

    def _get_title(self):
        out = _cli("eval", "document.title")
        return out

    # === Mode pages: structural checks ===

    def test_index_page_renders_with_temperatures(self):
        self._goto_and_wait("index.htm")
        self._screenshot("mode_rect")
        self.assertTrue(self._has_element("SteamTemp"), "SteamTemp element missing")
        self.assertTrue(self._has_element("PipeTemp"), "PipeTemp element missing")
        self.assertTrue(self._has_element("WaterTemp"), "WaterTemp element missing")
        self.assertTrue(self._has_element("Status"), "Status element missing")
        self.assertTrue(self._has_element("power"), "power button missing")

    def test_beer_page_renders_with_temperatures(self):
        self._goto_and_wait("beer.htm")
        self._screenshot("mode_beer")
        self.assertTrue(self._has_element("SteamTemp"), "SteamTemp element missing")
        self.assertTrue(self._has_element("Status"), "Status element missing")

    def test_distiller_page_renders(self):
        self._goto_and_wait("distiller.htm")
        self._screenshot("mode_dist")
        self.assertTrue(self._has_element("SteamTemp"), "SteamTemp element missing")
        self.assertTrue(self._has_element("Status"), "Status element missing")

    def test_nbk_page_renders(self):
        self._goto_and_wait("nbk.htm")
        self._screenshot("mode_nbk")
        self.assertTrue(self._has_element("SteamTemp"), "SteamTemp element missing")
        self.assertTrue(self._has_element("Status"), "Status element missing")

    def test_bk_page_renders(self):
        self._goto_and_wait("bk.htm")
        self._screenshot("mode_bk")
        self.assertTrue(self._has_element("SteamTemp"), "SteamTemp element missing")

    def test_setup_page_renders_with_form_fields(self):
        self._goto_and_wait("setup.htm")
        self._screenshot("setup")
        title = self._get_title()
        self.assertIn("Самовар", title)

    def test_program_page_renders(self):
        self._goto_and_wait("program.htm")
        self._screenshot("program")
        title = self._get_title()
        self.assertIn("Самовар", title)

    def test_chart_page_renders(self):
        self._goto_and_wait("chart.htm")
        self._screenshot("chart")
        title = self._get_title()
        self.assertIn("Самовар", title)

    # === AJAX data flow ===

    def test_ajax_endpoint_returns_valid_json(self):
        result = subprocess.check_output(
            ["curl", "-s", f"{BASE_URL}/ajax"],
            timeout=5, text=True,
        )
        data = json.loads(result)
        self.assertIn("SteamTemp", data)
        self.assertIn("version", data)
        self.assertIn("PowerOn", data)
        self.assertEqual(data["version"], "4.5.0-test")

    # === Template substitution ===

    def test_template_vars_replaced_in_index(self):
        result = subprocess.check_output(
            ["curl", "-s", f"{BASE_URL}/index.htm"],
            timeout=5, text=True,
        )
        # Template vars should be replaced, not present as %var%
        self.assertNotIn("%SteamColor%", result)
        self.assertNotIn("%PipeColor%", result)
        # Replacement values should be present
        self.assertIn("#e74c3c", result)
        self.assertIn("#3498db", result)

    def test_template_vars_replaced_in_setup(self):
        result = subprocess.check_output(
            ["curl", "-s", f"{BASE_URL}/setup.htm"],
            timeout=5, text=True,
        )
        self.assertNotIn("%Kp%", result)
        self.assertNotIn("%DeltaSteamTemp%", result)

    # === Static assets ===

    def test_common_js_served(self):
        result = subprocess.check_output(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             f"{BASE_URL}/common.js"],
            timeout=5, text=True,
        )
        self.assertEqual(result.strip(), "200")

    def test_style_css_served(self):
        result = subprocess.check_output(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             f"{BASE_URL}/style.css"],
            timeout=5, text=True,
        )
        self.assertEqual(result.strip(), "200")

    # === Endpoint contracts ===

    def test_command_endpoint_responds(self):
        result = subprocess.check_output(
            ["curl", "-s", "-X", "POST", f"{BASE_URL}/command"],
            timeout=5, text=True,
        )
        self.assertEqual(result.strip(), "OK")

    def test_program_endpoint_returns_program_text(self):
        result = subprocess.check_output(
            ["curl", "-s", f"{BASE_URL}/program"],
            timeout=5, text=True,
        )
        self.assertIn(";", result)
        self.assertIn("\n", result)


if __name__ == "__main__":
    unittest.main()
