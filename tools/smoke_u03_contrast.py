#!/usr/bin/env python3
import gzip
import re
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"
# Сборка: сюда build_web_assets.py кладёт .gz. Содержимое читаем из источника,
# продукты сжатия - отсюда.
BUILD = ROOT / "data"


def read_page(name: str) -> str:
    """Разворачивает <!--#include--> (data_raw/partials/) той же функцией, что
    использует сама сборка - не копией её логики. Импорт лениво (внутри функции):
    build_web_assets.py сам импортирует canonical_gzip из этого модуля, а прямой
    импорт на уровне модуля дал бы цикл."""
    from build_web_assets import resolve_includes
    return resolve_includes(name, (DATA / name).read_bytes()).decode("utf-8")


SENSOR_TOKENS = ("SteamColor", "PipeColor", "WaterColor", "TankColor", "ACPColor")
SENSOR_PAGES = (
    "index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm",
    "setup.htm", "chart.htm",
)
DELTA_PAGES = ("index.htm", "bk.htm", "chart.htm")


def canonical_gzip(content: bytes) -> bytes:
    compressor = zlib.compressobj(
        level=9, method=zlib.DEFLATED, wbits=-15, memLevel=8,
        strategy=zlib.Z_DEFAULT_STRATEGY,
    )
    deflated = compressor.compress(content) + compressor.flush(zlib.Z_FINISH)
    header = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"
    trailer = struct.pack("<II", zlib.crc32(content) & 0xFFFFFFFF, len(content) & 0xFFFFFFFF)
    return header + deflated + trailer


def verify_mandatory_fixes() -> None:
    index = read_page("index.htm")
    if index.count("l.style.color = '#8B0000';") != 1:
        raise AssertionError("data/index.htm: active row foreground cardinality")
    if index.count("e[q].style.color = '#8B0000';") != 1:
        raise AssertionError("data/index.htm: active row control foreground cardinality")
    if "l.style.color = 'red';" in index or "e[q].style.color = 'red';" in index:
        raise AssertionError("data/index.htm: unverified active row red remains")

    for name in DELTA_PAGES:
        text = read_page(name)
        if 'style="color: black;"' in text:
            raise AssertionError(f"data/{name}: DeltaTemp still uses black")
        if text.count('style="color: var(--text-strong);"') != 1:
            raise AssertionError(f"data/{name}: DeltaTemp theme color cardinality")

    program = read_page("program.htm")
    for literal in ("background: #fafafa;", "background: #fff;", "background: #eee;"):
        if literal in program:
            raise AssertionError(f"data/program.htm: fixed audit surface remains: {literal}")
    if program.count("background: var(--bg-program-panel);") != 1:
        raise AssertionError("data/program.htm: program panel token cardinality")
    # Было 2 (columnParamsResults, strategyNote), стало 3: добавлен блок-примечание
    # colSpeedClampNote (сигнал "рекомендованная скорость упёрлась в предел сечения
    # колонны"). Новый цвет не вводится - переиспользован уже проверенный на
    # контраст токен --bg-program-example.
    if program.count("background: var(--bg-program-example);") != 3:
        raise AssertionError("data/program.htm: program example token cardinality")

    setup_target_template = (
        'style="color: %{token}%; text-decoration-line: underline; '
        'text-decoration-color: %{token}%;"'
    )
    setup = read_page("setup.htm")
    for token in SENSOR_TOKENS:
        target = setup_target_template.format(token=token)
        if setup.count(target) != 1:
            raise AssertionError(f"data/setup.htm: {token} foreground accent cardinality")

    style = read_page("style.css")
    if style.count("#file-input {\n  padding: 0;\n  border: 1px solid #ddd;\n") != 1:
        raise AssertionError("data/style.css: file input baseline border changed")
    expected_message = (
        ".message_0 { background: var(--state-danger-bg); "
        "color: var(--text-on-accent); }"
    )
    if style.count(expected_message) != 1:
        raise AssertionError("message_0 foreground/background ownership")


def relative_luminance(color: str) -> float:
    text = color.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", text):
        text = "#" + "".join(channel * 2 for channel in text[1:])
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        raise AssertionError(f"opaque #rgb or #rrggbb color required, got {color!r}")
    channels = []
    for offset in (1, 3, 5):
        value = int(text[offset:offset + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: str, second: str) -> float:
    high, low = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def verify_button_contrast() -> None:
    """Цвета кнопок как в 6.27: --accent #3498db, hover #3498db97.

    WCAG 4.5 для этой палитры не выполняется (белый на #3498db - 3.15), это
    исходный вид интерфейса, и решением владельца от 01.09.2026 вид имеет
    приоритет над контрастом: более тёмный --accent сюда не подставляем.
    Замеренная цена решения зафиксирована списком ACCEPTED_CONTRAST в
    tools/test_u03_contrast_browser.py - там же ловится любое УХУДШЕНИЕ этих пар.

    Важно, что текст на наведении при этой палитре тёмный (--text-strong):
    фон #3498db97 полупрозрачный, его итоговый цвет зависит от подложки, и
    белый текст на нём давал 1.96 - хуже, чем что-либо в самой палитре 6.27."""
    style = read_page("style.css")
    values = {}
    for token in ("accent", "accent-hover", "text-on-accent"):
        found = re.findall(rf"--{token}:\s*([^;]+);", style)
        if len(found) != 1:
            raise AssertionError(f"data/style.css: --{token} declaration cardinality={len(found)}")
        values[token] = found[0].strip()
    if values["accent"].lower() != "#3498db":
        raise AssertionError(f"data/style.css: --accent must stay 6.27 #3498db, got {values['accent']}")
    if values["accent-hover"].lower() != "#3498db97":
        raise AssertionError(
            f"data/style.css: --accent-hover must stay 6.27 #3498db97, got {values['accent-hover']}"
        )
    if values["text-on-accent"].lower() not in ("#fff", "#ffffff"):
        raise AssertionError(
            f"data/style.css: --text-on-accent must stay white, got {values['text-on-accent']}"
        )
    # Текст на наведении обязан быть тёмным: фон полупрозрачный, белый на нём - 1.96.
    hover_rules = re.findall(r"\.button:(?:hover|active)[^{}]*\{([^{}]*)\}", style)
    if len(hover_rules) != 2 or any(
        "var(--text-strong)" not in body for body in hover_rules
    ):
        raise AssertionError("data/style.css: .button hover/active text must stay --text-strong")


def verify_chart_palette() -> None:
    text = read_page("chart.js")
    colors = re.findall(r"\{ key: '[^']+', label: '[^']+', color: '([^']+)' \}", text)
    if len(colors) != 6 or len(set(colors)) != 6:
        raise AssertionError("chart series palette must contain six distinct colors")


def verify_canonical_gzip() -> None:
    source = (DATA / "style.css").read_bytes()
    stored = (BUILD / "style.css.gz").read_bytes()
    first = canonical_gzip(source)
    second = canonical_gzip(source)
    if first != second or stored != first:
        raise AssertionError("style.css.gz is not the canonical deterministic projection")
    if stored[:10].hex() != "1f8b08000000000002ff":
        raise AssertionError(f"style.css.gz header changed: {stored[:10].hex()}")
    stream = zlib.decompressobj(wbits=31)
    expanded = stream.decompress(stored) + stream.flush()
    if not stream.eof or stream.unused_data or expanded != source:
        raise AssertionError("style.css.gz must be one complete member matching style.css")
    if gzip.decompress(stored) != source:
        raise AssertionError("style.css.gz standard decompression mismatch")


def main() -> int:
    try:
        verify_mandatory_fixes()
        verify_button_contrast()
        verify_chart_palette()
        verify_canonical_gzip()
    except (AssertionError, OSError, ValueError, RuntimeError) as error:
        print(f"U-03 contrast smoke failed: {error}", file=sys.stderr)
        return 1
    print("U-03 contrast smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
