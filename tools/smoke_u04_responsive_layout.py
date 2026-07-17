#!/usr/bin/env python3
import gzip
import hashlib
import json
import re
import sys
import zlib
from html.parser import HTMLParser
from pathlib import Path

from smoke_u03_contrast import canonical_gzip, verify_chart_palette, verify_mandatory_fixes


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"
# Сборка: сюда build_web_assets.py кладёт .gz. Содержимое читаем из источника,
# продукты сжатия - отсюда.
BUILD = ROOT / "data"
FROZEN_SHA256 = {
    "app.js": "29d3e0d773fafdd6caec3650f53bfad46afd7dd92c287986cfb0a67b67e6d092",
    "chart.js": "6ca38396b9a9c0ed8ac1333b310bac0d4b52997a6c8d5a587b9c9a3864131e6b",
    "edit.htm": "26b7e41df2a0a0197a14b9cf129f808fd001e760df4ed7c16df7a35a10b03ce6",
    "edit.htm.gz": "86e2801e2370cd45420ed84005194b752cc22198e7ab85faa33129bd28a50cac",
}
STRUCTURE_SHA256 = {
    "setup.htm": "be46553c03d166f0a11bb931303903ddd3e1fcd6b9f5be8fc1f608125bf04f66",
    "chart.htm": "c536a344fbc7c6aedd0bbfc4fb0475b63c37f817d4535ae7874b4813d89793fd",
}
LONG_INPUTS = ("blynkauth", "tgtoken", "tgchatid", "videourl")


class ContractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[list[object]] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        kept = sorted((key, value) for key, value in attrs if key not in ("class", "style"))
        self.parts.append(["start", tag, kept])

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip_depth:
            return
        kept = sorted((key, value) for key, value in attrs if key not in ("class", "style"))
        self.parts.append(["void", tag, kept])

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if not self.skip_depth:
            self.parts.append(["end", tag])

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        value = " ".join(data.split())
        if value:
            self.parts.append(["text", value])


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def structure_digest(path: Path) -> str:
    parser = ContractParser()
    parser.feed(path.read_text(encoding="utf-8"))
    payload = json.dumps(
        parser.parts, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return digest(payload)


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
    setup = (DATA / "setup.htm").read_text(encoding="utf-8")
    chart = (DATA / "chart.htm").read_text(encoding="utf-8")

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
    mobile_start = css.find("@media (max-width: 600px)")
    if mobile_start < 0:
        errors.append("data/style.css: existing 600px breakpoint missing")
        mobile_start = 0
    requirements = (
        ("#setupform", ("min-width:0", "box-sizing:border-box"), 0),
        (".setup-long-input", ("max-width:100%",), 0),
        ("#Main select[name=\"mode\"]", ("max-width:100%", "box-sizing:border-box"), 0),
        ("#setupform > .message_0", ("max-width:100%", "box-sizing:border-box"), 0),
        (".setup-actions", ("max-width:668px", "display:flex", "box-sizing:border-box"), 0),
        (".chart-messages-host", ("max-width:600px", "box-sizing:border-box"), 0),
        (".chart-status-form .container_column", ("min-width:0", "box-sizing:border-box"), 0),
        ("#chartdiv", ("min-width:0", "max-width:100%", "box-sizing:border-box"), 0),
        (".chart-panel", ("min-width:0", "max-width:100%", "box-sizing:border-box"), 0),
        (".chart-canvas", ("max-width:100%", "box-sizing:border-box"), 0),
        (".tooltip .tooltiptext", ("max-width:calc(100vw-1em)",), mobile_start),
    )
    for selector, declarations, start in requirements:
        require_rule(errors, css, selector, declarations, start)
    if "overflow-x: hidden" in css or "overflow-x:hidden" in css:
        errors.append("data/style.css: overflow-x:hidden is forbidden")
    if "overflow-x: clip" in css or "overflow-x:clip" in css:
        errors.append("data/style.css: overflow-x:clip is forbidden")


def verify_frozen_contract(errors: list[str]) -> None:
    for name, expected in FROZEN_SHA256.items():
        # .gz - продукт сборки, сырьё - источник.
        source = (BUILD if name.endswith(".gz") else DATA) / name
        actual = digest(source.read_bytes())
        if actual != expected:
            errors.append(f"data/{name}: frozen SHA changed: {actual}")
    for name, expected in STRUCTURE_SHA256.items():
        actual = structure_digest(DATA / name)
        if actual != expected:
            errors.append(f"data/{name}: DOM/text/control/action structure changed: {actual}")
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
        verify_frozen_contract(errors)
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
