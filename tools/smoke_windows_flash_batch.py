#!/usr/bin/env python3
"""Проверяет пользовательский Windows-сценарий сборки и прошивки Samovar."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "flash_windows.bat"


def validate(source: str) -> list[str]:
    errors: list[str] = []

    required = {
        "плата по умолчанию": 'set "BOARD=devkit"',
        "LittleFS по умолчанию отключена": 'set "LITTLEFS=no"',
        "DevKit окружение": 'set "PIO_ENV=Samovar"',
        "S3 окружение": 'set "PIO_ENV=Samovar_s3"',
        "параметр платы": 'if /I "%~1"=="--board"',
        "параметр LittleFS": 'if /I "%~1"=="--littlefs"',
        "проверка pio": "call :find_pio",
        "PlatformIO при имени пользователя с кириллицей": 'C:\\.platformio\\penv\\Scripts\\pio.exe',
        "установка без winget": "Python и winget не найдены",
        "официальный установщик PlatformIO": "platformio/platformio-core-installer/master/get-platformio.py",
        "поддерживаемая архитектура": 'if /I "%PROCESSOR_ARCHITECTURE%"=="AMD64"',
        "исключение псевдонима Microsoft Store": '\\Microsoft\\WindowsApps\\',
    }
    for name, token in required.items():
        if token not in source:
            errors.append(f"нет обязательного элемента: {name}")

    commands = [
        '"%PIO_EXE%" run -e "%PIO_ENV%"\n',
        '"%PIO_EXE%" run -e "%PIO_ENV%" -t upload\n',
        '"%PIO_EXE%" run -e "%PIO_ENV%" -t uploadfs\n',
        '"%PIO_EXE%" run -e "%PIO_ENV%" -t monitor\n',
    ]
    positions = [source.find(command) for command in commands]
    if any(position < 0 for position in positions):
        errors.append("нет полной цепочки compile -> upload -> uploadfs -> monitor")
    elif positions != sorted(positions) or len(set(positions)) != len(positions):
        errors.append("нарушен порядок compile -> upload -> uploadfs -> monitor")

    littlefs_guard = 'if /I "%LITTLEFS%"=="yes" ('
    guard_position = source.find(littlefs_guard)
    uploadfs_position = source.find(commands[2])
    monitor_position = source.find(commands[3])
    if not (0 <= guard_position < uploadfs_position < monitor_position):
        errors.append("uploadfs не защищён параметром --littlefs yes")

    for command in commands[:3]:
        command_position = source.find(command)
        if command_position >= 0:
            following = source[command_position + len(command):].lstrip().splitlines()
            if not following or following[0].strip() != "if errorlevel 1 goto :failed":
                errors.append(f"ошибка команды не останавливает сценарий: {command.strip()}")

    if 'sys.version_info ^< (3, 7)' in source or '$release.assets ^|' in source:
        errors.append("символ внутри кавычек ошибочно экранирован для cmd.exe")

    for token in ("call :ensure_git", ":ensure_git", ":find_git", "Git.Git", "samovar-git-64-bit.exe"):
        if token in source:
            errors.append(f"батник всё ещё устанавливает ненужный Git: {token}")

    return errors


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    errors = validate(source)

    mutations = {
        "неверное окружение S3": source.replace('set "PIO_ENV=Samovar_s3"', 'set "PIO_ENV=Samovar"'),
        "LittleFS загружается без разрешения": source.replace(
            'if /I "%LITTLEFS%"=="yes" (', 'if /I "%LITTLEFS%"=="no" (', 1
        ),
        "монитор открыт до прошивки": source.replace(
            '"%PIO_EXE%" run -e "%PIO_ENV%" -t monitor\n',
            '"%PIO_EXE%" run -e "%PIO_ENV%" -t upload\n',
            1,
        ),
    }
    for name, mutant in mutations.items():
        if not validate(mutant):
            errors.append(f'проверка не обнаружила мутацию "{name}"')

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1

    print("PASS: Windows-батник проверяет зависимости, параметры и порядок прошивки")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
