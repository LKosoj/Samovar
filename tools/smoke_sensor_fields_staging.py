#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
SENSORINIT = ROOT / "sensorinit.h"
SAMOVAR = ROOT / "Samovar.ino"
WEB = ROOT / "WebServer.ino"

errors = []


def read_file(path: Path) -> str:
    if not path.exists():
        errors.append(f"missing file: {path.relative_to(ROOT)}")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def require_token(name: str, body: str, token: str) -> None:
    if token not in body:
        errors.append(f"{name} missing token: {token}")


def forbid_token(name: str, body: str, token: str) -> None:
    if token in body:
        errors.append(f"{name} contains forbidden token: {token}")


def forbid_pattern(name: str, body: str, pattern: str) -> None:
    if re.search(pattern, body):
        errors.append(f"{name} matches forbidden pattern: {pattern}")


sensor_text = read_file(SENSORINIT)
samovar_text = read_file(SAMOVAR)
web_text = read_file(WEB)

functions = {}
for file_name, source, signature in [
    ("sensorinit.h", sensor_text, "inline void copy_ds_address_snapshot"),
    ("sensorinit.h", sensor_text, "void scan_ds_adress()"),
    ("sensorinit.h", sensor_text, "String get_DSAddressList"),
    ("Samovar.ino", samovar_text, "static void clear_ds_sensor_runtime"),
    ("Samovar.ino", samovar_text, "static void apply_setup_sensor_fields"),
    ("Samovar.ino", samovar_text, "void apply_config_runtime()"),
    ("Samovar.ino", samovar_text, "void loop()"),
    ("WebServer.ino", web_text, "String setupKeyProcessor"),
    ("WebServer.ino", web_text, "static bool apply_save_ds_addr_arg"),
    ("WebServer.ino", web_text, "void handleSave"),
]:
    try:
        functions[signature] = extract_function_body(source, signature)
    except ValueError as exc:
        errors.append(f"{file_name}: {exc}")
        functions[signature] = ""

if samovar_text:
    require_token("Samovar.ino DS registry mux", samovar_text, "portMUX_TYPE dsAddressMux = portMUX_INITIALIZER_UNLOCKED;")

if sensor_text:
    for token in [
        "struct DSAddressSnapshot",
        "DeviceAddress addr[SAMOVAR_DS_ADDRESS_MAX];",
        "uint8_t count;",
        "extern portMUX_TYPE dsAddressMux;",
        "inline bool ds_address_equal",
        "inline bool ds_address_invalid",
        "inline void set_invalid_ds_address",
    ]:
        require_token("sensorinit.h DS snapshot contract", sensor_text, token)

snapshot_body = functions.get("inline void copy_ds_address_snapshot", "")
if snapshot_body:
    require_ordered_tokens(
        "copy_ds_address_snapshot critical copy",
        snapshot_body,
        [
            "portENTER_CRITICAL(&dsAddressMux);",
            "uint8_t count = DScnt;",
            "snapshot.count = count;",
            "CopyDSAddress(DSAddr[i], snapshot.addr[i]);",
            "portEXIT_CRITICAL(&dsAddressMux);",
        ],
        errors,
    )

scan_body = functions.get("void scan_ds_adress()", "")
if scan_body:
    for token in [
        "DeviceAddress foundAddr[SAMOVAR_DS_ADDRESS_MAX];",
        "sensors.getAddress(foundAddr[dc], dc)",
        "sensors.setResolution(foundAddr[dc], 12)",
        "portENTER_CRITICAL(&dsAddressMux);",
        "DScnt = dc;",
        "CopyDSAddress(foundAddr[i], DSAddr[i]);",
        "portEXIT_CRITICAL(&dsAddressMux);",
    ]:
        require_token("scan_ds_adress snapshot commit", scan_body, token)
    for token in [
        "sensors.getAddress(DSAddr",
        "sensors.setResolution(DSAddr",
        "printAddress(DSAddr",
        "sensors.getResolution(DSAddr",
    ]:
        forbid_token("scan_ds_adress live global scan", scan_body, token)
    enter_token = "portENTER_CRITICAL(&dsAddressMux);"
    exit_token = "portEXIT_CRITICAL(&dsAddressMux);"
    enter_index = scan_body.find(enter_token)
    exit_index = scan_body.find(exit_token, enter_index + len(enter_token))
    if enter_index < 0 or exit_index < 0:
        errors.append("scan_ds_adress missing dsAddressMux commit boundary")
    else:
        pre_commit = scan_body[:enter_index]
        post_commit = scan_body[exit_index + len(exit_token):]
        forbid_pattern("scan_ds_adress pre-commit DS registry access", pre_commit, r"\b(?:DSAddr|DScnt)\b")
        forbid_pattern("scan_ds_adress post-commit DS registry access", post_commit, r"\b(?:DSAddr|DScnt)\b")

address_list_body = functions.get("String get_DSAddressList", "")
if address_list_body:
    for token in [
        "DSAddressSnapshot snapshot;",
        "copy_ds_address_snapshot(snapshot);",
        "i != snapshot.count",
        "getDSAddress(snapshot.addr[i])",
    ]:
        require_token("get_DSAddressList snapshot", address_list_body, token)
    for token in ["DScnt", "DSAddr["]:
        forbid_token("get_DSAddressList live globals", address_list_body, token)

setup_body = functions.get("String setupKeyProcessor", "")
if setup_body:
    for token in [
        "get_DSAddressList(getDSAddress(SamSetup.SteamAdress))",
        "get_DSAddressList(getDSAddress(SamSetup.PipeAdress))",
        "get_DSAddressList(getDSAddress(SamSetup.WaterAdress))",
        "get_DSAddressList(getDSAddress(SamSetup.TankAdress))",
        "get_DSAddressList(getDSAddress(SamSetup.ACPAdress))",
    ]:
        require_token("setupKeyProcessor persisted DS addresses", setup_body, token)
    for token in [
        "SteamSensor.Sensor",
        "PipeSensor.Sensor",
        "WaterSensor.Sensor",
        "TankSensor.Sensor",
        "ACPSensor.Sensor",
    ]:
        forbid_token("setupKeyProcessor runtime sensor address", setup_body, token)

apply_save_ds_body = functions.get("static bool apply_save_ds_addr_arg", "")
if apply_save_ds_body:
    for token in ("const DSAddressSnapshot& snapshot", "uint8_t resetBit", "uint8_t& resetMask"):
        require_token("apply_save_ds_addr_arg snapshot signature", web_text, token)
    for token in [
        "parse_save_long_arg(request, name, -1, SAMOVAR_DS_ADDRESS_MAX - 1, idx)",
        "DeviceAddress selectedAddress;",
        "set_invalid_ds_address(selectedAddress);",
        "idx >= snapshot.count",
        "CopyDSAddress(snapshot.addr[idx], selectedAddress);",
        "if (!ds_address_equal(target, selectedAddress))",
    ]:
        require_token("apply_save_ds_addr_arg snapshot parse", apply_save_ds_body, token)
    reset_if_token = "if (!ds_address_equal(target, selectedAddress))"
    try:
        reset_if_start = apply_save_ds_body.find(reset_if_token)
        reset_if_body, reset_if_end = extract_braced_block_after(apply_save_ds_body, reset_if_token)
        require_ordered_tokens(
            "apply_save_ds_addr_arg resets only when address changes",
            reset_if_body,
            [
                "CopyDSAddress(selectedAddress, target);",
                "resetMask |= resetBit;",
            ],
            errors,
        )
        reset_outside_if = apply_save_ds_body[:reset_if_start] + apply_save_ds_body[reset_if_end:]
        forbid_pattern("apply_save_ds_addr_arg reset outside address-change block", reset_outside_if, r"\bresetMask\s*\|=\s*resetBit\s*;")
    except ValueError as exc:
        errors.append(f"apply_save_ds_addr_arg reset block: {exc}")
    for token in ["DScnt", "DSAddr["]:
        forbid_token("apply_save_ds_addr_arg live globals", apply_save_ds_body, token)

handle_save_body = functions.get("void handleSave", "")
if handle_save_body:
    require_ordered_tokens(
        "handleSave snapshots DS registry before DS parsing",
        handle_save_body,
        [
            "DSAddressSnapshot dsSnapshot;",
            "copy_ds_address_snapshot(dsSnapshot);",
            'apply_save_ds_addr_arg(request, "SteamAddr", dsSnapshot, staged.SteamAdress, PROFILE_SENSOR_RESET_STEAM, sensorResetMask)',
            'apply_save_ds_addr_arg(request, "PipeAddr", dsSnapshot, staged.PipeAdress, PROFILE_SENSOR_RESET_PIPE, sensorResetMask)',
            'apply_save_ds_addr_arg(request, "WaterAddr", dsSnapshot, staged.WaterAdress, PROFILE_SENSOR_RESET_WATER, sensorResetMask)',
            'apply_save_ds_addr_arg(request, "TankAddr", dsSnapshot, staged.TankAdress, PROFILE_SENSOR_RESET_TANK, sensorResetMask)',
            'apply_save_ds_addr_arg(request, "ACPAddr", dsSnapshot, staged.ACPAdress, PROFILE_SENSOR_RESET_ACP, sensorResetMask)',
        ],
        errors,
    )
    for token in ["DScnt", "DSAddr["]:
        forbid_token("handleSave DS parsing live globals", handle_save_body, token)

clear_body = functions.get("static void clear_ds_sensor_runtime", "")
if clear_body:
    for token in ["avgTemp = 0;", "PrevTemp = 0;", "ErrCount = 0;"]:
        require_token("clear_ds_sensor_runtime readings reset", clear_body, token)
    forbid_pattern("clear_ds_sensor_runtime address mutation", clear_body, r"\bSensor\s*\[|\.Sensor\b|CopyDSAddress\s*\(")

apply_fields_body = functions.get("static void apply_setup_sensor_fields", "")
if apply_fields_body:
    require_ordered_tokens(
        "apply_setup_sensor_fields copies addresses before resets",
        apply_fields_body,
        [
            "CopyDSAddress(SamSetup.SteamAdress, SteamSensor.Sensor);",
            "CopyDSAddress(SamSetup.PipeAdress, PipeSensor.Sensor);",
            "CopyDSAddress(SamSetup.WaterAdress, WaterSensor.Sensor);",
            "CopyDSAddress(SamSetup.TankAdress, TankSensor.Sensor);",
            "CopyDSAddress(SamSetup.ACPAdress, ACPSensor.Sensor);",
            "if ((resetMask & PROFILE_SENSOR_RESET_STEAM) != 0) clear_ds_sensor_runtime(SteamSensor);",
        ],
        errors,
    )

apply_config_body = functions.get("void apply_config_runtime()", "")
if apply_config_body:
    require_token("apply_config_runtime sensor field apply", apply_config_body, "apply_setup_sensor_fields(0);")
    for token in [
        "CopyDSAddress(SamSetup.SteamAdress, SteamSensor.Sensor)",
        "CopyDSAddress(SamSetup.PipeAdress, PipeSensor.Sensor)",
        "CopyDSAddress(SamSetup.WaterAdress, WaterSensor.Sensor)",
        "CopyDSAddress(SamSetup.TankAdress, TankSensor.Sensor)",
        "CopyDSAddress(SamSetup.ACPAdress, ACPSensor.Sensor)",
    ]:
        forbid_token("apply_config_runtime direct sensor address copy", apply_config_body, token)

commit_signature = "static OperationError commit_profile_operation()"
commit_offset = samovar_text.rfind(commit_signature)
commit_body = extract_function_body(samovar_text[commit_offset:], commit_signature) if commit_offset >= 0 else ""
if commit_body:
    require_ordered_tokens(
        "profile owner applies sensor fields only after verified profile commit",
        commit_body,
        [
            "save_profile_nvs(active_profile_operation.settings)",
            "if (persistResult != PERSIST_OK)",
            "SamSetup = active_profile_operation.settings;",
            "apply_setup_sensor_fields(active_profile_operation.sensorResetMask);",
            "if (hasSettings) apply_config_runtime();",
        ],
        errors,
    )

if web_text:
    for token in ["DScnt", "DSAddr["]:
        if re.search(rf"\b{re.escape(token)}", web_text):
            errors.append(f"WebServer.ino contains direct DS registry token outside sensor snapshot API: {token}")

if errors:
    print("sensor fields staging smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("sensor fields staging smoke passed")
