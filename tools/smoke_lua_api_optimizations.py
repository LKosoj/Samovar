#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


lua_text = strip_cpp_comments(read_text("lua.h"))

if lua_text:
    for token in [
        "struct LuaNumVariableDescriptor",
        "static const LuaNumVariableDescriptor lua_num_variables[]",
        "find_lua_num_variable",
        "struct LuaStrVariableDescriptor",
        "static const LuaStrVariableDescriptor lua_str_variables[]",
        "find_lua_str_variable",
        "lua_compile_chunk_locked",
        "lua_exec_chunk_locked",
        "luaL_loadbuffer",
        "luaL_ref",
        "luaL_unref",
        "lua_rawgeti",
        "lua_pcall",
        "lua_install_constants_locked",
        'lua_set_number_global_locked("INPUT", INPUT)',
        'lua_set_number_global_locked("OUTPUT", OUTPUT)',
        'lua_set_number_global_locked("LOW", LOW)',
        'lua_set_number_global_locked("HIGH", HIGH)',
    ]:
        if token not in lua_text:
            errors.append(f"lua.h missing Lua variable descriptor contract: {token}")

    for function_name in [
        "lua_wrapper_millis",
        "lua_wrapper_get_state",
        "lua_wrapper_get_num_variable",
        "lua_wrapper_get_str_variable",
        "lua_wrapper_get_object",
    ]:
        try:
            body = extract_function_body(lua_text, f"static int {function_name}")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if "vTaskDelay" in body:
            errors.append(f"{function_name} is a pure/read-only Lua wrapper and must not yield")

    for function_name in [
        "lua_wrapper_http_request",
        "lua_wrapper_exp_analogRead",
        "lua_wrapper_set_stepper_target",
        "lua_wrapper_i2cpump_start",
    ]:
        try:
            body = extract_function_body(lua_text, f"static int {function_name}")
        except ValueError:
            continue
        if "vTaskDelay" not in body:
            errors.append(f"{function_name} touches slow IO/hardware and must keep an explicit yield")

    for function_name in [
        "lua_wrapper_set_num_variable",
        "lua_wrapper_get_num_variable",
        "lua_wrapper_set_str_variable",
        "lua_wrapper_get_str_variable",
    ]:
        try:
            body = extract_function_body(lua_text, f"static int {function_name}")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        dispatch_names = re.findall(
            r'\b(?:if|else\s+if)\s*\(\s*Var\s*==\s*"([^"]+)"',
            body,
        )
        expected_dispatch_names = (
            ["Msg"] if function_name == "lua_wrapper_set_str_variable" else []
        )
        if dispatch_names != expected_dispatch_names:
            errors.append(
                f"{function_name} has unexpected Lua variable dispatch: {dispatch_names!r}"
            )
        if function_name == "lua_wrapper_set_str_variable":
            msg_branch = body.find('if (Var == "Msg")')
            descriptor_path = body.find("find_lua_str_variable(Var)")
            if msg_branch < 0 or descriptor_path < msg_branch:
                errors.append(
                    "lua_wrapper_set_str_variable lost Msg-before-descriptor dispatch order"
                )

    for function_name in [
        "lua_wrapper_set_str_variable",
        "lua_wrapper_set_object",
        "lua_wrapper_set_lua_status",
    ]:
        try:
            body = extract_function_body(lua_text, f"static int {function_name}")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        mutation_gate = body.find("lua_reject_state_mutation(lua_state)")
        first_string = body.find("String ")
        if mutation_gate < 0 or first_string < 0 or mutation_gate > first_string:
            errors.append(
                f"{function_name} must reject state mutation before creating Arduino String"
            )

    try:
        body = extract_function_body(lua_text, "static int lua_wrapper_set_str_variable")
        deferred_error = body.find(
            'if (errorMessage) return luaL_error(lua_state, "%s", errorMessage);'
        )
        for token in [
            "const char* errorMessage = nullptr;",
            "String Var = lua_to_string_arg(lua_state, 1);",
            "String Val = lua_to_string_arg(lua_state, 2);",
            'errorMessage = "Msg busy";',
            'errorMessage = "Msg too long";',
            'errorMessage = "Msg event store corrupt";',
        ]:
            if token not in body:
                errors.append(f"lua_wrapper_set_str_variable missing deferred-error token: {token}")
        if deferred_error < 0 or "luaL_error" in body[:deferred_error]:
            errors.append(
                "lua_wrapper_set_str_variable must defer every direct Lua error until String destruction"
            )
        elif not re.search(
            r'}\s*if \(errorMessage\) return luaL_error\(lua_state, "%s", errorMessage\);',
            body,
        ):
            errors.append(
                "lua_wrapper_set_str_variable deferred error is not outside the String scope"
            )
    except ValueError as exc:
        errors.append(str(exc))

    try:
        body = extract_function_body(lua_text, "static int lua_wrapper_set_lua_status")
        deferred_error = body.find(
            'if (!statusSet) return luaL_error(lua_state, "Lua_status busy");'
        )
        if deferred_error < 0 or "luaL_error" in body[:deferred_error]:
            errors.append(
                "lua_wrapper_set_lua_status must report busy only after String destruction"
            )
        elif not re.search(
            r'}\s*if \(!statusSet\) return luaL_error\(lua_state, "Lua_status busy"\);',
            body,
        ):
            errors.append(
                "lua_wrapper_set_lua_status busy error is not outside the String scope"
            )
    except ValueError as exc:
        errors.append(str(exc))

    if lua_text.count('lua_getglobal(lua_state, "tostring")') != 1:
        errors.append("Lua wrappers must convert arguments through lua_to_string_arg only")

    try:
        body = extract_function_body(lua_text, "void load_lua_script")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    for token in [
        'lua_compile_chunk_locked(s1, "@script.lua", script1_ref)',
        "lua_compile_chunk_locked(s2, modeChunkName.c_str(), script2_ref)",
        "runtime_state_lock(portMAX_DELAY)",
    ]:
        if token not in body:
            errors.append(f"load_lua_script missing compiled reload token: {token}")

    try:
        body = extract_function_body(lua_text, "void do_lua_script")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    for token in [
        "lua_exec_chunk_locked(local_script1_ref)",
        "lua_exec_chunk_locked(local_script2_ref, true)",
    ]:
        if token not in body:
            errors.append(f"do_lua_script missing compiled execution token: {token}")
    for token in [
        "lua_exec_locked(local_s1)",
        "lua_exec_locked(local_s2",
        "Lua_dostring(&local_s1",
        "Lua_dostring(&local_s2",
    ]:
        if token in body:
            errors.append(f"do_lua_script still reparses periodic Lua source: {token}")

if errors:
    print("Lua API optimization smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Lua API optimization smoke passed")
