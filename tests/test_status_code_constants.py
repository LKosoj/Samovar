from pathlib import Path
import re
import unittest


STATUS_CODES_HEADER = Path("src/core/state/status_codes.h")
GREP_LOG = Path("docs/result/delivery/status_codes_grep_log.md")
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
STATUS_PATTERN = re.compile(r"\bSamovarStatusInt\b\s*(==|!=|<=|>=|=|<|>)\s*(-?\d+)")
STATUS_REVERSED_PATTERN = re.compile(r"(-?\d+)\s*(==|!=|<=|>=|<|>)\s*\bSamovarStatusInt\b")
COMMAND_PATTERN = re.compile(r"\bsam_command_sync\b\s*(==|!=|=)\s*(-?\d+)")
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


class StatusCodeConstantsTest(unittest.TestCase):
    def test_status_codes_header_exists_and_defines_all_constants(self) -> None:
        text = STATUS_CODES_HEADER.read_text(encoding="utf-8")
        required_tokens = [
            "SAMOVAR_STATUS_OFF = 0;",
            "SAMOVAR_STATUS_RECTIFICATION_RUN = 10;",
            "SAMOVAR_STATUS_RECTIFICATION_WAIT = 15;",
            "SAMOVAR_STATUS_RECTIFICATION_COMPLETE = 20;",
            "SAMOVAR_STATUS_CALIBRATION = 30;",
            "SAMOVAR_STATUS_RECTIFICATION_PAUSE = 40;",
            "SAMOVAR_STATUS_RECTIFICATION_WARMUP = 50;",
            "SAMOVAR_STATUS_RECTIFICATION_STABILIZING = 51;",
            "SAMOVAR_STATUS_RECTIFICATION_STABILIZED = 52;",
            "SAMOVAR_STATUS_DISTILLATION = 1000;",
            "SAMOVAR_STATUS_BEER = 2000;",
            "SAMOVAR_STATUS_BK = 3000;",
            "SAMOVAR_STATUS_NBK = 4000;",
            "SAMOVAR_COMMAND_NONE = SAMOVAR_NONE;",
            "SAMOVAR_COMMAND_RESET = SAMOVAR_RESET;",
            "SAMOVAR_COMMAND_DISTILLATION = SAMOVAR_DISTILLATION;",
            "SAMOVAR_COMMAND_BEER = SAMOVAR_BEER;",
            "SAMOVAR_COMMAND_BK = SAMOVAR_BK;",
            "SAMOVAR_COMMAND_NBK = SAMOVAR_NBK;",
        ]
        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_transition_logic_uses_named_status_and_command_values(self) -> None:
        offenders: list[str] = []
        for path in _iter_source_files():
            text = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"))
            for line_no, line in enumerate(text.splitlines(), start=1):
                if STATUS_PATTERN.search(line) or STATUS_REVERSED_PATTERN.search(line) or COMMAND_PATTERN.search(line):
                    offenders.append(f"{path}:{line_no}: {line.strip()}")
        self.assertEqual(offenders, [])

    def test_grep_log_exists_and_tracks_named_state_tokens(self) -> None:
        text = GREP_LOG.read_text(encoding="utf-8")
        required_tokens = [
            "# Step 2.2a status/command named-constant grep",
            "## Full SamovarStatusInt / sam_command_sync scan",
            "SAMOVAR_STATUS_RECTIFICATION_RUN",
            "SAMOVAR_STATUS_DISTILLATION",
            "SAMOVAR_STATUS_BEER",
            "SAMOVAR_STATUS_BK",
            "SAMOVAR_STATUS_NBK",
            "SAMOVAR_RESET",
            "SAMOVAR_NONE",
            "## Raw numeric literal matches for SamovarStatusInt",
            "## Raw numeric literal matches for sam_command_sync",
            "_No raw numeric literal matches found._",
        ]
        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
