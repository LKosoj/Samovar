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
        "copy_web_message_raw",
        "set_lua_status_value",
        "copy_lua_status",
        "copy_ajax_runtime_snapshot",
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
    for token in ["SessionDescription", "Lua_status", "program_Wait_Type"]:
        uses = find_token_uses("Samovar.h", token)
        if not uses:
            errors.append(f"Samovar.h missing shared global declaration: {token}")
        elif len(uses) != 1:
            errors.append(f"Samovar.h has unexpected extra uses of shared global {token}: {uses}")
    for token in ["Msg", "LogMsg", "msg_level"]:
        uses = find_token_uses("Samovar.h", token)
        if uses:
            errors.append(f"Samovar.h retains obsolete shared global {token}: {uses}")

for name in ["WebServer.ino", "Samovar.ino", "lua.h", "Menu.ino", "BK.h", "beer.h", "distiller.h", "nbk.h", "logic.h", "impurity_detector.h"]:
    if token_use_count(name, "pending_program_str") != 0:
        errors.append(f"{name} reintroduces forbidden raw pending_program_str storage")
    for token in ["SessionDescription", "Lua_status", "program_Wait_Type"]:
        if name == "Samovar.ino" and token == "SessionDescription":
            if token_use_count(name, token) != 1:
                errors.append(
                    "Samovar.ino owner commit must have exactly one locked SessionDescription write")
            continue
        if token_use_count(name, token) != 0:
            errors.append(f"{name} uses shared token {token} outside runtime helpers")
    for token in ["Msg", "LogMsg", "msg_level"]:
        if token_use_count(name, token) != 0:
            errors.append(f"{name} uses shared token {token} outside runtime message helpers")

if web_text:
    try:
        queue_body = extract_function_body(web_text, "static OperationError queue_profile_operation(")
        require_ordered_tokens(
            "queue_profile_operation copies validated POD under pending lock",
            queue_body,
            [
                "pending_command_lock",
                "operation_store_reserve_locked(",
                "reset_profile_operation_slot();",
                "active_profile_operation.program = *programDraft;",
                "profile_operation_phase_store(PROFILE_OPERATION_QUEUED);",
                "pending_command_unlock(true);",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))
    try:
        web_program_body = extract_function_body(web_text, "void web_program")
        require_ordered_tokens(
            "web_program stages bounded SessionDescription metadata",
            web_program_body,
            [
                'char descriptionValue[251] = "";',
                "description.length() > 250",
                "memcpy(descriptionValue, description.c_str(), description.length());",
                "metadataFlags |= PROFILE_OPERATION_METADATA_DESCRIPTION;",
                "queue_profile_operation(",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))

if samovar_text:
    try:
        signature = "static OperationError commit_profile_operation()"
        offset = samovar_text.rfind(signature)
        if offset < 0:
            raise ValueError(f"function not found: {signature}")
        commit_body = extract_function_body(samovar_text[offset:], signature)
        require_ordered_tokens(
            "owner commit locks metadata before program/description publication",
            commit_body,
            [
                "runtime_state_lock(pdMS_TO_TICKS(500))",
                "program_commit(active_profile_operation.program);",
                "SessionDescription = escapedDescription;",
                "runtime_state_unlock(runtimeLocked);",
            ],
            errors,
        )
        if "program_clear();" not in commit_body:
            errors.append("owner commit lost standalone clear")
    except ValueError as exc:
        errors.append(str(exc))

if lua_text:
    if "static bool lua_str_set_Msg" in lua_text:
        errors.append("Lua retains obsolete boolean Msg setter")
    if '{"Msg", lua_str_get_Msg, nullptr, LUA_VAR_RW, "Msg busy"}' not in lua_text:
        errors.append("Lua Msg descriptor lost specialized typed setter shape")
    try:
        set_str_body = extract_function_body(lua_text, "static int lua_wrapper_set_str_variable(")
        require_ordered_tokens(
            "Lua Msg setter maps typed runtime event results",
            set_str_body,
            [
                'if (Var == "Msg")',
                "append_web_message(Val, NOTIFY_MSG)",
                "RUNTIME_EVENT_PUBLISH_LOCK_BUSY",
                '"Msg busy"',
                "RUNTIME_EVENT_PUBLISH_TEXT_TOO_LONG",
                '"Msg too long"',
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
