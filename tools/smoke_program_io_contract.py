#!/usr/bin/env python3
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def require_token(name: str, body: str, token: str) -> None:
    if token not in body:
        errors.append(f"{name} missing token: {token}")


def forbid_token(name: str, body: str, token: str) -> None:
    if token in body:
        errors.append(f"{name} contains forbidden token: {token}")


program_io = strip_cpp_comments(read_text("program_io.h"))
logic = strip_cpp_comments(read_text("logic.h"))
distiller = strip_cpp_comments(read_text("distiller.h"))
beer = strip_cpp_comments(read_text("beer.h"))
nbk = strip_cpp_comments(read_text("nbk.h"))

if program_io:
    for token in [
        "enum ProgramFieldKind",
        "struct ProgramParseSpec",
        "using ProgramRowParser",
        "inline void program_clear_rows()",
        "inline bool program_parse_lines",
        "inline String program_serialize_rows",
        "PROGRAM_FIELD_TYPE",
        "PROGRAM_FIELD_VOLUME",
        "PROGRAM_FIELD_SPEED",
        "PROGRAM_FIELD_CAPACITY",
        "PROGRAM_FIELD_TEMP",
        "PROGRAM_FIELD_TIME",
        "PROGRAM_FIELD_POWER",
        "PROGRAM_FIELD_TEMP_SENSOR",
        "PROGRAM_FIELD_BEER_DEVICE",
    ]:
        require_token("program_io.h", program_io, token)

    try:
        body = extract_function_body(program_io, "inline bool program_parse_lines")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(
        "program_parse_lines shared skeleton",
        body,
        [
            "program_clear_rows();",
            "ProgramLen = 0;",
            "text.length() == 0",
            "text.length() > MAX_PROGRAM_INPUT_LEN",
            "copyStringSafe(input, text)",
            "strtok_r(input, \"\\n\", &saveLine)",
            "while (line && i < spec.maxRows)",
            "program_trim_line_right(line)",
            "spec.parseRow(line, lineLen, i, program[i], spec, rowErrorMessage)",
            "i++;",
            "ProgramLen = i;",
            "spec.expectedRowCount > 0 && i != spec.expectedRowCount",
            "if (i < PROGRAM_END)",
            "program[i].WType = PROGRAM_TYPE_NONE;",
        ],
        errors,
    )

    try:
        body = extract_function_body(program_io, "inline bool program_parse_rect_row")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(
        "rect parser pause rows use parsed type",
        body,
        [
            "if (ok && parsedType != 'P' && speed <= 0.0f) ok = false;",
            "if (ok && parsedType == 'P' && volume <= 0) ok = false;",
            "row.WType = parsedType;",
            "if (parsedType == 'P')",
            "row.Time = row.Volume / 60.0f / 60.0f;",
        ],
        errors,
    )
    forbid_token("rect parser pause rows use parsed type", body, "program[rowIndex].WType")

    specs = {
        "rect_program_parse_spec": [
            "Ошибка программы: слишком длинная строка (rect)",
            "Ошибка программы: неверный формат строки rect",
            "\"HBCTP\"",
            "PROGRAM_FIELD_TYPE",
            "PROGRAM_FIELD_VOLUME",
            "PROGRAM_FIELD_SPEED",
            "PROGRAM_FIELD_CAPACITY",
            "PROGRAM_FIELD_TEMP",
            "PROGRAM_FIELD_POWER",
            "PROGRAM_END",
            "program_parse_rect_row",
        ],
        "dist_program_parse_spec": [
            "Ошибка программы: слишком длинная строка (dist)",
            "Ошибка программы: неверный формат строки dist",
            "\"TASPR\"",
            "PROGRAM_FIELD_TYPE",
            "PROGRAM_FIELD_SPEED",
            "PROGRAM_FIELD_CAPACITY",
            "PROGRAM_FIELD_POWER",
            "PROGRAM_END",
            "program_parse_dist_row",
        ],
        "beer_program_parse_spec": [
            "Ошибка программы: слишком длинная строка (beer)",
            "Ошибка программы: неверный формат строки beer",
            "\"MPBCFWLA\"",
            "PROGRAM_FIELD_TYPE",
            "PROGRAM_FIELD_TEMP",
            "PROGRAM_FIELD_TIME",
            "PROGRAM_FIELD_BEER_DEVICE",
            "PROGRAM_FIELD_TEMP_SENSOR",
            "PROGRAM_END",
            "program_parse_beer_row",
        ],
        "nbk_program_parse_spec": [
            "Ошибка программы: слишком длинная строка (nbk)",
            "Ошибка программы: неверный формат строки nbk",
            "Ошибка программы: НБК должна содержать 4 строки H/S/O/W",
            "\"HSOW\"",
            "static const ProgramType expectedTypes[NBK_PROGRAM_MAX] = {'H', 'S', 'O', 'W'};",
            "NBK_PROGRAM_MAX",
            "program_parse_nbk_row",
        ],
    }
    for signature, tokens in specs.items():
        try:
            body = extract_function_body(program_io, f"inline const ProgramParseSpec& {signature}")
        except ValueError as exc:
            errors.append(str(exc))
            body = ""
        for token in tokens:
            require_token(signature, body, token)

    try:
        body = extract_function_body(program_io, "inline bool program_parse_beer_row")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(
        "beer parser preserves device-template error",
        body,
        [
            "delimCount == 4",
            "parse_program_type(tokType, spec.allowedTypes, parsedType)",
            "program_parse_beer_device",
            "errorMessage = \"Ошибка программы: неверный шаблон устройства beer\";",
        ],
        errors,
    )

    try:
        body = extract_function_body(program_io, "inline void program_append_beer_row")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_token("beer serializer keeps legacy integer time", body, "out += (String)(int)row.Time + \";\";")
    forbid_token("beer serializer keeps legacy integer time", body, "format_beer_step_minutes")

wrappers = [
    ("logic.h", logic, "void set_program", "program_parse_lines(WProgram, rect_program_parse_spec());"),
    ("logic.h", logic, "String get_program", "program_serialize_rows(s, k, program_append_rect_row)"),
    ("distiller.h", distiller, "void set_dist_program", "program_parse_lines(WProgram, dist_program_parse_spec());"),
    ("distiller.h", distiller, "String get_dist_program", "program_serialize_rows(0, PROGRAM_END, program_append_dist_row)"),
    ("beer.h", beer, "void set_beer_program", "program_parse_lines(WProgram, beer_program_parse_spec());"),
    ("beer.h", beer, "String get_beer_program", "program_serialize_rows(0, PROGRAM_END, program_append_beer_row)"),
    ("nbk.h", nbk, "void set_nbk_program", "program_parse_lines(WProgram, nbk_program_parse_spec());"),
    ("nbk.h", nbk, "String get_nbk_program", "program_serialize_rows(0, PROGRAM_END, program_append_nbk_row)"),
]

for file_name, text, signature, token in wrappers:
    if not text:
        continue
    try:
        body = extract_function_body(text, signature)
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_token(f"{file_name}:{signature}", body, token)
    for forbidden in [
        "MAX_PROGRAM_INPUT_LEN + 1",
        "strtok_r(input, \"\\n\"",
        "program_trim_line_right",
        "parse_program_type(tokType",
    ]:
        forbid_token(f"{file_name}:{signature}", body, forbidden)

for file_name, text in [
    ("logic.h", logic),
    ("distiller.h", distiller),
    ("beer.h", beer),
    ("nbk.h", nbk),
]:
    if not text:
        continue
    for forbidden in [
        "char input[MAX_PROGRAM_INPUT_LEN + 1]",
        "strtok_r(input, \"\\n\"",
        "while (line && i < PROGRAM_END)",
        "while (line && i < NBK_PROGRAM_MAX)",
    ]:
        forbid_token(file_name, text, forbidden)

if errors:
    print("Program IO contract smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Program IO contract smoke check passed")
