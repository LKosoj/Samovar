#ifndef RUNTIME_EVENT_LOG_H
#define RUNTIME_EVENT_LOG_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <utility>

static const uint8_t RUNTIME_EVENT_DESCRIPTOR_CAPACITY = 16;
static const uint16_t RUNTIME_EVENT_TEXT_POOL_BYTES = 10240;
static const uint16_t RUNTIME_EVENT_MAX_TEXT_BYTES = 10000;

enum RuntimeEventKind : uint8_t {
  RUNTIME_EVENT_MESSAGE = 1,
  RUNTIME_EVENT_CONSOLE = 2,
};

enum RuntimeEventAppendResult : uint8_t {
  RUNTIME_EVENT_APPEND_OK = 0,
  RUNTIME_EVENT_APPEND_EMPTY,
  RUNTIME_EVENT_TEXT_TOO_LONG,
  RUNTIME_EVENT_APPEND_INVALID_ARGUMENT,
  RUNTIME_EVENT_APPEND_CORRUPT,
};

enum RuntimeEventSelectResult : uint8_t {
  RUNTIME_EVENT_SELECT_FOUND = 0,
  RUNTIME_EVENT_SELECT_NONE,
  RUNTIME_EVENT_SELECT_CORRUPT,
};

enum RuntimeEventSnapshotResult : uint8_t {
  RUNTIME_EVENT_SNAPSHOT_OK = 0,
  RUNTIME_EVENT_SNAPSHOT_NO_MEMORY,
  RUNTIME_EVENT_SNAPSHOT_CORRUPT,
};

struct RuntimeEventDescriptor {
  uint32_t sequence;
  uint16_t offset;
  uint16_t length;
  uint8_t kind;
  uint8_t level;
};

struct RuntimeEventRing {
  RuntimeEventDescriptor descriptors[RUNTIME_EVENT_DESCRIPTOR_CAPACITY];
  char textPool[RUNTIME_EVENT_TEXT_POOL_BYTES + 1];
  uint32_t nextSequence;
  uint16_t writeOffset;
  uint16_t usedBytes;
  uint8_t oldestIndex;
  uint8_t count;
};

static_assert(sizeof(RuntimeEventDescriptor) <= 12, "RuntimeEventDescriptor exceeds RAM budget");
static_assert(sizeof(RuntimeEventRing) <= 10464, "RuntimeEventRing exceeds RAM budget");

extern RuntimeEventRing runtimeEventRing;

inline uint8_t runtime_event_descriptor_index(uint8_t oldestIndex, uint8_t offset) {
  return static_cast<uint8_t>((oldestIndex + offset) % RUNTIME_EVENT_DESCRIPTOR_CAPACITY);
}

inline uint16_t runtime_event_pool_advance(uint16_t offset, uint16_t length) {
  return static_cast<uint16_t>((static_cast<uint32_t>(offset) + length) % RUNTIME_EVENT_TEXT_POOL_BYTES);
}

inline uint32_t runtime_event_next_sequence(uint32_t sequence) {
  return sequence == UINT32_MAX ? 1U : sequence + 1U;
}

inline bool runtime_event_kind_valid(uint8_t kind) {
  return kind == RUNTIME_EVENT_MESSAGE || kind == RUNTIME_EVENT_CONSOLE;
}

inline void runtime_event_init(RuntimeEventRing& ring) {
  memset(&ring, 0, sizeof(ring));
  ring.nextSequence = 1;
  ring.textPool[RUNTIME_EVENT_TEXT_POOL_BYTES] = '\0';
}

inline bool runtime_event_validate_locked(const RuntimeEventRing& ring) {
  if (ring.nextSequence == 0 ||
      ring.writeOffset >= RUNTIME_EVENT_TEXT_POOL_BYTES ||
      ring.usedBytes > RUNTIME_EVENT_TEXT_POOL_BYTES ||
      ring.oldestIndex >= RUNTIME_EVENT_DESCRIPTOR_CAPACITY ||
      ring.count > RUNTIME_EVENT_DESCRIPTOR_CAPACITY ||
      ring.textPool[RUNTIME_EVENT_TEXT_POOL_BYTES] != '\0') {
    return false;
  }
  if (ring.count == 0) return ring.usedBytes == 0;

  uint32_t totalLength = 0;
  uint16_t expectedOffset = ring.descriptors[ring.oldestIndex].offset;
  uint32_t previousSequence = 0;
  for (uint8_t offset = 0; offset < ring.count; offset++) {
    const RuntimeEventDescriptor& descriptor =
        ring.descriptors[runtime_event_descriptor_index(ring.oldestIndex, offset)];
    if (descriptor.sequence == 0 || descriptor.offset != expectedOffset ||
        descriptor.length == 0 || descriptor.length > RUNTIME_EVENT_MAX_TEXT_BYTES ||
        !runtime_event_kind_valid(descriptor.kind)) {
      return false;
    }
    if (offset > 0 && descriptor.sequence != runtime_event_next_sequence(previousSequence)) {
      return false;
    }
    totalLength += descriptor.length;
    if (totalLength > RUNTIME_EVENT_TEXT_POOL_BYTES) return false;
    expectedOffset = runtime_event_pool_advance(expectedOffset, descriptor.length);
    previousSequence = descriptor.sequence;
  }
  return totalLength == ring.usedBytes && expectedOffset == ring.writeOffset &&
         ring.nextSequence == runtime_event_next_sequence(previousSequence);
}

inline RuntimeEventAppendResult runtime_event_append_locked(
    RuntimeEventRing& ring, RuntimeEventKind kind, uint8_t level,
    const char* text, size_t length, uint32_t* sequenceOut = nullptr) {
  if (length == 0) return RUNTIME_EVENT_APPEND_EMPTY;
  if (length > RUNTIME_EVENT_MAX_TEXT_BYTES) return RUNTIME_EVENT_TEXT_TOO_LONG;
  if (!text || !runtime_event_kind_valid(static_cast<uint8_t>(kind))) {
    return RUNTIME_EVENT_APPEND_INVALID_ARGUMENT;
  }
  if (!runtime_event_validate_locked(ring)) return RUNTIME_EVENT_APPEND_CORRUPT;

  uint8_t nextOldestIndex = ring.oldestIndex;
  uint8_t nextCount = ring.count;
  uint16_t nextUsedBytes = ring.usedBytes;
  while (nextCount == RUNTIME_EVENT_DESCRIPTOR_CAPACITY ||
         static_cast<size_t>(RUNTIME_EVENT_TEXT_POOL_BYTES - nextUsedBytes) < length) {
    const RuntimeEventDescriptor& evicted = ring.descriptors[nextOldestIndex];
    nextUsedBytes = static_cast<uint16_t>(nextUsedBytes - evicted.length);
    nextOldestIndex = runtime_event_descriptor_index(nextOldestIndex, 1);
    nextCount--;
  }

  const uint8_t descriptorIndex = runtime_event_descriptor_index(nextOldestIndex, nextCount);
  const uint32_t sequence = ring.nextSequence;
  const uint16_t textLength = static_cast<uint16_t>(length);
  const size_t contiguousBytes = RUNTIME_EVENT_TEXT_POOL_BYTES - ring.writeOffset;
  const uint16_t firstLength = static_cast<uint16_t>(
      length < contiguousBytes ? length : contiguousBytes);
  memcpy(&ring.textPool[ring.writeOffset], text, firstLength);
  if (firstLength < textLength) {
    memcpy(ring.textPool, text + firstLength, textLength - firstLength);
  }

  RuntimeEventDescriptor& descriptor = ring.descriptors[descriptorIndex];
  descriptor.sequence = sequence;
  descriptor.offset = ring.writeOffset;
  descriptor.length = textLength;
  descriptor.kind = static_cast<uint8_t>(kind);
  descriptor.level = level;
  ring.oldestIndex = nextOldestIndex;
  ring.count = static_cast<uint8_t>(nextCount + 1U);
  ring.usedBytes = static_cast<uint16_t>(nextUsedBytes + textLength);
  ring.writeOffset = runtime_event_pool_advance(ring.writeOffset, textLength);
  ring.nextSequence = runtime_event_next_sequence(sequence);
  ring.textPool[RUNTIME_EVENT_TEXT_POOL_BYTES] = '\0';
  if (sequenceOut) *sequenceOut = sequence;
  return RUNTIME_EVENT_APPEND_OK;
}

inline RuntimeEventSelectResult runtime_event_select_locked(
    const RuntimeEventRing& ring, uint32_t cursor, RuntimeEventDescriptor& selected) {
  if (!runtime_event_validate_locked(ring)) return RUNTIME_EVENT_SELECT_CORRUPT;
  if (ring.count == 0) return RUNTIME_EVENT_SELECT_NONE;

  uint8_t selectedOffset = 0;
  if (cursor != 0) {
    bool found = false;
    for (uint8_t offset = 0; offset < ring.count; offset++) {
      const RuntimeEventDescriptor& descriptor =
          ring.descriptors[runtime_event_descriptor_index(ring.oldestIndex, offset)];
      if (descriptor.sequence != cursor) continue;
      found = true;
      if (offset + 1U == ring.count) return RUNTIME_EVENT_SELECT_NONE;
      selectedOffset = static_cast<uint8_t>(offset + 1U);
      break;
    }
    if (!found) selectedOffset = 0;
  }
  selected = ring.descriptors[runtime_event_descriptor_index(ring.oldestIndex, selectedOffset)];
  return RUNTIME_EVENT_SELECT_FOUND;
}

inline RuntimeEventSelectResult runtime_event_select_latest_message_locked(
    const RuntimeEventRing& ring, RuntimeEventDescriptor& selected) {
  if (!runtime_event_validate_locked(ring)) return RUNTIME_EVENT_SELECT_CORRUPT;
  bool found = false;
  for (uint8_t offset = 0; offset < ring.count; offset++) {
    const RuntimeEventDescriptor& descriptor =
        ring.descriptors[runtime_event_descriptor_index(ring.oldestIndex, offset)];
    if (descriptor.kind == RUNTIME_EVENT_MESSAGE) {
      selected = descriptor;
      found = true;
    }
  }
  return found ? RUNTIME_EVENT_SELECT_FOUND : RUNTIME_EVENT_SELECT_NONE;
}

inline uint32_t runtime_event_latest_sequence_locked(const RuntimeEventRing& ring) {
  if (ring.count == 0 || ring.count > RUNTIME_EVENT_DESCRIPTOR_CAPACITY) return 0;
  const uint8_t newestIndex = runtime_event_descriptor_index(ring.oldestIndex, ring.count - 1);
  return ring.descriptors[newestIndex].sequence;
}

inline bool runtime_event_descriptor_retained_locked(
    const RuntimeEventRing& ring, const RuntimeEventDescriptor& selected) {
  for (uint8_t offset = 0; offset < ring.count; offset++) {
    const RuntimeEventDescriptor& descriptor =
        ring.descriptors[runtime_event_descriptor_index(ring.oldestIndex, offset)];
    if (descriptor.sequence == selected.sequence && descriptor.offset == selected.offset &&
        descriptor.length == selected.length && descriptor.kind == selected.kind &&
        descriptor.level == selected.level) {
      return true;
    }
  }
  return false;
}

template <typename Text>
inline RuntimeEventSnapshotResult runtime_event_copy_text_locked(
    const RuntimeEventRing& ring, const RuntimeEventDescriptor& selected, Text& output) {
  if (!runtime_event_validate_locked(ring) ||
      !runtime_event_descriptor_retained_locked(ring, selected)) {
    return RUNTIME_EVENT_SNAPSHOT_CORRUPT;
  }

  Text candidate;
  if (!candidate.reserve(selected.length)) return RUNTIME_EVENT_SNAPSHOT_NO_MEMORY;
  const uint16_t firstLength = static_cast<uint16_t>(
      selected.length < RUNTIME_EVENT_TEXT_POOL_BYTES - selected.offset
          ? selected.length
          : RUNTIME_EVENT_TEXT_POOL_BYTES - selected.offset);
  if (!candidate.concat(&ring.textPool[selected.offset], firstLength)) {
    return RUNTIME_EVENT_SNAPSHOT_NO_MEMORY;
  }
  const uint16_t secondLength = static_cast<uint16_t>(selected.length - firstLength);
  if (secondLength > 0 && !candidate.concat(ring.textPool, secondLength)) {
    return RUNTIME_EVENT_SNAPSHOT_NO_MEMORY;
  }
  if (candidate.length() != selected.length) {
    return RUNTIME_EVENT_SNAPSHOT_CORRUPT;
  }
  candidate.begin()[candidate.length()] = '\0';
  output = std::move(candidate);
  return RUNTIME_EVENT_SNAPSHOT_OK;
}

inline bool runtime_event_parse_cursor(const char* text, size_t length, uint32_t& cursor) {
  if (!text || length == 0 || length > 10) return false;
  uint32_t parsed = 0;
  for (size_t index = 0; index < length; index++) {
    const char character = text[index];
    if (character < '0' || character > '9') return false;
    const uint32_t digit = static_cast<uint32_t>(character - '0');
    if (parsed > (UINT32_MAX - digit) / 10U) return false;
    parsed = parsed * 10U + digit;
  }
  cursor = parsed;
  return true;
}

#endif
