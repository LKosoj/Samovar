#!/usr/bin/env python3
"""Расширенная проверка cppcheck (--force, все конфигурации #ifdef) с базовой линией.

Раньше этот запуск был помечен `continue-on-error: true` в CI и не мог упасть вообще -
находки уезжали только в артефакт cppcheck-extended.txt, который никто не обязан
открывать. `--force` перебирает все комбинации #ifdef и включает категорию `information`,
поэтому в принципе может находить больше, чем быстрая блокирующая проверка (job
static-analysis, tools/run_cppcheck.py без --force).

Решение: падать, но только на НОВЫХ находках - тех, которых нет в зафиксированной базе
tools/cppcheck_force_baseline.txt. Уже известные (принятые осознанно) находки не роняют
сборку, но остаются видимыми в логе шага, а не только в артефакте. Пополнять базу нужно
руками, когда новую находку разбирают и осознанно решают не чинить сразу.
"""
import argparse
import os
import re
import sys
from pathlib import Path

import run_cppcheck as cppcheck_tool
from check_local_includes import ExternalHeadersError, check_includes
from run_cppcheck import MANIFEST_PATH, ManifestError, cppcheck_command, load_manifest, validate_manifest
from runner_utils import positive_timeout

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "tools" / "cppcheck_force_baseline.txt"
# Замерено локально 2026-08-23: полный `cppcheck --force` по всем 8 .ino-юнитам
# в один поток занимает ~334с. -j (см. ниже) снижает это до ~230с здесь, но
# выигрыш ограничен - Samovar.ino один доминирует по времени, остальные 7
# файлов параллелизму почти не помогают. 900с - это ~2.7x запас над обоими
# замерами на случай, если раннер CI медленнее или с меньшим числом ядер.
DEFAULT_TIMEOUT_SECONDS = 900.0

# Формат ровно как в --template run_cppcheck.py: {file}:{line}:{column}: {severity}: {message} [{id}]
FINDING_PATTERN = re.compile(
    r"^.+:\d+:\d+: (error|warning|style|performance|portability|information): .+ \[\S+\]$"
)
# "Active checkers: N/592 (use --checkers-report=...) [checkersReport]" - служебное
# сообщение cppcheck о том, сколько его внутренних чекеров реально сработало на данном
# прогоне. N меняется от прогона к прогону на неизменном коде (зависит от того, какие
# участки кода реально прошли через анализ), поэтому эту строку нельзя занести в
# baseline - она всегда будет выглядеть как "новая находка". Это не находка о коде,
# а самоотчёт инструмента о себе самом - отбрасываем её до сравнения с baseline.
NOISE_ID_PATTERN = re.compile(r"\[checkersReport\]$")


def load_baseline(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def parse_findings(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if FINDING_PATTERN.match(line.strip()) and not NOISE_ID_PATTERN.search(line.strip())
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run cppcheck --force gated on a checked-in findings baseline")
    parser.add_argument("--report", type=Path, help="write a readable cppcheck report")
    parser.add_argument(
        "--timeout",
        type=positive_timeout,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"maximum cppcheck runtime in seconds (default: {DEFAULT_TIMEOUT_SECONDS:g})",
    )
    args = parser.parse_args()

    try:
        analysis_units = validate_manifest(ROOT, load_manifest(MANIFEST_PATH))
        # Своя проверка разрешимости include, а не через run_cppcheck.main(): этот
        # скрипт собирает команду сам и main() не зовёт, поэтому без явного вызова
        # расширенная джоба унаследовала бы --suppress=missingInclude вместе с
        # заглушённой категорией, но без замены (см. check_local_includes).
        include_problems = check_includes(ROOT)
    except (ManifestError, ExternalHeadersError, OSError) as error:
        print(f"cppcheck baseline check: {error}", file=sys.stderr)
        return 2

    if include_problems:
        for problem in include_problems:
            print(problem, file=sys.stderr)
        print(f"local include check failed: {len(include_problems)} problem(s)", file=sys.stderr)
        return 1

    command = cppcheck_command(analysis_units, force=True)
    # cppcheck -j распределяет 8 независимых .ino-юнитов по потокам (проверено:
    # даёт реальное ~30% ускорение, не меняет состав находок - см. DEFAULT_TIMEOUT_SECONDS).
    command.insert(1, f"-j{os.cpu_count() or 1}")
    print(f"Cppcheck command: {' '.join(command)}", flush=True)
    returncode, stdout, stderr, timed_out = cppcheck_tool.run_cppcheck(command, ROOT, args.timeout)

    if args.report:
        report_path = args.report if args.report.is_absolute() else ROOT / args.report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            cppcheck_tool.report_text(command, len(analysis_units), returncode, args.timeout, timed_out, stdout, stderr),
            encoding="utf-8",
        )

    # cppcheck пишет находки (warning/style/.../information) в stderr, а в stdout идёт
    # только прогресс ("Checking X: ...", "N/8 files checked"). Раньше здесь разбирался
    # только stdout - находки были невидимы для этого скрипта НЕЗАВИСИМО от содержимого
    # baseline, проверка молча пропускала вообще всё. Разбираем оба потока.
    findings = parse_findings(stdout) + parse_findings(stderr)
    baseline = load_baseline(BASELINE_PATH)
    new_findings = sorted(set(findings) - baseline)
    known_findings = sorted(set(findings) & baseline)
    stale_baseline = sorted(baseline - set(findings))

    print(f"cppcheck --force: {len(findings)} findings ({len(known_findings)} known, {len(new_findings)} new)")
    if known_findings:
        print("Known findings (in tools/cppcheck_force_baseline.txt, not blocking):")
        for line in known_findings:
            print(f"  {line}")
    if stale_baseline:
        print("Baseline entries no longer reproduced (safe to prune from tools/cppcheck_force_baseline.txt):")
        for line in stale_baseline:
            print(f"  {line}")
    if new_findings:
        print("NEW findings not in tools/cppcheck_force_baseline.txt:", file=sys.stderr)
        for line in new_findings:
            print(f"  {line}", file=sys.stderr)
    if stderr.strip():
        print(stderr, file=sys.stderr)

    if timed_out:
        print(f"cppcheck --force timed out after {args.timeout:g} seconds", file=sys.stderr)
        return 1
    if new_findings:
        return 1
    if returncode not in (0, 1):
        print(f"cppcheck --force exited with unexpected code {returncode}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
