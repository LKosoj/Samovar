#!/usr/bin/env python3
"""Запускает все браузерные UI-тесты tools/test_*_browser.py по-настоящему.

В отличие от отдельных smoke_*.py-проверок, которые лишь ищут строки-маркеры внутри
исходников test_*_browser.py (и остаются зелёными, даже если сам браузерный тест падает
на первом шаге), этот раннер реально запускает каждый файл через playwright-cli в
headless-браузере и падает, если упал хоть один.

Требует установленный `playwright-cli` (npm-пакет @playwright/cli) и загруженный Chromium -
см. шаг "Install Playwright CLI and browser" в .github/workflows/firmware-ci.yml.
Без playwright-cli каждый test_*_browser.py сам печатает понятную ошибку и завершается
с кодом 2 - раннер это не маскирует, а честно репортит как провал соответствующего файла.
"""
import argparse
import sys
from pathlib import Path

from run_smoke_tests import run_smoke_tests
from runner_utils import positive_timeout

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_TIMEOUT_SECONDS = 240.0


def discover_browser_tests(root: Path) -> list[Path]:
    return sorted((root / "tools").glob("test_*_browser.py"), key=lambda path: path.name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run every first-party browser UI test (requires playwright-cli)")
    parser.add_argument(
        "--timeout",
        type=positive_timeout,
        default=DEFAULT_TEST_TIMEOUT_SECONDS,
        help=f"maximum runtime per test in seconds (default: {DEFAULT_TEST_TIMEOUT_SECONDS:g})",
    )
    args = parser.parse_args()

    tests = discover_browser_tests(ROOT)
    if not tests:
        print("Browser test discovery failed: no tools/test_*_browser.py files found", file=sys.stderr)
        return 1
    return run_smoke_tests(tests, ROOT, sys.stdout, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
