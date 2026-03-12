from pathlib import Path
import re
import unittest


FS_LEGACY_FILE = Path("FS.ino")
NVS_MANAGER_FILE = Path("NVS_Manager.ino")
NVS_PROFILES_HEADER = Path("storage/nvs_profiles.h")

PRODUCTION_SOURCE_EXTENSIONS = {".ino", ".h", ".hpp", ".c", ".cc", ".cpp"}
EXCLUDED_TOP_LEVEL_DIRS = {
    ".git",
    ".pio",
    "ai_docs_site",
    "docs",
    "libraries",
    "tests",
}


def _iter_production_files():
    for path in Path(".").rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in PRODUCTION_SOURCE_EXTENSIONS:
            continue
        parts = path.parts
        if any(part in EXCLUDED_TOP_LEVEL_DIRS for part in parts):
            continue
        yield path


class StorageFsLegacyRemovalTests(unittest.TestCase):
    def test_fs_legacy_file_is_removed(self) -> None:
        self.assertFalse(FS_LEGACY_FILE.exists(), "FS.ino must be removed from the tree")

    def test_legacy_profile_proxy_api_is_absent_from_production_sources(self) -> None:
        legacy_patterns = [
            re.compile(r"\bsave_profile\s*\("),
            re.compile(r"\bload_profile\s*\("),
            re.compile(r"\bget_prf_name\s*\("),
        ]
        offenders = []
        for path in _iter_production_files():
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(pattern.search(text) for pattern in legacy_patterns):
                offenders.append(path.as_posix())
        self.assertEqual(
            offenders,
            [],
            f"Legacy FS proxy API must be removed from production sources: {offenders}",
        )

    def test_nvs_profiles_module_owns_canonical_profile_api(self) -> None:
        self.assertTrue(NVS_PROFILES_HEADER.exists(), "storage/nvs_profiles.h must exist")

        header_text = NVS_PROFILES_HEADER.read_text(encoding="utf-8")
        for snippet in [
            "inline void save_profile_nvs()",
            "inline void load_profile_nvs()",
            "inline void migrate_from_eeprom()",
            'return "sam_rect";',
            'meta.begin("sam_meta", true)',
        ]:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, header_text)

        manager_text = NVS_MANAGER_FILE.read_text(encoding="utf-8")
        self.assertIn('#include "storage/nvs_profiles.h"', manager_text)
        self.assertNotIn("void save_profile_nvs()", manager_text)
        self.assertNotIn("void load_profile_nvs()", manager_text)
        self.assertNotIn("void migrate_from_eeprom()", manager_text)


if __name__ == "__main__":
    unittest.main()
