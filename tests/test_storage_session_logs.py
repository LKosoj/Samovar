from pathlib import Path
import unittest


SESSION_LOGS_HEADER = Path("storage/session_logs.h")
FS_LEGACY_FILE = Path("FS.ino")
SENSORINIT_FILE = Path("sensorinit.h")

DIRECT_USERS = [
    Path("app/runtime_tasks.h"),
    Path("Menu.ino"),
    Path("modes/dist/dist_runtime.h"),
    Path("modes/beer/beer_runtime.h"),
    Path("modes/bk/bk_runtime.h"),
    Path("modes/nbk/nbk_runtime.h"),
]


class StorageSessionLogsModuleTests(unittest.TestCase):
    def test_session_logs_module_exists_with_expected_functions(self) -> None:
        self.assertTrue(SESSION_LOGS_HEADER.exists(), "storage/session_logs.h must exist")
        text = SESSION_LOGS_HEADER.read_text(encoding="utf-8")
        expected_snippets = [
            "inline String append_data();",
            "inline void create_data() {",
            "inline String append_data() {",
            'SPIFFS.open("/prg.csv", FILE_WRITE)',
            'SPIFFS.open("/data.csv", FILE_WRITE)',
            'SPIFFS.open("/data.csv", FILE_APPEND)',
            'SPIFFS.open("/state.csv", FILE_WRITE)',
            'SPIFFS.rename("/data.csv", "/data_old.csv")',
            "used_byte = SPIFFS.usedBytes();",
            'SendMsg("Заканчивается память!',
        ]
        for snippet in expected_snippets:
            self.assertIn(snippet, text)

    def test_legacy_fs_file_is_removed(self) -> None:
        self.assertFalse(FS_LEGACY_FILE.exists(), "FS.ino must be removed")

    def test_direct_users_include_session_logs_module(self) -> None:
        for path in DIRECT_USERS:
            text = path.read_text(encoding="utf-8")
            self.assertIn('#include "storage/session_logs.h"', text, str(path))

    def test_sensorinit_no_longer_carries_legacy_append_data_declaration(self) -> None:
        text = SENSORINIT_FILE.read_text(encoding="utf-8")
        self.assertNotIn("String append_data();", text)


if __name__ == "__main__":
    unittest.main()
