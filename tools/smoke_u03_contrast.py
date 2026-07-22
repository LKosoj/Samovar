#!/usr/bin/env python3
import gzip
import hashlib
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

SENSOR_TOKENS = ("SteamColor", "PipeColor", "WaterColor", "TankColor", "ACPColor")
SENSOR_PAGES = (
    "index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm",
    "setup.htm", "chart.htm",
)
DELTA_PAGES = ("index.htm", "bk.htm", "chart.htm")
STYLE_TOKEN_ALLOWLIST = (
    "accent", "accent-hover", "bg-page", "text-main", "text-strong",
    "text-on-accent", "text-history-link", "border-input", "border-soft",
    "msg-alarm", "state-danger-bg", "detector-ok-text", "detector-ok-bg",
    "detector-warn-text", "detector-warn-bg", "detector-alarm-text",
    "detector-alarm-bg",
)
NORMALIZED_SHA256 = {
    "style.css": "9fb63518cdf5ef78a9d4c6eea83250ff823dd44d52e60a6b4fcf83608264f7f5",
    "index.htm": "58d11c99c75f3d27eb9c2d4320651179471e548df54ba303e79cf5825bc23ee5",
    "beer.htm": "9d3a4ab340bb44d0d47d75fcd8acdd304d0bc0aacddcf3af177430531b2d7d69",
    "distiller.htm": "f929c701a50869a1062e51b8b85bf73d41f15c56a847414f5203ee046315d591",
    "bk.htm": "711c4854b58c7a3295bc8008a6aeb9d8c8bcc6aaa07490acb9fabf94b0c4412f",
    "nbk.htm": "a6e336f1c96c20d4e95381e27f747af780717bf7a7067f7f50b29be14cbb4d38",
    "setup.htm": "8e5f6004fbfd7525b2d4aebfd9e35fa28d2ca5ddce41b63b00b7921486317ccb",
    "chart.htm": "7beb4857bfa1e1445de8d7d2c51a2ef6a1207f70e83e371d41a2990a634e8a12",
    "program.htm": "c19b178f773db195059fb744d9c5a7709cc23e60798ebe73a5d951d394a18294",
    "i2cstepper.htm": "73cb500944566fa78dd21538e0cd3a3ca6124ed2c590c3d6027dd9586d6eb017",
    "chart.js": "c75f9056f18a8cd81622f6e2dbef6b7f1ead05467407183aec11a4aa6011b80e",
}
FROZEN_SHA256 = {
    "app.js": "29d3e0d773fafdd6caec3650f53bfad46afd7dd92c287986cfb0a67b67e6d092",
    "edit.htm": "26b7e41df2a0a0197a14b9cf129f808fd001e760df4ed7c16df7a35a10b03ce6",
    "edit.htm.gz": "86e2801e2370cd45420ed84005194b752cc22198e7ab85faa33129bd28a50cac",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_gzip(content: bytes) -> bytes:
    compressor = zlib.compressobj(
        level=9, method=zlib.DEFLATED, wbits=-15, memLevel=8,
        strategy=zlib.Z_DEFAULT_STRATEGY,
    )
    deflated = compressor.compress(content) + compressor.flush(zlib.Z_FINISH)
    header = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"
    trailer = struct.pack("<II", zlib.crc32(content) & 0xFFFFFFFF, len(content) & 0xFFFFFFFF)
    return header + deflated + trailer


def normalize_style(text: str) -> str:
    for token in STYLE_TOKEN_ALLOWLIST:
        text = re.sub(
            rf"(--{re.escape(token)}\s*:)\s*[^;]+;",
            rf"\1 <U03:{token}>;",
            text,
        )
    text = text.replace(
        ".message_0 { background: var(--msg-alarm); color: white; }",
        "<U03:message-0>",
    )
    text = text.replace(
        ".message_0 { background: var(--state-danger-bg); color: var(--text-on-accent); }",
        "<U03:message-0>",
    )
    text = re.sub(r"^\s+--msg-alarm: <U03:msg-alarm>;\n", "", text, flags=re.MULTILINE)

    def normalize_property(selector: str, property_name: str, marker: str) -> None:
        nonlocal text
        pattern = re.compile(
            rf"({re.escape(selector)}\s*\{{[^}}]*?\n\s*{re.escape(property_name)}\s*:)\s*[^;]+;",
            re.DOTALL,
        )
        text, count = pattern.subn(rf"\1 <U03:{marker}>;", text, count=1)
        if count != 1:
            raise AssertionError(f"CSS owner missing: {selector} {property_name}")

    normalize_property(".tab input", "border", "tab-input-border")
    normalize_property(".button:hover", "color", "button-hover-color")
    normalize_property(".button:active", "color", "button-active-color")
    normalize_property(
        'a[href]:focus-visible,\nbutton:focus-visible,\ninput:not([type="hidden"]):focus-visible,\nselect:focus-visible,\ntextarea:focus-visible,\nsummary:focus-visible,\ninput[type="checkbox"]:focus-visible + label,\n.file-upload-control:focus-within .custom-file-upload',
        "outline",
        "interactive-focus-outline",
    )
    normalize_property(".popup__button", "background-color", "popup-button-bg")
    normalize_property(".popup__button", "color", "popup-button-color")
    normalize_property(".theme-toggle", "border", "theme-toggle-border")
    normalize_property(".theme-toggle", "color", "theme-toggle-color")
    normalize_property(
        'input[type="radio"]:not(:checked) + label:before',
        "border",
        "choice-border",
    )
    normalize_property(
        'input[type="radio"]:not(:checked) + label:before',
        "background-color",
        "choice-background",
    )
    normalize_property(
        'input[type="checkbox"]:not(:checked) + label:after',
        "border-left",
        "checkbox-mark-left",
    )
    normalize_property(
        'input[type="checkbox"]:not(:checked) + label:after',
        "border-bottom",
        "checkbox-mark-bottom",
    )
    text = text.replace("fill='%23444'", "fill='<U03:select-arrow>'")
    text = text.replace("fill='%23777'", "fill='<U03:select-arrow>'")
    return text


def normalize_page(text: str) -> str:
    for token in SENSOR_TOKENS:
        source = f'style="color: %{token}%;"'
        target = (
            'style="color: var(--text-strong); text-decoration-line: underline; '
            f'text-decoration-color: %{token}%;"'
        )
        short_target = (
            'style="text-decoration-line: underline; '
            f'text-decoration-color: %{token}%;"'
        )
        marker = f'style="<U03:{token}>"'
        text = (
            text.replace(source, marker)
            .replace(target, marker)
            .replace(short_target, marker)
        )
    text = text.replace('style="color: black;"', 'style="<U03:delta>"')
    text = text.replace('style="color: var(--text-strong);"', 'style="<U03:delta>"')
    text = text.replace("background: #fafafa;", "background: <U03:program-panel>;")
    text = text.replace(
        "background: var(--bg-program-panel);", "background: <U03:program-panel>;"
    )
    text = text.replace("background: #fff;", "background: <U03:program-example>;")
    text = text.replace("background: #eee;", "background: <U03:program-example>;")
    text = text.replace(
        "background: var(--bg-program-example);", "background: <U03:program-example>;"
    )
    for source, marker in (
        ("#32CD3229", "row-b"), ("#B8E6B8", "row-b"),
        ("#FFFF0039", "row-c"), ("#FFF59D", "row-c"),
        ("#8B451334", "row-t"), ("#D8B9A4", "row-t"),
        ("#FF2929", "row-autotune"), ("#FF3838", "row-autotune"),
        ("#27ae60", "i2c-on"), ("#19733c", "i2c-on"),
        ("#229954", "i2c-on-hover"), ("#176b3a", "i2c-on-hover"),
    ):
        text = text.replace(source, f"<U03:{marker}>")

    text = text.replace("        l.style.color = '#17212B';\n", "")
    text = text.replace("          e[q].style.color = '#17212B';\n", "")
    text = text.replace("          e[q].style.borderColor = '#17212B';\n", "")
    text = text.replace("l.style.color = '#8B0000';", "l.style.color = 'red';")
    text = text.replace("e[q].style.color = '#8B0000';", "e[q].style.color = 'red';")
    text = text.replace(
        '      color += "color: #17212B; border-color: #17212B;";\n', ""
    )
    text = text.replace(
        '  color += "color: #17212B; border-color: #17212B;";\n', ""
    )

    text = text.replace(
        'style="font-size: xx-large; color:#444"',
        'style="font-size: xx-large; color:<U03:nbk-speed>"',
    )
    text = text.replace(
        'style="font-size: xx-large; color:var(--text-strong)"',
        'style="font-size: xx-large; color:<U03:nbk-speed>"',
    )
    for background in ("#FF6347", "#FFFF00", "#00BFFF", "#98FB98"):
        text = text.replace(
            f'style="background-color: {background}; color: #17212B;"',
            f'style="background-color: {background};"',
        )
    for old_color in ("honeydew", "navy", "#17212B"):
        text = text.replace(
            f'style="width:200px;display:inline-block;color:{old_color};"',
            'style="width:200px;display:inline-block;color:<U03:nbk-row-label>;"',
        )
    text = text.replace("color:#17212B;border-color:#17212B;", "")

    for source in (
        "color: #3498db; font-weight: bold; margin-bottom: 10px;",
        "color: var(--text-strong); font-weight: bold; margin-bottom: 10px;",
    ):
        text = text.replace(source, "color: <U03:program-heading>; font-weight: bold; margin-bottom: 10px;")
    for source in (
        "font-size: 0.9em; margin-bottom: 10px; color: #666;",
        "font-size: 0.9em; margin-bottom: 10px; color: var(--text-main);",
    ):
        text = text.replace(source, "font-size: 0.9em; margin-bottom: 10px; color: <U03:program-copy>;")
    for source in (
        "width: 100%; background: #3498db; color: white;",
        "width: 100%; background: var(--accent); color: var(--text-on-accent);",
    ):
        text = text.replace(source, "width: 100%; background: <U03:program-button>; color: <U03:program-button-text>;")
    return text


def normalize_chart(text: str) -> str:
    pattern = re.compile(r"(\{ key: '([^']+)', label: '[^']+', color: ')[^']+(' \})")
    normalized, count = pattern.subn(
        lambda match: match.group(1) + f"<U03:{match.group(2)}>" + match.group(3),
        text,
    )
    if count != 6:
        raise AssertionError(f"chart series cardinality changed: {count}")
    return normalized


def verify_source_boundary() -> None:
    for name, expected in FROZEN_SHA256.items():
        # .gz - продукт сборки, сырьё - источник.
        source = (BUILD if name.endswith(".gz") else DATA) / name
        actual = digest(source.read_bytes())
        if actual != expected:
            raise AssertionError(f"frozen data/{name} changed: {actual}")

    for name, expected in NORMALIZED_SHA256.items():
        text = (DATA / name).read_text(encoding="utf-8")
        if name == "style.css":
            text = normalize_style(text)
        elif name == "chart.js":
            text = normalize_chart(text)
        else:
            text = normalize_page(text)
        actual = digest(text.encode("utf-8"))
        if actual != expected:
            raise AssertionError(f"U-03 source boundary changed for data/{name}: {actual}")


def verify_mandatory_fixes() -> None:
    index = (DATA / "index.htm").read_text(encoding="utf-8")
    if index.count("l.style.color = '#8B0000';") != 1:
        raise AssertionError("data/index.htm: active row foreground cardinality")
    if index.count("e[q].style.color = '#8B0000';") != 1:
        raise AssertionError("data/index.htm: active row control foreground cardinality")
    if "l.style.color = 'red';" in index or "e[q].style.color = 'red';" in index:
        raise AssertionError("data/index.htm: unverified active row red remains")

    for name in DELTA_PAGES:
        text = (DATA / name).read_text(encoding="utf-8")
        if 'style="color: black;"' in text:
            raise AssertionError(f"data/{name}: DeltaTemp still uses black")
        if text.count('style="color: var(--text-strong);"') != 1:
            raise AssertionError(f"data/{name}: DeltaTemp theme color cardinality")

    program = (DATA / "program.htm").read_text(encoding="utf-8")
    for literal in ("background: #fafafa;", "background: #fff;", "background: #eee;"):
        if literal in program:
            raise AssertionError(f"data/program.htm: fixed audit surface remains: {literal}")
    if program.count("background: var(--bg-program-panel);") != 1:
        raise AssertionError("data/program.htm: program panel token cardinality")
    if program.count("background: var(--bg-program-example);") != 2:
        raise AssertionError("data/program.htm: program example token cardinality")

    full_target_template = (
        'style="color: var(--text-strong); text-decoration-line: underline; '
        'text-decoration-color: %{token}%;"'
    )
    short_target_template = (
        'style="text-decoration-line: underline; text-decoration-color: %{token}%;"'
    )
    for name in SENSOR_PAGES:
        text = (DATA / name).read_text(encoding="utf-8")
        target_template = (
            full_target_template if name == "setup.htm" else short_target_template
        )
        for token in SENSOR_TOKENS:
            target = target_template.format(token=token)
            if text.count(target) != 1:
                raise AssertionError(f"data/{name}: {token} readable accent cardinality")
            if f'style="color: %{token}%;"' in text:
                raise AssertionError(f"data/{name}: {token} remains a foreground")

    style = (DATA / "style.css").read_text(encoding="utf-8")
    if style.count("#file-input {\n  padding: 0;\n  border: 1px solid #ddd;\n") != 1:
        raise AssertionError("data/style.css: file input baseline border changed")
    expected_message = (
        ".message_0 { background: var(--state-danger-bg); "
        "color: var(--text-on-accent); }"
    )
    if style.count(expected_message) != 1:
        raise AssertionError("message_0 foreground/background ownership")


def verify_chart_palette() -> None:
    text = (DATA / "chart.js").read_text(encoding="utf-8")
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
        verify_source_boundary()
        verify_mandatory_fixes()
        verify_chart_palette()
        verify_canonical_gzip()
    except (AssertionError, OSError, ValueError, RuntimeError) as error:
        print(f"U-03 contrast smoke failed: {error}", file=sys.stderr)
        return 1
    print("U-03 contrast smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
