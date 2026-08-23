#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path
from typing import Iterable, TextIO

from runner_utils import positive_timeout, subprocess_output

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_TIMEOUT_SECONDS = 60.0


def discover_smoke_tests(root: Path) -> list[Path]:
    return sorted((root / "tools").glob("smoke_*.py"), key=lambda path: path.name)


def run_smoke_tests(
    tests: Iterable[Path],
    root: Path,
    output: TextIO,
    timeout_seconds: float,
) -> int:
    ordered_tests = list(tests)
    if not ordered_tests:
        print("Smoke test discovery failed: no tools/smoke_*.py files found", file=output)
        return 1

    failures: list[str] = []
    skipped: list[str] = []
    for index, path in enumerate(ordered_tests, start=1):
        relative_path = path.relative_to(root)
        print(f"[{index}/{len(ordered_tests)}] {relative_path}", file=output, flush=True)
        try:
            result = subprocess.run(
                [sys.executable, str(relative_path)],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            partial_output = subprocess_output(error.stdout)
            if partial_output:
                print(partial_output, end="" if partial_output.endswith("\n") else "\n", file=output)
            failures.append(str(relative_path))
            print(f"FAIL (timed out after {timeout_seconds:g} seconds)", file=output)
            continue
        except OSError as error:
            failures.append(str(relative_path))
            print(f"FAIL (could not start: {error})", file=output)
            continue

        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n", file=output)
        if result.returncode == 0:
            # SMOKE_SKIP: конвенция для тестов, которые не могут выполнить
            # часть проверок (нет node/g++ и т.п.). Раньше такой ранний выход
            # с кодом 0 неотличим от настоящего PASS в сводке - теперь считаем
            # его отдельно, чтобы пропуск не "растворялся" в passed.
            if "SMOKE_SKIP:" in result.stdout:
                skipped.append(str(relative_path))
                print("SKIP", file=output)
            else:
                print("PASS", file=output)
        else:
            failures.append(str(relative_path))
            print(f"FAIL (exit {result.returncode})", file=output)

    passed = len(ordered_tests) - len(failures) - len(skipped)
    print(
        f"Smoke summary: {passed} passed, {len(failures)} failed, {len(skipped)} skipped",
        file=output,
    )
    if skipped:
        print("Skipped tests:", file=output)
        for name in skipped:
            print(f" - {name}", file=output)
    if failures:
        print("Failed tests:", file=output)
        for name in failures:
            print(f" - {name}", file=output)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run every first-party smoke test")
    parser.add_argument(
        "--timeout",
        type=positive_timeout,
        default=DEFAULT_TEST_TIMEOUT_SECONDS,
        help=f"maximum runtime per test in seconds (default: {DEFAULT_TEST_TIMEOUT_SECONDS:g})",
    )
    args = parser.parse_args()
    return run_smoke_tests(discover_smoke_tests(ROOT), ROOT, sys.stdout, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
