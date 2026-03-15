from pathlib import Path
import re
import unittest


PRODUCTION_SOURCE_EXTENSIONS = {".ino", ".h", ".hpp", ".c", ".cc", ".cpp"}
EXCLUDED_TOP_LEVEL_DIRS = {
    ".git",
    ".pio",
    ".venv",
    "3D",
    "Lua_UART",
    "Stab-avr",
    "ai_docs_site",
    "docs",
    "libraries",
    "pro_mini_ntc",
    "tests",
}

# Это документированная пользовательская точка расширения, а не legacy-shell.
ALLOWED_NON_LEGACY_EMPTY_SHELLS = {Path("user_config_override.h")}

LEGACY_PROXY_PATTERNS = [
    re.compile(r"\bsave_profile\s*\("),
    re.compile(r"\bload_profile\s*\("),
    re.compile(r"\bget_prf_name\s*\("),
]

DISALLOWED_COMPATIBILITY_FILENAME = re.compile(r"(shim|adapter|compat)", re.IGNORECASE)


def _iter_production_files():
    for path in Path(".").rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in PRODUCTION_SOURCE_EXTENSIONS:
            continue
        if any(part in EXCLUDED_TOP_LEVEL_DIRS for part in path.parts):
            continue
        yield path


def _effective_source_lines(path: Path) -> list[str]:
    lines = []
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("//"):
            continue
        if stripped.startswith("/*") or stripped.startswith("*") or stripped.startswith("*/"):
            continue
        if stripped.startswith("#ifndef") or stripped.startswith("#define") or stripped.startswith("#endif"):
            continue
        if stripped.startswith("#pragma once") or stripped.startswith("#include"):
            continue
        if stripped in {"{", "}", "};"}:
            continue
        lines.append(stripped)
    return lines


class LegacyCleanupPhase9Test(unittest.TestCase):
    def test_no_zero_byte_production_sources_remain(self) -> None:
        offenders = sorted(
            path.as_posix()
            for path in _iter_production_files()
            if path.stat().st_size == 0
        )
        self.assertEqual(offenders, [], f"Zero-byte production sources must be removed: {offenders}")

    def test_no_empty_legacy_shell_sources_remain(self) -> None:
        offenders = []
        for path in _iter_production_files():
            if path in ALLOWED_NON_LEGACY_EMPTY_SHELLS:
                continue
            if not _effective_source_lines(path):
                offenders.append(path.as_posix())

        self.assertEqual(
            offenders,
            [],
            f"Empty legacy shell sources must be removed: {offenders}",
        )

    def test_no_compatibility_or_shim_source_filenames_remain(self) -> None:
        offenders = sorted(
            path.as_posix()
            for path in _iter_production_files()
            if DISALLOWED_COMPATIBILITY_FILENAME.search(path.stem)
        )
        self.assertEqual(
            offenders,
            [],
            f"Temporary compatibility/shim source files must be removed: {offenders}",
        )

    def test_legacy_proxy_api_is_absent_from_production_sources(self) -> None:
        offenders = []
        for path in _iter_production_files():
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(pattern.search(text) for pattern in LEGACY_PROXY_PATTERNS):
                offenders.append(path.as_posix())

        self.assertEqual(
            offenders,
            [],
            f"Legacy proxy API must be removed from production sources: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
