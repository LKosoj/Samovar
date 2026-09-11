#pragma once

#include <stdint.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <esp_timer.h>

// Парные события P02 живут только в RAM текущей загрузки. Вызывающий держит
// runtime_state_lock во время prepare_*(), а dispatch вызывает только после unlock.
constexpr size_t RUNTIME_PAIR_EVENT_PAYLOAD_MAX = 198;
constexpr uint8_t RUNTIME_PAIR_CAUSE_MIN = 1;
constexpr uint8_t RUNTIME_PAIR_CAUSE_MAX = 23;
constexpr uint8_t RUNTIME_PAIR_MODE_MAX = 7;
constexpr uint8_t RUNTIME_PAIR_ROW_NONE = 0xFF;

enum RuntimePairOutcome : uint8_t {
  RUNTIME_PAIR_RESUMED = 0,
  RUNTIME_PAIR_ROW_CHANGE = 1,
  RUNTIME_PAIR_USER_STOP = 2,
  RUNTIME_PAIR_PROCESS_END = 3,
  RUNTIME_PAIR_ERROR = 4,
};

enum RuntimePairPrepareResult : uint8_t {
  RUNTIME_PAIR_PREPARED = 0,
  RUNTIME_PAIR_DUPLICATE = 1,
  RUNTIME_PAIR_INVALID_ARGUMENT = 2,
  RUNTIME_PAIR_TEXT_EMPTY = 3,
  RUNTIME_PAIR_TEXT_INVALID_UTF8 = 4,
  RUNTIME_PAIR_TEXT_TOO_LONG = 5,
  RUNTIME_PAIR_ID_EXHAUSTED = 6,
};

enum RuntimePairDispatchResult : uint8_t {
  RUNTIME_PAIR_NOT_PENDING = 0,
  RUNTIME_PAIR_SENT_TO_SENDMSG = 1,
};

// Wire-коды P01: один список используют snapshot и runtime-пары.
enum UiWaitReason : uint8_t {
  UI_WAIT_MANUAL_RECT = 1,
  UI_WAIT_MANUAL_BEER = 2,
  UI_WAIT_RECT_STEAM = 3,
  UI_WAIT_RECT_PIPE = 4,
  UI_WAIT_RECT_DETECTOR = 5,
  UI_WAIT_RECT_PROGRAM_PAUSE = 6,
  UI_WAIT_DIST_HEATING = 7,
  UI_WAIT_DIST_INVALID_ALCOHOL = 8,
  UI_WAIT_BK_BOIL = 9,
  UI_WAIT_BK_WORK_POWER = 10,
  UI_WAIT_NBK_TRANSITION = 11,
  UI_WAIT_NBK_SAFE = 12,
  UI_WAIT_BEER_MALT = 13,
  UI_WAIT_BEER_SKIP_COOL_CONFIRM = 14,
  UI_WAIT_BEER_HOLD_CLOCK_FREEZE = 15,
  UI_WAIT_BEER_OPERATOR_WAIT = 16,
  UI_WAIT_SUVID_HOLD_OUTSIDE_BAND = 17,
  UI_WAIT_CHEESE_HOLD_CLOCK_FREEZE = 18,
  UI_WAIT_CHEESE_OPERATOR = 19,
  UI_WAIT_CHEESE_DOSE = 20,
  UI_WAIT_CHEESE_TEMPERATURE_OR_PH_CONFIRM = 21,
  UI_WAIT_ACTUATOR_CONFIRM = 22,
  UI_WAIT_LUA_KNOWN = 23,
};

enum UiControlSource : uint8_t {
  UI_CONTROL_SOURCE_UNKNOWN = 0,
  UI_CONTROL_SOURCE_PROGRAM = 1,
  UI_CONTROL_SOURCE_MANUAL = 2,
  UI_CONTROL_SOURCE_AUTO_WATER = 3,
  UI_CONTROL_SOURCE_SAFETY = 4,
  UI_CONTROL_SOURCE_OPERATION = 5,
  UI_CONTROL_SOURCE_AUTO_SPEED = 6,
  UI_CONTROL_SOURCE_DETECTOR = 7,
};

struct RuntimePairState {
  struct ActivePair {
    bool active;
    uint32_t sessionId;
    uint32_t pairId;
    uint8_t mode;
    uint8_t row;
  } active[RUNTIME_PAIR_CAUSE_MAX] = {};
  uint32_t bootId = 0;
  uint32_t nextPairId = 1;
  bool pairIdExhausted = false;
};

struct RuntimePairPendingEvent {
  char payload[RUNTIME_PAIR_EVENT_PAYLOAD_MAX + 1] = {};
  MESSAGE_TYPE level = NONE_MSG;
  bool ready = false;
};

struct RuntimePairEventFacts {
  uint32_t sessionId;
  uint8_t mode;
  uint8_t row;
  uint8_t cause;
  uint64_t monotonicMs;
  uint32_t localEpoch;
  int8_t timeZone;
};

inline uint64_t runtime_pair_monotonic_ms() {
  return static_cast<uint64_t>(esp_timer_get_time()) / 1000ULL;
}

inline uint32_t runtime_pair_utc_epoch(uint32_t localEpoch, int8_t timeZone) {
  const int64_t utcEpoch = static_cast<int64_t>(localEpoch) -
      static_cast<int64_t>(timeZone) * 3600;
  if (utcEpoch <= 0 || utcEpoch > UINT32_MAX) return 0;
  return static_cast<uint32_t>(utcEpoch);
}

inline void runtime_pair_state_init(RuntimePairState& state, uint32_t bootId) {
  state = RuntimePairState{};
  state.bootId = bootId;
}

inline bool runtime_pair_valid_utf8(const char* text, size_t& length) {
  length = 0;
  if (text == nullptr) return false;
  while (text[length] != '\0') {
    const uint8_t first = static_cast<uint8_t>(text[length]);
    size_t sequenceLength = 0;
    if (first <= 0x7F) {
      sequenceLength = 1;
    } else if (first >= 0xC2 && first <= 0xDF) {
      sequenceLength = 2;
    } else if (first >= 0xE0 && first <= 0xEF) {
      sequenceLength = 3;
    } else if (first >= 0xF0 && first <= 0xF4) {
      sequenceLength = 4;
    } else {
      return false;
    }
    for (size_t offset = 1; offset < sequenceLength; offset++) {
      const uint8_t next = static_cast<uint8_t>(text[length + offset]);
      if (next == 0 || (next & 0xC0) != 0x80) return false;
    }
    if ((first == 0xE0 && static_cast<uint8_t>(text[length + 1]) < 0xA0) ||
        (first == 0xED && static_cast<uint8_t>(text[length + 1]) > 0x9F) ||
        (first == 0xF0 && static_cast<uint8_t>(text[length + 1]) < 0x90) ||
        (first == 0xF4 && static_cast<uint8_t>(text[length + 1]) > 0x8F)) {
      return false;
    }
    length += sequenceLength;
    if (length > RUNTIME_PAIR_EVENT_PAYLOAD_MAX) return true;
  }
  return true;
}

inline RuntimePairPrepareResult runtime_pair_build_payload(
    RuntimePairPendingEvent& pending, uint32_t sessionId, uint32_t bootId,
    uint32_t pairId, char event, uint8_t mode, uint8_t row, uint8_t cause,
    uint8_t outcome, uint64_t monotonicMs, uint32_t localEpoch,
    int8_t timeZone, const char* tail, MESSAGE_TYPE level) {
  size_t tailLength = 0;
  if (!runtime_pair_valid_utf8(tail, tailLength)) return RUNTIME_PAIR_TEXT_INVALID_UTF8;
  if (tailLength == 0) return RUNTIME_PAIR_TEXT_EMPTY;
  const uint32_t utcEpoch = runtime_pair_utc_epoch(localEpoch, timeZone);
  const bool hasUtc = utcEpoch > NTP_PLAUSIBLE_MIN_EPOCH;
  const int headerLength = hasUtc
      ? snprintf(pending.payload, sizeof(pending.payload),
                 "@P1;s=%08lX;b=%08lX;p=%08lX;e=%c;m=%X;r=%02X;q=%02X;o=%02X;t=%016llX;u=%08lX|",
                 static_cast<unsigned long>(sessionId), static_cast<unsigned long>(bootId),
                 static_cast<unsigned long>(pairId), event, static_cast<unsigned>(mode),
                 static_cast<unsigned>(row), static_cast<unsigned>(cause),
                 static_cast<unsigned>(outcome), static_cast<unsigned long long>(monotonicMs),
                 static_cast<unsigned long>(utcEpoch))
      : snprintf(pending.payload, sizeof(pending.payload),
                 "@P1;s=%08lX;b=%08lX;p=%08lX;e=%c;m=%X;r=%02X;q=%02X;o=%02X;t=%016llX|",
                 static_cast<unsigned long>(sessionId), static_cast<unsigned long>(bootId),
                 static_cast<unsigned long>(pairId), event, static_cast<unsigned>(mode),
                 static_cast<unsigned>(row), static_cast<unsigned>(cause),
                 static_cast<unsigned>(outcome), static_cast<unsigned long long>(monotonicMs));
  if (headerLength < 0 || static_cast<size_t>(headerLength) + tailLength > RUNTIME_PAIR_EVENT_PAYLOAD_MAX) {
    pending.payload[0] = '\0';
    return RUNTIME_PAIR_TEXT_TOO_LONG;
  }
  memcpy(pending.payload + headerLength, tail, tailLength + 1);
  pending.level = level;
  pending.ready = true;
  return RUNTIME_PAIR_PREPARED;
}

inline RuntimePairPrepareResult runtime_pair_prepare_begin(
    RuntimePairState& state, const RuntimePairEventFacts& facts,
    const char* tail, MESSAGE_TYPE level, RuntimePairPendingEvent& pending) {
  pending.ready = false;
  if (facts.sessionId == 0 || facts.mode > RUNTIME_PAIR_MODE_MAX ||
      (facts.row == 0) || facts.cause < RUNTIME_PAIR_CAUSE_MIN ||
      facts.cause > RUNTIME_PAIR_CAUSE_MAX) {
    return RUNTIME_PAIR_INVALID_ARGUMENT;
  }
  RuntimePairState::ActivePair& active = state.active[facts.cause - 1];
  if (active.active) return RUNTIME_PAIR_DUPLICATE;
  if (state.pairIdExhausted) return RUNTIME_PAIR_ID_EXHAUSTED;
  const uint32_t pairId = state.nextPairId;
  const RuntimePairPrepareResult result = runtime_pair_build_payload(
      pending, facts.sessionId, state.bootId, pairId, 'B', facts.mode, facts.row,
      facts.cause, 0xFF, facts.monotonicMs, facts.localEpoch, facts.timeZone, tail, level);
  if (result != RUNTIME_PAIR_PREPARED) return result;
  active = {true, facts.sessionId, pairId, facts.mode, facts.row};
  if (pairId == UINT32_MAX) {
    state.pairIdExhausted = true;
  } else {
    state.nextPairId++;
  }
  return RUNTIME_PAIR_PREPARED;
}

inline RuntimePairPrepareResult runtime_pair_prepare_end(
    RuntimePairState& state, const RuntimePairEventFacts& facts,
    RuntimePairOutcome outcome, const char* tail, MESSAGE_TYPE level,
    RuntimePairPendingEvent& pending, uint32_t expectedPairId = 0) {
  pending.ready = false;
  if (facts.cause < RUNTIME_PAIR_CAUSE_MIN || facts.cause > RUNTIME_PAIR_CAUSE_MAX ||
      static_cast<uint8_t>(outcome) > RUNTIME_PAIR_ERROR) {
    return RUNTIME_PAIR_INVALID_ARGUMENT;
  }
  RuntimePairState::ActivePair& active = state.active[facts.cause - 1];
  if (!active.active) return RUNTIME_PAIR_DUPLICATE;
  if (expectedPairId != 0 && active.pairId != expectedPairId) {
    return RUNTIME_PAIR_DUPLICATE;
  }
  const RuntimePairPrepareResult result = runtime_pair_build_payload(
      pending, active.sessionId, state.bootId, active.pairId, 'E', active.mode,
      active.row, facts.cause, static_cast<uint8_t>(outcome), facts.monotonicMs,
      facts.localEpoch, facts.timeZone, tail, level);
  if (result != RUNTIME_PAIR_PREPARED) return result;
  active.active = false;
  return RUNTIME_PAIR_PREPARED;
}

inline RuntimePairDispatchResult runtime_pair_dispatch(RuntimePairPendingEvent& pending) {
  if (!pending.ready) return RUNTIME_PAIR_NOT_PENDING;
  SendMsg(String(pending.payload), pending.level);
  pending.ready = false;
  return RUNTIME_PAIR_SENT_TO_SENDMSG;
}
