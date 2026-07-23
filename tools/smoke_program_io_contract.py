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
sensorinit = strip_cpp_comments(read_text("sensorinit.h"))
samovar_api = strip_cpp_comments(read_text("samovar_api.h"))
blynk = strip_cpp_comments(read_text("Blynk.ino"))

if program_io:
    require_token("program_io.h", program_io, '#include "numeric_parse.h"')
    forbid_token("program_io.h", program_io, "parseFloatSafe(")
    forbid_token("program_io.h", program_io, "parseLongSafe(")
    for token in [
        "enum ProgramFieldKind",
        "enum ProgramFormat",
        "enum ProgramUpdateAction",
        "struct ProgramDraft",
        "struct ProgramParseSpec",
        "using ProgramRowParser",
        "inline void program_reset_draft",
        "inline void program_commit",
        "inline void program_clear()",
        "inline String format_program_parse_error",
        "inline ProgramFormat program_format_for_mode",
        "inline ProgramParseResult prepare_program_for_mode",
        "inline String serialize_program_for_mode",
        "inline ProgramParseResult program_parse_lines",
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

    for token in [
        "PROGRAM_FORMAT_UNSUPPORTED",
        "PROGRAM_PARSE_UNSUPPORTED_MODE",
        "case SAMOVAR_SUVID_MODE:",
        "case SAMOVAR_LUA_MODE:",
        "inline size_t program_count_char",
    ]:
        require_token("program_io.h program update contract", program_io, token)

    try:
        body = extract_function_body(program_io, "inline ProgramParseResult program_parse_lines")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(
        "program_parse_lines shared skeleton",
        body,
        [
            "program_reset_draft(draft);",
            "text.length() == 0",
            "text.length() > MAX_PROGRAM_INPUT_LEN",
            "copyStringSafe(input, text)",
            "while (*cursor != '\\0')",
            "program_trim_line_right(line)",
            "i >= spec.maxRows || i >= PROGRAM_END",
            "program_count_char(line, ';') != static_cast<size_t>(spec.fieldCount - 1)",
            "spec.parseRow(line, lineLen, i, draft.rows[i], spec, rowErrorMessage)",
            "i++;",
            "draft.len = i;",
            "i == 0",
            "spec.expectedRowCount > 0 && i != spec.expectedRowCount",
            "PROGRAM_PARSE_OK",
        ],
        errors,
    )
    for forbidden in ["program[", "ProgramLen", "SendMsg("]:
        forbid_token("program_parse_lines draft isolation", body, forbidden)

    try:
        body = extract_function_body(program_io, "inline void program_commit")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(
        "program_commit publishes only validated draft",
        body,
        [
            "i < draft.len",
            "program[i] = draft.rows[i];",
            "i = draft.len",
            "program[i].WType = PROGRAM_TYPE_NONE;",
            "ProgramLen = draft.len;",
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
    require_token("beer serializer keeps fractional time", body, "out += (String)row.Time + \";\";")
    forbid_token("beer serializer keeps fractional time", body, "(int)row.Time")

wrappers = [
    ("logic.h", logic, "ProgramParseResult set_program", "return program_parse_lines(WProgram, rect_program_parse_spec());"),
    ("logic.h", logic, "String get_program", "program_serialize_rows(s, k, program_append_rect_row)"),
    ("distiller.h", distiller, "ProgramParseResult set_dist_program", "return program_parse_lines(WProgram, dist_program_parse_spec());"),
    ("distiller.h", distiller, "String get_dist_program", "program_serialize_rows(0, PROGRAM_END, program_append_dist_row)"),
    ("beer.h", beer, "ProgramParseResult set_beer_program", "return program_parse_lines(WProgram, beer_program_parse_spec());"),
    ("beer.h", beer, "String get_beer_program", "program_serialize_rows(0, PROGRAM_END, program_append_beer_row)"),
    ("nbk.h", nbk, "ProgramParseResult set_nbk_program", "return program_parse_lines(WProgram, nbk_program_parse_spec());"),
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

if sensorinit:
    try:
        prepare_default = extract_function_body(
            sensorinit,
            "ProgramParseResult prepare_default_program_for_mode",
        )
        load_default = extract_function_body(
            sensorinit,
            "ProgramParseResult load_default_program_for_mode",
        )
    except ValueError as exc:
        errors.append(str(exc))
        prepare_default = ""
        load_default = ""
    for token in [
        "case SAMOVAR_RECTIFICATION_MODE:",
        "case SAMOVAR_DISTILLATION_MODE:",
        "case SAMOVAR_BEER_MODE:",
        "case SAMOVAR_BK_MODE:",
        "case SAMOVAR_NBK_MODE:",
        "case SAMOVAR_SUVID_MODE:",
        "case SAMOVAR_LUA_MODE:",
        "PROGRAM_PARSE_UNSUPPORTED_MODE",
        "return prepare_program_for_mode(mode, String(defaultProgram), draft);",
    ]:
        require_token("checked default prepare", prepare_default, token)
    for forbidden in [
        "set_program(",
        "set_dist_program(",
        "set_beer_program(",
        "set_nbk_program(",
    ]:
        forbid_token("checked default prepare", prepare_default, forbidden)
    require_ordered_tokens(
        "checked default commit",
        load_default,
        [
            "prepare_default_program_for_mode(mode, draft)",
            "if (result.ok()) program_commit(draft);",
            "return result;",
        ],
        errors,
    )

if samovar_api:
    for token in [
        "ProgramParseResult set_nbk_program(const String& WProgram);",
        "ProgramParseResult prepare_default_program_for_mode(SAMOVAR_MODE mode, ProgramDraft& draft);",
        "ProgramParseResult load_default_program_for_mode(SAMOVAR_MODE mode);",
    ]:
        require_token("samovar_api.h program result API", samovar_api, token)

if blynk:
    require_token("Blynk.ino centralized program serializer", blynk, '#include "program_io.h"')
    try:
        blynk_v24 = extract_function_body(blynk, "BLYNK_READ(V24)")
    except ValueError as exc:
        errors.append(str(exc))
        blynk_v24 = ""
    require_token(
        "Blynk V24 centralized mode mapping",
        blynk_v24,
        "Blynk.virtualWrite(V24, serialize_program_for_mode(Samovar_Mode));",
    )
    for forbidden in [
        "get_program(",
        "get_dist_program(",
        "get_beer_program(",
        "get_nbk_program(",
        "SAMOVAR_BEER_MODE",
        "SAMOVAR_SUVID_MODE",
        "SAMOVAR_DISTILLATION_MODE",
        "SAMOVAR_NBK_MODE",
    ]:
        forbid_token("Blynk V24 centralized mode mapping", blynk_v24, forbidden)

if errors:
    print("Program IO contract smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Program IO contract smoke check passed")
