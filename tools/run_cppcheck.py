#!/usr/bin/env python3
import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from runner_utils import positive_timeout, subprocess_output

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tools" / "static_analysis_sources.json"
SOURCE_SUFFIXES = {".h", ".ino"}
DEFAULT_TIMEOUT_SECONDS = 300.0


class ManifestError(ValueError):
    pass


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(f"cannot read {path}: {error}") from error
    if not isinstance(manifest, dict):
        raise ManifestError("manifest root must be an object")
    return manifest


def discover_root_sources(root: Path) -> list[str]:
    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_file() and path.suffix in SOURCE_SUFFIXES
    )


def validate_manifest(root: Path, manifest: dict[str, Any]) -> list[str]:
    if set(manifest) != {"inventory", "excluded"}:
        raise ManifestError("manifest must contain only 'inventory' and 'excluded'")

    inventory = manifest["inventory"]
    excluded = manifest["excluded"]
    if not isinstance(inventory, list) or not all(isinstance(name, str) for name in inventory):
        raise ManifestError("'inventory' must be a list of file names")
    if not isinstance(excluded, dict) or not all(
        isinstance(name, str) and isinstance(reason, str) and reason.strip()
        for name, reason in excluded.items()
    ):
        raise ManifestError("'excluded' must map file names to non-empty reasons")
    if inventory != sorted(set(inventory)):
        raise ManifestError("'inventory' must be unique and sorted")
    if list(excluded) != sorted(excluded):
        raise ManifestError("'excluded' keys must be sorted")

    invalid_inventory = [
        name
        for name in inventory
        if Path(name).name != name or Path(name).suffix not in SOURCE_SUFFIXES
    ]
    if invalid_inventory:
        raise ManifestError("invalid root source names: " + ", ".join(invalid_inventory))
    inventory_set = set(inventory)
    invalid_exclusions = sorted(set(excluded) - inventory_set)
    if invalid_exclusions:
        raise ManifestError("excluded files missing from inventory: " + ", ".join(invalid_exclusions))
    excluded_units = sorted(name for name in excluded if Path(name).suffix == ".ino")
    if excluded_units:
        raise ManifestError("root .ino files cannot be excluded: " + ", ".join(excluded_units))

    discovered = set(discover_root_sources(root))
    undeclared = sorted(discovered - inventory_set)
    missing = sorted(inventory_set - discovered)
    errors: list[str] = []
    if undeclared:
        errors.append("undeclared root firmware sources: " + ", ".join(undeclared))
    if missing:
        errors.append("inventory files not found: " + ", ".join(missing))
    if errors:
        raise ManifestError("; ".join(errors))
    analysis_units = sorted(name for name in inventory if Path(name).suffix == ".ino")
    if not analysis_units:
        raise ManifestError("root firmware inventory must contain at least one .ino analysis unit")
    return analysis_units


def cppcheck_command(analysis_units: list[str], force: bool) -> list[str]:
    enabled = "warning,performance,portability,information" if force else "warning,performance,portability"
    command = [
        "cppcheck",
        f"--enable={enabled}",
        "--std=c++11",
        "--inline-suppr",
        "--error-exitcode=1",
        "--suppress=missingIncludeSystem",
        "--language=c++",
        "--template={file}:{line}:{column}: {severity}: {message} [{id}]",
    ]
    if force:
        command.insert(1, "--force")
    return command + analysis_units


def run_cppcheck(command: list[str], root: Path, timeout_seconds: float) -> tuple[int, str, str, bool]:
    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        return result.returncode, result.stdout, result.stderr, False
    except subprocess.TimeoutExpired as error:
        stdout = subprocess_output(error.stdout)
        stderr = subprocess_output(error.stderr)
        timeout_message = f"cppcheck timed out after {timeout_seconds:g} seconds"
        stderr = f"{stderr.rstrip()}\n{timeout_message}" if stderr else timeout_message
        return 124, stdout, stderr, True


def report_text(
    command: list[str],
    source_count: int,
    returncode: int,
    timeout_seconds: float,
    timed_out: bool,
    stdout: str,
    stderr: str,
) -> str:
    sections = [
        "Cppcheck static analysis report",
        f"Sources: {source_count}",
        f"Timeout: {timeout_seconds:g} seconds",
        f"Timed out: {'yes' if timed_out else 'no'}",
        f"Exit code: {returncode}",
        f"Command: {shlex.join(command)}",
        "",
        "stdout:",
        stdout.rstrip(),
        "",
        "stderr:",
        stderr.rstrip(),
        "",
    ]
    return "\n".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the source manifest and run cppcheck")
    parser.add_argument("--force", action="store_true", help="check all preprocessor configurations")
    parser.add_argument("--report", type=Path, help="write a readable cppcheck report")
    parser.add_argument(
        "--timeout",
        type=positive_timeout,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"maximum cppcheck runtime in seconds (default: {DEFAULT_TIMEOUT_SECONDS:g})",
    )
    args = parser.parse_args()

    command: list[str] = []
    analysis_units: list[str] = []
    stdout = ""
    stderr = ""
    returncode = 2
    timed_out = False
    try:
        analysis_units = validate_manifest(ROOT, load_manifest(MANIFEST_PATH))
        command = cppcheck_command(analysis_units, args.force)
        print(f"Cppcheck command: {shlex.join(command)}", flush=True)
        returncode, stdout, stderr, timed_out = run_cppcheck(command, ROOT, args.timeout)
    except (ManifestError, OSError) as error:
        stderr = str(error)

    if stdout:
        print(stdout, end="" if stdout.endswith("\n") else "\n")
    if stderr:
        print(stderr, end="" if stderr.endswith("\n") else "\n", file=sys.stderr)
    if args.report:
        report_path = args.report if args.report.is_absolute() else ROOT / args.report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            report_text(
                command,
                len(analysis_units),
                returncode,
                args.timeout,
                timed_out,
                stdout,
                stderr,
            ),
            encoding="utf-8",
        )
    return returncode


if __name__ == "__main__":
    sys.exit(main())
