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
STYLE_TOKEN_ALLOWLIST = (
    "accent", "accent-hover", "bg-page", "text-main", "text-strong",
    "text-on-accent", "text-history-link", "border-input", "border-soft",
    "msg-alarm", "state-danger-bg", "detector-ok-text", "detector-ok-bg",
    "detector-warn-text", "detector-warn-bg", "detector-alarm-text",
    "detector-alarm-bg",
)
NORMALIZED_SHA256 = {
    "style.css": "c2e2bfc57ea49cf1d67318a71892c0205938635a45c2c17c1d7c1daedfe8f32d",
    "index.htm": "a6fbb2ead1b3242a1de2a8f26d03fe0d01ae1e240ea7b703b7415404334e4f75",
    "beer.htm": "c4d5d62913b60fe95dffe5ef845f6466b70a7125f47a6501d1bf810d8bcb8522",
    "distiller.htm": "eeb2e567b6f24d7b0123842cd4fe328e2db090b1ead133fdccbd71f856139709",
    "bk.htm": "373a86c784394b0551acc4b730655a9b77433505cb1184b4f38112edc3784147",
    "nbk.htm": "4e93fbdecf55696d9a6b3917e3170224bd5bf30259b72019cb61419e9ee954a6",
    "setup.htm": "16497361aaf0e4f1dee346e73051f7d824eb1ed9951ff71eff6f3b601ccc35b1",
    "chart.htm": "32736cc9f006e7c5890847723086aeec53bef61188e4b5883858e1b8895266eb",
    "program.htm": "c315d2a647e96f131bea24c21ca42b5cadc5faf3e8c3b2dc22ff68471e854849",
    "i2cstepper.htm": "27da2e5e24dfd54b59feca755364aba5b9a5fa214a847803b30f58d7a18cb315",
    "chart.js": "aae8513c74153e4ef5c6e29712331e9d39f9ea01b907ec2ac5ccabd1aa478e95",
}
FROZEN_SHA256 = {
    "app.js": "45633765356354e5190c85efe59e6678c2c76c47d183453d7224ef180963d00b",
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
        text = read_page(name)
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
        text = read_page(name)
        target_template = (
            full_target_template if name == "setup.htm" else short_target_template
        )
        for token in SENSOR_TOKENS:
            target = target_template.format(token=token)
            if text.count(target) != 1:
                raise AssertionError(f"data/{name}: {token} readable accent cardinality")
            if f'style="color: %{token}%;"' in text:
                raise AssertionError(f"data/{name}: {token} remains a foreground")

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
    """Кнопка и её hover красятся токенами, а текст на них всегда
    --text-on-accent. Полупрозрачный фон здесь запрещён: итоговый цвет зависит
    от подложки, и на светлой форме белый текст на #3498db97 давал 1.96 при
    норме WCAG 4.5. Браузерный гейт u03 этого не ловит - на #power кнопке
    inline-стиль перебивает .button:hover."""
    style = read_page("style.css")
    values = {}
    for token in ("accent", "accent-hover", "text-on-accent"):
        found = re.findall(rf"--{token}:\s*([^;]+);", style)
        if len(found) != 1:
            raise AssertionError(f"data/style.css: --{token} declaration cardinality={len(found)}")
        values[token] = found[0].strip()
    foreground = values["text-on-accent"]
    for token in ("accent", "accent-hover"):
        ratio = contrast_ratio(values[token], foreground)
        if ratio < 4.5:
            raise AssertionError(
                f"data/style.css: --{token} vs --text-on-accent contrast {ratio:.2f} < 4.5"
            )


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
        verify_source_boundary()
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
