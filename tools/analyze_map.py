#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Анализатор GNU ld map-файла для ESP32 (PlatformIO).

Почему прошлые «простые» парсеры часто врут:
- В map-файле есть «шапки» секций (.text/.rodata/...) и дальше идут вложенные строки
  с адресом/размером/объектом с отступом.
- Размер «прошивки» для флеша — это в основном вклад секций кода/rodata, а не bss.

Этот скрипт:
- Парсит вложенный memory map (строки с отступом) и суммирует вклад по объектам/библиотекам
- Печатает ТОП по flash- и ram-секциям (приближенно, по именам секций)
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Dict, Iterable, List, Tuple


FLASH_SECTION_PREFIXES = (
    ".text",
    ".rodata",
    ".irom",
    ".drom",
    ".flash",
    ".literal",
)

RAM_SECTION_PREFIXES = (
    ".data",
    ".bss",
    ".iram",
    ".dram",
    ".noinit",
    ".rtc",
    ".phyiram",
)

# Секции, которые не попадают во flash/RAM прошивки (DWARF-отладка, метаданные Xtensa).
# Их содержимое пропускается при подсчёте размеров.
SKIP_SECTION_PREFIXES = (
    ".debug",
    ".xt.prop",
    ".xt.lit",
    ".xtensa",
    ".comment",
)


@dataclass
class SizeAcc:
    flash: int = 0
    ram: int = 0
    other: int = 0
    by_section: DefaultDict[str, int] = None  # type: ignore

    def __post_init__(self) -> None:
        if self.by_section is None:
            self.by_section = defaultdict(int)

    @property
    def total(self) -> int:
        return self.flash + self.ram + self.other


# Output-секция: начинается СТРОГО с позиции 0 (.name<ws>0xaddr<ws>0xsize).
# Строки с ведущим пробелом — это contribution-строки, не заголовки.
OUTPUT_SECTION_RE = re.compile(
    r"^(\.[A-Za-z0-9_.$]+)\s+0x[0-9a-fA-F]+\s+0x[0-9a-fA-F]+\s*"
)

# Однострочная contribution (1 пробел + .name + addr + size + path на одной строке).
# Пример: ' .rodata.str1.1  0x3f401234  0x10  lib/libfoo.a(bar.o)'
SINGLE_CONTRIB_RE = re.compile(
    r"^ (\.[A-Za-z0-9_.$]+)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+(\S.+)$"
)

# Перенесённое имя input-секции (только имя, данные на следующей строке).
# Пример: ' .iram1.29.literal\n'
RENAMED_SECTION_RE = re.compile(
    r"^ (\.[A-Za-z0-9_.$]+)\s*$"
)

# Строка с данными contribution (addr + size + path), обычно с большим отступом.
# Используется как для перенесённых имён, так и самостоятельно.
CONTRIB_RE = re.compile(
    r"^\s{2,}0x[0-9a-fA-F]+\s+0x([0-9a-fA-F]+)\s+(\S.+?)\s*$"
)


def classify_section(section: str) -> str:
    s = section.strip()
    if s.startswith(FLASH_SECTION_PREFIXES):
        return "flash"
    if s.startswith(RAM_SECTION_PREFIXES):
        return "ram"
    return "other"


def extract_owner(path: str) -> str:
    """
    Превращает путь/описание объекта в «владельца» для агрегации.
    Примеры:
    - .pio/build/Samovar/lib845/libESP_Async_WebServer.a(WebServer.cpp.o) -> ESP_Async_WebServer
    - .pio/build/Samovar/src/Samovar.ino.cpp.o -> PROJECT:Samovar.ino
    - .../tools/sdk/esp32/lib/libwpa_supplicant.a(wpa.c.obj) -> IDF:wpa_supplicant
    - .../toolchain-xtensa-.../libgcc.a(unwind-dw2-fde.o) -> TOOLCHAIN:libgcc
    """
    p = path.strip()

    m = re.search(r"/lib[0-9a-f]+/lib([^/.]+)\.a\(", p)
    if m:
        return m.group(1)

    m = re.search(r"/src/([^/]+)\.cpp\.o\b", p)
    if m:
        fn = m.group(1)
        # Самое полезное — выделить Samovar.ino отдельно
        if fn.startswith("Samovar.ino"):
            return "PROJECT:Samovar.ino"
        return f"PROJECT:{fn}"

    m = re.search(r"/tools/sdk/esp32/(?:ld/)?lib/lib([^/.]+)\.a\(", p)
    if m:
        return f"IDF:{m.group(1)}"

    m = re.search(r"/toolchain-[^/]+/.*/(lib[^/]+)\.a\(", p)
    if m:
        return f"TOOLCHAIN:{m.group(1)}"

    m = re.search(r"libFrameworkArduino\.a\(", p)
    if m:
        return "FrameworkArduino"

    return "UNKNOWN"


def format_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _account(
    path: str,
    size: int,
    current_section: str,
    owner_sizes: Dict[str, SizeAcc],
    file_sizes: Dict[str, SizeAcc],
) -> None:
    """Записать размер size в нужные аккумуляторы."""
    owner = extract_owner(path)
    bucket = classify_section(current_section)

    acc = owner_sizes[owner]
    acc.by_section[current_section] += size
    if bucket == "flash":
        acc.flash += size
    elif bucket == "ram":
        acc.ram += size
    else:
        acc.other += size

    fm = re.search(r"\(([^)]+)\)", path)
    if fm:
        fname = fm.group(1)
    else:
        fm = re.search(r"([^/\s]+\.o(?:bj)?)\b", path)
        fname = fm.group(1) if fm else None

    if fname:
        facc = file_sizes[fname]
        facc.by_section[current_section] += size
        if bucket == "flash":
            facc.flash += size
        elif bucket == "ram":
            facc.ram += size
        else:
            facc.other += size


def parse_map(map_path: str) -> Tuple[Dict[str, SizeAcc], Dict[str, SizeAcc]]:
    """
    Возвращает:
    - owner_sizes: агрегация по владельцам (библиотека/проект/IDF/...)
    - file_sizes: агрегация по конкретным файлам (объектам), если удалось извлечь

    Парсит ТОЛЬКО регион «Linker script and memory map» (P-2: Discarded input
    sections до этого маркера полностью пропускаются).

    Различает четыре типа строк внутри региона:
      (а) Output-секция:      .name<ws>0xaddr<ws>0xsize  — начинается с позиции 0
      (б) Однострочная вклад: ' .name 0xaddr 0xsize path' — 1 пробел + всё на строке (P-1)
      (в) Перенесённое имя:   ' .name\\n'               — 1 пробел, только имя
      (г) Строка данных:      '   0xaddr 0xsize path'   — отступ ≥2, данные
    """
    owner_sizes: Dict[str, SizeAcc] = defaultdict(SizeAcc)
    file_sizes: Dict[str, SizeAcc] = defaultdict(SizeAcc)

    current_section: str | None = None
    skip_current = False  # пропускать contributions текущей output-секции
    in_memory_map = False  # P-2: флаг — находимся ли в нужном регионе

    try:
        with open(map_path, "r", encoding="latin-1", errors="ignore") as f:
            for line in f:
                # P-2: пропускаем всё до маркера «Linker script and memory map»
                if not in_memory_map:
                    if line.startswith("Linker script and memory map"):
                        in_memory_map = True
                    continue

                # (а) Output-секция: начинается с точки в позиции 0
                m = OUTPUT_SECTION_RE.match(line)
                if m:
                    current_section = m.group(1)
                    skip_current = current_section.startswith(SKIP_SECTION_PREFIXES)
                    # Размер шапки не суммируем — он раскладывается на вложенные строки
                    continue

                if not current_section or skip_current:
                    continue

                # (б) P-1: однострочная contribution ' .name 0xaddr 0xsize path'
                m = SINGLE_CONTRIB_RE.match(line)
                if m:
                    # Имя input-секции обновляет current_section для корректной классификации
                    current_section = m.group(1)
                    size = int(m.group(3), 16)
                    if size > 0:
                        _account(m.group(4), size, current_section, owner_sizes, file_sizes)
                    continue

                # (в) Перенесённое имя input-секции (только имя, данные на следующей строке)
                m = RENAMED_SECTION_RE.match(line)
                if m:
                    current_section = m.group(1)
                    continue

                # (г) Строка данных contribution: '   0xaddr 0xsize path'
                m = CONTRIB_RE.match(line)
                if m:
                    size = int(m.group(1), 16)
                    if size > 0:
                        _account(m.group(2), size, current_section, owner_sizes, file_sizes)

    except FileNotFoundError:
        print(f"Ошибка: файл не найден: {map_path}", file=sys.stderr)
        sys.exit(1)

    return owner_sizes, file_sizes


def print_top(title: str, items: Iterable[Tuple[str, SizeAcc]], top_n: int) -> None:
    print("=" * 96)
    print(title)
    print("=" * 96)
    print(f"{'Объект':<40} {'FLASH':>12} {'RAM':>12} {'OTHER':>12} {'TOTAL':>12}")
    print("-" * 96)
    for name, acc in list(items)[:top_n]:
        print(
            f"{name[:39]:<40} {format_size(acc.flash):>12} {format_size(acc.ram):>12} {format_size(acc.other):>12} {format_size(acc.total):>12}"
        )
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description="Анализ firmware.map (GNU ld) для ESP32/PlatformIO")
    ap.add_argument("map", nargs="?", default="firmware.map", help="Путь к map-файлу (по умолчанию firmware.map)")
    ap.add_argument("--top", type=int, default=30, help="Сколько строк выводить (по умолчанию 30)")
    ap.add_argument("--sections", action="store_true", help="Показать топ-секции внутри топ-1 объекта")
    args = ap.parse_args()

    owner_sizes, file_sizes = parse_map(args.map)

    owners_sorted = sorted(owner_sizes.items(), key=lambda kv: kv[1].total, reverse=True)
    files_sorted = sorted(file_sizes.items(), key=lambda kv: kv[1].total, reverse=True)

    print(f"Анализ файла: {args.map}")
    print()
    print_top(f"ТОП-{args.top} по владельцам (библиотеки/IDF/проект)", owners_sorted, args.top)
    print_top(f"ТОП-{args.top} по объектным файлам (.o/.obj)", files_sorted, args.top)

    if args.sections and owners_sorted:
        name, acc = owners_sorted[0]
        sec_sorted = sorted(acc.by_section.items(), key=lambda kv: kv[1], reverse=True)[:50]
        print("=" * 96)
        print(f"ТОП-секций для: {name}")
        print("=" * 96)
        for sec, sz in sec_sorted:
            print(f"{sec:<40} {format_size(sz):>12}")


if __name__ == "__main__":
    main()

