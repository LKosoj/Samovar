from pathlib import Path
import unittest


MENU_FILE = Path("Menu.ino")
BOOTSTRAP_SOURCE = Path("Samovar.ino")
SEARCH_ROOTS = [
    Path("Samovar.ino"),
    Path("Samovar.h"),
    Path("app"),
    Path("io"),
    Path("modes"),
    Path("state"),
    Path("storage"),
    Path("support"),
    Path("ui"),
    Path("mkdocs.yml"),
]
ALLOWED_SUFFIXES = {"", ".h", ".ino", ".cpp", ".c", ".py", ".yml", ".param"}


class MenuInoRemovedTests(unittest.TestCase):
    def test_menu_ino_file_is_removed(self) -> None:
        self.assertFalse(MENU_FILE.exists(), "Menu.ino must be removed")

    def test_samovar_bootstrap_uses_menu_headers_directly(self) -> None:
        text = BOOTSTRAP_SOURCE.read_text(encoding="utf-8")
        self.assertIn('#include "ui/menu/strings.h"', text)
        self.assertIn('#include "ui/menu/input.h"', text)

    def test_repo_has_no_live_menu_ino_references(self) -> None:
        for root in SEARCH_ROOTS:
          if root.is_dir():
            files = [
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix in ALLOWED_SUFFIXES
            ]
          else:
            files = [root]
          for path in files:
            with self.subTest(path=path.as_posix()):
              text = path.read_text(encoding="utf-8")
              self.assertNotIn("Menu.ino", text)


if __name__ == "__main__":
    unittest.main()
