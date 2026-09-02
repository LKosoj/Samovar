#pragma once

#include <Arduino.h>
#include <string.h>
#include <type_traits>
#include "Samovar.h"
#include "numeric_parse.h"

// [T29] program[]/ProgramLen читаются/пишутся из разных задач (async_tcp/Blynk
// против loop()) - защищены тем же спинлоком, что и SamSetup (configMux,
// определён в Samovar.ino). program_io.h подключается (через beer.h/logic.h/
// sensorinit.h) РАНЬШЕ строки с определением configMux - здесь только extern,
// как и для dsAddressMux в sensorinit.h.
extern portMUX_TYPE configMux;

// --- Щедрые физические границы числовых полей исполняемой программы -----------
// Пределы намеренно ШИРОКИЕ: отбрасывают только физически бессмысленные значения
// (напр. Power=1e38, Temp=-500), не отвергая ни одной легитимной пользовательской
// программы. Значения выведены из существующих схем валидации прошивки.

// Температура (°C). Верх — потолок температурных полей setup: DistTemp/NbkSteamT
// = 0..150 (WebServer.ino). Ниже 0 ни один режим не работает.
constexpr float PROGRAM_TEMP_MIN = 0.0f;
constexpr float PROGRAM_TEMP_MAX = 150.0f;

// Скорость отбора — расход л/ч (RECT/NBK). Потолок = абсолютный предел скорости из
// parse_control_nbk (value < 8000) и CONTROL_STEPPER_SPEED_MAX (control_numeric_input.h).
// 0 допустим: у NBK это sentinel «взять значение по умолчанию», у RECT отбор со
// speed<=0 для не-'P' строк отвергается отдельной проверкой ниже.
constexpr float PROGRAM_RATE_MIN = 0.0f;
constexpr float PROGRAM_RATE_MAX = 8000.0f;

// «Speed» строки дистилляции — НЕ расход, а порог перехода: целевая T куба ('T', °C),
// либо спиртуозность ('A'/'P', % об.), либо доля ('S'/'R', 0..1) — см. distiller.h.
// 0..150 покрывает температуру (потолок DistTemp), спиртуозность (<100) и доли.
// Это лишь первый грубый фильтр; точные типозависимые границы — в program_parse_dist_row().
constexpr float PROGRAM_DIST_THRESHOLD_MIN = 0.0f;
constexpr float PROGRAM_DIST_THRESHOLD_MAX = 150.0f;

// Мощность/напряжение строки. Поле полиморфно: В (не-SEM, ≤ MAX_VOLTAGE=230) либо Вт
// (SEM, ≤ 52900/R из control_power_input_max, макс. ~52900 при R→1). Может быть
// ОТРИЦАТЕЛЬНЫМ — относительное смещение target_power_volt+Power (logic.h/distiller.h),
// поэтому диапазон симметричный.
constexpr float PROGRAM_POWER_MAX = 52900.0f;
constexpr float PROGRAM_POWER_MIN = -PROGRAM_POWER_MAX;

// [fix П33] «Время» строки программы пива (мин): выдержка температурной паузы ('P')
// или момент внесения хмеля от начала кипячения ('B') — см. program_parse_beer_row()
// и beer.h. До этой правки поле не имело верхней границы и принимало значения вплоть
// до FLT_MAX (~3.4e38), которые дальше портят экран и расчёты (beer_stage_elapsed_ms()
// делится на это значение). Потолок в 24 часа с большим запасом покрывает любой
// реальный этап варки (мэш-паузы обычно до нескольких часов, кипячение — до пары часов).
constexpr float PROGRAM_TIME_MIN = 0.0f;
constexpr float PROGRAM_TIME_MAX = 1440.0f;

struct ProgramDraft {
  WProgram rows[PROGRAM_MAX];
  uint8_t len;
};

constexpr size_t PROGRAM_DRAFT_MAX_BYTES = 640;
static_assert(std::is_trivially_copyable<WProgram>::value, "WProgram must remain safe for fixed draft copies");
static_assert(sizeof(ProgramDraft) <= PROGRAM_DRAFT_MAX_BYTES, "ProgramDraft exceeds the firmware stack budget");

enum ProgramUpdateAction : uint8_t {
  PROGRAM_UPDATE_NONE = 0,
  PROGRAM_UPDATE_REPLACE,
  PROGRAM_UPDATE_CLEAR,
};

enum ProgramFormat : uint8_t {
  PROGRAM_FORMAT_UNSUPPORTED = 0,
  PROGRAM_FORMAT_RECT,
  PROGRAM_FORMAT_DIST,
  PROGRAM_FORMAT_BEER,
  PROGRAM_FORMAT_NBK,
};

inline ProgramFormat program_format_for_mode(SAMOVAR_MODE mode) {
  switch (mode) {
    case SAMOVAR_RECTIFICATION_MODE:
    case SAMOVAR_BK_MODE:
    case SAMOVAR_LUA_MODE:
      return PROGRAM_FORMAT_RECT;
    case SAMOVAR_DISTILLATION_MODE:
      return PROGRAM_FORMAT_DIST;
    case SAMOVAR_BEER_MODE:
    case SAMOVAR_SUVID_MODE:
      return PROGRAM_FORMAT_BEER;
    case SAMOVAR_NBK_MODE:
      return PROGRAM_FORMAT_NBK;
    default:
      return PROGRAM_FORMAT_UNSUPPORTED;
  }
}

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
  const char* tooManyRowsMessage;
  const char* finalCountMessage;
  const char* allowedTypes;
  const ProgramFieldKind* fields;
  uint8_t fieldCount;
  uint8_t maxRows;
  const ProgramType* expectedTypes;
  uint8_t expectedRowCount;
  ProgramRowParser parseRow;
};

inline ProgramParseResult program_parse_result(
    ProgramParseError error,
    uint16_t lineNumber,
    const char* errorMessage) {
  return {error, lineNumber, errorMessage};
}

inline String format_program_parse_error(const ProgramParseResult& result) {
  String message = result.errorMessage ? result.errorMessage : "Ошибка программы";
  if (result.lineNumber > 0) {
    message += " (строка ";
    message += String(result.lineNumber);
    message += ")";
  }
  return message;
}

inline void program_reset_draft(ProgramDraft& draft) {
  for (uint8_t i = 0; i < PROGRAM_END; i++) {
    draft.rows[i] = {};
  }
  draft.len = 0;
}

inline void program_commit(const ProgramDraft& draft) {
  // [T29] Нельзя разрывать: иначе читатель (program_serialize_rows() из
  // async_tcp/Blynk) увидит новое число строк (ProgramLen) со старым
  // содержимым program[] или наоборот.
  portENTER_CRITICAL(&configMux);
  for (uint8_t i = 0; i < draft.len; i++) {
    program[i] = draft.rows[i];
  }
  for (uint8_t i = draft.len; i < PROGRAM_END; i++) {
    // Обнуляем строку целиком, а не только WType - иначе capacity_num/Power
    // от прошлой, более длинной программы остаются висеть в "удалённом" слоте
    // и могут быть ошибочно применены (см. run_dist_program()).
    program[i] = {};
    program[i].WType = PROGRAM_TYPE_NONE;
  }
  ProgramLen = draft.len;
  portEXIT_CRITICAL(&configMux);
}

inline void program_clear() {
  // [T29] Тот же риск рваного чтения, что и в program_commit() - program_clear()
  // тоже вызывается из commit_profile_operation() (loop()) параллельно с
  // читателями program[] из async_tcp/Blynk.
  portENTER_CRITICAL(&configMux);
  for (uint8_t i = 0; i < PROGRAM_END; i++) {
    program[i].WType = PROGRAM_TYPE_NONE;
  }
  ProgramLen = 0;
  portEXIT_CRITICAL(&configMux);
}

inline size_t program_trim_line_right(char* line) {
  size_t lineLen = strlen(line);
  while (lineLen > 0 && (line[lineLen - 1] == '\r' || line[lineLen - 1] == ' ' || line[lineLen - 1] == '\t')) {
    line[--lineLen] = '\0';
  }
  return lineLen;
}

inline size_t program_count_char(const char* text, char needle) {
  size_t count = 0;
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
         parse_bounded_long(tokDevType, 0, UINT8_MAX, devType).ok() &&
         parse_bounded_long(tokSpeed, LONG_MIN, LONG_MAX, speed).ok() &&
         parse_bounded_long(tokOnTime, 0, UINT16_MAX, onTime).ok() &&
         parse_bounded_long(tokOffTime, 0, UINT16_MAX, offTime).ok();
}

inline bool program_validate_beer_row_semantics(
    ProgramType type,
    float temp,
    float timeMin,
    long devType,
    long speed,
    long onTime,
    long offTime,
    long sensor,
    const char*& errorMessage) {
  (void)sensor;
  const bool noDevice = devType == 0 && speed == 0 && onTime == 0 && offTime == 0;
  const bool zeroTempTime = temp == 0.0f && timeMin == 0.0f;
  const bool validDeviceMask = devType >= 1 && devType <= 3;
  const bool validDeviceSchedule = validDeviceMask && onTime > 0;
  const bool mixerScheduleValid = noDevice || validDeviceSchedule;
  if (!mixerScheduleValid) {
    errorMessage = "Ошибка программы: устройство должно быть 0^0^0^0 или маской 1..3 с ненулевым расписанием";
    return false;
  }
  switch (type) {
    case 'M':
    case 'C':
    case 'F':
      if (temp > 0.0f && timeMin == 0.0f) return true;
      errorMessage = "Ошибка программы: для типа M/C/F Temp больше 0 и Time=0";
      return false;
    case 'P':
      if (temp > 0.0f && timeMin > 0.0f) return true;
      errorMessage = "Ошибка программы: для типа P Temp и Time должны быть больше 0";
      return false;
    case 'B':
      if (temp == 0.0f && timeMin > 0.0f) return true;
      errorMessage = "Ошибка программы: для типа B Temp=0 и Time больше 0";
      return false;
    case 'W':
      if (zeroTempTime) return true;
      errorMessage = "Ошибка программы: для типа W Temp=0 и Time=0";
      return false;
    case 'L':
#ifdef USE_LUA
      if (zeroTempTime && noDevice && sensor == 0) return true;
      errorMessage = "Ошибка программы: для типа L нужны нулевые параметры";
#else
      errorMessage = "Ошибка программы: тип L требует USE_LUA";
#endif
      return false;
    case 'A':
      if (temp > 0.0f && timeMin == 0.0f && noDevice) return true;
      errorMessage = "Ошибка программы: для типа A Temp больше 0, Time=0 и устройство=0^0^0^0";
      return false;
    default:
      errorMessage = "Ошибка программы: неизвестный тип beer";
      return false;
  }
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
            parse_bounded_long(tokVolume, 0, UINT16_MAX, volume).ok() &&
            parse_bounded_float(tokSpeed, PROGRAM_RATE_MIN, PROGRAM_RATE_MAX, speed).ok() &&
            parse_bounded_long(tokCap, 0, CAPACITY_NUM, cap).ok() &&
            parse_bounded_float(tokTemp, PROGRAM_TEMP_MIN, PROGRAM_TEMP_MAX, temp).ok() &&
            parse_bounded_float(tokPower, PROGRAM_POWER_MIN, PROGRAM_POWER_MAX, power).ok();

  if (ok && parsedType != 'P' && speed <= 0.0f) ok = false;
  if (ok && parsedType == 'P' && volume <= 0) ok = false;
  // [Ф2] Строка отбора без объёма и температуры не завершится никогда (переход по
  // объёму требует цель != 0). validate_rect_program_startable() ловит это только при
  // старте - строка, сохранённая уже во время отбора, проходила мимо.
  if (ok && parsedType != 'P' && volume <= 0 && temp <= 0.0f) ok = false;
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

inline bool program_parse_dist_row(char* line, size_t, uint8_t, WProgram& row, const ProgramParseSpec& spec, const char*& errorMessage) {
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
            parse_bounded_float(tokSpeed, PROGRAM_DIST_THRESHOLD_MIN, PROGRAM_DIST_THRESHOLD_MAX, speed).ok() &&
            parse_bounded_long(tokCap, 0, CAPACITY_NUM, cap).ok() &&
            parse_bounded_float(tokPower, PROGRAM_POWER_MIN, PROGRAM_POWER_MAX, power).ok();

  // Типозависимое сужение общих границ PROGRAM_DIST_THRESHOLD_*: поле Speed
  // хранит разный физический смысл в зависимости от WType (см. комментарий выше).
  if (ok && (parsedType == 'S' || parsedType == 'R') && (speed <= 0.0f || speed >= 1.0f)) {
    errorMessage = "Ошибка программы: для типа S/R Speed должен быть в диапазоне (0,1)";
    ok = false;
  }
  if (ok && (parsedType == 'A' || parsedType == 'P') && speed >= 100.0f) {
    errorMessage = "Ошибка программы: для типа A/P Speed должен быть в диапазоне [0,100)";
    ok = false;
  }
  if (ok && parsedType == 'T' && speed <= 0.0f) {
    errorMessage = "Ошибка программы: для типа T Speed должен быть в диапазоне (0,150]";
    ok = false;
  }

  if (!ok) return false;

  row.WType = parsedType;
  row.Speed = speed;
  row.capacity_num = (uint8_t)cap;
  row.Power = power;
  return true;
}

inline bool program_parse_beer_row(char* line, size_t lineLen, uint8_t, WProgram& row, const ProgramParseSpec& spec, const char*& errorMessage) {
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
  bool ok = parse_program_type(tokType, spec.allowedTypes, parsedType) &&
            tokTemp && tokTime && tokDevice && tokSensor &&
            !tokExtra &&
            parse_bounded_float(tokTemp, PROGRAM_TEMP_MIN, PROGRAM_TEMP_MAX, temp).ok() &&
            parse_bounded_float(tokTime, PROGRAM_TIME_MIN, PROGRAM_TIME_MAX, timeMin).ok() &&
            parse_bounded_long(tokSensor, 0, 4, sensor).ok();

  long devType = 0;
  long speed = 0;
  long onTime = 0;
  long offTime = 0;
  if (ok && !program_parse_beer_device(tokDevice, devType, speed, onTime, offTime)) {
    errorMessage = "Ошибка программы: неверный шаблон устройства beer";
    ok = false;
  }

  if (ok && !program_validate_beer_row_semantics(
      parsedType, temp, timeMin, devType, speed, onTime, offTime, sensor, errorMessage)) {
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
            parse_bounded_float(tokSpeed, PROGRAM_RATE_MIN, PROGRAM_RATE_MAX, speed).ok() &&
            parse_bounded_float(tokPower, PROGRAM_POWER_MIN, PROGRAM_POWER_MAX, power).ok();

  if (!ok) return false;

  row.WType = parsedType;
  row.Speed = speed;
  row.Power = power;
  return true;
}

inline ProgramParseResult program_parse_lines(
    const String& text,
    const ProgramParseSpec& spec,
    ProgramDraft& draft) {
  program_reset_draft(draft);

  if (text.length() == 0) {
    return program_parse_result(
        PROGRAM_PARSE_EMPTY_INPUT,
        0,
        "Пустая программа: используйте явную очистку");
  }
  if (text.length() > MAX_PROGRAM_INPUT_LEN) {
    return program_parse_result(PROGRAM_PARSE_INPUT_TOO_LONG, 0, spec.tooLongMessage);
  }

  char input[MAX_PROGRAM_INPUT_LEN + 1] = {0};
  copyStringSafe(input, text);

  uint8_t i = 0;
  uint16_t lineNumber = 1;
  char* cursor = input;
  while (*cursor != '\0') {
    char* line = cursor;
    char* newline = strchr(cursor, '\n');
    if (newline) {
      *newline = '\0';
      cursor = newline + 1;
    } else {
      cursor += strlen(cursor);
    }

    size_t lineLen = program_trim_line_right(line);
    if (lineLen == 0) {
      lineNumber++;
      continue;
    }

    if (i >= spec.maxRows || i >= PROGRAM_END) {
      return program_parse_result(
          PROGRAM_PARSE_TOO_MANY_ROWS,
          lineNumber,
          spec.tooManyRowsMessage);
    }

    if (spec.fieldCount == 0 ||
        program_count_char(line, ';') != static_cast<size_t>(spec.fieldCount - 1)) {
      return program_parse_result(
          PROGRAM_PARSE_INVALID_ROW,
          lineNumber,
          spec.invalidFormatMessage);
    }

    const char* rowErrorMessage = nullptr;
    if (!spec.parseRow(line, lineLen, i, draft.rows[i], spec, rowErrorMessage)) {
      return program_parse_result(
          PROGRAM_PARSE_INVALID_ROW,
          lineNumber,
          rowErrorMessage ? rowErrorMessage : spec.invalidFormatMessage);
    }

    i++;
    lineNumber++;
  }
  draft.len = i;

  if (i == 0) {
    return program_parse_result(
        PROGRAM_PARSE_EMPTY_INPUT,
        0,
        "Пустая программа: используйте явную очистку");
  }

  if (spec.expectedRowCount > 0 && i != spec.expectedRowCount) {
    return program_parse_result(
        PROGRAM_PARSE_WRONG_ROW_COUNT,
        lineNumber,
        spec.finalCountMessage);
  }

  (void)spec.fields;
  return program_parse_result(PROGRAM_PARSE_OK, 0, nullptr);
}

inline ProgramParseResult program_parse_lines(
    const String& text,
    const ProgramParseSpec& spec) {
  ProgramDraft draft{};
  ProgramParseResult result = program_parse_lines(text, spec, draft);
  if (result.ok()) {
    program_commit(draft);
  }
  return result;
}

inline String program_serialize_rows(uint8_t start, uint8_t end, ProgramRowSerializer serializer) {
  // [T29] Снимок под спинлоком: String-конкатенация (аллокации) внутри
  // portENTER_CRITICAL запрещена, поэтому копируем фиксированный массив под
  // защитой, а строку собираем уже снаружи, из снимка.
  WProgram snapshot[PROGRAM_MAX];
  portENTER_CRITICAL(&configMux);
  memcpy(snapshot, program, sizeof(snapshot));
  portEXIT_CRITICAL(&configMux);
  String out = "";
  for (uint8_t i = start; i < end; i++) {
    if (program_type_empty(snapshot[i].WType)) break;
    serializer(out, snapshot[i]);
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
  out += (String)row.Time + ";";
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
    "Ошибка программы: слишком много строк rect",
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
    "Ошибка программы: слишком много строк dist",
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
    "Ошибка программы: слишком много строк beer",
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
    "Ошибка программы: слишком много строк nbk",
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

inline const ProgramParseSpec* program_parse_spec_for_mode(SAMOVAR_MODE mode) {
  switch (program_format_for_mode(mode)) {
    case PROGRAM_FORMAT_RECT:
      return &rect_program_parse_spec();
    case PROGRAM_FORMAT_DIST:
      return &dist_program_parse_spec();
    case PROGRAM_FORMAT_BEER:
      return &beer_program_parse_spec();
    case PROGRAM_FORMAT_NBK:
      return &nbk_program_parse_spec();
    case PROGRAM_FORMAT_UNSUPPORTED:
    default:
      return nullptr;
  }
}

// [П1 доп.] program_parse_lines() пропускает пустые строки исходного текста,
// наращивая lineNumber БЕЗ увеличения индекса i (см. цикл там же) - поэтому
// индекс draft.rows[i] не совпадает с физическим номером строки, если в
// программе есть пустые строки. Хелпер повторяет тот же проход по тексту
// (то же условие "пустая": program_trim_line_right - обрезка '\r'/' '/'\t'
// справа, длина 0) только для диагностики; сам разбор не трогает.
inline uint16_t program_physical_line_for_row(const String& text, uint8_t rowIndex) {
  const char* cursor = text.c_str();
  uint16_t lineNumber = 1;
  uint8_t seen = 0;
  while (*cursor != '\0') {
    const char* line = cursor;
    const char* newline = strchr(cursor, '\n');
    size_t lineLen = newline ? static_cast<size_t>(newline - line) : strlen(line);
    cursor = newline ? newline + 1 : cursor + lineLen;
    while (lineLen > 0 && (line[lineLen - 1] == '\r' || line[lineLen - 1] == ' ' || line[lineLen - 1] == '\t')) {
      lineLen--;
    }
    if (lineLen == 0) {
      lineNumber++;
      continue;
    }
    if (seen == rowIndex) {
      return lineNumber;
    }
    seen++;
    lineNumber++;
  }
  return lineNumber;
}

inline ProgramParseResult prepare_program_for_mode(
    SAMOVAR_MODE mode,
    const String& text,
    ProgramDraft& draft) {
  const ProgramParseSpec* spec = program_parse_spec_for_mode(mode);
  if (!spec) {
    program_reset_draft(draft);
    return program_parse_result(
        PROGRAM_PARSE_UNSUPPORTED_MODE,
        0,
        "Ошибка программы: неподдерживаемый режим");
  }
  ProgramParseResult result = program_parse_lines(text, *spec, draft);
#ifdef SAMOVAR_USE_POWER
  // [Б7.2] Только ректификация: check_alarm() (alarm.h) в момент окончания разгона
  // безусловно применяет apply_program_power_row(program[0].Power) - первая строка
  // обязана задавать АБСОЛЮТНУЮ уставку, иначе колонна останется на полной мощности
  // разгона. Условие эквивалентно ветке "абсолют" в apply_program_power_row():
  // порог положителен, поэтому "abs(power) > порог && power > 0" совпадает с
  // "power > порог". БК и Lua делят тот же формат строки, но к этому переходу
  // программу не привязывают - их не проверяем.
  if (result.ok() && mode == SAMOVAR_RECTIFICATION_MODE && draft.len > 0 &&
      !(draft.rows[0].Power > PROGRAM_POWER_ABS_THRESHOLD)) {
    program_reset_draft(draft);
    result = program_parse_result(
        PROGRAM_PARSE_INVALID_ROW,
        1,
        "Ошибка программы: первая строка должна задавать абсолютную мощность/напряжение (иначе колонна останется на полной мощности разгона)");
  }
  // [П1] Дистилляция: правило устроено иначе, чем в ректификации. run_dist_program()
  // применяет program[i].Power не при старте строки i, а в момент, когда СРАБОТАЛО
  // её условие (переход i -> i+1, distiller.h::run_dist_program()). Строка с
  // Power == 0 регулятор не трогает (apply_program_power_row(0) - no-op), поэтому
  // регулятор может оставаться в разгоне (target_power_volt == 0) сколько угодно
  // строк подряд. Опасен именно ПЕРВЫЙ вызов apply_program_power_row() с ненулевым
  // Power: если это поправка (|Power| <= порога), она считается от target_power_volt,
  // который в разгоне ещё 0, и итог уходит ниже порога WORK/SLEEP - нагрев молча
  // гаснет при PowerOn == true. Программа, где Power == 0 у ВСЕХ строк, не
  // проверяется - разгон длится весь процесс, это штатный случай (встроенный дефолт
  // sensorinit.h именно такой).
  if (result.ok() && mode == SAMOVAR_DISTILLATION_MODE) {
    for (uint8_t i = 0; i < draft.len; i++) {
      if (draft.rows[i].Power == 0.0f) continue;
      if (!(draft.rows[i].Power > PROGRAM_POWER_ABS_THRESHOLD)) {
        program_reset_draft(draft);
        result = program_parse_result(
            PROGRAM_PARSE_INVALID_ROW,
            program_physical_line_for_row(text, i),
            "Ошибка программы: первая строка с ненулевым напряжением/мощностью должна задавать абсолютное значение, а не поправку (иначе нагрев в разгоне может незаметно выключиться)");
      }
      break;
    }
  }
#endif
  return result;
}

inline String serialize_program_for_mode(SAMOVAR_MODE mode) {
  switch (program_format_for_mode(mode)) {
    case PROGRAM_FORMAT_RECT:
      return program_serialize_rows(0, PROGRAM_END, program_append_rect_row);
    case PROGRAM_FORMAT_DIST:
      return program_serialize_rows(0, PROGRAM_END, program_append_dist_row);
    case PROGRAM_FORMAT_BEER:
      return program_serialize_rows(0, PROGRAM_END, program_append_beer_row);
    case PROGRAM_FORMAT_NBK:
      return program_serialize_rows(0, PROGRAM_END, program_append_nbk_row);
    case PROGRAM_FORMAT_UNSUPPORTED:
    default:
      return String();
  }
}
