#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def strip_comments_and_literals(source: str) -> str:
    result: list[str] = []
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
    escaped = False
    index = 0
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                result.append("\n")
            else:
                result.append(" ")
            index += 1
            continue
        if in_block_comment:
            if char == "*" and next_char == "/":
                result.extend("  ")
                in_block_comment = False
                index += 2
            else:
                result.append("\n" if char == "\n" else " ")
                index += 1
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            result.append("\n" if char == "\n" else " ")
            index += 1
            continue
        if in_char:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                in_char = False
            result.append("\n" if char == "\n" else " ")
            index += 1
            continue
        if char == "/" and next_char == "/":
            result.extend("  ")
            in_line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            result.extend("  ")
            in_block_comment = True
            index += 2
            continue
        if char == '"':
            in_string = True
            result.append(" ")
            index += 1
            continue
        if char == "'":
            in_char = True
            result.append(" ")
            index += 1
            continue
        result.append(char)
        index += 1
    return "".join(result)


def find_token_uses(name: str, token: str) -> list[int]:
    text = read_text(name)
    if not text:
        return []
    stripped = strip_comments_and_literals(text)
    pattern = re.compile(rf"\b{re.escape(token)}\b")
    return [line_no for line_no, line in enumerate(stripped.splitlines(), 1) if pattern.search(line)]


def token_use_count(name: str, token: str) -> int:
    return len(find_token_uses(name, token))


runtime_text = read_text("runtime_helpers.h")
samovar_h_text = read_text("Samovar.h")
samovar_text = read_text("Samovar.ino")
web_text = read_text("WebServer.ino")
lua_text = read_text("lua.h")

if runtime_text:
    for fn in [
        "copy_program_wait_type",
        "copy_program_wait_type_text",
        "set_program_wait_type",
        "copy_session_description",
        "set_session_description_value",
        "copy_mqtt_session_description",
        "set_web_message_raw",
        "copy_web_message_raw",
        "set_lua_status_value",
        "copy_lua_status",
        "consume_ajax_runtime_snapshot",
        "append_web_message",
        "append_console_log",
    ]:
        if fn not in runtime_text:
            errors.append(f"runtime_helpers.h missing shared-state helper: {fn}")
    try:
        mqtt_body = extract_function_body(runtime_text, "inline bool copy_mqtt_session_description")
        require_ordered_tokens(
            "copy_mqtt_session_description copies then sanitizes local description",
            mqtt_body,
            [
                "description = SessionDescription;",
                "runtime_state_unlock(true);",
                'description.replace(",", ";");',
            ],
            errors,
        )
        if 'SessionDescription.replace' in mqtt_body:
            errors.append("copy_mqtt_session_description mutates global SessionDescription")
    except ValueError as exc:
        errors.append(str(exc))

if samovar_h_text:
    for token in ["SessionDescription", "Lua_status", "Msg", "LogMsg", "msg_level", "program_Wait_Type"]:
        uses = find_token_uses("Samovar.h", token)
        if not uses:
            errors.append(f"Samovar.h missing shared global declaration: {token}")
        elif len(uses) != 1:
            errors.append(f"Samovar.h has unexpected extra uses of shared global {token}: {uses}")

for name in ["WebServer.ino", "Samovar.ino", "lua.h", "Menu.ino", "BK.h", "beer.h", "distiller.h", "nbk.h", "logic.h", "impurity_detector.h"]:
    if name == "Samovar.ino":
        if token_use_count(name, "pending_program_str") != 2:
            errors.append("Samovar.ino must only declare pending_program_str and copy it in loop()")
    elif name == "WebServer.ino":
        if token_use_count(name, "pending_program_str") != 2:
            errors.append("WebServer.ino must only write pending_program_str from pending queue helpers")
    elif token_use_count(name, "pending_program_str") != 0:
        errors.append(f"{name} uses pending_program_str outside the pending command owner files")
    for token in ["SessionDescription", "Lua_status", "program_Wait_Type"]:
        if token_use_count(name, token) != 0:
            errors.append(f"{name} uses shared token {token} outside runtime helpers")
    for token in ["Msg", "LogMsg", "msg_level"]:
        if token_use_count(name, token) != 0:
            errors.append(f"{name} uses shared token {token} outside runtime message helpers")

if web_text:
    try:
        queue_body = extract_function_body(web_text, "static bool queue_pending_program")
        require_ordered_tokens(
            "queue_pending_program serializes pending_program_str before flag",
            queue_body,
            [
                "pending_command_lock",
                "pending_program_mode != PPM_NONE",
                "pending_program_str = programText;",
                "__sync_synchronize();",
                "pending_program_mode = mode;",
                "pending_command_unlock(true);",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))
    try:
        setup_body = extract_function_body(web_text, "static bool queue_pending_setup_save")
        require_ordered_tokens(
            "queue_pending_setup_save checks pending program slot before storing program text",
            setup_body,
            [
                "pending_command_lock",
                "pending_save_profile_flag",
                "pending_program_mode != PPM_NONE",
                "pending_program_str = programText;",
                "__sync_synchronize();",
                "pending_save_profile_flag = true;",
                "pending_program_mode = programMode;",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))
    try:
        web_program_body = extract_function_body(web_text, "void web_program")
        require_ordered_tokens(
            "web_program writes SessionDescription through helper",
            web_program_body,
            [
                "String description = request->arg(\"Descr\");",
                "description.replace(\"%\", \"&#37;\");",
                "set_session_description_value(description",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))

if samovar_text:
    try:
        loop_body = extract_function_body(samovar_text, "void loop()")
        require_ordered_tokens(
            "loop copies pending_program_str under pending_command_lock before applying",
            loop_body,
            [
                "pending_command_lock",
                "pending_program_mode != PPM_NONE",
                "pstr = pending_program_str;",
                "pending_program_mode = PPM_NONE;",
                "pending_command_unlock(locked);",
                "if (ppm != PPM_NONE) {",
                "program_update_session_active()",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))

if lua_text:
    try:
        set_str_body = extract_function_body(lua_text, "static bool lua_str_set_Msg")
        require_ordered_tokens(
            "Lua Msg setter uses shared-state helper",
            set_str_body,
            [
                "set_web_message_raw(value)",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))
    try:
        get_str_body = extract_function_body(lua_text, "static bool lua_str_get_Msg")
        require_ordered_tokens(
            "Lua Msg getter uses shared-state helper",
            get_str_body,
            [
                "copy_web_message_raw(value)",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))
    try:
        lua_status_body = extract_function_body(lua_text, "static int lua_wrapper_set_lua_status")
        if "set_lua_status_value(Var)" not in lua_status_body:
            errors.append("Lua_status wrapper does not use set_lua_status_value")
    except ValueError as exc:
        errors.append(str(exc))

if errors:
    print("Shared-state string smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("Shared-state string smoke check passed")
