#!/usr/bin/env python3
import gzip
import hashlib
import re
import struct
import sys
import zlib
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"
# Сборка: сюда build_web_assets.py кладёт .gz. Содержимое читаем из источника,
# продукты сжатия - отсюда.
BUILD = ROOT / "data"
PAGES = (
    "index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm",
    "program.htm", "setup.htm", "chart.htm", "calibrate.htm",
    "i2cstepper.htm", "brewxml.htm",
)
MODE_PAGES = ("index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm")
MESSAGE_PAGES = (*MODE_PAGES, "program.htm", "chart.htm")
UPLOAD_PAGES = ("beer.htm", "program.htm", "setup.htm", "brewxml.htm")
GENERATED_PAGES = ("index.htm", "beer.htm", "distiller.htm", "program.htm")
SETUP_CONTROLS = (
    "mode", "DistTemp", "DistTimeF", "ColDiam", "ColHeight", "PackDens",
    "MaxPressureValue", "SteamAddr", "DeltaSteamTemp", "SetSteamTemp",
    "SteamDelay", "PipeAddr", "DeltaPipeTemp", "SetPipeTemp", "PipeDelay",
    "WaterAddr", "DeltaWaterTemp", "SetWaterTemp", "WaterDelay", "TankAddr",
    "DeltaTankTemp", "SetTankTemp", "TankDelay", "ACPAddr", "DeltaACPTemp",
    "SetACPTemp", "ACPDelay", "StepperStepMl", "StepperStepMlI2C", "Kp", "Ki",
    "Kd", "StbVoltage", "BVolt", "NbkIn", "NbkDelta", "NbkDM", "NbkDP",
    "NbkSteamT", "NbkOwPress", "blynkauth", "tgtoken", "tgchatid", "videourl",
    "TimeZone", "HeaterR", "LogPeriod", "rele1", "rele2", "rele3", "rele4",
)
PAGE_LABELS = {
    "index.htm": ("Voltage", "pumpspeed", "lua_str_i", "Descr", "WProgram"),
    "beer.htm": (
        "Voltage", "m_type", "m_direction", "m_time", "m_pause",
        "lua_str_i", "Descr", "WProgram",
    ),
    "distiller.htm": ("Voltage", "lua_str_i", "Descr", "WProgram"),
    "bk.htm": ("Voltage", "lua_str_i"),
    "nbk.htm": ("Voltage", "lua_str_i", "Descr", "WProgram"),
    "program.htm": (
        "loadprogram", "heaterMaxPower", "vless", "vlssp", "vlp", "vlhp", "vltp",
        "trest", "sum",
    ),
    "calibrate.htm": ("pump_type", "kstepperspd", "stepperstepml"),
    "i2cstepper.htm": (
        "mixerRpm", "mixerRunSec", "mixerPauseSec", "pumpMode", "pumpMlHour",
        "pumpPauseSec", "fillingMl", "fillingMlHour", "stepsPerMl",
    ),
}
FROZEN = {
    "edit.htm": "26b7e41df2a0a0197a14b9cf129f808fd001e760df4ed7c16df7a35a10b03ce6",
    "edit.htm.gz": "86e2801e2370cd45420ed84005194b752cc22198e7ab85faa33129bd28a50cac",
}
KEY_LISTENER_REGISTRATION = re.compile(
    r"\baddEventListener\s*\(\s*(['\"])(?:keydown|keyup|keypress)\1\s*,",
    re.I,
)
UNLOCK_AUDIO_LISTENER = "document.addEventListener('keydown', unlockAudio, { once: true });"


def canonical_gzip(content: bytes) -> bytes:
    compressor = zlib.compressobj(
        level=9, method=zlib.DEFLATED, wbits=-15, memLevel=8,
        strategy=zlib.Z_DEFAULT_STRATEGY,
    )
    deflated = compressor.compress(content) + compressor.flush(zlib.Z_FINISH)
    header = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"
    trailer = struct.pack("<II", zlib.crc32(content) & 0xFFFFFFFF, len(content) & 0xFFFFFFFF)
    return header + deflated + trailer


def app_key_listener_error(source: str) -> str | None:
    count = source.count(UNLOCK_AUDIO_LISTENER)
    if count != 1:
        return f"exact unlockAudio keydown registration count is {count}"
    remaining = source.replace(UNLOCK_AUDIO_LISTENER, "", 1)
    if KEY_LISTENER_REGISTRATION.search(remaining):
        return "additional key listener registration"
    return None


def verify_keyboard_guard(errors: list[str]) -> None:
    mutations = {
        "concise arrow": "node.addEventListener('keydown', e => node.click());",
        "named callback": "node.addEventListener('keypress', emulateClick);",
    }
    for name, source in mutations.items():
        if KEY_LISTENER_REGISTRATION.search(source) is None:
            errors.append(f"keyboard guard misses {name} registration")
    if app_key_listener_error(UNLOCK_AUDIO_LISTENER) is not None:
        errors.append("keyboard guard rejects exact unlockAudio allow-case")


class MarkupParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root_lang: str | None = None
        self.ids: list[str] = []
        self.labels: list[str] = []
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self.tags.append((tag, values))
        if tag == "html" and self.root_lang is None:
            self.root_lang = values.get("lang")
        if values.get("id"):
            self.ids.append(str(values["id"]))
        if tag == "label" and values.get("for"):
            self.labels.append(str(values["for"]))

    handle_startendtag = handle_starttag


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_page(name: str) -> tuple[str, MarkupParser]:
    source = (DATA / name).read_text(encoding="utf-8")
    parser = MarkupParser()
    parser.feed(source)
    return source, parser


def function_body(source: str, name: str) -> str:
    match = re.search(rf"\bfunction\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", source)
    if not match:
        raise AssertionError(f"data/app.js: missing function {name}")
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(match.end() - 1, len(source)):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "'\"`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[match.end():index]
    raise AssertionError(f"data/app.js: unterminated function {name}")


def check_markup(errors: list[str]) -> None:
    parsed = {name: parse_page(name) for name in PAGES}
    for name, (source, parser) in parsed.items():
        if parser.root_lang != "ru":
            errors.append(f"data/{name}: html lang must be ru")
        duplicates = sorted(key for key, count in Counter(parser.ids).items() if count > 1)
        if duplicates:
            errors.append(f"data/{name}: duplicate static IDs: {duplicates}")
        for tag, attrs in parser.tags:
            tabindex = attrs.get("tabindex")
            if tabindex is not None and re.fullmatch(r"[+-]?\d+", tabindex.strip()):
                if int(tabindex) > 0:
                    errors.append(f"data/{name}: positive tabindex on {tag}")
            for event_name in ("onkeydown", "onkeyup", "onkeypress"):
                if event_name in attrs:
                    errors.append(f"data/{name}: inline {event_name} on {tag}")
        if KEY_LISTENER_REGISTRATION.search(source):
            errors.append(f"data/{name}: key listener registration")

    for name in MODE_PAGES:
        source, _ = parsed[name]
        requirements = (
            ("history-trigger", "SamovarApp.showHistory()", 'aria-controls="historyBox"', 'aria-expanded="false"'),
            ("history-clear", "SamovarApp.clearHistory()"),
            ("messages-clear", "SamovarApp.clearMessages()", 'aria-controls="messages"'),
        )
        for required in requirements:
            class_name, handler, *tokens = required
            match = re.search(
                rf"<button\b(?=[^>]*\bclass=['\"][^'\"]*\b{class_name}\b)[^>]*>", source, re.I
            )
            if not match or "type=\"button\"" not in match.group(0).replace("'", '"'):
                errors.append(f"data/{name}: missing native {class_name} button")
                continue
            tag = match.group(0).replace("'", '"')
            if handler not in tag or any(token not in tag for token in tokens):
                errors.append(f"data/{name}: {class_name} contract mismatch")
        if re.search(r"<div\b[^>]*onclick=['\"]SamovarApp\.(?:showHistory|clearHistory|clearMessages)", source, re.I):
            errors.append(f"data/{name}: click-only history/message div remains")

    for name in ("program.htm", "chart.htm"):
        source, _ = parsed[name]
        match = re.search(r"<button\b(?=[^>]*\bclass=['\"][^'\"]*\bmessages-clear\b)[^>]*>", source, re.I)
        if not match or "SamovarApp.clearMessages()" not in match.group(0):
            errors.append(f"data/{name}: missing native messages-clear button")

    setup_source, setup = parsed["setup.htm"]
    for name in SETUP_CONTROLS:
        controls = [attrs for tag, attrs in setup.tags if tag in ("input", "select", "textarea") and attrs.get("name") == name]
        if len(controls) != 1 or controls[0].get("id") != name:
            errors.append(f"data/setup.htm: {name} must have exact id=name")
        if setup.labels.count(name) != 1:
            errors.append(f"data/setup.htm: {name} must have one label[for]")
    if not re.search(
        r"<output\s+id=['\"]PackDensDisplay['\"]\s+name=['\"]PackDensDisplay['\"]\s+for=['\"]PackDens['\"]>%PackDens%</output>",
        setup_source,
    ):
        errors.append("data/setup.htm: PackDensDisplay output contract mismatch")
    if setup.ids.count("selftest") != 1 or setup.ids.count("scanSensorsButton") != 1:
        errors.append("data/setup.htm: selftest/scanSensorsButton IDs are not unique")
    if setup.ids.count("rescanSensors") != 0:
        errors.append("data/setup.htm: rescanSensors function name must not be used as an ID")

    for page, control_ids in PAGE_LABELS.items():
        labels = parsed[page][1].labels
        for control_id in control_ids:
            if labels.count(control_id) != 1:
                errors.append(f"data/{page}: {control_id} must have one visible label[for]")
    for page in ("index.htm", "beer.htm", "distiller.htm", "nbk.htm"):
        source, _ = parsed[page]
        if re.search(r"<summary\b[^>]*>\s*<label\b", source, re.I):
            errors.append(f"data/{page}: summary must not contain a control label")
    for page in MODE_PAGES:
        source, _ = parsed[page]
        if not re.search(r"<label\s+for=['\"]lua_str_i['\"]>Lua:</label>", source):
            errors.append(f"data/{page}: exact visible Lua label missing")
    for page in ("beer.htm", "bk.htm"):
        source, _ = parsed[page]
        if source.count('<span id="pump-speed-label">Скорость насоса:</span>') != 1:
            errors.append(f"data/{page}: pump speed must retain one visible shared owner")
        for control_id in ("PWM", "PWMt"):
            matches = [
                attrs for tag, attrs in parsed[page][1].tags
                if tag == "input" and attrs.get("id") == control_id
            ]
            if len(matches) != 1 or matches[0].get("aria-labelledby") != "pump-speed-label":
                errors.append(f"data/{page}: {control_id} shared pump-speed ownership mismatch")

    nbk_source, nbk = parsed["nbk.htm"]
    for row in range(1, 5):
        for prefix, header in (("pspeed", "nbk-program-col-speed"), ("ppower", "programPwrLabel")):
            control_id = f"{prefix}{row}"
            matches = [attrs for tag, attrs in nbk.tags if tag == "input" and attrs.get("id") == control_id]
            expected = f"nbk-program-row-{row} {header}"
            if len(matches) != 1 or matches[0].get("aria-labelledby") != expected:
                errors.append(f"data/nbk.htm: {control_id} row/column ownership mismatch")
    if re.search(r"\b(?:pspeed|ppower)[1-4]\b[^>]*\baria-label\s*=", nbk_source):
        errors.append("data/nbk.htm: generic aria-label used for static program controls")

    for name in UPLOAD_PAGES:
        source, _ = parsed[name]
        owners = re.findall(
            r"<div\b(?=[^>]*\bclass=['\"][^'\"]*\bfile-upload-control\b)[^>]*>"
            r"([\s\S]*?)</div>",
            source,
            re.I,
        )
        pair = (
            r"<label\b(?=[^>]*\bfor=['\"]fileToLoad['\"])[^>]*>[\s\S]*?</label>"
            r"\s*<input\b(?=[^>]*\btype=['\"]file['\"])(?=[^>]*\bid=['\"]fileToLoad['\"])[^>]*>"
        )
        if len(owners) != 1 or re.fullmatch(rf"\s*{pair}\s*", owners[0], re.I) is None:
            errors.append(f"data/{name}: upload pair missing exact file-upload-control owner")
        file_tags = [attrs for tag, attrs in parsed[name][1].tags if tag == "input" and attrs.get("type") == "file"]
        if len(file_tags) != 1 or file_tags[0].get("id") != "fileToLoad":
            errors.append(f"data/{name}: native file input contract changed")

    for name in GENERATED_PAGES:
        source, _ = parsed[name]
        if source.count('document.createElement("button")') != 2:
            errors.append(f"data/{name}: plus/minus must be native generated buttons")
        for token in (
            ".type = \"button\"", '.className = "program-row-action"',
            'document.createElement("img")', '.alt = ""', "aria-labelledby",
        ):
            if token not in source:
                errors.append(f"data/{name}: generated row contract missing {token}")
        if re.search(r"document\.createElement\(['\"]img['\"]\)[\s\S]{0,180}setAttribute\(['\"]onclick", source):
            errors.append(f"data/{name}: interactive generated img remains")

    program_source, _ = parsed["program.htm"]
    for control_id in ("WProgram", "WProgram1"):
        match = re.search(rf"<textarea\b[^>]*\bid=['\"]{control_id}['\"][^>]*>", program_source)
        if not match or not re.search(r"\bhidden(?:\s|=|>)", match.group(0)):
            errors.append(f"data/program.htm: hidden transport {control_id} remains focusable")


def check_scripts(errors: list[str]) -> None:
    app = (DATA / "app.js").read_text(encoding="utf-8")
    verify_keyboard_guard(errors)
    key_listener_error = app_key_listener_error(app)
    if key_listener_error:
        errors.append(f"data/app.js: {key_listener_error}")
    apply_theme = function_body(app, "applyTheme")
    open_tab = function_body(app, "openTab")
    show_history = function_body(app, "showHistory")
    render_message = function_body(app, "renderMessage")
    for token in (
        "Включить тёмную тему", "Включить светлую тему", "aria-label", "aria-pressed",
    ):
        if token not in apply_theme:
            errors.append(f"data/app.js: applyTheme missing {token}")
    if "aria-hidden" not in open_tab or "aria-pressed" not in open_tab:
        errors.append("data/app.js: openTab semantic state missing")
    if "aria-expanded" not in show_history:
        errors.append("data/app.js: showHistory aria-expanded state missing")
    for token in ('<button type="button"', "message-dismiss", "SamovarApp.removeLastMessage()"):
        if token not in render_message:
            errors.append(f"data/app.js: renderMessage missing {token}")
    # setup.htm and i2cstepper.htm no longer keep local copies of openTab/applyTheme; they
    # delegate to the shared, already ARIA-verified app.js implementations above. Confirm the
    # delegation wiring is actually present instead of re-checking duplicated logic.
    setup = (DATA / "setup.htm").read_text(encoding="utf-8")
    if "SamovarApp.openTab(" not in setup:
        errors.append("data/setup.htm: tab buttons do not delegate to SamovarApp.openTab")
    if "SamovarApp.initTheme(" not in setup or "SamovarApp.toggleTheme(" not in setup:
        errors.append("data/setup.htm: theme toggle does not delegate to SamovarApp")
    i2c = (DATA / "i2cstepper.htm").read_text(encoding="utf-8")
    if "SamovarApp.initTheme(" not in i2c or "SamovarApp.toggleTheme(" not in i2c:
        errors.append("data/i2cstepper.htm: theme toggle does not delegate to SamovarApp")


def check_css(errors: list[str]) -> None:
    css = (DATA / "style.css").read_text(encoding="utf-8")
    css_rules = re.findall(r"([^{}]+)\{([^{}]*)\}", css, re.S)
    file_rule = next(
        (body for selector, body in css_rules
         if re.search(r"input\[type=['\"]?file['\"]?\]", selector, re.I)),
        None,
    )
    if file_rule is None or re.search(r"display\s*:\s*none", file_rule, re.I):
        errors.append("data/style.css: native file input is not visually-hidden/focusable")
    focus_rules = re.findall(r"([^{}]*:focus(?:-visible|-within)[^{}]*)\{([^{}]*)\}", css, re.I)
    merged = [selector for selector, body in focus_rules
              if "a[href]:focus-visible" in selector and
              ".file-upload-control:focus-within .custom-file-upload" in selector and
              "outline" in body.lower()]
    if len(merged) != 1:
        errors.append("data/style.css: exact merged focus contract missing")
    if re.search(r"outline\s*:\s*(?:none|0)(?:\D|$)", css, re.I):
        errors.append("data/style.css: focus outline disabled")
    target_rule = re.search(
        r"([^{}]*\.theme-toggle[^{}]*\.program-row-action[^{}]*)\{([^{}]*)\}", css, re.I | re.S
    )
    compact = re.sub(r"\s+", "", target_rule.group(2)).lower() if target_rule else ""
    if "min-width:44px" not in compact or "min-height:44px" not in compact:
        errors.append("data/style.css: 44x44 actual-target rule missing")
    for width in (900, 600):
        media = re.search(
            rf"@media\s*\(max-width:\s*{width}px\)\s*\{{([\s\S]*?)(?=\n\}})",
            css,
            re.I,
        )
        if not media or re.search(
            r"\.tab\s+input\s*\{[^{}]*min-height\s*:\s*44px", media.group(1), re.I
        ) is None:
            errors.append(f"data/style.css: {width}px tab override must retain 44px height")
    row_rules = [
        body for selector, body in css_rules if ".program-row-action" in selector
    ]
    if any(re.search(r"min-width\s*:\s*0(?:\D|$)", body, re.I) for body in row_rules):
        errors.append("data/style.css: responsive program-row action cancels 44px width")
    if not any(re.search(r"min-width\s*:\s*44px", body, re.I) for body in row_rules):
        errors.append("data/style.css: responsive program-row action lacks 44px width")
    if re.search(r"\.message-dismiss\s*\{[^{}]*\bfont\s*:", css, re.I):
        errors.append("data/style.css: message-dismiss resets inherited message font size")


def check_projection(errors: list[str]) -> None:
    source = (DATA / "style.css").read_bytes()
    stored = (BUILD / "style.css.gz").read_bytes()
    expected = canonical_gzip(source)
    if stored != expected or stored[:10].hex() != "1f8b08000000000002ff":
        errors.append("data/style.css.gz: canonical projection mismatch")
    try:
        stream = zlib.decompressobj(wbits=31)
        expanded = stream.decompress(stored) + stream.flush()
        if not stream.eof or stream.unused_data or expanded != source or gzip.decompress(stored) != source:
            errors.append("data/style.css.gz: single-member decompression mismatch")
    except (OSError, RuntimeError, ValueError, zlib.error) as error:
        errors.append(f"manifest/gzip projection error: {error}")
    for name, expected_hash in FROZEN.items():
        # .gz - продукт сборки, сырьё - источник.
        source = (BUILD if name.endswith(".gz") else DATA) / name
        actual = digest(source)
        if actual != expected_hash:
            errors.append(f"data/{name}: frozen SHA changed: {actual}")


def main() -> int:
    errors: list[str] = []
    checks = (check_markup, check_scripts, check_css, check_projection)
    for check in checks:
        try:
            check(errors)
        except (AssertionError, OSError, UnicodeError, re.error) as error:
            errors.append(f"{check.__name__} harness failure: {error}")
    if errors:
        for error in errors:
            print(f"U-05 accessibility static failure: {error}", file=sys.stderr)
        print(f"U-05 accessibility static smoke failed: {len(errors)} failures", file=sys.stderr)
        return 1
    print("U-05 accessibility static smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
