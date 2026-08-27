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
SENSORINIT = ROOT / "sensorinit.h"
SAMOVAR = ROOT / "Samovar.ino"
WEB = ROOT / "WebServer.ino"
HEADER = ROOT / "Samovar.h"

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
header_text = read_file(HEADER)

functions = {}
for file_name, source, signature in [
    ("sensorinit.h", sensor_text, "inline void copy_ds_address_snapshot"),
    ("sensorinit.h", sensor_text, "void scan_ds_adress()"),
    ("sensorinit.h", sensor_text, "String get_DSAddressList"),
    ("Samovar.ino", samovar_text, "static void clear_ds_sensor_runtime"),
    ("Samovar.ino", samovar_text, "static void apply_setup_sensor_fields"),
    ("Samovar.ino", samovar_text, "static void tick_report_sensor_errors"),
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
    if "get_DSAddressList(getDSAddress(SamSetup.*f.member))" not in setup_body:
        errors.append("setupKeyProcessor persisted DS addresses: table-driven lookup not found")
    for var_name, member in (
        ("SteamAddr", "SteamAdress"), ("PipeAddr", "PipeAdress"),
        ("WaterAddr", "WaterAdress"), ("TankAddr", "TankAdress"),
        ("ACPAddr", "ACPAdress"),
    ):
        initializer = f'{{"{var_name}", &SetupEEPROM::{member}}}'
        if initializer not in web_text:
            errors.append(f"setupKeyProcessor DS address table missing initializer for {var_name}: {initializer}")
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
    # handleSave больше не вызывает apply_save_ds_addr_arg построчно по имени сенсора:
    # один generic-цикл по kSaveDsAddrFields делает это для всех пяти. Порядок
    # Steam/Pipe/Water/Tank/ACP проверяется отдельно ниже, на самой таблице.
    require_ordered_tokens(
        "handleSave snapshots DS registry before DS parsing",
        handle_save_body,
        [
            "DSAddressSnapshot dsSnapshot;",
            "copy_ds_address_snapshot(dsSnapshot);",
            "for (const SaveDsAddrField &f : kSaveDsAddrFields)",
            "apply_save_ds_addr_arg(request, f.name, dsSnapshot, staged.*f.member, f.resetBit, sensorResetMask)",
        ],
        errors,
    )
    for token in ["DScnt", "DSAddr["]:
        forbid_token("handleSave DS parsing live globals", handle_save_body, token)

ds_table_match = re.search(r"kSaveDsAddrFields\[\]\s*=\s*\{(.*?)\};", web_text, re.S)
if not ds_table_match:
    errors.append("kSaveDsAddrFields table not found in WebServer.ino")
else:
    require_ordered_tokens(
        "kSaveDsAddrFields keeps Steam/Pipe/Water/Tank/ACP order",
        ds_table_match.group(1),
        [
            '{"SteamAddr", &SetupEEPROM::SteamAdress, PROFILE_SENSOR_RESET_STEAM}',
            '{"PipeAddr", &SetupEEPROM::PipeAdress, PROFILE_SENSOR_RESET_PIPE}',
            '{"WaterAddr", &SetupEEPROM::WaterAdress, PROFILE_SENSOR_RESET_WATER}',
            '{"TankAddr", &SetupEEPROM::TankAdress, PROFILE_SENSOR_RESET_TANK}',
            '{"ACPAddr", &SetupEEPROM::ACPAdress, PROFILE_SENSOR_RESET_ACP}',
        ],
        errors,
    )

clear_body = functions.get("static void clear_ds_sensor_runtime", "")
if clear_body:
    for token in ["avgTemp = 0;", "PrevTemp = 0;", "ErrCount = 0;"]:
        require_token("clear_ds_sensor_runtime readings reset", clear_body, token)
    forbid_pattern("clear_ds_sensor_runtime address mutation", clear_body, r"\bSensor\s*\[|\.Sensor\b|CopyDSAddress\s*\(")

report_errors_body = functions.get("static void tick_report_sensor_errors", "")
if report_errors_body:
    require_ordered_tokens(
        "tick_report_sensor_errors stays silent without heat",
        report_errors_body,
        [
            "if (!PowerOn && !lua_heater_channel_raised()) return;",
            "if (!sensor_configured(*sensorList[i])) continue;",
            "if (sensorList[i]->ErrCount > 10)",
            "SendMsg(kSensorSetupFields[i].errorMessage, ALARM_MSG);",
        ],
        errors,
    )

apply_fields_body = functions.get("static void apply_setup_sensor_fields", "")
if apply_fields_body:
    require_ordered_tokens(
        "apply_setup_sensor_fields copies addresses before resets",
        apply_fields_body,
        [
            "CopyDSAddress(SamSetup.*kSensorSetupFields[i].address, sensorList[i]->Sensor);",
            "resetMask & kSensorSetupFields[i].resetBit",
            "clear_ds_sensor_runtime(*sensorList[i]);",
        ],
        errors,
    )

# Связка «поле профиля <-> датчик» больше не записана в каждой строке кода: она держится
# на том, что порядок kSensorSetupFields совпадает с sensorList. Перепутанный порядок
# записал бы адрес чужого датчика и раздал бы чужие уставки, поэтому проверяем его явно.
require_ordered_tokens(
    "kSensorSetupFields order matches sensorList",
    samovar_text,
    [
        "kSensorSetupFields[DS_SENSOR_COUNT] = {",
        "&SetupEEPROM::SteamAdress, PROFILE_SENSOR_RESET_STEAM, &SetupEEPROM::SetSteamTemp,",
        "&SetupEEPROM::SteamDelay, \"Ошибка датчика температуры пара!\"},",
        "&SetupEEPROM::PipeAdress, PROFILE_SENSOR_RESET_PIPE, &SetupEEPROM::SetPipeTemp,",
        "&SetupEEPROM::PipeDelay, \"Ошибка датчика температуры царги!\"},",
        "&SetupEEPROM::WaterAdress, PROFILE_SENSOR_RESET_WATER, &SetupEEPROM::SetWaterTemp,",
        "&SetupEEPROM::WaterDelay, \"Ошибка датчика температуры воды!\"},",
        "&SetupEEPROM::TankAdress, PROFILE_SENSOR_RESET_TANK, &SetupEEPROM::SetTankTemp,",
        "&SetupEEPROM::TankDelay, \"Ошибка датчика температуры куба!\"},",
        "&SetupEEPROM::ACPAdress, PROFILE_SENSOR_RESET_ACP, &SetupEEPROM::SetACPTemp,",
        "&SetupEEPROM::ACPDelay, \"Ошибка датчика температуры в ТСА!\"},",
    ],
    errors,
)

# Сам sensorList - вторая половина той же связки: kSensorSetupFields[i] осмыслен только
# вместе с sensorList[i]. Массив раздаёт адреса, уставки и тексты аварий пяти датчикам
# сразу (Samovar.ino, FS.ino, sensorinit.h), поэтому перестановка строк здесь молча
# применила бы настройки «воды» к кубу. Длину пиним тоже: значение больше пяти оставит
# в хвосте nullptr, который циклы разыменуют.
require_ordered_tokens(
    "Samovar.h sensorList keeps Steam/Pipe/Water/Tank/ACP order",
    strip_cpp_comments(header_text),
    [
        "static const uint8_t DS_SENSOR_COUNT = 5;",
        "DSSensor* const sensorList[DS_SENSOR_COUNT] = {",
        "&SteamSensor, &PipeSensor, &WaterSensor, &TankSensor, &ACPSensor};",
    ],
    errors,
)

apply_config_body = functions.get("void apply_config_runtime()", "")
if apply_config_body:
    require_token("apply_config_runtime sensor field apply", apply_config_body, "apply_setup_sensor_fields(0);")
    # Уставка и задержка берутся из разных полей таблицы; перепутать их местами компилятор
    # позволит молча (uint16_t приводится к float), поэтому пиним обе строки цикла.
    require_ordered_tokens(
        "apply_config_runtime applies setpoint and delay per sensor",
        apply_config_body,
        [
            "sensorList[i]->SetTemp = SamSetup.*kSensorSetupFields[i].setTemp;",
            "sensorList[i]->Delay = SamSetup.*kSensorSetupFields[i].delay;",
        ],
        errors,
    )
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
