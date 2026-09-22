#!/usr/bin/env python3
"""Сохранение оптимума и программы НБК в общем профиле NVS."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def ordered(text: str, tokens: list[str], message: str, errors: list[str]) -> None:
    position = 0
    for token in tokens:
        found = text.find(token, position)
        if found < 0:
            errors.append(f"{message}: missing ordered token {token!r}")
            return
        position = found + len(token)


def test_optimum_helper(samovar: str) -> int:
    body = extract_function_body(
        samovar,
        "void persist_nbk_optimum(float optimalPower, float optimalFeed) {",
    )
    harness = r'''
#include <cassert>

enum PersistResult { PERSIST_OK, PERSIST_WRITE_FAILED };
struct SetupEEPROM {
  float untouched;
  float NbkOptimalPower;
  float NbkOptimalFeed;
};

SetupEEPROM SamSetup{};
int configMux = 0;
#define portENTER_CRITICAL(lock) ((void)(lock))
#define portEXIT_CRITICAL(lock) ((void)(lock))

static PersistResult nextResult = PERSIST_OK;
static int saveCalls = 0;
static SetupEEPROM saved{};
PersistResult save_profile_nvs(const SetupEEPROM& candidate) {
  saveCalls++;
  saved = candidate;
  return nextResult;
}

void persist_nbk_optimum(float optimalPower, float optimalFeed) {
@BODY@
}

int main() {
  SamSetup = {42.0f, 100.0f, 2.0f};
  nextResult = PERSIST_OK;
  persist_nbk_optimum(1500.0f, 8.5f);
  assert(saveCalls == 1);
  assert(saved.untouched == 42.0f);
  assert(saved.NbkOptimalPower == 1500.0f);
  assert(saved.NbkOptimalFeed == 8.5f);
  assert(SamSetup.NbkOptimalPower == 1500.0f);
  assert(SamSetup.NbkOptimalFeed == 8.5f);

  persist_nbk_optimum(1500.0f, 8.5f);
  assert(saveCalls == 1);

  nextResult = PERSIST_WRITE_FAILED;
  persist_nbk_optimum(2200.0f, 14.0f);
  assert(saveCalls == 2);
  assert(saved.NbkOptimalPower == 2200.0f);
  assert(saved.NbkOptimalFeed == 14.0f);
  assert(SamSetup.NbkOptimalPower == 1500.0f);
  assert(SamSetup.NbkOptimalFeed == 8.5f);
  return 0;
}
'''.replace("@BODY@", body)
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-nvs-") as temp_dir:
        source = Path(temp_dir) / "test.cpp"
        binary = Path(temp_dir) / "test"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode != 0:
            sys.stderr.write(compiled.stdout + compiled.stderr)
            return compiled.returncode
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(ran.stdout)
        sys.stderr.write(ran.stderr)
        return ran.returncode


def test_program_mapping(samovar: str) -> int:
    body = extract_function_body(
        samovar,
        "static void program_store_nbk_profile(\n"
        "    SetupEEPROM& profile,\n"
        "    const ProgramDraft& draft,\n"
        "    ProgramUpdateAction action) {",
    )
    harness = r'''
#include <cassert>
#include <cstdint>

enum ProgramUpdateAction : uint8_t {
  PROGRAM_UPDATE_REPLACE = 0,
  PROGRAM_UPDATE_CLEAR,
};
struct ProgramRow { float Speed; float Power; };
struct ProgramDraft { ProgramRow rows[4]; uint8_t len; };
struct SetupEEPROM {
  uint8_t NbkProgramLength;
  float NbkProgramHSpeed;
  float NbkProgramHPower;
  float NbkProgramSSpeed;
  float NbkProgramSPower;
  float NbkProgramOSpeed;
  float NbkProgramOPower;
  float NbkProgramWSpeed;
  float NbkProgramWPower;
};

static void program_store_nbk_profile(
    SetupEEPROM& profile,
    const ProgramDraft& draft,
    ProgramUpdateAction action) {
@BODY@
}

int main() {
  SetupEEPROM profile{};
  ProgramDraft first{{{1.5f, 101.0f}, {2.5f, 202.0f},
                      {3.5f, 303.0f}, {4.5f, 404.0f}}, 4};
  program_store_nbk_profile(profile, first, PROGRAM_UPDATE_REPLACE);
  assert(profile.NbkProgramLength == 4);
  assert(profile.NbkProgramHSpeed == 1.5f && profile.NbkProgramHPower == 101.0f);
  assert(profile.NbkProgramSSpeed == 2.5f && profile.NbkProgramSPower == 202.0f);
  assert(profile.NbkProgramOSpeed == 3.5f && profile.NbkProgramOPower == 303.0f);
  assert(profile.NbkProgramWSpeed == 4.5f && profile.NbkProgramWPower == 404.0f);

  ProgramDraft second{{{11.0f, 1111.0f}, {12.0f, 1222.0f},
                       {13.0f, 1333.0f}, {14.0f, 1444.0f}}, 4};
  program_store_nbk_profile(profile, second, PROGRAM_UPDATE_REPLACE);
  assert(profile.NbkProgramHSpeed == 11.0f && profile.NbkProgramSPower == 1222.0f);
  assert(profile.NbkProgramOSpeed == 13.0f && profile.NbkProgramWPower == 1444.0f);

  program_store_nbk_profile(profile, second, PROGRAM_UPDATE_CLEAR);
  assert(profile.NbkProgramLength == 0);
  assert(profile.NbkProgramHSpeed == 11.0f && profile.NbkProgramWPower == 1444.0f);
  return 0;
}
'''.replace("@BODY@", body)
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-program-nvs-") as temp_dir:
        source = Path(temp_dir) / "test.cpp"
        binary = Path(temp_dir) / "test"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode != 0:
            sys.stderr.write(compiled.stdout + compiled.stderr)
            return compiled.returncode
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(ran.stdout)
        sys.stderr.write(ran.stderr)
        return ran.returncode


def main() -> int:
    samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    nbk = (ROOT / "nbk.h").read_text(encoding="utf-8")
    api = (ROOT / "samovar_api.h").read_text(encoding="utf-8")
    program_io = (ROOT / "program_io.h").read_text(encoding="utf-8")
    errors: list[str] = []

    optimum_body = extract_function_body(
        samovar,
        "void persist_nbk_optimum(float optimalPower, float optimalFeed) {",
    )
    require("SendMsg" not in optimum_body, "ошибка записи оптимума не должна создавать сообщение", errors)
    ordered(
        optimum_body,
        [
            "candidate = SamSetup",
            "candidate.NbkOptimalPower = optimalPower",
            "candidate.NbkOptimalFeed = optimalFeed",
            "if (save_profile_nvs(candidate) != PERSIST_OK) return",
            "SamSetup.NbkOptimalPower = optimalPower",
            "SamSetup.NbkOptimalFeed = optimalFeed",
        ],
        "атомарное сохранение оптимума",
        errors,
    )
    require(
        "void persist_nbk_optimum(float optimalPower, float optimalFeed);" in api,
        "API сохранения оптимума не объявлен",
        errors,
    )

    run_body = extract_function_body(
        nbk, "void run_nbk_program(uint8_t num, bool workConfirmed, bool optimumEntry) {"
    )
    ordered(
        run_body,
        [
            "if (!nbk_stage_sensors_valid(program[num].WType)) return",
            "if (program[num].WType == 'W')",
            "program[ProgramNum].WType == 'O'",
            "nbk_opt_found",
            "persist_nbk_optimum(nbk_Mo, nbk_Po)",
        ],
        "успешный выход O->W сохраняет оптимум",
        errors,
    )
    require("nbk_Mo = SamSetup.NbkOptimalPower;" in run_body, "новая сессия не загружает Мо из NVS", errors)
    require("nbk_Po = SamSetup.NbkOptimalFeed;" in run_body, "новая сессия не загружает По из NVS", errors)

    commit_body = extract_function_body(samovar, "static OperationError commit_profile_operation() {")
    require(
        "active_profile_operation.targetMode == SAMOVAR_NBK_MODE" in commit_body,
        "сохраняемая программа должна определяться целевым режимом",
        errors,
    )
    ordered(
        commit_body,
        [
            "persistNbkProgram",
            "program_store_nbk_profile(",
            "save_profile_nvs(nbkProgramProfile)",
            "SamSetup = nbkProgramProfile",
            "program_commit(active_profile_operation.program)",
        ],
        "программа НБК сначала сохраняется в NVS, затем применяется",
        errors,
    )
    require(
        "persistNbkProgram ? nbkProgramProfile : active_profile_operation.settings" in commit_body and
        "if (persistNbkProgram && !hasSettings)" in commit_body,
        "настройки и программа НБК должны сохраняться одним объединённым профилем",
        errors,
    )
    require("serialize_nbk_program_draft" not in program_io,
            "фиксированная программа НБК не должна сохраняться текстом", errors)
    store_profile_body = extract_function_body(
        samovar,
        "static void program_store_nbk_profile(\n    SetupEEPROM& profile,\n    const ProgramDraft& draft,\n    ProgramUpdateAction action) {",
    )
    ordered(
        store_profile_body,
        [
            "profile.NbkProgramLength = draft.len",
            "profile.NbkProgramHSpeed = draft.rows[0].Speed",
            "profile.NbkProgramWPower = draft.rows[3].Power",
        ],
        "сохранение восьми изменяемых значений программы НБК",
        errors,
    )

    profile_restore_body = extract_function_body(
        samovar, "static ProgramParseResult restore_nbk_program_from_profile() {"
    )
    ordered(
        profile_restore_body,
        [
            "SamSetup.NbkProgramLength == 0",
            "SamSetup.NbkProgramLength != NBK_PROGRAM_MAX",
            "static const ProgramType types[NBK_PROGRAM_MAX] = {'H', 'S', 'O', 'W'}",
            "SamSetup.NbkProgramHSpeed",
            "SamSetup.NbkProgramWPower",
            "program_commit(draft)",
        ],
        "восстановление фиксированных строк H/S/O/W из значений NVS",
        errors,
    )

    restore_body = extract_function_body(samovar, "static void restore_state_snapshot() {")
    require(
        "if (Samovar_Mode == SAMOVAR_NBK_MODE)" in restore_body and
        "restored = ProgramLen == NBK_PROGRAM_MAX;" in restore_body,
        "/state.csv всё ещё подменяет программу НБК из NVS",
        errors,
    )
    require(
        "const bool programLost = Samovar_Mode != SAMOVAR_NBK_MODE" in restore_body,
        "очищенная в NVS программа НБК не должна считаться потерянной из-за /state.csv",
        errors,
    )

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if test_optimum_helper(samovar) != 0:
        return 1
    if test_program_mapping(samovar) != 0:
        return 1
    print("NBK NVS optimum/program persistence smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
