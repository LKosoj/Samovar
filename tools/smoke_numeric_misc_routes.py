#!/usr/bin/env python3
import hashlib
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8", errors="ignore")


web = strip_cpp_comments(read("WebServer.ino"))
samovar = strip_cpp_comments(read("Samovar.ino"))


def body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


program = body(web, "void web_program")
calibrate = body(web, "void calibrate_command")
column = body(web, "static void handle_column_params_request")
save = body(web, "void handleSave")
save_allowlist = body(web, "static bool save_param_name_allowed")
recv = body(samovar, "void recvMsg")
loop = body(samovar, "void loop()")
commit_signature = "static OperationError commit_profile_operation()"
commit_offset = samovar.rfind(commit_signature)
commit = body(samovar[commit_offset:], commit_signature) if commit_offset >= 0 else ""
process_signature = "static void process_profile_operation()"
process_offset = samovar.rfind(process_signature)
process = body(samovar[process_offset:], process_signature) if process_offset >= 0 else ""

require_ordered_tokens(
    "program request allowlist and metadata queue",
    program,
    [
        "for (size_t index = 0; index < request->params(); index++)",
        'param->name() == "vless"',
        "!known || !param->isPost() || param->isFile()",
        'request_param_count(request, "Descr")',
        'char descriptionValue[251] = "";',
        "description.length() > 250",
        "metadataFlags |= PROFILE_OPERATION_METADATA_DESCRIPTION;",
        "queue_profile_operation(",
    ],
    errors,
)
# vless остаётся известным именем ради старой страницы программы, но значение не читается.
for token in ["parse_control_vless(", 'get_request_param(request, "vless")']:
    if token in program:
        errors.append(f"web_program still reads vless: {token}")
require_ordered_tokens(
    "profile owner applies program metadata after race checks",
    process + commit,
    [
        "PROFILE_OPERATION_REQUIRE_PROGRAM_IDLE",
        "program_update_session_active()",
        "commit_profile_operation();",
        "runtime_state_lock(pdMS_TO_TICKS(500))",
        "program_commit(active_profile_operation.program);",
        "SessionDescription = escapedDescription;",
    ],
    errors,
)

require_ordered_tokens(
    "calibration exact schema and typed queue",
    calibrate,
    [
        "startCount + finishCount != 1",
        "startCount == 1 ? speedCount != 1 : speedCount != 0",
        "parse_control_calibration_speed(",
        "OperationId operationId = 0;",
        "PendingLocalCalCmd command = {};",
        "queue_pending_local_cal(command, operationId)",
        "I2CStepperDevice* device = select_i2c_stepper_device(request, address);",
        "i2cstepper_v3_address_is_mixer(address)",
        "device->config.stepsPerMl == 0",
        "const uint64_t rate =",
        "rate > UINT32_MAX",
        "command.pumpMlHour = uint32_t(rate);",
        "queue_pending_i2ccal(command, operationId)",
        "send_operation_accepted(request, operationId);",
    ],
    errors,
)
if "CurrrentStepperSpeed =" in calibrate or ".toInt()" in calibrate:
    errors.append("calibrate handler mutates/narrows speed before loop")

for token in [
    "input->isFile() || input->isPost()",
    "parse_exact_enum(input->value().c_str(), allowed, 3, parsed)",
    'build_error_envelope("argument", "mat", "Invalid mat")',
    'build_error_envelope("argument", "diam", "Invalid diam")',
    "column_diam_allowed(parsed)",
    "calculate_column_etalon(material, diamInches)",
]:
    if token not in column:
        errors.append(f"column material/diam gate missing: {token}")

for token in ["parseLongSafe", "parseFloatSafe", ".toInt()", ".toFloat()"]:
    if token in save:
        errors.append(f"handleSave contains legacy conversion: {token}")
require_ordered_tokens(
    "save allowlist/source gate precedes staging",
    save,
    [
        "for (size_t index = 0; index < request->params(); index++)",
        "save_param_name_allowed(param->name())",
        'build_error_envelope(\n              "not_allowed", param ? param->name().c_str() : nullptr,\n              "Invalid request field")',
        "!param->isPost() || param->isFile()",
        "request_param_count(request, param->name().c_str()) != 1",
        "SetupEEPROM staged = SamSetup;",
    ],
    errors,
)
# save_param_name_allowed больше не хардкодит name == "...": оно перебирает те же
# таблицы/массивы имён, что применяет handleSave (см. tools/smoke_handle_save_staging.py
# для полной проверки). Здесь просто убеждаемся, что нужные имена всё ещё в источнике
# истины и что старая захардкоженная цепочка сравнений не вернулась.
for source, name in (
    ("kSaveU16Fields", "SteamDelay"),
    ("kSaveSpecialNames", "fullsetup"),
    ("kSaveSpecialNames", "WProgram"),
):
    table_match = re.search(rf"{source}\[\]\s*=\s*\{{(.*?)\}};", web, re.S)
    if not table_match or f'"{name}"' not in table_match.group(1):
        errors.append(f"save allowlist source {source} missing {name}")
if re.search(r'name\s*==\s*"', save_allowlist):
    errors.append("save allowlist still hardcodes a literal name == \"...\" comparison")

require_ordered_tokens(
    "WebSerial fixed strict command",
    recv,
    [
        "len > WEBSERIAL_COMMAND_MAX",
        "data[index] == '\\0'",
        'strcmp(command, "print") == 0',
        'static const char prefix[] = "WFpulseCount=";',
        "parse_bounded_uint16(valueText, 0, UINT16_MAX, value)",
        "if (!result.ok())",
        "water_pulse_count_set(value);",
    ],
    errors,
)
for token in ["String d", ".toInt()", "getValue("]:
    if token in recv:
        errors.append(f"WebSerial contains legacy parser: {token}")

expected_hashes = {
    # [Б7] хэш обновлён: PROGRAM_POWER_ABS_THRESHOLD переехала из power_regulator.h
    # в program_types.h (без изменения существующих enum/struct/inline-функций), а
    # program_io.h::prepare_program_for_mode() под SAMOVAR_USE_POWER стал проверять,
    # что первая строка ректификационной программы задаёт абсолютную мощность -
    # при ошибке draft сбрасывается тем же паттерном, что и остальные reject'ы этой
    # функции, program[] не коммитится (draft isolation A-09 не нарушена).
    # [Ф2] хэш обновлён: разборщик строки ректификации отвергает строку H/B/C/T
    # без объёма и температуры (никогда не завершится) - той же схемой ok=false,
    # что и соседние проверки; draft isolation A-09 не тронута.
    # [П1/П5, 02.09.2026] хэш обновлён: prepare_program_for_mode() для дистилляции
    # требует, чтобы первая строка с ненулевой мощностью была абсолютной уставкой
    # (в разгоне target_power_volt == 0, поправка ушла бы ниже порога), а строки
    # S/R принимают долю в (0,1) вместо (0,1]; отказ - тем же сбросом draft,
    # program[] не коммитится, A-09 не нарушена.
    # [П1 доп.] номер физической строки в сообщении.
    # [БК п.9, 02.09.2026] хэш обновлён: новый формат PROGRAM_FORMAT_BK (пятое поле
    # «Т пара») и общий разбор четырёх полей с DIST; отказы - тем же сбросом draft,
    # program[] не коммитится, A-09 не нарушена.
    # 05.09.2026: добавлен отдельный строгий формат программы Cheese с шестым
    # полем Param и направлением устройства только -1..1; разбор по-прежнему
    # идёт в draft до атомарного commit.
    # 09.09.2026: Lua-строки хранят вызов в общем текстовом пуле черновика;
    # пул коммитится вместе со строками под тем же configMux, поэтому изоляция
    # черновика A-09 сохранена.
    # 13.09.2026: добавлен строгий тип F программы Cheese; точный множитель F
    # хранится в той же 4-байтовой ячейке строки и коммитится только со всем
    # черновиком, поэтому изоляция A-09 сохранена.
    # 13.09.2026: D со способом 3 хранит точное число шагов в той же 4-байтовой
    # ячейке строки; разбор и запись по-прежнему выполняются только в черновике.
    # 17.09.2026: строке F пива разрешено время (0 = бесконечно, потолок 30 суток);
    # меняется только проверка значений строки внутри черновика, A-09 не затронута.
    # 17.09.2026: шесть program_append_*_row переведены с "out += (String)x + \";\""
    # (два временных String на поле) на последовательные "out += x; out += ';';" -
    # итоговый сериализованный текст не изменился ни на символ, разбор (A-09) не тронут.
    # 17.09.2026: литералы errorMessage/ProgramParseSpec.*Message лишились общего
    # префикса "Ошибка программы: " - он теперь единственный раз приклеивается в
    # format_program_parse_error(); итоговый текст для пользователя не изменился
    # ни на символ (экономия флеша), значения и разбор (A-09) не тронуты.
    # 20.09.2026: строка отбора ректификации (не пауза) отвергается при скорости выше
    # RECT_RATE_MAX_LPH = 20 л/ч - тем же ok=false в разборе строки, что и соседние
    # проверки; разбор по-прежнему идёт в черновике, A-09 не тронута.
    # 20.09.2026 (правка программы при идущем процессе): добавлены
    # program_row_serializer_for_mode() и program_first_changed_locked_row();
    # serialize_program_for_mode() выбирает сериализатор через первую. Разбор (A-09)
    # и сериализованный текст не тронуты.
    "program_io.h": "26b4207311db5f098a3ffd7d7e040514496f594eee3a5875eb7966ffb3d09a8f",
    "program_types.h": "93b085c108487dc89b221156f91112b898a7a554fb21713a4dac4e4e48f5f96a",
}
for name, expected in expected_hashes.items():
    actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    if actual != expected:
        errors.append(f"frozen A-09 dependency changed: {name} {actual}")

if errors:
    print("Numeric miscellaneous route smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Numeric miscellaneous route smoke passed")
