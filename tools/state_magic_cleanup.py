from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import state_inventory  # noqa: E402


DELIVERY_DIR = ROOT / "docs" / "result" / "delivery"
MAGIC_CLEANUP_LOG = DELIVERY_DIR / "magic_cleanup_log.md"
STATE_VARIABLES = (
    "SamovarStatusInt",
    "sam_command_sync",
    "Samovar_Mode",
    "Samovar_CR_Mode",
    "startval",
)
SEMANTIC_HELPERS = (
    "samovar_status_is_rectification",
    "samovar_status_allows_rectification_withdrawal",
    "samovar_status_has_rectification_program_progress",
    "startval_is_rect_program_state",
    "startval_is_active_non_calibration",
    "startval_is_beer_program_started",
)
COMMENT_LINE_PATTERN = re.compile(r"//.*")
COMMENT_BLOCK_PATTERN = re.compile(r"/\*.*?\*/", flags=re.DOTALL)


def strip_comments(text: str) -> str:
    text = COMMENT_BLOCK_PATTERN.sub("", text)
    return COMMENT_LINE_PATTERN.sub("", text)


def collect_raw_numeric_literal_matches(files: list[Path]) -> dict[str, list[state_inventory.Occurrence]]:
    matches: dict[str, list[state_inventory.Occurrence]] = {}
    for variable in STATE_VARIABLES:
        forward = re.compile(state_inventory.NUMERIC_PATTERN_TEMPLATE.format(variable=re.escape(variable)))
        reverse = re.compile(state_inventory.REVERSED_NUMERIC_PATTERN_TEMPLATE.format(variable=re.escape(variable)))
        occurrences: list[state_inventory.Occurrence] = []
        for path in files:
            relative_path = path.relative_to(ROOT).as_posix()
            owner = state_inventory.owner_for_path(relative_path)
            for line_no, raw_line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                line = strip_comments(raw_line).strip()
                if not line:
                    continue
                if forward.search(line) or reverse.search(line):
                    occurrences.append(
                        state_inventory.Occurrence(
                            path=relative_path,
                            line_no=line_no,
                            owner=owner,
                            text=line,
                        )
                    )
        matches[variable] = occurrences
    return matches


def collect_helper_occurrences(files: list[Path]) -> dict[str, list[state_inventory.Occurrence]]:
    return {helper: state_inventory.find_occurrences(files, helper) for helper in SEMANTIC_HELPERS}


def render_section(title: str, occurrences: list[state_inventory.Occurrence], empty_text: str) -> str:
    lines = [f"## {title}", ""]
    if not occurrences:
        lines.append(empty_text)
        return "\n".join(lines)
    lines.append("```text")
    for occurrence in state_inventory.dedupe_occurrences(occurrences):
        lines.append(f"{occurrence.path}:{occurrence.line_no}: {occurrence.text}")
    lines.append("```")
    return "\n".join(lines)


def render_magic_cleanup_log(audit: dict[str, object]) -> str:
    files: list[str] = audit["files"]
    raw_matches: dict[str, list[state_inventory.Occurrence]] = audit["raw_matches"]
    helper_occurrences: dict[str, list[state_inventory.Occurrence]] = audit["helper_occurrences"]
    parts = [
        "# Step 2.5 magic number cleanup audit",
        "",
        "## Scope",
        "",
        f"- Просканировано `*.h/*.cpp/*.ino`: `{len(files)}` файлов из git-дерева.",
        "- Проверены только state-semantics переменные: `SamovarStatusInt`, `sam_command_sync`, `Samovar_Mode`, `Samovar_CR_Mode`, `startval`.",
        "- Literal-числа допустимы только вне state semantics: в аппаратных лимитах, низкоуровневых протоколах и compile-time конфиге.",
        "- Остаточная transition semantics должна выражаться либо именованными токенами, либо helper-предикатами из `src/core/state/status_codes.h` и `src/core/state/mode_codes.h`.",
        "",
    ]
    for variable in STATE_VARIABLES:
        parts.append(
            render_section(
                f"Raw numeric literal matches for {variable}",
                raw_matches[variable],
                "_No raw numeric literal matches found._",
            )
        )
        parts.append("")

    parts.extend(
        [
            "## Named semantic helper call sites",
            "",
            "Ниже перечислены helper-предикаты, которыми заменены последние неявные state-range semantics в критической логике.",
            "",
        ]
    )
    for helper in SEMANTIC_HELPERS:
        parts.append(
            render_section(
                helper,
                helper_occurrences[helper],
                "_Helper is defined but has no call sites._",
            )
        )
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def build_audit() -> dict[str, object]:
    files = state_inventory.tracked_source_files()
    return {
        "files": [path.relative_to(ROOT).as_posix() for path in files],
        "raw_matches": collect_raw_numeric_literal_matches(files),
        "helper_occurrences": collect_helper_occurrences(files),
    }


def write_doc() -> None:
    audit = build_audit()
    DELIVERY_DIR.mkdir(parents=True, exist_ok=True)
    MAGIC_CLEANUP_LOG.write_text(render_magic_cleanup_log(audit), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit state semantics for raw numeric literal comparisons.")
    parser.add_argument("--write", action="store_true", help="Write docs/result/delivery/magic_cleanup_log.md")
    args = parser.parse_args()
    if args.write:
        write_doc()
        return
    print(render_magic_cleanup_log(build_audit()), end="")


if __name__ == "__main__":
    main()
