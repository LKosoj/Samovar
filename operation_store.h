#pragma once

#include <stddef.h>
#include <stdint.h>
#include <type_traits>

using OperationId = uint32_t;

enum OperationKind : uint8_t {
  OPERATION_KIND_NONE = 0,
  OPERATION_KIND_SAVE,
  OPERATION_KIND_PROGRAM,
  OPERATION_KIND_I2C_STEPPER,
  OPERATION_KIND_I2C_PUMP,
  OPERATION_KIND_CALIBRATION,
};

enum OperationState : uint8_t {
  OPERATION_STATE_EMPTY = 0,
  OPERATION_STATE_QUEUED,
  OPERATION_STATE_RUNNING,
  OPERATION_STATE_SUCCEEDED,
  OPERATION_STATE_FAILED,
};

enum OperationError : uint8_t {
  OPERATION_ERROR_NONE = 0,
  OPERATION_ERROR_INVALID_ID,
  OPERATION_ERROR_NOT_FOUND,
  OPERATION_ERROR_STORE_FULL,
  OPERATION_ERROR_LOCK_BUSY,
  OPERATION_ERROR_INVALID_TRANSITION,
  OPERATION_ERROR_INTERNAL,
  OPERATION_ERROR_CANCELLED,
  OPERATION_ERROR_PROFILE_PERSIST_FAILED,
  OPERATION_ERROR_MODE_SWITCH_FAILED,
  OPERATION_ERROR_RUNTIME_BUSY,
  OPERATION_ERROR_I2C_CONFIG_BUSY,
  OPERATION_ERROR_I2C_COMMAND_FAILED,
  OPERATION_ERROR_I2C_DEVICE_ERROR,
  OPERATION_ERROR_I2C_REFRESH_FAILED,
  OPERATION_ERROR_CALIBRATION_INVALID_RESULT,
  OPERATION_ERROR_STALE_REAPED,
};

struct OperationRecord {
  OperationId id;
  OperationKind kind;
  OperationState state;
  OperationError error;
};

static const size_t OPERATION_STORE_CAPACITY = 8;

struct OperationStore {
  OperationRecord records[OPERATION_STORE_CAPACITY];
  OperationId nextId;
};

static_assert(std::is_trivial<OperationRecord>::value,
              "OperationRecord must remain trivial");
static_assert(std::is_standard_layout<OperationRecord>::value,
              "OperationRecord must remain standard-layout");
static_assert(std::is_trivial<OperationStore>::value,
              "OperationStore must remain trivial");
static_assert(std::is_standard_layout<OperationStore>::value,
              "OperationStore must remain standard-layout");
static_assert(sizeof(OperationRecord) <= 8,
              "OperationRecord exceeds its fixed RAM budget");
static_assert(sizeof(OperationStore) <= 68,
              "OperationStore exceeds its fixed RAM budget");

namespace operation_store_detail {

inline OperationId next_nonzero_id(OperationId id) {
  return id == UINT32_MAX ? 1U : id + 1U;
}

inline bool terminal(OperationState state) {
  return state == OPERATION_STATE_SUCCEEDED || state == OPERATION_STATE_FAILED;
}

inline size_t find_record(const OperationStore& store, OperationId id) {
  for (size_t index = 0; index < OPERATION_STORE_CAPACITY; index++) {
    if (store.records[index].state != OPERATION_STATE_EMPTY &&
        store.records[index].id == id) {
      return index;
    }
  }
  return OPERATION_STORE_CAPACITY;
}

}  // namespace operation_store_detail

inline OperationError operation_store_reserve_locked(
    OperationStore& store,
    OperationKind kind,
    OperationId& outId) {
  if (kind == OPERATION_KIND_NONE) return OPERATION_ERROR_INTERNAL;

  size_t slot = OPERATION_STORE_CAPACITY;
  for (size_t index = 0; index < OPERATION_STORE_CAPACITY; index++) {
    if (store.records[index].state == OPERATION_STATE_EMPTY) {
      slot = index;
      break;
    }
  }

  const OperationId nextCandidate = store.nextId == 0 ? 1U : store.nextId;
  if (slot == OPERATION_STORE_CAPACITY) {
    uint32_t oldestAge = 0;
    bool foundTerminal = false;
    for (size_t index = 0; index < OPERATION_STORE_CAPACITY; index++) {
      const OperationRecord& record = store.records[index];
      if (!operation_store_detail::terminal(record.state)) continue;
      const uint32_t age = uint32_t(nextCandidate - record.id);
      if (!foundTerminal || age > oldestAge) {
        foundTerminal = true;
        oldestAge = age;
        slot = index;
      }
    }
    if (!foundTerminal) return OPERATION_ERROR_STORE_FULL;
  }

  OperationId candidate = nextCandidate;
  bool collision = true;
  for (size_t attempt = 0; attempt <= OPERATION_STORE_CAPACITY; attempt++) {
    collision = false;
    for (size_t index = 0; index < OPERATION_STORE_CAPACITY; index++) {
      if (store.records[index].id == candidate) {
        collision = true;
        break;
      }
    }
    if (!collision) break;
    candidate = operation_store_detail::next_nonzero_id(candidate);
  }
  if (collision) return OPERATION_ERROR_INTERNAL;

  outId = candidate;
  store.records[slot] = {
      candidate, kind, OPERATION_STATE_QUEUED, OPERATION_ERROR_NONE};
  store.nextId = operation_store_detail::next_nonzero_id(candidate);
  return OPERATION_ERROR_NONE;
}

inline OperationError operation_store_copy_locked(
    const OperationStore& store,
    OperationId id,
    OperationRecord& outRecord) {
  if (id == 0) return OPERATION_ERROR_INVALID_ID;
  const size_t index = operation_store_detail::find_record(store, id);
  if (index == OPERATION_STORE_CAPACITY) return OPERATION_ERROR_NOT_FOUND;
  outRecord = store.records[index];
  return OPERATION_ERROR_NONE;
}

inline OperationError operation_store_mark_running_locked(
    OperationStore& store,
    OperationId id) {
  if (id == 0) return OPERATION_ERROR_INVALID_ID;
  const size_t index = operation_store_detail::find_record(store, id);
  if (index == OPERATION_STORE_CAPACITY) return OPERATION_ERROR_NOT_FOUND;
  OperationRecord& record = store.records[index];
  if (record.state != OPERATION_STATE_QUEUED) {
    return OPERATION_ERROR_INVALID_TRANSITION;
  }
  record.state = OPERATION_STATE_RUNNING;
  return OPERATION_ERROR_NONE;
}

inline OperationError operation_store_finish_locked(
    OperationStore& store,
    OperationId id,
    OperationState terminalState,
    OperationError error) {
  if (id == 0) return OPERATION_ERROR_INVALID_ID;
  const size_t index = operation_store_detail::find_record(store, id);
  if (index == OPERATION_STORE_CAPACITY) return OPERATION_ERROR_NOT_FOUND;
  OperationRecord& record = store.records[index];
  const bool success = terminalState == OPERATION_STATE_SUCCEEDED &&
                       error == OPERATION_ERROR_NONE &&
                       record.state == OPERATION_STATE_RUNNING;
  const bool failure = terminalState == OPERATION_STATE_FAILED &&
                       error != OPERATION_ERROR_NONE &&
                       (record.state == OPERATION_STATE_QUEUED ||
                        record.state == OPERATION_STATE_RUNNING);
  if (!success && !failure) return OPERATION_ERROR_INVALID_TRANSITION;
  record.state = terminalState;
  record.error = error;
  return OPERATION_ERROR_NONE;
}

inline const char* operation_state_code(OperationState state) {
  switch (state) {
    case OPERATION_STATE_EMPTY: return "empty";
    case OPERATION_STATE_QUEUED: return "queued";
    case OPERATION_STATE_RUNNING: return "running";
    case OPERATION_STATE_SUCCEEDED: return "succeeded";
    case OPERATION_STATE_FAILED: return "failed";
  }
  return "empty";
}

inline const char* operation_error_code(OperationError error) {
  switch (error) {
    case OPERATION_ERROR_NONE: return "none";
    case OPERATION_ERROR_INVALID_ID: return "invalid_operation_id";
    case OPERATION_ERROR_NOT_FOUND: return "operation_not_found";
    case OPERATION_ERROR_STORE_FULL: return "operation_store_full";
    case OPERATION_ERROR_LOCK_BUSY: return "operation_store_busy";
    case OPERATION_ERROR_INVALID_TRANSITION: return "invalid_operation_transition";
    case OPERATION_ERROR_INTERNAL: return "operation_internal";
    case OPERATION_ERROR_CANCELLED: return "operation_cancelled";
    case OPERATION_ERROR_PROFILE_PERSIST_FAILED: return "profile_persist_failed";
    case OPERATION_ERROR_MODE_SWITCH_FAILED: return "mode_switch_failed";
    case OPERATION_ERROR_RUNTIME_BUSY: return "operation_runtime_busy";
    case OPERATION_ERROR_I2C_CONFIG_BUSY: return "i2c_config_busy";
    case OPERATION_ERROR_I2C_COMMAND_FAILED: return "i2c_command_failed";
    case OPERATION_ERROR_I2C_DEVICE_ERROR: return "i2c_device_error";
    case OPERATION_ERROR_I2C_REFRESH_FAILED: return "i2c_refresh_failed";
    case OPERATION_ERROR_CALIBRATION_INVALID_RESULT: return "calibration_invalid_result";
    case OPERATION_ERROR_STALE_REAPED: return "operation_stale_reaped";
  }
  return "operation_internal";
}

// Сторож зависших операций. Терминальные записи эвиктятся при reserve; но если
// fail-closed оставляет запись в QUEUED/RUNNING навсегда, слот держится вечно и все
// новые команды получают STORE_FULL до перезагрузки. Реапер переводит не-терминальные
// записи старше OPERATION_STALE_TIMEOUT_MS в FAILED/STALE_REAPED, освобождая слот.
//
// Время старта не хранится в OperationRecord (жёсткий POD-бюджет), поэтому оно ведётся
// здесь по слоту: при первом наблюдении не-терминальной записи фиксируется nowMs;
// повторное использование слота (другой id) сбрасывает отсчёт. Погрешность ≤ одного
// периода вызова (PKG-G зовёт раз в секунду) и пренебрежима на фоне 5-минутного порога.
//
// Вызывающий ДЕРЖИТ pending_command_lock (суффикс _locked) — этот же лок защищает и
// внутреннее tracking-состояние (реапер зовётся только из loop() под ним).
// Возвращает true РОВНО ОДИН раз — на первой эвикции за загрузку — чтобы вызывающий
// выдал однократный ALARM; последующие эвикции возвращают false.
static const uint32_t OPERATION_STALE_TIMEOUT_MS = 300000U;  // 5 минут

inline bool operation_store_reap_stale_locked(OperationStore& store, uint32_t nowMs) {
  static OperationId seenId[OPERATION_STORE_CAPACITY] = {};
  static uint32_t seenSince[OPERATION_STORE_CAPACITY] = {};
  static bool alarmEmitted = false;
  bool reapedNow = false;
  for (size_t index = 0; index < OPERATION_STORE_CAPACITY; index++) {
    OperationRecord& record = store.records[index];
    const bool nonTerminal = record.state == OPERATION_STATE_QUEUED ||
                             record.state == OPERATION_STATE_RUNNING;
    if (!nonTerminal) {
      seenId[index] = 0;
      seenSince[index] = 0;
      continue;
    }
    if (seenId[index] != record.id) {
      seenId[index] = record.id;
      seenSince[index] = nowMs;
      continue;
    }
    if ((int32_t)(nowMs - seenSince[index]) >= (int32_t)OPERATION_STALE_TIMEOUT_MS) {
      record.state = OPERATION_STATE_FAILED;
      record.error = OPERATION_ERROR_STALE_REAPED;
      seenId[index] = 0;
      seenSince[index] = 0;
      reapedNow = true;
    }
  }
  if (reapedNow && !alarmEmitted) {
    alarmEmitted = true;
    return true;
  }
  return false;
}
