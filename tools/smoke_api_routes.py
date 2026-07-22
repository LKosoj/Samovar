#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import (
    extract_braced_block_after,
    extract_function_body,
    require_ordered_tokens,
    strip_cpp_comments,
)

ROOT = Path(__file__).resolve().parents[1]
ws_file = ROOT / "WebServer.ino"
DATA = ROOT / "data_raw"
if not ws_file.exists():
    print("ERROR: WebServer.ino not found")
    sys.exit(1)

errors = []
text = ws_file.read_text(encoding="utf-8", errors="ignore")

if "Access-Control-Allow-Origin" in text:
    errors.append("WebServer.ino still sets Access-Control-Allow-Origin")
if 'DefaultHeaders::Instance().addHeader("Access-Control-Allow-Origin", "*")' in text:
    errors.append("WebServer.ino still exposes wildcard CORS through DefaultHeaders")

for direct_program_call in ["set_program(", "set_beer_program(", "set_dist_program(", "set_nbk_program("]:
    if direct_program_call in text:
        errors.append(f"WebServer.ino applies program directly: {direct_program_call}")

route_re = re.compile(r'server\.on\("(?P<path>/[^\"]*)"\s*,\s*(?P<method>HTTP_[A-Z_| ]+)')
routes = {}
for match in route_re.finditer(text):
    path = match.group("path")
    method = match.group("method").replace(" ", "")
    routes.setdefault(path, []).append(method)

required = {
    "/": None,
    "/ajax": "HTTP_GET",
    "/getlog": "HTTP_GET",
}

for path, method in required.items():
    if path not in routes:
        errors.append(f"missing route: {path}")
        continue
    if method and method not in routes[path]:
        errors.append(f"route {path} missing method {method}; found {sorted(routes[path])}")

exact_route_methods = {
    "/command": "HTTP_POST",
    "/program": "HTTP_POST",
    "/save": "HTTP_POST",
    "/calibrate": "HTTP_GET",
    "/i2cpump": "HTTP_GET",
    "/i2cstepper": "HTTP_GET",
    "/lua": "HTTP_GET",
}
for route, expected_method in exact_route_methods.items():
    matches = re.findall(
        rf'server\.on\("{re.escape(route)}"\s*,\s*(HTTP_[A-Z_]+)\s*,',
        text,
    )
    if matches != [expected_method]:
        errors.append(
            f"route {route} must be registered exactly once as "
            f"{expected_method}; found {matches}"
        )

if DATA.exists():
    for page_file in list(DATA.glob("*.htm")) + list(DATA.glob("*.js")):
        page_text = page_file.read_text(encoding="utf-8", errors="ignore")
        if "/command?" in page_text:
            errors.append(f"{page_file.relative_to(ROOT)} still references GET /command? transport")
        if re.search(r"\bfetch\s*\(\s*['\"]\/command['\"][^)]*method\s*:\s*['\"]GET['\"]", page_text, flags=re.S):
            errors.append(f"{page_file.relative_to(ROOT)} still fetches /command with GET")

# Streaming JSON contract for /ajax
ajax_handler_re = re.compile(
    r'server\.on\("/ajax"\s*,\s*HTTP_GET\s*,\s*\[\]\(AsyncWebServerRequest \*request\)\s*\{(?P<body>.*?)\n\s*\}\);',
    re.S,
)
ajax_handler = ajax_handler_re.search(text)
if not ajax_handler:
    errors.append("/ajax handler not found")
elif "send_ajax_json(request);" not in ajax_handler.group("body"):
    errors.append("/ajax handler does not use send_ajax_json(request)")

samovar_ino = ROOT / "Samovar.ino"
if samovar_ino.exists():
    samovar_text = samovar_ino.read_text(encoding="utf-8", errors="ignore")
    try:
        telemetry_writer = extract_function_body(
            samovar_text, "static void writeAjaxTelemetryFields(")
        require_ordered_tokens(
            "/ajax exposes numeric ProgramNum without localized status parsing",
            telemetry_writer,
            [
                'jsonAddKey(out, first, "ProgramNum")',
                "out.print(snapshot.programIndex + 1)",
                'jsonAddKey(out, first, "ProgramIndex")',
                "out.print(snapshot.programIndex)",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))
else:
    errors.append("Samovar.ino not found")

index_htm = ROOT / "data_raw" / "index.htm"
if index_htm.exists():
    index_text = index_htm.read_text(encoding="utf-8", errors="ignore")
    if "indexOf('Прг №')" in index_text or 'indexOf("Прг №")' in index_text:
        errors.append("data_raw/index.htm still parses ProgramNum from localized Status")
    if "Number(myObj.ProgramNum || 0)" not in index_text:
        errors.append("data_raw/index.htm does not use numeric /ajax ProgramNum")
else:
    errors.append("data_raw/index.htm not found")

# Async-safe /command pipeline contract.
try:
    command_body = extract_function_body(text, "void web_command(AsyncWebServerRequest *request)")
except ValueError as exc:
    errors.append(str(exc))
    command_body = ""

try:
    command_param_body = extract_function_body(text, "static bool get_web_command_action")
except ValueError as exc:
    errors.append(str(exc))
    command_param_body = ""

for scope_name, scope_body in [
    ("get_web_command_action", command_param_body),
    ("web_command", command_body),
]:
    for token in ["getParam(name, false)", "request->hasArg(", "request->arg("]:
        if token in scope_body:
            errors.append(f"/command {scope_name} contains query/fallback API: {token}")

if command_param_body:
    require_ordered_tokens(
        "/command requires exactly one POST body action",
        command_param_body,
        [
            "request->params() != 1",
            "request->getParam(0)",
            "!param->isPost()",
            "param->isFile()",
            "name.toLowerCase()",
            "!web_command_name_allowed(name)",
        ],
        errors,
    )

if command_body:
    allowed_responses = {"OK", "BUSY", "IGNORED", "POWER_OFF", "BAD_REQUEST"}
    response_bodies = re.findall(
        r'(?:send_web_command_response\s*\(\s*request\s*,\s*\d+\s*,|request->send\s*\(\s*\d+\s*,\s*"text/plain"\s*,)\s*"([^"]*)"',
        command_body,
    )
    for body in response_bodies:
        if body not in allowed_responses:
            errors.append(f"/command response body is not a contract token: {body}")
    for token in sorted(allowed_responses):
        if token not in response_bodies:
            errors.append(f"/command response token missing: {token}")

    try:
        command_key_body = extract_function_body(text, "static bool web_command_name_allowed")
    except ValueError as exc:
        errors.append(str(exc))
        command_key_body = ""
    for token in [
        'name == "voltage"',
        'name == "mixer"',
        'name == "watert"',
        'name == "pumpspeed"',
        'name == "pnbk"',
        'name == "nbkopt"',
    ]:
        if token not in command_key_body:
            errors.append(f"/command throttle key does not recognize branch: {token}")

    for token in [
        "get_web_command_action(request, action, actionParam)",
        "if (!parseResult.ok())",
        "String commandKey = action;",
        "commandKey == last_command_key",
        "last_command_key = commandKey;",
    ]:
        if token not in command_body:
            errors.append(f"/command throttle no longer keys by command: {token}")

    pending_contract = {
        "voltage": "queue_pending_value(pending_voltage_flag, pending_voltage_value, voltage)",
        "mixer": "queue_pending_value(pending_mixer_flag, pending_mixer_on, boolValue)",
        "pnbk": "queue_pending_nbk(nbkCommand)",
        "watert": "queue_pending_value(pending_water_temp_flag, pending_water_temp_value, waterPwm)",
        "pumpspeed": "queue_pending_value(pending_pump_speed_flag, pending_pump_speed_steps, pumpSpeedSteps)",
        "nbkopt": "queue_pending_flag(pending_nbkopt_flag)",
        "rescands": "queue_pending_flag(pending_rescan_ds_flag)",
        "lua": "queue_pending_string(pending_lua_file_flag, pending_lua_file, actionParam->value())",
    }
    for name, token in pending_contract.items():
        if f'action == "{name}"' not in command_body:
            errors.append(f"/command missing branch: {name}")
        if token not in command_body:
            errors.append(f"/command {name} does not use pending queue: {token}")

    forbidden_direct_calls = [
        "set_current_power(",
        "set_mixer(",
        "set_water_temp(",
        "set_pump_speed(",
        "menu_reset_wifi(",
        "run_lua_script(",
        "load_lua_script(",
        "scan_ds_adress(",
        "fileToAppend.flush(",
        "nbk_Mo =",
        "nbk_Po =",
    ]
    for token in forbidden_direct_calls:
        if token in command_body:
            errors.append(f"/command contains direct async operation: {token}")
    require_ordered_tokens(
        "/command rescands rejects active process before queuing OneWire scan",
        command_body,
        [
            'action == "rescands"',
            "samovar_process_active()",
            'send_web_command_response(request, 503, "BUSY")',
            "queue_pending_flag(pending_rescan_ds_flag)",
        ],
        errors,
    )
    try:
        rescands_body, _ = extract_braced_block_after(command_body, 'action == "rescands"')
        rescands_active_body, rescands_active_end = extract_braced_block_after(
            rescands_body,
            "if (samovar_process_active())",
        )
        # 503, как и все остальные отказы /command: занятость - это временная
        # неготовность, а не конфликт состояния, и клиенту незачем различать их.
        if 'send_web_command_response(request, 503, "BUSY")' not in rescands_active_body:
            errors.append("/command rescands active branch does not return 503 BUSY")
        if "return;" not in rescands_active_body:
            errors.append("/command rescands active branch does not return before queueing")
        if "queue_pending_flag(pending_rescan_ds_flag)" in rescands_active_body:
            errors.append("/command rescands active branch still queues OneWire scan")
        rescands_after_active = rescands_body[rescands_active_end:]
        if "queue_pending_flag(pending_rescan_ds_flag)" not in rescands_after_active:
            errors.append("/command rescands queue is not after active-process reject")
    except ValueError as exc:
        errors.append(str(exc))

if "scan_ds_adress(" in text:
    errors.append("WebServer.ino contains direct OneWire scan")

menu_file = ROOT / "Menu.ino"
if menu_file.exists():
    menu_text = menu_file.read_text(encoding="utf-8", errors="ignore")
    if "scan_ds_adress(" in menu_text:
        errors.append("Menu.ino contains direct OneWire scan")
else:
    errors.append("Menu.ino not found")

try:
    profile_queue_body = extract_function_body(
        text, "static OperationError queue_profile_operation(")
except ValueError as exc:
    errors.append(str(exc))
    profile_queue_body = ""

if profile_queue_body:
    require_ordered_tokens(
        "profile queue checks slot/session before atomic reserve",
        profile_queue_body,
        [
            "pending_command_lock(pdMS_TO_TICKS(50))",
            "profile_operation_phase_load() != PROFILE_OPERATION_EMPTY",
            "requireProgramIdle && program_update_session_active()",
            "operation_store_reserve_locked(",
            "reset_profile_operation_slot();",
            "profile_operation_phase_store(PROFILE_OPERATION_QUEUED);",
        ],
        errors,
    )

try:
    web_program_body = extract_function_body(text, "void web_program")
except ValueError as exc:
    errors.append(str(exc))
    web_program_body = ""

try:
    program_json_body = extract_function_body(text, "static void send_program_json_response")
except ValueError as exc:
    errors.append(str(exc))
    program_json_body = ""

if program_json_body:
    for token in [
        '"{\\"ok\\":"',
        'json += ",\\"err\\":";',
        'toJsonString(err)',
        'json += ",\\"program\\":";',
        'toJsonString(programText)',
        'request->beginResponse(statusCode, "application/json", json)',
        'response->addHeader("Cache-Control", "no-store")',
        "request->send(response)",
    ]:
        if token not in program_json_body:
            errors.append(f"/program JSON response helper missing token: {token}")

try:
    program_accepted_body = extract_function_body(
        text, "static void send_program_operation_accepted(")
except ValueError as exc:
    errors.append(str(exc))
    program_accepted_body = ""

if program_accepted_body:
    for token in (
        r'\"ok\":true',
        r'\"err\":\"\"',
        r'\"program\":',
        r'\"operationId\":',
        r'\"state\":\"queued\"',
        r'\"error\":\"none\"',
        '202, "application/json", json',
    ):
        if token not in program_accepted_body:
            errors.append(f"/program accepted response missing token: {token}")

if web_program_body:
    require_ordered_tokens(
        "/program validates action and draft before pending queue",
        web_program_body,
        [
            'const uint8_t clearCount = request_param_count(request, "clear");',
            'const uint8_t wProgramCount = request_param_count(request, "WProgram");',
            'wProgramCount == 1 ? get_request_param(request, "WProgram") : nullptr',
            "wProgramCount == 1 && (!wProgramParam || wProgramParam->isFile())",
            'F("WProgram должен быть текстовым параметром")',
            'clearParam->value() != "1"',
            "ProgramDraft programDraft{};",
            "ProgramUpdateAction programAction = PROGRAM_UPDATE_NONE;",
            "prepare_program_for_mode(",
            "sourceMode,",
            "if (!result.ok())",
            "programAction = PROGRAM_UPDATE_REPLACE;",
            "uint8_t metadataFlags = 0;",
            "parse_control_vless(",
            "const bool hasMetadata = metadataFlags != 0;",
            "queue_profile_operation(",
            "send_program_operation_accepted(request, responseProgram, operationId);",
        ],
        errors,
    )
    if 'request->send(' in web_program_body:
        errors.append("/program handler bypasses JSON response helper")
    for token in [
        "PROGRAM_UPDATE_CLEAR",
        "format_program_parse_error(result)",
        "serialize_program_for_mode(sourceMode)",
    ]:
        if token not in web_program_body:
            errors.append(f"/program action contract missing token: {token}")
    for forbidden in ["pending_program_str", ".toFloat()", "program_commit(", "program_clear("]:
        if forbidden in web_program_body:
            errors.append(f"/program handler contains forbidden token: {forbidden}")
    for token in ["set_program(", "set_beer_program(", "set_dist_program(", "set_nbk_program("]:
        if token in web_program_body:
            errors.append(f"/program handler applies program directly: {token}")

app_js = ROOT / "data_raw" / "app.js"
if app_js.exists():
    app_text = app_js.read_text(encoding="utf-8", errors="ignore")
    try:
        post_program_body = extract_function_body(app_text, "async function postProgram")
        read_program_body = extract_function_body(app_text, "async function readProgramResponse")
        clear_program_body = extract_function_body(app_text, "async function clearProgram")
    except ValueError as exc:
        errors.append(str(exc))
        post_program_body = ""
        read_program_body = ""
        clear_program_body = ""
    if post_program_body:
        for token in [
            "const body = new FormData();",
            "const allowedFields = ['WProgram', 'vless', 'Descr'];",
            "form.querySelectorAll('[name=\"' + name + '\"]')",
            "body.append(name, fields[0].value);",
            "await fetch('/program', { method: 'POST', body: body })",
            "readProgramResponse(resp)",
            "await waitForOperation(result.operationId);",
            "result.state = 'succeeded';",
        ]:
            if token not in post_program_body:
                errors.append(f"data_raw/app.js postProgram missing queue contract token: {token}")
        if "new FormData(form)" in post_program_body:
            errors.append("data_raw/app.js postProgram serializes non-allowlisted form fields")
    if read_program_body:
        for token in [
            "await resp.json()",
            "typeof result.ok !== 'boolean'",
            "typeof result.err !== 'string'",
            "typeof result.program !== 'string'",
            "Некорректный контракт /program.",
            "const acceptedKeys = baseKeys.concat(['operationId', 'state', 'error']);",
            "validateOperationPayload(result, acceptedKeys, undefined, '/program');",
            "result.httpStatus = resp.status;",
            "result.queued = result.ok && resp.status === 202;",
        ]:
            if token not in read_program_body:
                errors.append(f"data_raw/app.js readProgramResponse missing JSON contract token: {token}")
        if "resp.text()" in read_program_body:
            errors.append("data_raw/app.js program response parser still reads text response")
    if clear_program_body:
        require_ordered_tokens(
            "data_raw/app.js clearProgram sends exact standalone clear action",
            clear_program_body,
            [
                "confirm('Очистить текущую программу?')",
                "const body = new FormData();",
                "body.append('clear', '1');",
                "await fetch('/program', { method: 'POST', body: body })",
                "readProgramResponse(resp)",
                "if (!result.queued)",
                "await waitForOperation(result.operationId);",
                "Программа очищена.",
            ],
            errors,
        )
        if "WProgram" in clear_program_body:
            errors.append("data_raw/app.js clearProgram serializes WProgram")
    if "clearProgram: clearProgram" not in app_text:
        errors.append("data_raw/app.js does not export clearProgram")
else:
    errors.append("data_raw/app.js not found")

program_clear_browser = ROOT / "tools" / "test_program_clear_ui_browser.py"
if not program_clear_browser.exists():
    errors.append("tools/test_program_clear_ui_browser.py not found")
else:
    browser_text = program_clear_browser.read_text(encoding="utf-8", errors="ignore")
    for token in [
        '{ name: "desktop", width: 1440, height: 900 }',
        '{ name: "mobile", width: 390, height: 844 }',
        'const pages = ["index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm", "program.htm"]',
        "for (const status of [202, 400, 409, 503])",
        "cancelled confirmation sent a request",
        "invalid clear body",
        "feedback is not visible",
        "feedback.text.includes(lastMessage)",
        "page.on(\"pageerror\"",
        "playwright-cli is required for this explicit browser gate",
    ]:
        if token not in browser_text:
            errors.append(f"program clear browser gate missing token: {token}")

program_pages = [
    "index.htm",
    "beer.htm",
    "distiller.htm",
    "nbk.htm",
    "bk.htm",
    "program.htm",
    "brewxml.htm",
    "setup.htm",
]
clear_program_pages = {
    "index.htm",
    "beer.htm",
    "distiller.htm",
    "nbk.htm",
    "bk.htm",
    "program.htm",
}
for page in program_pages:
    page_file = ROOT / "data_raw" / page
    if not page_file.exists():
        errors.append(f"data_raw/{page} not found")
        continue
    page_text = page_file.read_text(encoding="utf-8", errors="ignore")
    if "SamovarApp.postProgram(" not in page_text:
        errors.append(f"data_raw/{page} does not use SamovarApp.postProgram for /program")
    if "fetch('/program'" in page_text or 'fetch("/program"' in page_text:
        errors.append(f"data_raw/{page} still posts /program directly")
    if page in clear_program_pages:
        if page_text.count("id='clearprogram'") != 1:
            errors.append(f"data_raw/{page} must contain exactly one clearprogram button")
        if "SamovarApp.clearProgram();" not in page_text:
            errors.append(f"data_raw/{page} clear button does not use shared clearProgram helper")
        if "Изменение программы принято в обработку." in page_text:
            errors.append(f"data_raw/{page} still reports queued work as success")
        if page == "program.htm":
            for token in ['id="messagesBox"', 'id="messages"']:
                if token not in page_text:
                    errors.append(f"data_raw/program.htm visible feedback missing token: {token}")
    for token in [
        'text !== "OK"',
        "text !== 'OK'",
        'alert("Ok")',
        "alert('Ok')",
        "WProgram').value = text",
        'WProgram").value = text',
        "result.program",
        "response.program",
    ]:
        if token in page_text:
            errors.append(f"data_raw/{page} still has old /program text handling: {token}")

try:
    save_body = extract_function_body(text, "void handleSave")
except ValueError as exc:
    errors.append(str(exc))
    save_body = ""

if save_body:
    require_ordered_tokens(
        "/save rejects clear, validates draft, then queues POD",
        save_body,
        [
            'request_param_count(request, "clear") != 0',
            'const uint8_t wProgramCount = request_param_count(request, "WProgram");',
            'wProgramCount == 1 ? get_request_param(request, "WProgram") : nullptr',
            "wProgramCount == 1 && (!wProgramParam || wProgramParam->isFile())",
            'build_error_envelope("argument", "WProgram", "WProgram must be a text parameter")',
            "prepare_program_for_mode(",
            "programDraftPtr = &programDraft;",
            "prepare_default_program_for_mode(",
            "queue_profile_operation(",
            "wProgramCount == 1,",
            "send_save_operation_accepted(request, operationId);",
        ],
        errors,
    )
    for forbidden in ["pending_program_str", "PendingProgramMode", "pendingProgramText"]:
        if forbidden in save_body:
            errors.append(f"/save reintroduces raw pending program token: {forbidden}")

mode_registry_file = ROOT / "mode_registry.h"
if mode_registry_file.exists():
    mode_registry_text = mode_registry_file.read_text(encoding="utf-8", errors="ignore")
    try:
        owner_body = extract_function_body(mode_registry_text, "inline bool mode_is_program_owner")
    except ValueError as exc:
        errors.append(str(exc))
        owner_body = ""
    for token in [
        "SAMOVAR_RECTIFICATION_MODE",
        "SAMOVAR_DISTILLATION_MODE",
        "SAMOVAR_BEER_MODE",
        "SAMOVAR_BK_MODE",
        "SAMOVAR_NBK_MODE",
        "SAMOVAR_SUVID_MODE",
        "SAMOVAR_LUA_MODE",
    ]:
        if token not in owner_body:
            errors.append(f"program owner helper missing mode: {token}")
    try:
        active_body = extract_function_body(mode_registry_text, "inline bool program_update_session_active")
    except ValueError as exc:
        errors.append(str(exc))
        active_body = ""
    for token in [
        "PowerOn",
        "mode_is_program_owner(Samovar_Mode)",
        "mode_status_session_active(SamovarStatusInt)",
        "mode_startval_session_active(startval)",
    ]:
        if token not in active_body:
            errors.append(f"program active helper missing state token: {token}")
    try:
        status_active_body = extract_function_body(mode_registry_text, "inline bool mode_status_session_active")
    except ValueError as exc:
        errors.append(str(exc))
        status_active_body = ""
    for token in [
        "status > SAMOVAR_STATUS_IDLE && status < SAMOVAR_STATUS_DISTILLATION",
        "ops[i].activeStatus > SAMOVAR_STATUS_IDLE && ops[i].activeStatus == status",
    ]:
        if token not in status_active_body:
            errors.append(f"mode_status_session_active missing token: {token}")
    try:
        startval_active_body = extract_function_body(mode_registry_text, "inline bool mode_startval_session_active")
    except ValueError as exc:
        errors.append(str(exc))
        startval_active_body = ""
    for token in [
        "ops[i].startvalRangeHigh > ops[i].startvalRangeLow",
        "value >= ops[i].startvalRangeLow && value < ops[i].startvalRangeHigh",
    ]:
        if token not in startval_active_body:
            errors.append(f"mode_startval_session_active missing token: {token}")
else:
    errors.append("mode_registry.h not found")

samovar_file = ROOT / "Samovar.ino"
if samovar_file.exists():
    samovar_text = samovar_file.read_text(encoding="utf-8", errors="ignore")
    try:
        loop_body = extract_function_body(samovar_text, "void loop()")
    except ValueError as exc:
        errors.append(str(exc))
        loop_body = ""
    require_ordered_tokens(
        "pending_lua_reload_flag loop contract",
        loop_body,
        [
            "locked && pending_lua_reload_flag",
            "pending_lua_reload_flag = false;",
            "hasPendingLuaReload = true;",
            "pending_command_unlock(locked);",
            "if (hasPendingLuaReload) {",
            "load_lua_script();",
        ],
        errors,
    )
    require_ordered_tokens(
        "pending_lua_start_flag loop contract",
        loop_body,
        [
            "locked && pending_lua_start_flag",
            "hasPendingLuaStart = true;",
            "pending_command_unlock(locked);",
            "if (hasPendingLuaStart) {",
            "if (start_lua_script()) {",
            "pending_lua_start_flag = false;",
        ],
        errors,
    )
    require_ordered_tokens(
        "pending_lua_file_flag loop contract",
        loop_body,
        [
            "locked && pending_lua_file_flag",
            "luaFile = pending_lua_file;",
            "hasPendingLuaFile = true;",
            "pending_command_unlock(locked);",
            "if (hasPendingLuaFile) {",
            "if (run_lua_script(luaFile)) {",
            "pending_lua_file_flag = false;",
        ],
        errors,
    )
    process_signature = "static void process_profile_operation()"
    process_offset = samovar_text.rfind(process_signature)
    process_body = extract_function_body(
        samovar_text[process_offset:], process_signature) if process_offset >= 0 else ""
    require_ordered_tokens(
        "profile operation rechecks races before owner commit",
        process_body,
        [
            "PROFILE_OPERATION_REQUIRE_PROGRAM_IDLE",
            "program_update_session_active()",
            "Samovar_Mode != sourceMode",
            "OPERATION_ERROR_CANCELLED",
            "commit_profile_operation();",
            "set_profile_operation_terminal(",
        ],
        errors,
    )
    for forbidden in [
        "pending_program_str",
        "set_program(",
        "set_beer_program(",
        "set_dist_program(",
        "set_nbk_program(",
        "prepare_program_for_mode(",
        "program_parse_lines(",
    ]:
        if forbidden in loop_body:
            errors.append(f"pending program loop contains forbidden parse/string token: {forbidden}")
    if "scan_ds_adress(" in loop_body or "pending_rescan_ds_flag" in loop_body:
        errors.append("loop() contains direct OneWire rescan handling")
    try:
        sys_ticker_body = extract_function_body(samovar_text, "void triggerSysTicker(void *parameter)")
    except ValueError as exc:
        errors.append(str(exc))
        sys_ticker_body = ""
    if sys_ticker_body:
        require_ordered_tokens(
            "SysTicker serializes pending OneWire scan with normal DS polling",
            sys_ticker_body,
            [
                "bool rescanDs = false;",
                "pending_command_lock(pdMS_TO_TICKS(50))",
                "if (locked && pending_rescan_ds_flag) {",
                "pending_rescan_ds_flag = false;",
                "rescanDs = !mode_switch_in_progress();",
                "pending_command_unlock(locked);",
                "if (rescanDs) {",
                "samovar_process_active()",
                'SendMsg("Сканирование датчиков отклонено: процесс активен.", WARNING_MSG);',
                "DS_getvalue();",
                "scan_ds_adress();",
                "DS_getvalue();",
            ],
            errors,
        )
        if samovar_text.count("scan_ds_adress(") != sys_ticker_body.count("scan_ds_adress("):
            errors.append("Samovar.ino contains OneWire scan outside triggerSysTicker")
        try:
            rescan_body, rescan_end = extract_braced_block_after(sys_ticker_body, "if (rescanDs)")
            active_rescan_body, active_rescan_end = extract_braced_block_after(
                rescan_body,
                "if (samovar_process_active())",
            )
            scan_rescan_body, _ = extract_braced_block_after(rescan_body, "else", active_rescan_end)
            poll_rescan_body, _ = extract_braced_block_after(sys_ticker_body, "else", rescan_end)
            if 'SendMsg("Сканирование датчиков отклонено: процесс активен.", WARNING_MSG);' not in active_rescan_body:
                errors.append("SysTicker active OneWire rescan branch does not warn")
            if "DS_getvalue();" not in active_rescan_body:
                errors.append("SysTicker active OneWire rescan branch does not poll DS values")
            if "scan_ds_adress();" in active_rescan_body:
                errors.append("SysTicker active OneWire rescan branch still scans OneWire")
            if "scan_ds_adress();" not in scan_rescan_body:
                errors.append("SysTicker idle OneWire rescan branch does not scan OneWire")
            if "DS_getvalue();" not in poll_rescan_body:
                errors.append("SysTicker normal OneWire branch does not poll DS values")
            if "scan_ds_adress();" in poll_rescan_body:
                errors.append("SysTicker normal OneWire branch scans OneWire")
        except ValueError as exc:
            errors.append(str(exc))
else:
    errors.append("Samovar.ino not found")

sensor_file = ROOT / "sensorinit.h"
if sensor_file.exists():
    sensor_text = sensor_file.read_text(encoding="utf-8", errors="ignore")
    if "void scan_ds_adress()" not in sensor_text:
        errors.append("sensorinit.h missing scan_ds_adress definition")
    sensor_init_index = sensor_text.find("void sensor_init(void)")
    if sensor_init_index < 0:
        errors.append("sensorinit.h missing sensor_init()")
    elif "scan_ds_adress();" not in sensor_text[sensor_init_index:sensor_init_index + 5000]:
        errors.append("sensor_init() no longer performs boot OneWire scan")
else:
    errors.append("sensorinit.h not found")

spiffs_file = ROOT / "SPIFFSEditor.h"
if spiffs_file.exists():
    spiffs_text = spiffs_file.read_text(encoding="utf-8", errors="ignore")
    # Гейт разрушающих операций редактора: и активный процесс, и ещё не выполненное
    # отложенное закрытие журнала (close идёт тиком SysTicker уже после того, как
    # samovar_process_active() стала ложной — иначе осталось бы окно гонки).
    gate_marker = "samovar_process_active() || data_log_close_pending()"
    post_error_marker = "request->getAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR).length() > 0"
    post_error_index = spiffs_text.find(post_error_marker)
    if post_error_index < 0:
        errors.append(f"SPIFFSEditor POST upload error response missing: {post_error_marker}")
    else:
        post_error_window = spiffs_text[post_error_index:post_error_index + 200]
        if 'request->send(503, "text/plain", "BUSY");' not in post_error_window:
            errors.append('SPIFFSEditor POST upload error response missing: request->send(503, "text/plain", "BUSY");')
    try:
        upload_body = extract_function_body(spiffs_text, "void SPIFFSEditor::handleUpload")
    except ValueError as exc:
        errors.append(str(exc))
        upload_body = ""
    if upload_body:
        require_ordered_tokens(
            "SPIFFSEditor .lua reload is rejected across the mode-barrier race",
            upload_body,
            [
                'getValue(filename, \'.\', 1) == "lua"',
                "if (mode_switch_in_progress())",
                "request->setAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR, SPIFFS_EDITOR_LUA_RELOAD_BUSY);",
                "pending_command_lock(pdMS_TO_TICKS(50))",
                "if (locked && !mode_switch_in_progress())",
                "pending_lua_reload_flag = true;",
                "request->setAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR, SPIFFS_EDITOR_LUA_RELOAD_BUSY);",
                "pending_command_unlock(locked);",
            ],
            errors,
        )
        if upload_body.count("mode_switch_in_progress()") < 2:
            errors.append("SPIFFSEditor .lua upload does not recheck the mode barrier under the pending lock")
        for token in ["load_lua_script(", "run_lua_script("]:
            if token in upload_body:
                errors.append(f"SPIFFSEditor upload contains direct Lua operation: {token}")
        # Гейт «идёт процесс / журнал ещё закрывается»: во время перегонки и пока
        # не выполнено отложенное закрытие журнала редактор не пишет чанки на ФС
        # (гонка с журналом на ядре 0). Загрузчик помечает запрос, ответ 503 даёт
        # handleRequest. Гейт обязан стоять ДО открытия файла на запись, иначе
        # перестановка гейта после _fs.open(p, "w") пройдёт незамеченной.
        upload_gate_index = upload_body.find(gate_marker)
        upload_open_index = upload_body.find('_fs.open(p, "w")')
        if upload_gate_index < 0:
            errors.append("SPIFFSEditor upload is not gated by samovar_process_active()/data_log_close_pending()")
        elif upload_open_index < 0 or upload_gate_index > upload_open_index:
            errors.append("SPIFFSEditor upload gate does not precede the file open for write")
        if "SPIFFS_EDITOR_BUSY_PROCESS_ACTIVE" not in upload_body:
            errors.append("SPIFFSEditor upload does not flag the busy reason when a process is active")
        # Гейт должен проверяться не только при открытии файла (первый чанк), но и
        # на каждом последующем вызове handleUpload: процесс может стартовать на
        # ядре 0 уже в ходе загрузки, и тогда запись оставшихся чанков снова
        # гонялась бы с журналом. Устойчивое к текстовым переформулировкам условие
        # достижимости — гейт стоит на ГЛУБИНЕ ВЛОЖЕННОСТИ 0 тела handleUpload (на
        # одном уровне с guard'ом записи `if (request->_tempFile)`), т.е. НЕ обёрнут
        # ни в какой БЛОК ({...}: `if (!index) { ... }`, `if (index==0) { ... }`,
        # второй такой же блок, голые {}). Любая скобочная обёртка, ограничивающая
        # рекчек первым чанком, повышает глубину — и ловится независимо от её
        # текстовой формы, в отличие от позиционного/по-литералу сравнения.
        # Счётчик пропускает содержимое строковых/символьных литералов, чтобы
        # непарная `{`/`}` внутри строки (напр. отладочный `"note {"`) не сбивала
        # глубину и не давала ложного падения на корректной правке.
        #
        # ПРИНЯТАЯ ГРАНИЦА ТЕХНИКИ (не ловится статикой — держат компиляция 7
        # окружений и ревью): (1) нейтрализация самого условия (`if (false && ...)`);
        # (2) БЕЗСКОБОЧНАЯ обёртка control-flow (`if (!index)` без `{}` над рекчеком):
        # подсчёт скобок — прокси для control-flow-вложенности, а `if/for/while` без
        # скобок создают вложенность БЕЗ `{`, поэтому brace-depth её принципиально не
        # видит. Догонять это новыми частными правилами = разбор грамматики C++, что
        # для smoke-пина неоправданно; достоверно закрыл бы только рантайм-харнесс
        # (решение о трудозатратах — за владельцем). Пин ловит все РЕАЛИСТИЧНЫЕ
        # регрессии рекчека: удаление, перестановку после записи, скобочную обёртку.
        body_nc = strip_cpp_comments(upload_body)
        write_pos = body_nc.find("request->_tempFile.write(data, len)")
        depth = 0
        pos = 0
        in_string = False
        in_char = False
        escaped = False
        gate_at_body_level = False
        while pos < len(body_nc):
            ch = body_nc[pos]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                pos += 1
                continue
            if in_char:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == "'":
                    in_char = False
                pos += 1
                continue
            if ch == '"':
                in_string = True
                pos += 1
                continue
            if ch == "'":
                in_char = True
                pos += 1
                continue
            if body_nc.startswith(gate_marker, pos):
                if depth == 0 and (write_pos < 0 or pos < write_pos):
                    gate_at_body_level = True
                pos += len(gate_marker)
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            pos += 1
        if upload_body.count(gate_marker) < 2:
            errors.append("SPIFFSEditor upload gates only the first chunk (no re-check before writing later chunks)")
        elif write_pos < 0:
            errors.append("SPIFFSEditor upload has no chunk write to guard")
        elif not gate_at_body_level:
            errors.append("SPIFFSEditor upload re-check gate is not at handleUpload body level (unreachable for chunks after the first)")

    # Разрушающие операции редактора (DELETE, создание через PUT) обязаны
    # отклоняться при активном процессе ДО того, как тронут ФС. Проверяем каждую
    # ветку отдельно и требуем, чтобы гейт стоял перед мутацией, иначе выпадение
    # или сдвиг одного гейта пройдёт незамеченным.
    # (handleRequest не извлекается через extract_function_body: тело строит JSON
    # с литеральными { } в строках, чего брейс-парсер хелпера не разбирает.)
    # Якорим поиск на определении handleRequest: те же маркеры методов есть и в
    # canHandle (там они лишь `return true`), а гейт нужен именно в handleRequest.
    handle_request_index = spiffs_text.find("void SPIFFSEditor::handleRequest")
    if handle_request_index < 0:
        errors.append("SPIFFSEditor::handleRequest definition not found")
        handle_request_index = 0
    busy_send = 'request->send(503, "text/plain", "BUSY");'
    for method_marker, mutation, label in (
        ("request->method() == HTTP_DELETE", "_fs.remove(", "DELETE"),
        ("request->method() == HTTP_PUT", '_fs.open(filename, "w")', "PUT create"),
    ):
        branch_index = spiffs_text.find(method_marker, handle_request_index)
        if branch_index < 0:
            errors.append(f"SPIFFSEditor {label} branch not found")
            continue
        # Окно ограничиваем телом самой ветки — до следующего разветвления по
        # методу или до следующего определения метода класса. Иначе гейт соседней
        # ветки подменил бы удалённый гейт текущей, и мутация прошла бы незамеченной.
        search_from = branch_index + len(method_marker)
        boundaries = [
            idx
            for idx in (
                spiffs_text.find("request->method() == HTTP_", search_from),
                spiffs_text.find("void SPIFFSEditor::", search_from),
            )
            if idx >= 0
        ]
        window_end = min(boundaries) if boundaries else len(spiffs_text)
        window = spiffs_text[branch_index:window_end]
        gate_index = window.find(gate_marker)
        mutation_index = window.find(mutation)
        if gate_index < 0 or busy_send not in window[gate_index:gate_index + 150]:
            errors.append(f"SPIFFSEditor {label} is not gated by samovar_process_active()/data_log_close_pending() with 503 BUSY")
        elif mutation_index < 0 or gate_index > mutation_index:
            errors.append(f"SPIFFSEditor {label} gate does not precede the filesystem mutation")
else:
    errors.append("SPIFFSEditor.h not found")

if errors:
    print("API smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("API smoke check passed")
print(f"Discovered routes: {len(routes)}")
