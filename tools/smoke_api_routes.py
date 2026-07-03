#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
ws_file = ROOT / "WebServer.ino"
DATA = ROOT / "data"
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
    routes.setdefault(path, set()).add(method)

required = {
    "/": None,
    "/ajax": "HTTP_GET",
    "/command": "HTTP_POST",
    "/program": "HTTP_POST",
    "/save": "HTTP_POST",
    "/calibrate": "HTTP_GET",
    "/i2cpump": "HTTP_GET",
    "/getlog": "HTTP_GET",
}

for path, method in required.items():
    if path not in routes:
        errors.append(f"missing route: {path}")
        continue
    if method and method not in routes[path]:
        errors.append(f"route {path} missing method {method}; found {sorted(routes[path])}")

if routes.get("/command") != {"HTTP_POST"}:
    errors.append(f"/command must be POST-only; found {sorted(routes.get('/command', set()))}")

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
        ajax_body = extract_function_body(samovar_text, "void send_ajax_json(AsyncWebServerRequest *request)")
        require_ordered_tokens(
            "/ajax exposes numeric ProgramNum without localized status parsing",
            ajax_body,
            [
                'jsonAddKey(out, first, "ProgramNum")',
                "out.print(ProgramNum + 1)",
                'jsonAddKey(out, first, "ProgramIndex")',
                "out.print(ProgramNum)",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))
else:
    errors.append("Samovar.ino not found")

index_htm = ROOT / "data" / "index.htm"
if index_htm.exists():
    index_text = index_htm.read_text(encoding="utf-8", errors="ignore")
    if "indexOf('Прг №')" in index_text or 'indexOf("Прг №")' in index_text:
        errors.append("data/index.htm still parses ProgramNum from localized Status")
    if "Number(myObj.ProgramNum || 0)" not in index_text:
        errors.append("data/index.htm does not use numeric /ajax ProgramNum")
else:
    errors.append("data/index.htm not found")

# Async-safe /command pipeline contract.
try:
    command_body = extract_function_body(text, "void web_command(AsyncWebServerRequest *request)")
except ValueError as exc:
    errors.append(str(exc))
    command_body = ""

try:
    command_param_body = extract_function_body(text, "static const AsyncWebParameter* get_web_command_param")
except ValueError as exc:
    errors.append(str(exc))
    command_param_body = ""

for scope_name, scope_body in [
    ("get_web_command_param", command_param_body),
    ("web_command", command_body),
]:
    for token in ["getParam(name, false)", "request->hasArg(", "request->arg(", "getParam(0)"]:
        if token in scope_body:
            errors.append(f"/command {scope_name} contains query/fallback API: {token}")

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
        command_key_body = extract_function_body(text, "static String get_web_command_key(AsyncWebServerRequest *request)")
    except ValueError as exc:
        errors.append(str(exc))
        command_key_body = ""
    if "getParam(0)" in command_key_body:
        errors.append("/command throttle key uses first query parameter")
    if "getParam(name, true)" not in text:
        errors.append("/command does not read POST body params with getParam(name, true)")
    for token in [
        'web_command_has_arg(request, "voltage")',
        'web_command_has_arg(request, "mixer")',
        'web_command_has_arg(request, "watert")',
        'web_command_has_arg(request, "pumpspeed")',
        'web_command_has_arg(request, "pnbk")',
        'web_command_has_arg(request, "nbkopt")',
    ]:
        if token not in command_key_body:
            errors.append(f"/command throttle key does not recognize branch: {token}")

    for token in [
        "String commandKey = get_web_command_key(request);",
        "commandKey == last_command_key",
        "last_command_key = commandKey;",
    ]:
        if token not in command_body:
            errors.append(f"/command throttle no longer keys by command: {token}")

    pending_contract = {
        "voltage": "queue_pending_float(pending_voltage_flag, pending_voltage_value, voltage)",
        "mixer": "queue_pending_bool(pending_mixer_flag, pending_mixer_on, mixerValue == 1)",
        "pnbk": "queue_pending_float(pending_pnbk_flag, pending_pnbk_value, pnbkValue)",
        "watert": "queue_pending_float(pending_water_temp_flag, pending_water_temp_value, waterTemp)",
        "pumpspeed": "queue_pending_float(pending_pump_speed_flag, pending_pump_speed_rate, pumpSpeed)",
        "nbkopt": "queue_pending_flag(pending_nbkopt_flag)",
        "rescands": "queue_pending_flag(pending_rescan_ds_flag)",
        "lua": "queue_pending_string(pending_lua_file_flag, pending_lua_file, web_command_arg(request, \"lua\"))",
    }
    for name, token in pending_contract.items():
        if f'web_command_has_arg(request, "{name}")' not in command_body:
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
            'web_command_has_arg(request, "rescands")',
            "samovar_process_active()",
            'send_web_command_response(request, 409, "BUSY")',
            "queue_pending_flag(pending_rescan_ds_flag)",
        ],
        errors,
    )
    try:
        rescands_body, _ = extract_braced_block_after(command_body, 'web_command_has_arg(request, "rescands")')
        rescands_active_body, rescands_active_end = extract_braced_block_after(
            rescands_body,
            "if (samovar_process_active())",
        )
        if 'send_web_command_response(request, 409, "BUSY")' not in rescands_active_body:
            errors.append("/command rescands active branch does not return 409 BUSY")
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

lua_handler_re = re.compile(
    r'server\.on\("/lua"\s*,\s*HTTP_GET\s*,\s*\[\]\(AsyncWebServerRequest \*request\)\s*\{(?P<body>.*?)\n\s*\}\);',
    re.S,
)
lua_handler = lua_handler_re.search(text)
if lua_handler:
    lua_body = lua_handler.group("body")
    for token in [
        'request->hasArg("script")',
        "queue_pending_string(pending_lua_file_flag, pending_lua_file, request->arg(\"script\"))",
        "queue_pending_flag(pending_lua_start_flag)",
    ]:
        if token not in lua_body:
            errors.append(f"/lua handler missing pending contract: {token}")
    for token in ["run_lua_script(", "load_lua_script(", "get_lua_script_list("]:
        if token in lua_body:
            errors.append(f"/lua handler contains direct async Lua/SPIFFS operation: {token}")
else:
    errors.append("/lua handler not found")

try:
    reject_program_body = extract_function_body(text, "bool reject_program_update_if_busy(AsyncWebServerRequest *request)")
except ValueError as exc:
    errors.append(str(exc))
    reject_program_body = ""

if reject_program_body:
    require_ordered_tokens(
        "program update reject checks pending slot before active session",
        reject_program_body,
        [
            "pending_program_slot_busy()",
            "request->send(503, \"text/plain\", \"BUSY: предыдущее изменение программы ещё не применено\")",
            "program_update_session_active()",
            "request->send(409, \"text/plain\", \"BUSY: программа не изменена, активна сессия режима\")",
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
        'request->send(statusCode, "application/json", json)',
    ]:
        if token not in program_json_body:
            errors.append(f"/program JSON response helper missing token: {token}")

try:
    reject_program_json_body = extract_function_body(text, "static bool reject_program_update_if_busy_json")
except ValueError as exc:
    errors.append(str(exc))
    reject_program_json_body = ""

if reject_program_json_body:
    require_ordered_tokens(
        "program JSON reject checks pending slot before active session",
        reject_program_json_body,
        [
            "pending_program_slot_busy()",
            'send_program_json_response(request, 503, false, F("BUSY: предыдущее изменение программы ещё не применено"), String())',
            "program_update_session_active()",
            'send_program_json_response(request, 409, false, F("BUSY: программа не изменена, активна сессия режима"), String())',
        ],
        errors,
    )

if web_program_body:
    require_ordered_tokens(
        "/program rejects with JSON before pending queue",
        web_program_body,
        [
            "const AsyncWebParameter *wProgramParam = get_request_param(request, \"WProgram\");",
            "reject_program_update_if_busy_json(request)",
            "queue_pending_program(pendingMode, wProgramParam->value())",
        ],
        errors,
    )
    if 'request->send(' in web_program_body:
        errors.append("/program handler bypasses JSON response helper")
    if 'send_program_json_response(request, 200, true, String(), responseProgram)' not in web_program_body:
        errors.append("/program success does not use JSON contract")
    for token in ["set_program(", "set_beer_program(", "set_dist_program(", "set_nbk_program("]:
        if token in web_program_body:
            errors.append(f"/program handler applies program directly: {token}")

app_js = ROOT / "data" / "app.js"
if app_js.exists():
    app_text = app_js.read_text(encoding="utf-8", errors="ignore")
    try:
        post_program_body = extract_function_body(app_text, "async function postProgram")
    except ValueError as exc:
        errors.append(str(exc))
        post_program_body = ""
    if post_program_body:
        for token in [
            "await fetch('/program', { method: 'POST', body: new FormData(form) })",
            "await resp.json()",
            "typeof result.ok !== 'boolean'",
            "typeof result.err !== 'string'",
            "typeof result.program !== 'string'",
            "Некорректный контракт /program.",
        ]:
            if token not in post_program_body:
                errors.append(f"data/app.js postProgram missing JSON contract token: {token}")
        if "resp.text()" in post_program_body:
            errors.append("data/app.js postProgram still reads text response")
else:
    errors.append("data/app.js not found")

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
for page in program_pages:
    page_file = ROOT / "data" / page
    if not page_file.exists():
        errors.append(f"data/{page} not found")
        continue
    page_text = page_file.read_text(encoding="utf-8", errors="ignore")
    if "SamovarApp.postProgram(" not in page_text:
        errors.append(f"data/{page} does not use SamovarApp.postProgram for /program")
    if "fetch('/program'" in page_text or 'fetch("/program"' in page_text:
        errors.append(f"data/{page} still posts /program directly")
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
            errors.append(f"data/{page} still has old /program text handling: {token}")

try:
    save_body = extract_function_body(text, "void handleSave")
except ValueError as exc:
    errors.append(str(exc))
    save_body = ""

if save_body:
    require_ordered_tokens(
        "/save rejects active session before pending setup/program queue",
        save_body,
        [
            "get_request_param(request, \"WProgram\") && reject_program_update_if_busy(request)",
            "queue_pending_setup_save(setupSave, hasProgram, pendingMode, pendingProgramText, hasSwitchMode, requestedMode, busyText)",
        ],
        errors,
    )

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
        "SamovarStatusInt > 0 && SamovarStatusInt < 1000",
        "SamovarStatusInt == 1000",
        "SamovarStatusInt == 2000",
        "SamovarStatusInt == 3000",
        "SamovarStatusInt == 4000",
        "startval > 0 && startval < 1000",
        "startval == 1000",
        "startval >= 2000 && startval < 3000",
        "startval == 3000",
        "startval >= 4000 && startval < 5000",
    ]:
        if token not in active_body:
            errors.append(f"program active helper missing state token: {token}")
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
    require_ordered_tokens(
        "pending program loop rejects active session before applying program",
        loop_body,
        [
            "if (ppm != PPM_NONE) {",
            "program_update_session_active()",
            "Программа не изменена: активна сессия режима.",
            "case PPM_RECT: set_program(pstr); break;",
            "case PPM_BEER: set_beer_program(pstr); break;",
            "case PPM_DIST: set_dist_program(pstr); break;",
            "case PPM_NBK:  set_nbk_program(pstr); break;",
        ],
        errors,
    )
    try:
        pending_program_body, _ = extract_braced_block_after(loop_body, "if (ppm != PPM_NONE)")
        active_reject_body, active_reject_end = extract_braced_block_after(
            pending_program_body,
            "if (program_update_session_active())",
        )
        else_index = pending_program_body.find("else", active_reject_end)
        if else_index < 0:
            errors.append("pending program apply has no else branch after active-session reject")
            apply_body = ""
        else:
            apply_body, _ = extract_braced_block_after(pending_program_body, "else", active_reject_end)
        for token in ["set_program(", "set_beer_program(", "set_dist_program(", "set_nbk_program("]:
            if token in active_reject_body:
                errors.append(f"pending program active reject branch still applies program: {token}")
            if token not in apply_body:
                errors.append(f"pending program else branch missing apply call: {token}")
    except ValueError as exc:
        errors.append(str(exc))
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
                "if (pending_rescan_ds_flag) {",
                "pending_rescan_ds_flag = false;",
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
            rescan_body, rescan_end = extract_braced_block_after(sys_ticker_body, "if (pending_rescan_ds_flag)")
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
    post_error_marker = "request->getAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR) == SPIFFS_EDITOR_LUA_RELOAD_BUSY"
    post_error_index = spiffs_text.find(post_error_marker)
    if post_error_index < 0:
        errors.append(f"SPIFFSEditor POST upload error response missing: {post_error_marker}")
    else:
        post_error_window = spiffs_text[post_error_index:post_error_index + 300]
        if 'request->send(503, "text/plain", "BUSY");' not in post_error_window:
            errors.append('SPIFFSEditor POST upload error response missing: request->send(503, "text/plain", "BUSY");')
    try:
        upload_body = extract_function_body(spiffs_text, "void SPIFFSEditor::handleUpload")
    except ValueError as exc:
        errors.append(str(exc))
        upload_body = ""
    if upload_body:
        for token in [
            'getValue(filename, \'.\', 1) == "lua"',
            "pending_command_lock(pdMS_TO_TICKS(50))",
            "pending_lua_reload_flag = true;",
            "request->setAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR, SPIFFS_EDITOR_LUA_RELOAD_BUSY);",
            "pending_command_unlock(locked);",
        ]:
            if token not in upload_body:
                errors.append(f"SPIFFSEditor .lua upload reload contract missing: {token}")
        for token in ["load_lua_script(", "run_lua_script("]:
            if token in upload_body:
                errors.append(f"SPIFFSEditor upload contains direct Lua operation: {token}")
else:
    errors.append("SPIFFSEditor.h not found")

if errors:
    print("API smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("API smoke check passed")
print(f"Discovered routes: {len(routes)}")
