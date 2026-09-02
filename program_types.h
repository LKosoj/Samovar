#ifndef PROGRAM_TYPES_H
#define PROGRAM_TYPES_H

using ProgramType = char;

constexpr ProgramType PROGRAM_TYPE_NONE = '\0';
constexpr uint8_t PROGRAM_MAX = CAPACITY_NUM * 2;
constexpr uint8_t PROGRAM_END = PROGRAM_MAX;
constexpr uint8_t NBK_PROGRAM_MAX = 4;

static_assert(PROGRAM_MAX > 0 && PROGRAM_MAX < 255, "PROGRAM_MAX must fit uint8_t and leave room for sentinel math");
static_assert(PROGRAM_END == PROGRAM_MAX, "PROGRAM_END is a sentinel, not a valid program[] index");

// [Б7.1] Перенесено из power_regulator.h: нужен раньше (program_io.h,
// logic.h::validate_rect_program_startable()), чем power_regulator.h подключается
// в logic.h.
// Порог трактовки поля Power строки программы: |Power| выше него и Power > 0 -
// абсолютная уставка (В для KVIC/RMVK, Вт для SEM_AVR), иначе - дельта к текущей
// target_power_volt, 0 - строка явно "не трогать регулятор".
// НЕ путать с POWER_WORK_MODE_THRESHOLD (порог WORK/SLEEP самого регулятора) -
// для SEM_AVR числа разные (400 против 100), совпадают только у KVIC/RMVK (40).
#ifdef SAMOVAR_USE_SEM_AVR
static constexpr float PROGRAM_POWER_ABS_THRESHOLD = 400.0f;
#else
static constexpr float PROGRAM_POWER_ABS_THRESHOLD = 40.0f;
#endif

enum ProgramParseError : uint8_t {
  PROGRAM_PARSE_OK = 0,
  PROGRAM_PARSE_EMPTY_INPUT,
  PROGRAM_PARSE_INPUT_TOO_LONG,
  PROGRAM_PARSE_TOO_MANY_ROWS,
  PROGRAM_PARSE_INVALID_ROW,
  PROGRAM_PARSE_WRONG_ROW_COUNT,
  PROGRAM_PARSE_UNSUPPORTED_MODE,
};

struct ProgramParseResult {
  ProgramParseError error;
  uint16_t lineNumber;
  const char* errorMessage;

  bool ok() const {
    return error == PROGRAM_PARSE_OK;
  }
};

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
