#!/usr/bin/env python3
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]


HARNESS = r'''
#include <array>
#include <cstdint>
#include <cstring>
#include <functional>
#include <iostream>
#include <mutex>
#include <thread>

#include "operation_store.h"

namespace {

int failures = 0;

void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

bool same_record(const OperationRecord& left, const OperationRecord& right) {
  return left.id == right.id && left.kind == right.kind &&
         left.state == right.state && left.error == right.error;
}

std::array<uint8_t, sizeof(OperationStore)> store_bytes(
    const OperationStore& store) {
  std::array<uint8_t, sizeof(OperationStore)> bytes{};
  std::memcpy(bytes.data(), &store, sizeof(store));
  return bytes;
}

void check_store_unchanged(
    const OperationStore& store,
    const std::array<uint8_t, sizeof(OperationStore)>& before,
    const char* message) {
  check(std::memcmp(before.data(), &store, sizeof(store)) == 0, message);
}

void test_zero_init_wrap_and_collision() {
  OperationStore store{};
  OperationId id = 77;
  check(operation_store_reserve_locked(store, OPERATION_KIND_SAVE, id) ==
            OPERATION_ERROR_NONE,
        "zero-init reserve failed");
  check(id == 1 && store.nextId == 2, "zero-init did not issue ID 1");
  check(store.records[0].id == 1 &&
            store.records[0].kind == OPERATION_KIND_SAVE &&
            store.records[0].state == OPERATION_STATE_QUEUED &&
            store.records[0].error == OPERATION_ERROR_NONE,
        "zero-init record mismatch");

  OperationStore wrap{};
  wrap.nextId = UINT32_MAX;
  OperationId maxId = 0;
  check(operation_store_reserve_locked(
            wrap, OPERATION_KIND_PROGRAM, maxId) == OPERATION_ERROR_NONE,
        "UINT32_MAX reserve failed");
  check(maxId == UINT32_MAX && wrap.nextId == 1,
        "allocator did not skip zero after UINT32_MAX");
  OperationId wrappedId = 0;
  check(operation_store_reserve_locked(
            wrap, OPERATION_KIND_PROGRAM, wrappedId) == OPERATION_ERROR_NONE,
        "wrapped reserve failed");
  check(wrappedId == 1 && wrap.nextId == 2,
        "wrapped allocator did not continue at ID 1");

  OperationStore collision{};
  collision.nextId = UINT32_MAX;
  collision.records[0] = {UINT32_MAX, OPERATION_KIND_SAVE,
                          OPERATION_STATE_SUCCEEDED, OPERATION_ERROR_NONE};
  collision.records[1] = {1, OPERATION_KIND_PROGRAM,
                          OPERATION_STATE_FAILED, OPERATION_ERROR_INTERNAL};
  OperationId collisionId = 0;
  check(operation_store_reserve_locked(
            collision, OPERATION_KIND_CALIBRATION, collisionId) ==
            OPERATION_ERROR_NONE,
        "wrap collision reserve failed");
  check(collisionId == 2 && collision.nextId == 3,
        "allocator collided with retained IDs across wrap");
  check(collision.records[2].id == 2,
        "empty slot was not selected before terminal collision records");
}

void test_slot_selection_and_modular_age() {
  OperationStore store{};
  OperationId first = 0;
  OperationId second = 0;
  OperationId third = 0;
  check(operation_store_reserve_locked(
            store, OPERATION_KIND_SAVE, first) == OPERATION_ERROR_NONE,
        "first reserve failed");
  check(operation_store_reserve_locked(
            store, OPERATION_KIND_PROGRAM, second) == OPERATION_ERROR_NONE,
        "second reserve failed");
  check(operation_store_mark_running_locked(store, first) ==
            OPERATION_ERROR_NONE,
        "first mark-running failed");
  check(operation_store_finish_locked(
            store, first, OPERATION_STATE_SUCCEEDED, OPERATION_ERROR_NONE) ==
            OPERATION_ERROR_NONE,
        "first finish failed");
  check(operation_store_reserve_locked(
            store, OPERATION_KIND_I2C_PUMP, third) == OPERATION_ERROR_NONE,
        "third reserve failed");
  check(store.records[0].id == first && store.records[2].id == third,
        "terminal slot was reused while an empty slot existed");

  OperationStore wrapped{};
  wrapped.nextId = 4;
  const OperationId retained[OPERATION_STORE_CAPACITY] = {
      3, UINT32_MAX, 1, UINT32_MAX - 2U,
      2, UINT32_MAX - 1U, UINT32_MAX - 4U, UINT32_MAX - 3U};
  for (size_t index = 0; index < OPERATION_STORE_CAPACITY; index++) {
    const bool failed = (index % 2U) != 0;
    wrapped.records[index] = {
        retained[index],
        OPERATION_KIND_SAVE,
        failed ? OPERATION_STATE_FAILED : OPERATION_STATE_SUCCEEDED,
        failed ? OPERATION_ERROR_INTERNAL : OPERATION_ERROR_NONE};
  }
  OperationId replacement = 0;
  check(operation_store_reserve_locked(
            wrapped, OPERATION_KIND_PROGRAM, replacement) ==
            OPERATION_ERROR_NONE,
        "terminal reuse reserve failed");
  check(replacement == 4, "terminal reuse issued the wrong sequential ID");
  check(wrapped.records[6].id == 4 &&
            wrapped.records[6].state == OPERATION_STATE_QUEUED,
        "terminal reuse did not select maximum modular age");
  check(wrapped.records[0].id == 3,
        "terminal reuse depended on array index or completion state");
}

void test_full_store_is_atomic() {
  OperationStore store{};
  for (size_t index = 0; index < OPERATION_STORE_CAPACITY; index++) {
    OperationId id = 0;
    check(operation_store_reserve_locked(
              store, OPERATION_KIND_I2C_STEPPER, id) == OPERATION_ERROR_NONE,
          "active-store setup reserve failed");
    if ((index % 2U) != 0) {
      check(operation_store_mark_running_locked(store, id) ==
                OPERATION_ERROR_NONE,
            "active-store setup mark-running failed");
    }
  }

  const auto before = store_bytes(store);
  OperationId rejectedId = 900;
  check(operation_store_reserve_locked(
            store, OPERATION_KIND_SAVE, rejectedId) ==
            OPERATION_ERROR_STORE_FULL,
        "full active store did not return STORE_FULL");
  check(rejectedId == 900, "failed reserve modified its output ID");
  check_store_unchanged(store, before, "STORE_FULL mutated the store");

  check(operation_store_reserve_locked(
            store, OPERATION_KIND_NONE, rejectedId) ==
            OPERATION_ERROR_INTERNAL,
        "NONE kind was accepted");
  check_store_unchanged(store, before, "invalid kind mutated the store");
}

void test_transitions_are_strict_and_atomic() {
  OperationStore store{};
  OperationId succeeded = 0;
  check(operation_store_reserve_locked(
            store, OPERATION_KIND_SAVE, succeeded) == OPERATION_ERROR_NONE,
        "success transition reserve failed");

  auto before = store_bytes(store);
  check(operation_store_finish_locked(
            store, succeeded, OPERATION_STATE_SUCCEEDED,
            OPERATION_ERROR_NONE) == OPERATION_ERROR_INVALID_TRANSITION,
        "QUEUED to SUCCEEDED was accepted");
  check_store_unchanged(store, before, "QUEUED to SUCCEEDED mutated record");

  check(operation_store_mark_running_locked(store, succeeded) ==
            OPERATION_ERROR_NONE,
        "QUEUED to RUNNING failed");
  before = store_bytes(store);
  check(operation_store_mark_running_locked(store, succeeded) ==
            OPERATION_ERROR_INVALID_TRANSITION,
        "RUNNING to RUNNING was accepted");
  check_store_unchanged(store, before, "RUNNING to RUNNING mutated record");

  check(operation_store_finish_locked(
            store, succeeded, OPERATION_STATE_SUCCEEDED,
            OPERATION_ERROR_INTERNAL) == OPERATION_ERROR_INVALID_TRANSITION,
        "success with non-NONE error was accepted");
  check_store_unchanged(store, before, "invalid success mutated record");
  check(operation_store_finish_locked(
            store, succeeded, OPERATION_STATE_FAILED,
            OPERATION_ERROR_NONE) == OPERATION_ERROR_INVALID_TRANSITION,
        "FAILED with NONE error was accepted");
  check_store_unchanged(store, before, "invalid failure mutated record");

  check(operation_store_finish_locked(
            store, succeeded, OPERATION_STATE_SUCCEEDED,
            OPERATION_ERROR_NONE) == OPERATION_ERROR_NONE,
        "RUNNING to SUCCEEDED failed");
  before = store_bytes(store);
  check(operation_store_mark_running_locked(store, succeeded) ==
            OPERATION_ERROR_INVALID_TRANSITION,
        "terminal to RUNNING was accepted");
  check(operation_store_finish_locked(
            store, succeeded, OPERATION_STATE_FAILED,
            OPERATION_ERROR_INTERNAL) == OPERATION_ERROR_INVALID_TRANSITION,
        "repeated terminal transition was accepted");
  check_store_unchanged(store, before, "terminal transition mutated record");

  OperationId runningFailure = 0;
  check(operation_store_reserve_locked(
            store, OPERATION_KIND_PROGRAM, runningFailure) ==
            OPERATION_ERROR_NONE,
        "running-failure reserve failed");
  check(operation_store_mark_running_locked(store, runningFailure) ==
            OPERATION_ERROR_NONE,
        "running-failure mark failed");
  check(operation_store_finish_locked(
            store, runningFailure, OPERATION_STATE_FAILED,
            OPERATION_ERROR_INTERNAL) == OPERATION_ERROR_NONE,
        "RUNNING to FAILED failed");

  OperationId queuedFailure = 0;
  check(operation_store_reserve_locked(
            store, OPERATION_KIND_CALIBRATION, queuedFailure) ==
            OPERATION_ERROR_NONE,
        "queued-failure reserve failed");
  check(operation_store_finish_locked(
            store, queuedFailure, OPERATION_STATE_FAILED,
            OPERATION_ERROR_INVALID_TRANSITION) == OPERATION_ERROR_NONE,
        "explicit QUEUED to FAILED cancellation failed");

  before = store_bytes(store);
  check(operation_store_mark_running_locked(store, 0) ==
            OPERATION_ERROR_INVALID_ID,
        "zero transition ID was not rejected");
  check(operation_store_finish_locked(
            store, 9999, OPERATION_STATE_FAILED,
            OPERATION_ERROR_INTERNAL) == OPERATION_ERROR_NOT_FOUND,
        "unknown transition ID was not rejected");
  check_store_unchanged(store, before, "unknown transition mutated store");
}

void test_lookup_and_expiry() {
  OperationStore store{};
  OperationRecord output = {91, OPERATION_KIND_SAVE,
                            OPERATION_STATE_RUNNING, OPERATION_ERROR_INTERNAL};
  const OperationRecord sentinel = output;
  check(operation_store_copy_locked(store, 0, output) ==
            OPERATION_ERROR_INVALID_ID,
        "lookup ID zero was not rejected");
  check(same_record(output, sentinel), "invalid lookup modified output");
  check(operation_store_copy_locked(store, 400, output) ==
            OPERATION_ERROR_NOT_FOUND,
        "unknown lookup did not return NOT_FOUND");
  check(same_record(output, sentinel), "unknown lookup modified output");

  OperationId first = 0;
  check(operation_store_reserve_locked(
            store, OPERATION_KIND_SAVE, first) == OPERATION_ERROR_NONE,
        "lookup reserve failed");
  check(operation_store_copy_locked(store, first, output) ==
            OPERATION_ERROR_NONE &&
            output.state == OPERATION_STATE_QUEUED,
        "active lookup mismatch");
  check(operation_store_mark_running_locked(store, first) ==
            OPERATION_ERROR_NONE,
        "lookup terminal setup mark failed");
  check(operation_store_finish_locked(
            store, first, OPERATION_STATE_SUCCEEDED,
            OPERATION_ERROR_NONE) == OPERATION_ERROR_NONE,
        "lookup terminal setup finish failed");
  check(operation_store_copy_locked(store, first, output) ==
            OPERATION_ERROR_NONE &&
            output.state == OPERATION_STATE_SUCCEEDED,
        "terminal lookup mismatch");

  for (size_t index = 1; index < OPERATION_STORE_CAPACITY; index++) {
    OperationId id = 0;
    check(operation_store_reserve_locked(
              store, OPERATION_KIND_PROGRAM, id) == OPERATION_ERROR_NONE,
          "expiry setup reserve failed");
    check(operation_store_finish_locked(
              store, id, OPERATION_STATE_FAILED,
              OPERATION_ERROR_INTERNAL) == OPERATION_ERROR_NONE,
          "expiry setup finish failed");
  }
  OperationId replacement = 0;
  check(operation_store_reserve_locked(
            store, OPERATION_KIND_I2C_PUMP, replacement) ==
            OPERATION_ERROR_NONE,
        "expiry replacement reserve failed");
  check(replacement == 9, "expiry replacement ID mismatch");
  check(operation_store_copy_locked(store, first, output) ==
            OPERATION_ERROR_NOT_FOUND,
        "reused terminal ID did not expire");
}

void test_concurrent_readers_are_nondestructive() {
  OperationStore store{};
  OperationId id = 0;
  check(operation_store_reserve_locked(
            store, OPERATION_KIND_PROGRAM, id) == OPERATION_ERROR_NONE,
        "reader reserve failed");
  check(operation_store_mark_running_locked(store, id) ==
            OPERATION_ERROR_NONE,
        "reader mark-running failed");
  check(operation_store_finish_locked(
            store, id, OPERATION_STATE_FAILED,
            OPERATION_ERROR_INTERNAL) == OPERATION_ERROR_NONE,
        "reader terminal setup failed");
  const OperationRecord expected = store.records[0];
  const auto before = store_bytes(store);
  std::mutex lock;
  bool firstOk = true;
  bool secondOk = true;
  const auto reader = [&](bool& ok) {
    for (size_t iteration = 0; iteration < 500; iteration++) {
      std::lock_guard<std::mutex> guard(lock);
      OperationRecord record{};
      if (operation_store_copy_locked(store, id, record) !=
              OPERATION_ERROR_NONE ||
          !same_record(record, expected)) {
        ok = false;
      }
    }
  };
  std::thread firstReader(reader, std::ref(firstOk));
  std::thread secondReader(reader, std::ref(secondOk));
  firstReader.join();
  secondReader.join();
  check(firstOk && secondOk, "concurrent readers observed different records");
  check_store_unchanged(store, before, "lookup destructively consumed record");
}

void test_wire_codes() {
  check(std::strcmp(operation_state_code(OPERATION_STATE_QUEUED), "queued") == 0,
        "queued state code mismatch");
  check(std::strcmp(operation_state_code(OPERATION_STATE_RUNNING), "running") == 0,
        "running state code mismatch");
  check(std::strcmp(operation_state_code(OPERATION_STATE_SUCCEEDED), "succeeded") == 0,
        "succeeded state code mismatch");
  check(std::strcmp(operation_state_code(OPERATION_STATE_FAILED), "failed") == 0,
        "failed state code mismatch");
  check(std::strcmp(operation_error_code(OPERATION_ERROR_INVALID_ID),
                    "invalid_operation_id") == 0,
        "invalid ID error code mismatch");
  check(std::strcmp(operation_error_code(OPERATION_ERROR_NOT_FOUND),
                    "operation_not_found") == 0,
        "not-found error code mismatch");
  check(std::strcmp(operation_error_code(OPERATION_ERROR_STORE_FULL),
                    "operation_store_full") == 0,
        "store-full error code mismatch");
  check(std::strcmp(operation_error_code(OPERATION_ERROR_LOCK_BUSY),
                    "operation_store_busy") == 0,
        "lock-busy error code mismatch");
  check(std::strcmp(operation_error_code(OPERATION_ERROR_CANCELLED),
                    "operation_cancelled") == 0,
        "cancelled error code mismatch");
  check(std::strcmp(operation_error_code(OPERATION_ERROR_PROFILE_PERSIST_FAILED),
                    "profile_persist_failed") == 0,
        "profile-persist error code mismatch");
  check(std::strcmp(operation_error_code(OPERATION_ERROR_MODE_SWITCH_FAILED),
                    "mode_switch_failed") == 0,
        "mode-switch error code mismatch");
  check(std::strcmp(operation_error_code(OPERATION_ERROR_RUNTIME_BUSY),
                    "operation_runtime_busy") == 0,
        "runtime-busy error code mismatch");
  check(std::strcmp(operation_error_code(OPERATION_ERROR_I2C_CONFIG_BUSY),
                    "i2c_config_busy") == 0,
        "I2C config-busy error code mismatch");
  check(std::strcmp(operation_error_code(OPERATION_ERROR_I2C_COMMAND_FAILED),
                    "i2c_command_failed") == 0,
        "I2C command-failed error code mismatch");
  check(std::strcmp(operation_error_code(OPERATION_ERROR_I2C_DEVICE_ERROR),
                    "i2c_device_error") == 0,
        "I2C device-error code mismatch");
  check(std::strcmp(operation_error_code(OPERATION_ERROR_I2C_REFRESH_FAILED),
                    "i2c_refresh_failed") == 0,
        "I2C refresh-failed error code mismatch");
  check(std::strcmp(operation_error_code(OPERATION_ERROR_CALIBRATION_INVALID_RESULT),
                    "calibration_invalid_result") == 0,
        "calibration invalid-result error code mismatch");
}

}  // namespace

int main() {
  test_zero_init_wrap_and_collision();
  test_slot_selection_and_modular_age();
  test_full_store_is_atomic();
  test_transitions_are_strict_and_atomic();
  test_lookup_and_expiry();
  test_concurrent_readers_are_nondestructive();
  test_wire_codes();

  if (failures != 0) return 1;
  std::cout << "OperationStore behavioral checks passed\n";
  return 0;
}
'''


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def static_checks() -> list[str]:
    errors: list[str] = []
    header = (ROOT / "operation_store.h").read_text(encoding="utf-8")
    samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    api = (ROOT / "samovar_api.h").read_text(encoding="utf-8")
    webserver = (ROOT / "WebServer.ino").read_text(encoding="utf-8")
    header_code = strip_cpp_comments(header)
    samovar_code = strip_cpp_comments(samovar)
    api_code = strip_cpp_comments(api)

    banned_patterns = {
        "Arduino String": r"\bString\b",
        "STL container": r"\bstd::(?:array|deque|list|map|set|unordered_map|unordered_set|vector)\b",
        "dynamic allocation": r"\b(?:new|malloc|calloc|realloc|free)\b",
        "callback": r"\bcallback\b",
        "timestamp": r"\btimestamp\b",
        "FreeRTOS primitive": r"\b(?:xSemaphore|xQueue|xTask|SemaphoreHandle_t|QueueHandle_t|TaskHandle_t)",
    }
    for label, pattern in banned_patterns.items():
        require(not re.search(pattern, header_code),
                f"operation_store.h contains forbidden {label}", errors)

    record_match = re.search(
        r"struct\s+OperationRecord\s*\{(?P<body>.*?)\};", header_code, re.S)
    store_match = re.search(
        r"struct\s+OperationStore\s*\{(?P<body>.*?)\};", header_code, re.S)
    require(record_match is not None, "OperationRecord definition missing", errors)
    require(store_match is not None, "OperationStore definition missing", errors)
    if record_match:
        require(
            " ".join(record_match.group("body").split()) ==
            "OperationId id; OperationKind kind; OperationState state; OperationError error;",
            "OperationRecord contains fields outside the fixed POD contract",
            errors,
        )
    if store_match:
        require(
            " ".join(store_match.group("body").split()) ==
            "OperationRecord records[OPERATION_STORE_CAPACITY]; OperationId nextId;",
            "OperationStore contains ordering or ownership fields outside the contract",
            errors,
        )
    for token in (
        "OPERATION_STORE_CAPACITY = 8",
        "sizeof(OperationRecord) <= 8",
        "sizeof(OperationStore) <= 68",
        "std::is_trivial<OperationRecord>",
        "std::is_standard_layout<OperationRecord>",
        "std::is_trivial<OperationStore>",
        "std::is_standard_layout<OperationStore>",
        "operation_store_reserve_locked",
        "operation_store_copy_locked",
        "operation_store_mark_running_locked",
        "operation_store_finish_locked",
        "operation_state_code",
        "operation_error_code",
    ):
        require(token in header_code, f"operation_store.h missing {token}", errors)
    for token in ("reuseCursor", "completionCounter", "generation", "timestamp"):
        require(token not in header_code,
                f"operation_store.h contains forbidden ordering field {token}", errors)

    webserver_code = strip_cpp_comments(webserver)
    reserve_owners = (
        "queue_profile_operation",
        "queue_pending_i2cstepper",
        "queue_pending_i2cpump",
        "queue_pending_i2ccal",
        "queue_pending_local_cal",
    )
    reserve_count = 0
    for owner in reserve_owners:
        owner_body = extract_function_body(
            webserver_code, f"static OperationError {owner}(")
        owner_count = owner_body.count("operation_store_reserve_locked(")
        require(owner_count == 1,
                f"{owner} must reserve exactly once", errors)
        reserve_count += owner_count
    require(webserver_code.count("operation_store_reserve_locked(") == reserve_count == 5,
            "WebServer.ino reserve callsites are outside the accepted owner inventory", errors)
    require("operation_store_mark_running_locked(" not in webserver_code and
            "operation_store_finish_locked(" not in webserver_code,
            "WebServer.ino owns a non-reserve OperationStore transition", errors)
    profile_process_offset = samovar_code.rfind(
        "static void process_profile_operation()")
    profile_process = extract_function_body(
        samovar_code[profile_process_offset:],
        "static void process_profile_operation()")
    transition_owners = {
        "process_profile_operation": profile_process,
        "publish_profile_operation_terminal": extract_function_body(
            samovar_code, "static void publish_profile_operation_terminal()"),
        "process_pending_i2c_operations": extract_function_body(
            samovar_code, "static void process_pending_i2c_operations()"),
        "cancel_queued_i2c_operations_locked": extract_function_body(
            samovar_code, "static bool cancel_queued_i2c_operations_locked("),
    }
    expected_transitions = {
        "process_profile_operation": (1, 1),
        "publish_profile_operation_terminal": (0, 1),
        "process_pending_i2c_operations": (1, 1),
        "cancel_queued_i2c_operations_locked": (0, 1),
    }
    mark_count = 0
    finish_count = 0
    for owner, owner_body in transition_owners.items():
        actual = (
            owner_body.count("operation_store_mark_running_locked("),
            owner_body.count("operation_store_finish_locked("),
        )
        require(actual == expected_transitions[owner],
                f"{owner} transition ownership mismatch: {actual}", errors)
        mark_count += actual[0]
        finish_count += actual[1]
    require("operation_store_reserve_locked(" not in samovar_code and
            samovar_code.count("operation_store_mark_running_locked(") == mark_count == 2 and
            samovar_code.count("operation_store_finish_locked(") == finish_count == 4,
            "Samovar.ino transitions are outside the accepted A-12/A-02 owner inventory", errors)
    require(not re.search(
                r"\boperation_store_(?:reserve|mark_running|finish)_locked\s*\(",
                api_code),
            "samovar_api.h contains a production transition callsite", errors)
    require(len(re.findall(r"\bOperationStore\s+operationStore\s*\{\s*\}\s*;", samovar_code)) == 1,
            "Samovar.ino must define exactly one zero-initialized operationStore", errors)
    require('#include "operation_store.h"' in samovar,
            "Samovar.ino does not include operation_store.h", errors)
    require('#include "operation_store.h"' in api,
            "samovar_api.h does not include operation_store.h", errors)
    require(len(re.findall(r"\bextern\s+OperationStore\s+operationStore\s*;", api_code)) == 1,
            "samovar_api.h must declare exactly one operationStore extern", errors)
    require(not re.search(r"\boperation_store_\w+\s*\(", api_code),
            "samovar_api.h contains an OperationStore wrapper", errors)
    require(webserver.count('server.on("/ajax", HTTP_GET') == 1,
            "existing /ajax route changed or was duplicated", errors)
    require("queue_profile_operation" in webserver and
            "process_profile_operation" in samovar,
            "A-12 profile operation integration is missing", errors)
    require("operationStoreMutex" not in samovar and "operationStoreTask" not in samovar,
            "Samovar.ino contains a new OperationStore mutex/task", errors)

    try:
        ajax = extract_function_body(
            samovar, "void send_ajax_json(AsyncWebServerRequest *request)")
        ajax_query = extract_function_body(
            samovar, "static RuntimeAjaxQuery classifyRuntimeAjaxQuery(")
        ajax_query_error = extract_function_body(
            samovar, "static bool sendRuntimeAjaxQueryError(")
        ajax_event_response = extract_function_body(
            samovar, "static bool sendRuntimeEventResponse(")
        ajax_telemetry_writer = extract_function_body(
            samovar, "static void writeAjaxTelemetryFields(")
    except ValueError as error:
        errors.append(str(error))
        ajax = ""
        ajax_query = ""
        ajax_query_error = ""
        ajax_event_response = ""
        ajax_telemetry_writer = ""
    if ajax:
        lookup, separator, telemetry = ajax.partition(
            "AjaxTelemetrySnapshot snapshot{};")
        require(bool(separator), "lookup branch does not precede telemetry snapshots", errors)
        require("allOperationIds" in ajax_query and "parameterCount == 1" in ajax_query,
                "duplicate-only operationId is not rejected", errors)
        require("runtime_event_parse_cursor(" in ajax_query,
                "operationId does not use the strict decimal uint32 parser", errors)
        require("operationId != 0" in ajax_query,
                "operationId parser accepts zero", errors)
        require("toInt(" not in ajax_query,
                "operationId parser uses partial Arduino conversion", errors)
        require(r'{\"operationId\":0,\"error\":\"%s\"}' in ajax_query_error,
                "invalid lookup JSON contract mismatch", errors)
        require(lookup.count(r'{\"operationId\":%lu,\"error\":\"%s\"}') == 2,
                "not-found/busy lookup JSON contract mismatch", errors)
        found_json = r'{\"operationId\":%lu,\"state\":\"%s\",\"error\":\"%s\"}'
        require(found_json in lookup, "found lookup JSON contract mismatch", errors)
        require(lookup.count(r'\"state\"') == 1,
                "failure lookup invents a wire state", errors)
        require('"unknown"' not in lookup,
                "lookup introduces forbidden unknown wire state", errors)
        require("beginResponse(400, contentType, body)" in ajax_query_error,
                "lookup missing invalid-ID 400 response", errors)
        for token in ('beginResponse(503,', 'beginResponse(404,', 'beginResponse(200,'):
            require(token in lookup, f"lookup missing {token}", errors)
        copy_index = lookup.find("operation_store_copy_locked")
        unlock_index = lookup.find("pending_command_unlock(true);", copy_index)
        serialize_index = lookup.find(found_json, unlock_index)
        require(0 <= copy_index < unlock_index < serialize_index,
                "lookup does not copy under lock and serialize after unlock", errors)
        for token in (r'\"kind\"', r'\"timestamp\"', r'\"detail\"', r'\"payload\"'):
            require(token not in lookup,
                    f"lookup response exposes forbidden field {token}", errors)
        require(ajax.count('addHeader("Cache-Control", "no-store")') == 6 and
                ajax_query_error.count('addHeader("Cache-Control", "no-store")') == 1 and
                ajax_event_response.count('addHeader("Cache-Control", "no-store")') == 1,
                "not every /ajax branch sets Cache-Control: no-store", errors)
        require('addHeader("Cache-Control", "no-cache")' not in ajax,
                "/ajax retains no-cache instead of no-store", errors)
        for key in ('"bme_temp"', '"SteamTemp"', '"Status"', '"Lstatus"'):
            require(key in ajax_telemetry_writer,
                    f"telemetry path lost existing key {key}", errors)

    manifest = json.loads(
        (ROOT / "tools" / "static_analysis_sources.json").read_text(encoding="utf-8"))
    require(manifest["inventory"].count("operation_store.h") == 1,
            "static analysis inventory must contain operation_store.h once", errors)
    return errors


def run_behavioral_harness() -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-operation-store-") as temp_dir:
        temp = Path(temp_dir)
        harness = temp / "operation_store_test.cpp"
        binary = temp / "operation_store_test"
        harness.write_text(HARNESS, encoding="utf-8")
        compiled = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pthread",
                "-I",
                str(ROOT),
                str(harness),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode != 0:
            sys.stderr.write(compiled.stdout)
            sys.stderr.write(compiled.stderr)
            return compiled.returncode
        executed = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(executed.stdout)
        sys.stderr.write(executed.stderr)
        return executed.returncode


def main() -> int:
    behavioral_result = run_behavioral_harness()
    if behavioral_result != 0:
        return behavioral_result

    errors = static_checks()
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print("smoke_operation_store: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
