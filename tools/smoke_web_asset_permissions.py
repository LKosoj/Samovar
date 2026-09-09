#!/usr/bin/env python3
"""Сборщик сохраняет права data/ и переносит их на создаваемые файлы."""
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_web_assets


def main() -> int:
    original_target = build_web_assets.TARGET
    errors: list[str] = []

    try:
        with tempfile.TemporaryDirectory() as temporary:
            for directory_mode, expected_file_mode in ((0o2775, 0o664), (0o2750, 0o640)):
                target = Path(temporary) / "data"
                target.mkdir()
                target.chmod(directory_mode)
                build_web_assets.TARGET = target

                if build_web_assets.main() != 0:
                    errors.append(f"сборка завершилась ошибкой для data={directory_mode:o}")
                    continue

                actual_directory_mode = stat.S_IMODE(target.stat().st_mode)
                if actual_directory_mode != directory_mode:
                    errors.append(
                        f"права data/ изменились: {directory_mode:o} -> "
                        f"{actual_directory_mode:o}"
                    )

                wrong_files = sorted(
                    path.name
                    for path in target.iterdir()
                    if path.is_file()
                    and stat.S_IMODE(path.stat().st_mode) != expected_file_mode
                )
                if wrong_files:
                    errors.append(
                        f"при data={directory_mode:o} ожидались файлы "
                        f"{expected_file_mode:o}: {', '.join(wrong_files)}"
                    )

                for path in target.iterdir():
                    path.unlink()
                target.rmdir()
    finally:
        build_web_assets.TARGET = original_target

    if errors:
        print("web asset permissions smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1

    print("web asset permissions smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
