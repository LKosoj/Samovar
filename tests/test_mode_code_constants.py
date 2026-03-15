from pathlib import Path
import re
import unittest


MODE_CODES_HEADER = Path("src/core/state/mode_codes.h")
GREP_LOG = Path("docs/result/delivery/mode_codes_grep_log.md")
SOURCE_ROOTS = [
    Path("app"),
    Path("io"),
    Path("modes"),
    Path("ui"),
    Path("storage"),
    Path("Blynk.ino"),
    Path("Samovar.ino"),
    Path("impurity_detector.h"),
]
MODE_PATTERN = re.compile(r"\bSamovar_(?:CR_)?Mode\b\s*(==|!=|<=|>=|=|<|>)\s*(-?\d+)")
MODE_REVERSED_PATTERN = re.compile(r"(-?\d+)\s*(==|!=|<=|>=|<|>)\s*\bSamovar_(?:CR_)?Mode\b")
STARTVAL_PATTERN = re.compile(r"\bstartval\b\s*(==|!=|<=|>=|=|<|>)\s*(-?\d+)")
STARTVAL_REVERSED_PATTERN = re.compile(r"(-?\d+)\s*(==|!=|<=|>=|<|>)\s*\bstartval\b")
COMMENT_LINE_PATTERN = re.compile(r"//.*")
COMMENT_BLOCK_PATTERN = re.compile(r"/\*.*?\*/", flags=re.DOTALL)


def _iter_source_files():
    for root in SOURCE_ROOTS:
        if root.is_file():
            yield root
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix in {".h", ".cpp", ".ino"}:
                yield path


def _strip_comments(text: str) -> str:
    text = COMMENT_BLOCK_PATTERN.sub("", text)
    return COMMENT_LINE_PATTERN.sub("", text)


class ModeCodeConstantsTest(unittest.TestCase):
    def test_mode_codes_header_exists_and_defines_all_constants(self) -> None:
        text = MODE_CODES_HEADER.read_text(encoding="utf-8")
        required_tokens = [
            "enum SAMOVAR_MODE",
            "SAMOVAR_RECTIFICATION_MODE = 0",
            "SAMOVAR_DISTILLATION_MODE = 1",
            "SAMOVAR_BEER_MODE = 2",
            "SAMOVAR_BK_MODE = 3",
            "SAMOVAR_NBK_MODE = 4",
            "SAMOVAR_SUVID_MODE = 5",
            "SAMOVAR_LUA_MODE = 6",
            "SAMOVAR_STARTVAL_RECT_IDLE = 0;",
            "SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING = 1;",
            "SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE = 2;",
            "SAMOVAR_STARTVAL_RECT_STOPPED = 3;",
            "SAMOVAR_STARTVAL_CALIBRATION = 100;",
            "SAMOVAR_STARTVAL_DISTILLATION_ENTRY = 1000;",
            "SAMOVAR_STARTVAL_BEER_ENTRY = 2000;",
            "SAMOVAR_STARTVAL_BEER_MALT_HEATING = 2001;",
            "SAMOVAR_STARTVAL_BEER_MALT_WAIT = 2002;",
            "SAMOVAR_STARTVAL_BK_ENTRY = 3000;",
            "SAMOVAR_STARTVAL_NBK_ENTRY = 4000;",
            "SAMOVAR_STARTVAL_NBK_PROGRAM_RUNNING = 4001;",
        ]
        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_transition_logic_uses_named_mode_and_startval_values(self) -> None:
        offenders: list[str] = []
        for path in _iter_source_files():
            text = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"))
            for line_no, line in enumerate(text.splitlines(), start=1):
                if (
                    MODE_PATTERN.search(line)
                    or MODE_REVERSED_PATTERN.search(line)
                    or STARTVAL_PATTERN.search(line)
                    or STARTVAL_REVERSED_PATTERN.search(line)
                ):
                    offenders.append(f"{path}:{line_no}: {line.strip()}")
        self.assertEqual(offenders, [])

    def test_grep_log_exists_and_tracks_named_mode_and_startval_tokens(self) -> None:
        text = GREP_LOG.read_text(encoding="utf-8")
        required_tokens = [
            "# Step 2.2b mode/startval named-constant grep",
            "## Full Samovar_Mode / Samovar_CR_Mode / startval scan",
            "SAMOVAR_RECTIFICATION_MODE",
            "SAMOVAR_BEER_MODE",
            "SAMOVAR_NBK_MODE",
            "SAMOVAR_STARTVAL_RECT_IDLE",
            "SAMOVAR_STARTVAL_CALIBRATION",
            "SAMOVAR_STARTVAL_BEER_ENTRY",
            "SAMOVAR_STARTVAL_NBK_PROGRAM_RUNNING",
            "## Raw numeric literal matches for Samovar_Mode / Samovar_CR_Mode",
            "## Raw numeric literal matches for startval",
            "_No raw numeric literal matches found._",
        ]
        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
