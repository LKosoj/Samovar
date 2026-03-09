"""
Copyright (c) 2024 l.feng. All rights reserved.

cppcheck-wheel: Package cppcheck as a python wheel.
"""

from __future__ import annotations

import argparse
import functools
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from importlib_metadata import distribution

from ._version import version as __version__

__all__ = ["__version__", "cppcheck", "get_cppcheck_dir"]


@functools.lru_cache(maxsize=None)
def get_cppcheck_dir() -> Path:
    """Cppcheck binary directory"""
    package_files = distribution(__package__).files
    assert package_files is not None, f"There must exist {__package__} files"
    for file in package_files:
        if str(file).startswith(f"{__package__}/Cppcheck"):
            resolved_file = Path(str(file.locate())).resolve(strict=True)
            cppcheck_path = resolved_file.parents[1]
            if cppcheck_path.exists():
                return cppcheck_path
    raise FileNotFoundError("No found for Cppcheck in package " + __package__)


def _program(name: str, args: Iterable[str]) -> int:
    return subprocess.call([get_cppcheck_dir() / name, *args], close_fds=False)


def _program_exit(name: str, *args: str) -> None:
    if sys.platform.startswith("win"):
        raise SystemExit(_program(name, args))
    cppcheck_exe = get_cppcheck_dir() / name
    os.execl(cppcheck_exe, cppcheck_exe, *args)


def cppcheck() -> None:
    """Cppcheck entry"""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show the current version of cppcheck-wheel",
    )
    args, _ = parser.parse_known_args()
    if args.version:
        result = subprocess.run(
            [get_cppcheck_dir() / "cppcheck", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        cppcheck_version_out = result.stdout.rstrip()
        sys.stdout.write(f"{cppcheck_version_out} from cppcheck-wheel {__version__}\n")
    else:
        _program_exit("cppcheck", *sys.argv[1:])
