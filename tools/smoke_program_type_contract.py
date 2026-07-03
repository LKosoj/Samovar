#!/usr/bin/env python3
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


def forbid_direct_current_wtype(name: str, body: str) -> None:
    forbidden = "program[ProgramNum].WType"
    if forbidden in body:
        errors.append(f"{name} reads {forbidden} directly")


program_types = read_text("program_types.h")
runtime_helpers = read_text("runtime_helpers.h")

if program_types:
    for token in [
        "using ProgramType = char;",
        "constexpr ProgramType PROGRAM_TYPE_NONE = '\\0';",
        "constexpr uint8_t PROGRAM_MAX = CAPACITY_NUM * 2;",
    ]:
        if token not in program_types:
            errors.append(f"program_types.h missing ProgramType source-of-truth token: {token}")

if runtime_helpers:
    try:
        body = extract_function_body(runtime_helpers, "inline ProgramType program_type_at")
        require_ordered_tokens(
            "program_type_at bounds program[] reads",
            body,
            [
                "if (index >= PROGRAM_MAX) return PROGRAM_TYPE_NONE;",
                "return program[index].WType;",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))

    try:
        body = extract_function_body(runtime_helpers, "inline ProgramType current_program_type")
        require_ordered_tokens(
            "current_program_type uses bounded helper",
            body,
            ["return program_type_at(ProgramNum);"],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))

checks = [
    ("Samovar.ino", "void triggerSysTicker"),
    ("Samovar.ino", "void send_ajax_json"),
    ("logic.h", "void withdrawal"),
    ("logic.h", "String get_nbk_status_text"),
    ("logic.h", "String get_beer_status_text"),
    ("logic.h", "void set_body_temp"),
    ("alarm.h", "void check_alarm"),
    ("impurity_detector.h", "bool is_first_body_program_after_heads"),
    ("impurity_detector.h", "void process_impurity_detector"),
    ("beer.h", "void check_alarm_beer"),
    ("nbk.h", "void SetSpeed"),
    ("nbk.h", "bool check_nbk_critical_alarms"),
]

for file_name, signature in checks:
    text = read_text(file_name)
    if not text:
        continue
    try:
        body = extract_function_body(text, signature)
    except ValueError as exc:
        errors.append(str(exc))
        continue
    forbid_direct_current_wtype(f"{file_name}:{signature}", body)

snapshot_requirements = {
    "Samovar.ino:void triggerSysTicker": ["current_program_type()"],
    "Samovar.ino:void send_ajax_json": ["current_program_type()"],
    "logic.h:void withdrawal": ["program_type_at(currentProgram)"],
    "logic.h:String get_nbk_status_text": ["current_program_type()"],
    "logic.h:String get_beer_status_text": ["current_program_type()"],
    "logic.h:void set_body_temp": ["current_program_type()"],
    "alarm.h:void check_alarm": ["current_program_type()"],
    "impurity_detector.h:bool is_first_body_program_after_heads": ["program_type_at(static_cast<uint8_t>(i))"],
    "impurity_detector.h:void process_impurity_detector": [
        "const uint8_t currentProgram = ProgramNum;",
        "const ProgramType currentType = program_type_at(currentProgram);",
    ],
    "beer.h:void check_alarm_beer": ["current_program_type()"],
    "nbk.h:void SetSpeed": ["current_program_type()"],
    "nbk.h:bool check_nbk_critical_alarms": ["current_program_type()"],
}

for key, tokens in snapshot_requirements.items():
    file_name, signature = key.split(":", 1)
    text = read_text(file_name)
    if not text:
        continue
    try:
        body = extract_function_body(text, signature)
    except ValueError:
        continue
    for token in tokens:
        if token not in body:
            errors.append(f"{key} missing ProgramType snapshot/helper token: {token}")

withdrawal_body = ""
logic_text = read_text("logic.h")
if logic_text:
    try:
        withdrawal_body = extract_function_body(logic_text, "void withdrawal")
    except ValueError as exc:
        errors.append(str(exc))

if withdrawal_body:
    if "ProgramLen - 3" in withdrawal_body:
        errors.append("logic.h:void withdrawal must not subtract from ProgramLen in unsigned bounds checks")
    if "bool hasTwoNextPrograms = currentProgram + 2 < ProgramLen;" not in withdrawal_body:
        errors.append("logic.h:void withdrawal missing explicit two-next-program bounds snapshot")
    if "program[ProgramNum].Speed = actualRate;" in withdrawal_body:
        errors.append("logic.h:void withdrawal writes Speed through live ProgramNum instead of currentProgram snapshot")
    if "program[currentProgram].Speed = actualRate;" not in withdrawal_body:
        errors.append("logic.h:void withdrawal missing currentProgram Speed write")

detector_text = read_text("impurity_detector.h")
if detector_text:
    try:
        detector_body = extract_function_body(detector_text, "void process_impurity_detector")
        if "program[ProgramNum].Speed" in detector_body:
            errors.append("impurity_detector.h:void process_impurity_detector reads Speed through live ProgramNum")
        if "program[currentProgram].Speed" not in detector_body:
            errors.append("impurity_detector.h:void process_impurity_detector missing currentProgram Speed reads")
        if "is_first_body_program_after_heads(currentProgram, currentType)" not in detector_body:
            errors.append("impurity_detector.h:void process_impurity_detector does not pass ProgramType snapshot to first-body helper")
    except ValueError as exc:
        errors.append(str(exc))

if errors:
    print("Program type contract smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("Program type contract smoke check passed")
