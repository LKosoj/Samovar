#!/usr/bin/env python3
import gzip
import re
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_web_assets import resolve_includes
from smoke_u03_contrast import canonical_gzip, verify_chart_palette, verify_mandatory_fixes


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"
# Сборка: сюда build_web_assets.py кладёт .gz. Содержимое читаем из источника,
# продукты сжатия - отсюда.
BUILD = ROOT / "data"


def read_page(name: str) -> str:
    """Разворачивает <!--#include--> (data_raw/partials/) той же функцией, что
    использует сама сборка - не копией её логики."""
    return resolve_includes(name, (DATA / name).read_bytes()).decode("utf-8")


LONG_INPUTS = ("blynkauth", "tgtoken", "tgchatid", "videourl")


def rule_body(css: str, selector: str, start: int = 0) -> str | None:
    match = re.search(re.escape(selector) + r"\s*\{([^{}]*)\}", css[start:], re.DOTALL)
    return match.group(1) if match else None


def require_rule(
    errors: list[str], css: str, selector: str, declarations: tuple[str, ...], start: int = 0
) -> None:
    body = rule_body(css, selector, start)
    if body is None:
        errors.append(f"data/style.css: missing selector {selector}")
        return
    compact = re.sub(r"\s+", "", body).lower()
    for declaration in declarations:
        if re.sub(r"\s+", "", declaration).lower() not in compact:
            errors.append(f"data/style.css: {selector} missing {declaration}")
    if re.search(r"overflow-x\s*:\s*(?:hidden|clip)|display\s*:\s*none|text-overflow\s*:|white-space\s*:\s*nowrap|position\s*:\s*(?:fixed|sticky)", body, re.I):
        errors.append(f"data/style.css: {selector} hides, clips, or fixes responsive content")


def verify_markup(errors: list[str]) -> None:
    setup = read_page("setup.htm")
    chart = read_page("chart.htm")

    if re.search(r"min-width\s*:\s*1024(?:\s*;|\s*['\"])", setup, re.I):
        errors.append("data/setup.htm: unitless min-width:1024 remains")
    form_match = re.search(r"<form\b[^>]*\bid=['\"]setupform['\"][^>]*>", setup, re.I)
    if not form_match or re.search(r"\bstyle\s*=", form_match.group(0), re.I):
        errors.append("data/setup.htm: #setupform must have no inline layout style")

    for name in LONG_INPUTS:
        match = re.search(rf"<input\b[^>]*\bname=['\"]{name}['\"][^>]*>", setup, re.I)
        if not match:
            errors.append(f"data/setup.htm: missing input[name={name}]")
            continue
        tag = match.group(0)
        class_match = re.search(r"\bclass=['\"]([^'\"]*)['\"]", tag, re.I)
        classes = class_match.group(1).split() if class_match else []
        if classes.count("setup-long-input") != 1:
            errors.append(f"data/setup.htm: input[name={name}] missing exact setup-long-input class")
        if not re.search(r"style=['\"][^'\"]*width\s*:\s*(?:22|30)em\s*;?[^'\"]*['\"]", tag, re.I):
            errors.append(f"data/setup.htm: input[name={name}] desktop em width changed")

    action_match = re.search(
        r"<div\b[^>]*>\s*<input\b[^>]*\bid=['\"]save['\"]", setup, re.I
    )
    if not action_match or not re.search(
        r"\bclass=['\"][^'\"]*\bsetup-actions\b[^'\"]*['\"]", action_match.group(0), re.I
    ):
        errors.append("data/setup.htm: #save/#return/#edit owner missing setup-actions class")
    if action_match and re.search(r"width\s*:\s*668px", action_match.group(0), re.I):
        errors.append("data/setup.htm: fixed width:668px action owner remains")

    host_match = re.search(
        r"<div\b[^>]*>\s*<div\b[^>]*\bid=['\"]messagesBox['\"]", chart, re.I
    )
    if not host_match or not re.search(
        r"\bclass=['\"][^'\"]*\bchart-messages-host\b[^'\"]*['\"]", host_match.group(0), re.I
    ):
        errors.append("data/chart.htm: #messagesBox owner missing chart-messages-host class")
    if host_match and re.search(r"(?:left\s*:\s*200px|width\s*:\s*600px)", host_match.group(0), re.I):
        errors.append("data/chart.htm: absolute 200px/600px message geometry remains inline")

    form_match = re.search(r"<form\b[^>]*action=['\"]none['\"][^>]*>", chart, re.I)
    if not form_match or not re.search(
        r"\bclass=['\"][^'\"]*\bchart-status-form\b[^'\"]*['\"]", form_match.group(0), re.I
    ):
        errors.append("data/chart.htm: status form missing chart-status-form class")


def verify_css(errors: list[str]) -> None:
    css = (DATA / "style.css").read_text(encoding="utf-8")
    if "@media (max-width: 600px)" not in css:
        errors.append("data/style.css: existing 600px breakpoint missing")
    requirements = (
        ("#setupform", ("min-width:0", "box-sizing:border-box"), 0),
        (".setup-long-input", ("max-width:100%",), 0),
        ("#Main select[name=\"mode\"]", ("max-width:100%", "box-sizing:border-box"), 0),
        # Плашки сообщений (#request_error и тосты) описаны одним общим правилом
        # на три класса - ищем его по последнему селектору списка. Раньше блочная
        # модель чинилась только для формы настроек (#setupform > .message_0), и
        # на program.htm тот же #request_error вылезал за форму на 22px.
        (".message_2", ("width:100%", "box-sizing:border-box"), 0),
        (".setup-actions", ("max-width:668px", "display:flex", "box-sizing:border-box"), 0),
        (".chart-messages-host", ("max-width:600px", "box-sizing:border-box"), 0),
        (".chart-status-form .container_column", ("min-width:0", "box-sizing:border-box"), 0),
        ("#chartdiv", ("min-width:0", "max-width:100%", "box-sizing:border-box"), 0),
        (".chart-panel", ("min-width:0", "max-width:100%", "box-sizing:border-box"), 0),
        (".chart-canvas", ("max-width:100%", "box-sizing:border-box"), 0),
        # [код-ревью 24.08 #1] Старое "max-width:calc(100vw-1em)" в 600px-блоке было
        # частью самого бага (конфликтовало с "calc(100vw-2em)" из 900px-блока) и
        # удалено вместе с фиксом; правило теперь в 900px-блоке и использует
        # position:fixed (как .popup) - под запрет "hides, clips, or fixes" ниже
        # попадёт любая проверка этого правила через require_rule, так что здесь
        # его больше не пиновать. Реальная защита от переполнения теперь - браузерный
        # checkTooltipFit в tools/test_u04_responsive_layout_browser.py (меряет
        # boundingBox в живом DOM на program.htm/index.htm/distiller.htm/setup.htm).
    )
    for selector, declarations, start in requirements:
        require_rule(errors, css, selector, declarations, start)
    if "overflow-x: hidden" in css or "overflow-x:hidden" in css:
        errors.append("data/style.css: overflow-x:hidden is forbidden")
    if "overflow-x: clip" in css or "overflow-x:clip" in css:
        errors.append("data/style.css: overflow-x:clip is forbidden")


def verify_u03_contract(errors: list[str]) -> None:
    try:
        verify_mandatory_fixes()
        verify_chart_palette()
    except AssertionError as error:
        errors.append(f"post-U03 color contract changed: {error}")


def verify_projection(errors: list[str]) -> None:
    source = (DATA / "style.css").read_bytes()
    stored = (BUILD / "style.css.gz").read_bytes()
    expected = canonical_gzip(source)
    if expected != canonical_gzip(source) or stored != expected:
        errors.append("data/style.css.gz: canonical deterministic projection mismatch")
    if stored[:10].hex() != "1f8b08000000000002ff":
        errors.append(f"data/style.css.gz: non-canonical header {stored[:10].hex()}")
    stream = zlib.decompressobj(wbits=31)
    expanded = stream.decompress(stored) + stream.flush()
    if not stream.eof or stream.unused_data or expanded != source or gzip.decompress(stored) != source:
        errors.append("data/style.css.gz: single-member decompression mismatch")


def main() -> int:
    errors: list[str] = []
    try:
        verify_markup(errors)
        verify_css(errors)
        verify_u03_contract(errors)
        verify_projection(errors)
    except (OSError, UnicodeError, re.error, zlib.error) as error:
        errors.append(f"harness error: {error}")
    if errors:
        for error in errors:
            print(f"U-04 responsive static failure: {error}", file=sys.stderr)
        print(f"U-04 responsive static smoke failed: {len(errors)} failures", file=sys.stderr)
        return 1
    print("U-04 responsive static smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
