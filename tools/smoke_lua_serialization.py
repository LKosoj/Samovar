#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def forbid_tokens(name: str, body: str, tokens: list[str]) -> None:
    for token in tokens:
        if token in body:
            errors.append(f"{name} contains forbidden token: {token}")


lua_text = strip_cpp_comments(read_text("lua.h"))
samovar_text = strip_cpp_comments(read_text("Samovar.ino"))
web_text = strip_cpp_comments(read_text("WebServer.ino"))

if lua_text:
    if lua_text.count("Lua_dostring(") != 1:
        errors.append("Lua_dostring must appear exactly once")
    try:
        body = extract_function_body(lua_text, "inline String lua_exec_locked")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    if "lua.Lua_dostring(&script)" not in body:
        errors.append("lua_exec_locked does not own Lua_dostring")

    try:
        body = extract_function_body(lua_text, "String run_lua_string")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    forbid_tokens("run_lua_string", body, ["lua_exec(", "lua_exec_locked(", "Lua_dostring("])
    for token in ["queue_lua_inline_job", "Lua busy"]:
        if token not in body:
            errors.append(f"run_lua_string missing queued-job contract: {token}")

    try:
        body = extract_function_body(lua_text, "void run_lua_script")
    except ValueError as exc:
        try:
            body = extract_function_body(lua_text, "bool run_lua_script")
        except ValueError:
            errors.append(str(exc))
            body = ""
    forbid_tokens("run_lua_script", body, ["btn_script ="])
    for token in ["queue_lua_script_job", "Lua busy"]:
        if token not in body:
            errors.append(f"run_lua_script missing queued-job contract: {token}")

    try:
        body = extract_function_body(lua_text, "void start_lua_script")
    except ValueError as exc:
        try:
            body = extract_function_body(lua_text, "bool start_lua_script")
        except ValueError:
            errors.append(str(exc))
            body = ""
    forbid_tokens("start_lua_script", body, ["lua_finished ="])
    for token in ["request_lua_periodic_start", "Lua busy"]:
        if token not in body:
            errors.append(f"start_lua_script missing request contract: {token}")

    try:
        body = extract_function_body(lua_text, "void do_lua_script")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(
        "Lua task handles one-shot jobs before periodic scripts",
        body,
        [
            "take_lua_job",
            "lua_exec_locked",
            "consume_lua_periodic_start_request",
            "lua_periodic_active",
        ],
        errors,
    )
    for token in ["btn_script", "lua_finished = false;"]:
        if token in body:
            errors.append(f"do_lua_script still uses legacy Lua state token: {token}")
    try:
        job_body, _ = extract_braced_block_after(body, "if (take_lua_job")
        if "if (ota_running)" in job_body:
            errors.append("do_lua_script can drop a taken one-shot Lua job during OTA")
    except ValueError as exc:
        errors.append(str(exc))

    try:
        body = extract_function_body(lua_text, "static int lua_wrapper_set_capacity")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    if body:
        require_ordered_tokens(
            "Lua setCapacity validates before uint8_t cast",
            body,
            [
                "int a = luaL_checkinteger(lua_state, 1);",
                "a < 0 || a > CAPACITY_NUM",
                "return luaL_error(lua_state, \"capacity out of range\");",
                "set_capacity((uint8_t)a);",
            ],
            errors,
        )
        forbid_tokens(
            "lua_wrapper_set_capacity",
            body,
            [
                "uint8_t a = luaL_checknumber",
                "uint8_t a = luaL_checkinteger",
                "set_capacity(a);",
            ],
        )

if samovar_text:
    try:
        body = extract_function_body(samovar_text, "void triggerSysTicker(void *parameter)")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    forbid_tokens(
        "triggerSysTicker",
        body,
        [
            "start_lua_script",
            "run_lua_script",
            "run_lua_string",
            "lua_exec",
            "Lua_dostring",
            "btn_script",
            "lua_finished",
        ],
    )
    try:
        body = extract_function_body(samovar_text, "void loop()")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    if body:
        require_ordered_tokens(
            "pending Lua start flag is cleared only after request success",
            body,
            [
                "if (locked && pending_lua_start_flag) {",
                "hasPendingLuaStart = true;",
                "if (start_lua_script()) {",
                "if (locked && pending_lua_start_flag) {",
                "pending_lua_start_flag = false;",
            ],
            errors,
        )
        try:
            start_body, _ = extract_braced_block_after(body, "if (locked && pending_lua_start_flag)")
            if "pending_lua_start_flag = false;" in start_body:
                errors.append("pending_lua_start_flag is cleared before Lua start request succeeds")
        except ValueError as exc:
            errors.append(str(exc))
        require_ordered_tokens(
            "pending Lua file flag is cleared only after queue success",
            body,
            [
                "if (locked && pending_lua_file_flag) {",
                "luaFile = pending_lua_file;",
                "hasPendingLuaFile = true;",
                "if (run_lua_script(luaFile)) {",
                "if (locked && pending_lua_file_flag && pending_lua_file == luaFile) {",
                "pending_lua_file_flag = false;",
            ],
            errors,
        )
        try:
            file_body, _ = extract_braced_block_after(body, "if (locked && pending_lua_file_flag)")
            if "pending_lua_file_flag = false;" in file_body:
                errors.append("pending_lua_file_flag is cleared before Lua job is queued")
        except ValueError as exc:
            errors.append(str(exc))
        require_ordered_tokens(
            "pending Lua inline flag is cleared only after queue success",
            body,
            [
                "if (locked && pending_lua_flag) {",
                "lstr = pending_lua_str;",
                "hasPendingLuaString = true;",
                "if (run_lua_string(lstr).length() == 0) {",
                "if (locked && pending_lua_flag && pending_lua_str == lstr) {",
                "pending_lua_flag = false;",
            ],
            errors,
        )
        try:
            inline_body, _ = extract_braced_block_after(body, "if (locked && pending_lua_flag)")
            if "pending_lua_flag = false;" in inline_body:
                errors.append("pending_lua_flag is cleared before Lua inline job is queued")
        except ValueError as exc:
            errors.append(str(exc))

if web_text:
    try:
        body = extract_function_body(web_text, "void web_command(AsyncWebServerRequest *request)")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    forbid_tokens("web_command", body, ["run_lua_script(", "run_lua_string(", "lua_exec(", "Lua_dostring("])
    if re.search(r"run_lua_script\s*\(|run_lua_string\s*\(|lua_exec\s*\(|Lua_dostring\s*\(", web_text):
        errors.append("WebServer.ino contains direct Lua execution")

if errors:
    print("Lua serialization smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("Lua serialization smoke check passed")
