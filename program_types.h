#ifndef PROGRAM_TYPES_H
#define PROGRAM_TYPES_H

using ProgramType = char;

constexpr ProgramType PROGRAM_TYPE_NONE = '\0';
constexpr uint8_t PROGRAM_MAX = CAPACITY_NUM * 2;
constexpr uint8_t PROGRAM_END = PROGRAM_MAX;
constexpr uint8_t NBK_PROGRAM_MAX = 4;

static_assert(PROGRAM_MAX > 0 && PROGRAM_MAX < 255, "PROGRAM_MAX must fit uint8_t and leave room for sentinel math");
static_assert(PROGRAM_END == PROGRAM_MAX, "PROGRAM_END is a sentinel, not a valid program[] index");

inline bool program_type_empty(ProgramType type) {
  return type == PROGRAM_TYPE_NONE;
}

inline bool program_type_one_of(ProgramType type, const char *allowedTypes) {
  if (program_type_empty(type) || !allowedTypes) return false;
  for (const char *p = allowedTypes; *p; p++) {
    if (type == *p) return true;
  }
  return false;
}

inline bool parse_program_type(const char *text, const char *allowedTypes, ProgramType& type) {
  if (!text || text[0] == '\0' || text[1] != '\0') return false;
  ProgramType parsed = text[0];
  if (!program_type_one_of(parsed, allowedTypes)) return false;
  type = parsed;
  return true;
}

inline String program_type_to_string(ProgramType type) {
  if (program_type_empty(type)) return String();
  return String(type);
}

inline void append_program_type(String& text, ProgramType type) {
  if (!program_type_empty(type)) text += type;
}

#endif
