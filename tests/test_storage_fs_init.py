from pathlib import Path
import unittest


FS_INIT_HEADER = Path("storage/fs_init.h")
FS_LEGACY_FILE = Path("FS.ino")
SERVER_INIT_HEADER = Path("ui/web/server_init.h")


class StorageFsInitModuleTests(unittest.TestCase):
    def test_fs_init_module_exists_with_expected_initialization_steps(self) -> None:
        self.assertTrue(FS_INIT_HEADER.exists(), "storage/fs_init.h must exist")
        text = FS_INIT_HEADER.read_text(encoding="utf-8")
        expected_snippets = [
            "inline void FS_init(void)",
            "SPIFFS.begin(false)",
            "SPIFFS.format()",
            "total_byte = SPIFFS.totalBytes();",
            "events.onConnect(",
            "server.addHandler(&events);",
            "server.addHandler(new SPIFFSEditor(SPIFFS));",
            "server.onNotFound(",
            "server.onFileUpload(",
            "server.onRequestBody(",
        ]
        for snippet in expected_snippets:
            self.assertIn(snippet, text)

    def test_legacy_fs_file_no_longer_defines_fs_init(self) -> None:
        text = FS_LEGACY_FILE.read_text(encoding="utf-8")
        self.assertNotIn("void FS_init(void) {", text)

    def test_server_init_includes_fs_init_module_and_keeps_call(self) -> None:
        text = SERVER_INIT_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "storage/fs_init.h"', text)
        self.assertNotIn("void FS_init(void);", text)
        self.assertIn("FS_init();", text)


if __name__ == "__main__":
    unittest.main()
