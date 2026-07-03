#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
NVS = ROOT / "NVS_Manager.ino"
SAMOVAR = ROOT / "Samovar.ino"
API = ROOT / "samovar_api.h"

errors: list[str] = []


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


def extract_function_definition_body(source: str, signature: str) -> str:
    offset = 0
    while True:
        start = source.find(signature, offset)
        if start < 0:
            raise ValueError(f"function not found: {signature}")
        brace = source.find("{", start)
        semicolon = source.find(";", start, brace if brace >= 0 else len(source))
        if brace >= 0 and semicolon < 0:
            return extract_function_body(source[start:], signature)
        offset = start + len(signature)


nvs_text = strip_cpp_comments(read_file(NVS))
samovar_text = strip_cpp_comments(read_file(SAMOVAR))
api_text = strip_cpp_comments(read_file(API))

functions: dict[str, str] = {}
for file_name, source, signature in [
    ("NVS_Manager.ino", nvs_text, "static bool save_samovar_nvs_compaction_backup"),
    ("NVS_Manager.ino", nvs_text, "static bool compact_samovar_nvs_namespaces"),
    ("NVS_Manager.ino", nvs_text, "static bool recover_pending_samovar_nvs_compaction"),
    ("NVS_Manager.ino", nvs_text, "bool recover_pending_nvs_compaction()"),
    ("NVS_Manager.ino", nvs_text, "void load_profile_nvs()"),
    ("Samovar.ino", samovar_text, "void setup()"),
]:
    try:
        functions[signature] = extract_function_definition_body(source, signature)
    except ValueError as exc:
        errors.append(f"{file_name}: {exc}")
        functions[signature] = ""

if api_text:
    require_token("samovar_api.h public recovery prototype", api_text, "bool recover_pending_nvs_compaction();")

wrapper_body = functions.get("bool recover_pending_nvs_compaction()", "")
if wrapper_body:
    require_ordered_tokens(
        "public recovery wrapper",
        wrapper_body,
        [
            "return recover_pending_samovar_nvs_compaction();",
        ],
        errors,
    )

save_backup_body = functions.get("static bool save_samovar_nvs_compaction_backup", "")
if save_backup_body:
    require_ordered_tokens(
        "durable backup write order",
        save_backup_body,
        [
            "nvs_open(SAMOVAR_NVS_COMPACTION_BACKUP_NAMESPACE, NVS_READWRITE, &handle)",
            "nvs_erase_all(handle)",
            "nvs_commit(handle)",
            "nvs_set_blob(handle, SAMOVAR_NVS_COMPACTION_BACKUP_DATA_KEY, blob, totalLen)",
            "nvs_set_u32(handle, SAMOVAR_NVS_COMPACTION_BACKUP_MAGIC_KEY, SAMOVAR_NVS_COMPACTION_BACKUP_MAGIC)",
            "nvs_commit(handle)",
        ],
        errors,
    )
    set_blob_index = save_backup_body.find("nvs_set_blob(handle, SAMOVAR_NVS_COMPACTION_BACKUP_DATA_KEY")
    set_marker_index = save_backup_body.find("nvs_set_u32(handle, SAMOVAR_NVS_COMPACTION_BACKUP_MAGIC_KEY")
    if set_blob_index != -1 and set_marker_index != -1 and set_marker_index < set_blob_index:
        errors.append("durable backup marker is written before backup data")

compact_body = functions.get("static bool compact_samovar_nvs_namespaces", "")
if compact_body:
    require_ordered_tokens(
        "compaction recover/backup/erase/restore/clear order",
        compact_body,
        [
            "recover_pending_samovar_nvs_compaction()",
            "backup_samovar_nvs_entries(entries, SAMOVAR_NVS_BACKUP_MAX_ENTRIES, count)",
            "save_samovar_nvs_compaction_backup(entries, count)",
            "nvs_erase_all(handle)",
            "restore_samovar_nvs_entries(entries, count)",
            "clear_samovar_nvs_compaction_backup();",
        ],
        errors,
    )

load_profile_body = functions.get("void load_profile_nvs()", "")
if load_profile_body:
    forbid_token("load_profile_nvs late recovery", load_profile_body, "recover_pending_samovar_nvs_compaction")
    forbid_token("load_profile_nvs late public recovery", load_profile_body, "recover_pending_nvs_compaction")
    require_token(
        "load_profile_nvs direct common namespace load",
        load_profile_body,
        "load_profile_nvs_from_namespace(SAMOVAR_COMMON_PROFILE_NAMESPACE);",
    )

setup_body = functions.get("void setup()", "")
if setup_body:
    require_ordered_tokens(
        "setup recovery before migration and config read",
        setup_body,
        [
            "recover_pending_nvs_compaction()",
            "migrate_from_eeprom();",
            "read_config();",
        ],
        errors,
    )
    recovery_if = re.search(
        r"if\s*\(\s*!recover_pending_nvs_compaction\(\)\s*\)\s*\{(?P<body>.*?)\n\s*\}",
        setup_body,
        re.DOTALL,
    )
    if not recovery_if:
        errors.append("setup missing fail-fast recovery guard")
    else:
        guard_body = recovery_if.group("body")
        require_token("setup recovery failure log", guard_body, 'Serial.println(F("FATAL: NVS compaction recovery failed"));')
        require_ordered_tokens(
            "setup recovery failure stops boot",
            guard_body,
            [
                "while (true)",
                "delay(1000);",
            ],
            errors,
        )

if nvs_text:
    compact_start = nvs_text.find("static bool compact_samovar_nvs_namespaces")
    compact_recovery = nvs_text.find("recover_pending_samovar_nvs_compaction()", compact_start)
    if compact_start == -1 or compact_recovery == -1:
        errors.append("compact_samovar_nvs_namespaces must still call static recovery")

if errors:
    print("NVS durable compaction smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("NVS durable compaction smoke check passed")
