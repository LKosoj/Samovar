#pragma once

#include <Arduino.h>
#include <string.h>
#include "Samovar.h"
#include "samovar_api.h"

enum ProgramFieldKind : uint8_t {
  PROGRAM_FIELD_TYPE,
  PROGRAM_FIELD_VOLUME,
  PROGRAM_FIELD_SPEED,
  PROGRAM_FIELD_CAPACITY,
  PROGRAM_FIELD_TEMP,
  PROGRAM_FIELD_TIME,
  PROGRAM_FIELD_POWER,
  PROGRAM_FIELD_TEMP_SENSOR,
  PROGRAM_FIELD_BEER_DEVICE,
};

struct ProgramParseSpec;
using ProgramRowParser = bool (*)(char* line, size_t lineLen, uint8_t rowIndex, WProgram& row, const ProgramParseSpec& spec, const char*& errorMessage);
using ProgramRowSerializer = void (*)(String& out, const WProgram& row);

struct ProgramParseSpec {
  const char* tooLongMessage;
  const char* invalidFormatMessage;
  const char* finalCountMessage;
  const char* allowedTypes;
  const ProgramFieldKind* fields;
  uint8_t fieldCount;
  uint8_t maxRows;
  const ProgramType* expectedTypes;
  uint8_t expectedRowCount;
  ProgramRowParser parseRow;
};

inline void program_clear_rows() {
  for (int j = 0; j < PROGRAM_END; j++) {
    program[j].WType = PROGRAM_TYPE_NONE;
  }
}

inline size_t program_trim_line_right(char* line) {
  size_t lineLen = strlen(line);
  while (lineLen > 0 && (line[lineLen - 1] == '\r' || line[lineLen - 1] == ' ' || line[lineLen - 1] == '\t')) {
    line[--lineLen] = '\0';
  }
  return lineLen;
}

inline uint8_t program_count_char(const char* text, char needle) {
  uint8_t count = 0;
  for (const char* p = text; p && *p; p++) {
    if (*p == needle) count++;
  }
  return count;
}

inline bool program_parse_beer_device(char* token, long& devType, long& speed, long& onTime, long& offTime) {
  if (program_count_char(token, '^') != 3) return false;

  char* saveTok = nullptr;
  char* tokDevType = strtok_r(token, "^", &saveTok);
  char* tokSpeed = strtok_r(nullptr, "^", &saveTok);
  char* tokOnTime = strtok_r(nullptr, "^", &saveTok);
  char* tokOffTime = strtok_r(nullptr, "^", &saveTok);
  char* tokExtra = strtok_r(nullptr, "^", &saveTok);

  return tokDevType && tokSpeed && tokOnTime && tokOffTime &&
         !tokExtra &&
         parseLongSafe(tokDevType, devType) &&
         parseLongSafe(tokSpeed, speed) &&
         parseLongSafe(tokOnTime, onTime) &&
         parseLongSafe(tokOffTime, offTime) &&
         devType >= 0 && devType <= 255 &&
         onTime >= 0 && onTime <= 65535 &&
         offTime >= 0 && offTime <= 65535;
}

inline bool program_parse_rect_row(char* line, size_t, uint8_t, WProgram& row, const ProgramParseSpec& spec, const char*&) {
  char* saveTok = nullptr;
  char* tokType = strtok_r(line, ";", &saveTok);
  char* tokVolume = strtok_r(nullptr, ";", &saveTok);
  char* tokSpeed = strtok_r(nullptr, ";", &saveTok);
  char* tokCap = strtok_r(nullptr, ";", &saveTok);
  char* tokTemp = strtok_r(nullptr, ";", &saveTok);
  char* tokPower = strtok_r(nullptr, ";", &saveTok);
  char* tokExtra = strtok_r(nullptr, ";", &saveTok);

  long volume = 0;
  long cap = 0;
  float speed = 0;
  float temp = 0;
  float power = 0;
  ProgramType parsedType = PROGRAM_TYPE_NONE;
  bool ok = parse_program_type(tokType, spec.allowedTypes, parsedType) &&
            tokVolume && tokSpeed && tokCap && tokTemp && tokPower &&
            !tokExtra &&
            parseLongSafe(tokVolume, volume) &&
            parseFloatSafe(tokSpeed, speed) &&
            parseLongSafe(tokCap, cap) &&
            parseFloatSafe(tokTemp, temp) &&
            parseFloatSafe(tokPower, power) &&
            volume >= 0 && volume <= 65535 &&
            cap >= 0 && cap <= CAPACITY_NUM;

  if (ok && parsedType != 'P' && speed <= 0.0f) ok = false;
  if (ok && parsedType == 'P' && volume <= 0) ok = false;
  if (!ok) return false;

  row.WType = parsedType;
  row.Volume = (uint16_t)volume;
  row.Speed = speed;
  row.capacity_num = (uint8_t)cap;
  row.Temp = temp;
  row.Power = power;
  if (parsedType == 'P') {
    row.Time = row.Volume / 60.0f / 60.0f;
  } else {
    row.Time = row.Volume / row.Speed / 1000.0f;
  }
  return true;
}

inline bool program_parse_dist_row(char* line, size_t, uint8_t, WProgram& row, const ProgramParseSpec& spec, const char*&) {
  char* saveTok = nullptr;
  char* tokType = strtok_r(line, ";", &saveTok);
  char* tokSpeed = strtok_r(nullptr, ";", &saveTok);
  char* tokCap = strtok_r(nullptr, ";", &saveTok);
  char* tokPower = strtok_r(nullptr, ";", &saveTok);
  char* tokExtra = strtok_r(nullptr, ";", &saveTok);

  float speed = 0;
  float power = 0;
  long cap = 0;
  ProgramType parsedType = PROGRAM_TYPE_NONE;
  bool ok = parse_program_type(tokType, spec.allowedTypes, parsedType) &&
            tokSpeed && tokCap && tokPower &&
            !tokExtra &&
            parseFloatSafe(tokSpeed, speed) &&
            parseLongSafe(tokCap, cap) &&
            parseFloatSafe(tokPower, power) &&
            cap >= 0 && cap <= CAPACITY_NUM;

  if (!ok) return false;

  row.WType = parsedType;
  row.Speed = speed;
  row.capacity_num = (uint8_t)cap;
  row.Power = power;
  return true;
}

inline bool program_parse_beer_row(char* line, size_t lineLen, uint8_t, WProgram& row, const ProgramParseSpec& spec, const char*& errorMessage) {
  uint8_t delimCount = program_count_char(line, ';');

  char* saveTok = nullptr;
  char* tokType = strtok_r(line, ";", &saveTok);
  char* tokTemp = strtok_r(nullptr, ";", &saveTok);
  char* tokTime = strtok_r(nullptr, ";", &saveTok);
  char* tokDevice = strtok_r(nullptr, ";", &saveTok);
  char* tokSensor = strtok_r(nullptr, ";", &saveTok);
  char* tokExtra = strtok_r(nullptr, ";", &saveTok);

  float temp = 0.0f;
  float timeMin = 0.0f;
  long sensor = 0;
  ProgramType parsedType = PROGRAM_TYPE_NONE;
  bool ok = delimCount == 4 &&
            parse_program_type(tokType, spec.allowedTypes, parsedType) &&
            tokTemp && tokTime && tokDevice && tokSensor &&
            !tokExtra &&
            parseFloatSafe(tokTemp, temp) &&
            parseFloatSafe(tokTime, timeMin) &&
            parseLongSafe(tokSensor, sensor) &&
            sensor >= 0 && sensor <= 4 &&
            timeMin >= 0.0f;

  long devType = 0;
  long speed = 0;
  long onTime = 0;
  long offTime = 0;
  if (ok && !program_parse_beer_device(tokDevice, devType, speed, onTime, offTime)) {
    errorMessage = "Ошибка программы: неверный шаблон устройства beer";
    ok = false;
  }

  if (!ok) return false;
  (void)lineLen;

  row.WType = parsedType;
  row.Temp = temp;
  row.Time = timeMin;
  row.capacity_num = (uint8_t)devType;
  row.Speed = (float)speed;
  row.Volume = (uint16_t)onTime;
  row.Power = (uint16_t)offTime;
  row.TempSensor = (uint8_t)sensor;
  return true;
}

inline bool program_parse_nbk_row(char* line, size_t, uint8_t rowIndex, WProgram& row, const ProgramParseSpec& spec, const char*&) {
  char* saveTok = nullptr;
  char* tokType = strtok_r(line, ";", &saveTok);
  char* tokSpeed = strtok_r(nullptr, ";", &saveTok);
  char* tokPower = strtok_r(nullptr, ";", &saveTok);
  char* tokExtra = strtok_r(nullptr, ";", &saveTok);

  float speed = 0;
  float power = 0;
  ProgramType parsedType = PROGRAM_TYPE_NONE;
  bool ok = parse_program_type(tokType, spec.allowedTypes, parsedType) &&
            tokSpeed && tokPower &&
            !tokExtra &&
            spec.expectedTypes &&
            rowIndex < spec.expectedRowCount &&
            parsedType == spec.expectedTypes[rowIndex] &&
            parseFloatSafe(tokSpeed, speed) &&
            parseFloatSafe(tokPower, power);

  if (!ok) return false;

  row.WType = parsedType;
  row.Speed = speed;
  row.Power = power;
  return true;
}

inline bool program_parse_lines(const String& text, const ProgramParseSpec& spec) {
  program_clear_rows();
  ProgramLen = 0;

  if (text.length() == 0) return true;
  if (text.length() > MAX_PROGRAM_INPUT_LEN) {
    SendMsg(spec.tooLongMessage, ALARM_MSG);
    return false;
  }

  char input[MAX_PROGRAM_INPUT_LEN + 1] = {0};
  copyStringSafe(input, text);

  uint8_t i = 0;
  char* saveLine = nullptr;
  char* line = strtok_r(input, "\n", &saveLine);
  while (line && i < spec.maxRows) {
    size_t lineLen = program_trim_line_right(line);
    if (lineLen == 0) {
      line = strtok_r(nullptr, "\n", &saveLine);
      continue;
    }

    const char* rowErrorMessage = nullptr;
    if (!spec.parseRow(line, lineLen, i, program[i], spec, rowErrorMessage)) {
      program_clear_rows();
      ProgramLen = 0;
      SendMsg(rowErrorMessage ? rowErrorMessage : spec.invalidFormatMessage, ALARM_MSG);
      return false;
    }

    i++;
    ProgramLen = i;
    line = strtok_r(nullptr, "\n", &saveLine);
  }

  if (spec.expectedRowCount > 0 && i != spec.expectedRowCount) {
    program_clear_rows();
    ProgramLen = 0;
    SendMsg(spec.finalCountMessage, ALARM_MSG);
    return false;
  }

  if (i < PROGRAM_END) {
    program[i].WType = PROGRAM_TYPE_NONE;
  }
  (void)spec.fields;
  (void)spec.fieldCount;
  return true;
}

inline String program_serialize_rows(uint8_t start, uint8_t end, ProgramRowSerializer serializer) {
  String out = "";
  for (uint8_t i = start; i < end; i++) {
    if (program_type_empty(program[i].WType)) break;
    serializer(out, program[i]);
  }
  return out;
}

inline void program_append_rect_row(String& out, const WProgram& row) {
  append_program_type(out, row.WType);
  out += ";";
  out += (String)row.Volume + ";";
  out += (String)row.Speed + ";";
  out += (String)row.capacity_num + ";";
  out += (String)row.Temp + ";";
  out += (String)row.Power + "\n";
}

inline void program_append_dist_row(String& out, const WProgram& row) {
  append_program_type(out, row.WType);
  out += ";";
  out += (String)row.Speed + ";";
  out += (String)(int)row.capacity_num + ";";
  out += (String)row.Power + "\n";
}

inline void program_append_beer_row(String& out, const WProgram& row) {
  append_program_type(out, row.WType);
  out += ";";
  out += (String)row.Temp + ";";
  out += (String)(int)row.Time + ";";
  out += (String)row.capacity_num + "^" + (int)row.Speed + "^" + row.Volume + "^" + (int)row.Power + ";";
  out += (String)row.TempSensor + "\n";
}

inline void program_append_nbk_row(String& out, const WProgram& row) {
  append_program_type(out, row.WType);
  out += ";";
  out += (String)row.Speed + ";";
  out += (String)row.Power + "\n";
}

inline const ProgramParseSpec& rect_program_parse_spec() {
  static const ProgramFieldKind fields[] = {
    PROGRAM_FIELD_TYPE,
    PROGRAM_FIELD_VOLUME,
    PROGRAM_FIELD_SPEED,
    PROGRAM_FIELD_CAPACITY,
    PROGRAM_FIELD_TEMP,
    PROGRAM_FIELD_POWER,
  };
  static const ProgramParseSpec spec = {
    "Ошибка программы: слишком длинная строка (rect)",
    "Ошибка программы: неверный формат строки rect",
    nullptr,
    "HBCTP",
    fields,
    static_cast<uint8_t>(sizeof(fields) / sizeof(fields[0])),
    PROGRAM_END,
    nullptr,
    0,
    program_parse_rect_row,
  };
  return spec;
}

inline const ProgramParseSpec& dist_program_parse_spec() {
  static const ProgramFieldKind fields[] = {
    PROGRAM_FIELD_TYPE,
    PROGRAM_FIELD_SPEED,
    PROGRAM_FIELD_CAPACITY,
    PROGRAM_FIELD_POWER,
  };
  static const ProgramParseSpec spec = {
    "Ошибка программы: слишком длинная строка (dist)",
    "Ошибка программы: неверный формат строки dist",
    nullptr,
    "TASPR",
    fields,
    static_cast<uint8_t>(sizeof(fields) / sizeof(fields[0])),
    PROGRAM_END,
    nullptr,
    0,
    program_parse_dist_row,
  };
  return spec;
}

inline const ProgramParseSpec& beer_program_parse_spec() {
  static const ProgramFieldKind fields[] = {
    PROGRAM_FIELD_TYPE,
    PROGRAM_FIELD_TEMP,
    PROGRAM_FIELD_TIME,
    PROGRAM_FIELD_BEER_DEVICE,
    PROGRAM_FIELD_TEMP_SENSOR,
  };
  static const ProgramParseSpec spec = {
    "Ошибка программы: слишком длинная строка (beer)",
    "Ошибка программы: неверный формат строки beer",
    nullptr,
    "MPBCFWLA",
    fields,
    static_cast<uint8_t>(sizeof(fields) / sizeof(fields[0])),
    PROGRAM_END,
    nullptr,
    0,
    program_parse_beer_row,
  };
  return spec;
}

inline const ProgramParseSpec& nbk_program_parse_spec() {
  static const ProgramFieldKind fields[] = {
    PROGRAM_FIELD_TYPE,
    PROGRAM_FIELD_SPEED,
    PROGRAM_FIELD_POWER,
  };
  static const ProgramType expectedTypes[NBK_PROGRAM_MAX] = {'H', 'S', 'O', 'W'};
  static const ProgramParseSpec spec = {
    "Ошибка программы: слишком длинная строка (nbk)",
    "Ошибка программы: неверный формат строки nbk",
    "Ошибка программы: НБК должна содержать 4 строки H/S/O/W",
    "HSOW",
    fields,
    static_cast<uint8_t>(sizeof(fields) / sizeof(fields[0])),
    NBK_PROGRAM_MAX,
    expectedTypes,
    NBK_PROGRAM_MAX,
    program_parse_nbk_row,
  };
  return spec;
}
