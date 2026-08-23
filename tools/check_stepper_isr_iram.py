#!/usr/bin/env python3
"""Проверка, что обработчик прерывания шагового двигателя не обращается во флеш.

Прерывание StepperTicker зарегистрировано с ESP_INTR_FLAG_IRAM (см. USE_STEPPER_IRAM_ISR
в Samovar.h), поэтому оно продолжает работать, пока идёт запись в файл и кэш флеш-памяти
отключён. Если в обработчик попадёт хоть один вызов или литерал из флеша, прошивка
упадёт с "Cache disabled but cached memory region accessed" ровно в момент записи лога.

Проверка работает по собранным прошивкам, поэтому не подходит под маску smoke_*.py.
Список окружений обязателен и не берётся из того, что случайно лежит в .pio/build -
иначе "собрали одно окружение, проверили одно и сказали OK". В CI вызывается по разу
на каждое окружение из матрицы сборки (все 7 - USE_STEPPER_IRAM_ISR определён
безусловно в Samovar.h и действует на все окружения platformio.ini одинаково).

    pio run -e Samovar && python3 tools/check_stepper_isr_iram.py Samovar
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / ".pio" / "build"
PACKAGES = Path.home() / ".platformio" / "packages"
ISR_SYMBOL = "_Z13StepperTickerv"
# Секции, размещённые во флеше: обращение к ним из обработчика недопустимо.
FLASH_SECTION_MARKERS = (".flash.", "irom", "drom")


def toolchain_prefix(env_name: str) -> Path:
    if env_name.endswith("_s3"):
        return PACKAGES / "toolchain-xtensa-esp32s3" / "bin" / "xtensa-esp32s3-elf-"
    return PACKAGES / "toolchain-xtensa-esp32" / "bin" / "xtensa-esp32-elf-"


def run_tool(tool: Path, *args: str) -> str:
    return subprocess.run([str(tool), *args], capture_output=True, text=True, check=True).stdout


def section_map(objdump: Path, elf: Path) -> list[tuple[str, int, int]]:
    sections = []
    for line in run_tool(objdump, "-h", str(elf)).splitlines():
        match = re.match(r"\s*\d+\s+(\S+)\s+([0-9a-f]{8})\s+([0-9a-f]{8})", line)
        if match:
            sections.append((match.group(1), int(match.group(3), 16), int(match.group(2), 16)))
    return sections


def symbol_map(nm: Path, elf: Path) -> dict[int, str]:
    symbols: dict[int, str] = {}
    for line in run_tool(nm, str(elf)).splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3:
            try:
                symbols.setdefault(int(parts[0], 16), parts[2].strip())
            except ValueError:
                pass
    return symbols


def read_word(objdump: Path, elf: Path, address: int) -> int | None:
    dump = run_tool(objdump, "-s", f"--start-address={address:#x}", f"--stop-address={address + 4:#x}", str(elf))
    for line in dump.splitlines():
        match = re.match(r"\s*([0-9a-f]{8}) ([0-9a-f]{8})", line)
        if match and int(match.group(1), 16) == address:
            raw = match.group(2)
            return int("".join(reversed([raw[i:i + 2] for i in range(0, 8, 2)])), 16)
    return None


def isr_body(objdump: Path, elf: Path) -> list[str] | None:
    listing = run_tool(objdump, "-d", "--section=.iram0.text", str(elf)).splitlines()
    start = None
    for index, line in enumerate(listing):
        if re.match(rf"^[0-9a-f]{{8}} <{ISR_SYMBOL}>:", line):
            start = index
            break
    if start is None:
        return None
    body = []
    for line in listing[start + 1:]:
        if re.match(r"^[0-9a-f]{8} <", line):
            break
        if line.strip():
            body.append(line)
    return body


def check_env(env_name: str) -> tuple[bool, str]:
    elf = BUILD_DIR / env_name / "firmware.elf"
    if not elf.exists():
        return False, f"{env_name}: не найден {elf} - окружение не собрано"
    prefix = toolchain_prefix(env_name)
    objdump = Path(str(prefix) + "objdump")
    nm = Path(str(prefix) + "nm")
    if not objdump.exists():
        return False, f"{env_name}: не найден {objdump}"

    body = isr_body(objdump, elf)
    if body is None:
        return False, f"{env_name}: {ISR_SYMBOL} отсутствует в .iram0.text (обработчик не в IRAM)"

    sections = section_map(objdump, elf)
    symbols = symbol_map(nm, elf)

    def section_of(address: int) -> str:
        for name, vma, size in sections:
            if vma <= address < vma + size:
                return name
        return "?"

    def in_flash(address: int) -> bool:
        name = section_of(address)
        return any(marker in name for marker in FLASH_SECTION_MARKERS)

    problems = []
    for line in body:
        call = re.search(r"\bcall[048]\s+([0-9a-f]+)", line)
        if call:
            target = int(call.group(1), 16)
            if in_flash(target):
                problems.append(f"вызов {target:#x} ({symbols.get(target, '?')}) в {section_of(target)}")
        literal = re.search(r"l32r\s+a\d+, (?:0x)?([0-9a-f]+)", line)
        if literal:
            address = int(literal.group(1), 16)
            value = read_word(objdump, elf, address)
            if value is None:
                problems.append(f"не удалось прочитать литерал по адресу {address:#x}")
            elif in_flash(value):
                problems.append(f"адрес {value:#x} ({symbols.get(value, '?')}) в {section_of(value)}")

    if problems:
        return False, f"{env_name}: обработчик обращается во флеш:\n    " + "\n    ".join(problems)
    return True, f"{env_name}: обращений во флеш нет ({len(body)} инструкций)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "environments",
        nargs="+",
        help="имена окружений platformio.ini для проверки (обязательны, без умолчаний по .pio/build)",
    )
    args = parser.parse_args()

    environments = args.environments
    failed = False
    for env_name in environments:
        ok, message = check_env(env_name)
        print(("OK   " if ok else "ОШИБКА ") + message)
        failed |= not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
