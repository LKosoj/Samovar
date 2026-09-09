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

// «Speed» строки дистилляции И БК — НЕ расход, а порог перехода: целевая T куба ('T', °C),
// либо спиртуозность ('A'/'P', % об.), либо доля ('S'/'R', 0..1) — см. distiller.h.
// 0..150 покрывает температуру (потолок DistTemp), спиртуозность (<100) и доли.
// Это лишь первый грубый фильтр; точные типозависимые границы — в program_parse_threshold_fields().
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
  uint16_t textPoolLen;
  char textPool[PROGRAM_TEXT_POOL_SIZE];
};

constexpr size_t PROGRAM_DRAFT_MAX_BYTES = 1800;
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
  PROGRAM_FORMAT_BK,  // [БК п.9] БК ушла из группы RECT в собственный формат (5-е поле - Тпара)
  PROGRAM_FORMAT_CHEESE,
};

inline ProgramFormat program_format_for_mode(SAMOVAR_MODE mode) {
  switch (mode) {
    case SAMOVAR_RECTIFICATION_MODE:
    case SAMOVAR_LUA_MODE:
      return PROGRAM_FORMAT_RECT;
    case SAMOVAR_BK_MODE:
      return PROGRAM_FORMAT_BK;
    case SAMOVAR_DISTILLATION_MODE:
      return PROGRAM_FORMAT_DIST;
    case SAMOVAR_BEER_MODE:
    case SAMOVAR_SUVID_MODE:
      return PROGRAM_FORMAT_BEER;
    case SAMOVAR_NBK_MODE:
      return PROGRAM_FORMAT_NBK;
    case SAMOVAR_CHEESE_MODE:
      return PROGRAM_FORMAT_CHEESE;
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
  PROGRAM_FIELD_PARAM,
};

struct ProgramParseSpec;
using ProgramRowParser = bool (*)(char* line, size_t lineLen, uint8_t rowIndex, WProgram& row, const ProgramParseSpec& spec, const char*& errorMessage);
using ProgramRowSerializer = void (*)(String& out, const WProgram& row, const char* textPool);

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
  draft.textPoolLen = 1;
  draft.textPool[0] = '\0';
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
  memcpy(programTextPool, draft.textPool, draft.textPoolLen);
  if (draft.textPoolLen < PROGRAM_TEXT_POOL_SIZE) {
    memset(programTextPool + draft.textPoolLen, 0,
           PROGRAM_TEXT_POOL_SIZE - draft.textPoolLen);
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
  programTextPool[0] = '\0';
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

inline const char* program_lua_text(const WProgram& row, const char* textPool) {
  if (!textPool || row.LuaTextOffset >= PROGRAM_TEXT_POOL_SIZE) return "";
  return textPool + row.LuaTextOffset;
}

inline bool copy_program_lua_text(uint8_t rowIndex, char* destination, size_t destinationSize) {
  if (!destination || destinationSize == 0 || rowIndex >= ProgramLen || rowIndex >= PROGRAM_END) return false;
  bool copied = false;
  portENTER_CRITICAL(&configMux);
  const uint16_t offset = program[rowIndex].LuaTextOffset;
  if (offset > 0 && offset < PROGRAM_TEXT_POOL_SIZE) {
    const size_t length = strnlen(programTextPool + offset, PROGRAM_TEXT_POOL_SIZE - offset);
    if (length > 0 && length + 1 <= destinationSize) {
      memcpy(destination, programTextPool + offset, length + 1);
      copied = true;
    }
  }
  portEXIT_CRITICAL(&configMux);
  return copied;
}

inline int8_t program_lua_text_field_index(const ProgramParseSpec& spec) {
  for (uint8_t i = 0; i < spec.fieldCount; i++) {
    if (spec.fields[i] == PROGRAM_FIELD_BEER_DEVICE) return i;
  }
  for (uint8_t i = 0; i < spec.fieldCount; i++) {
    if (spec.fields[i] == PROGRAM_FIELD_VOLUME) {
      for (uint8_t j = 0; j < spec.fieldCount; j++) {
        if (spec.fields[j] == PROGRAM_FIELD_SPEED) return j;
      }
    }
  }
  for (uint8_t i = 0; i < spec.fieldCount; i++) {
    if (spec.fields[i] == PROGRAM_FIELD_POWER) return i;
  }
  return -1;
}

inline bool program_validate_lua_text(const char* text) {
  if (!text || !*text) return false;
  const char* separator = strchr(text, '^');
  const size_t fileLen = separator ? static_cast<size_t>(separator - text) : strlen(text);
  if (fileLen < 5 || strncmp(text + fileLen - 4, ".lua", 4) != 0) return false;
  const char* argument = separator;
  while (argument) {
    argument++;
    const char* next = strchr(argument, '^');
    const size_t length = next ? static_cast<size_t>(next - argument) : strlen(argument);
    if (length == 0) return false;
    argument = next;
  }
  return true;
}

inline bool program_store_lua_text(
    const char* line,
    const ProgramParseSpec& spec,
    WProgram& row,
    ProgramDraft& draft,
    const char*& errorMessage) {
  const int8_t targetField = program_lua_text_field_index(spec);
  if (targetField < 0) return false;
  const char* start = line;
  for (int8_t i = 0; i < targetField; i++) {
    start = strchr(start, ';');
    if (!start) return false;
    start++;
  }
  const char* end = strchr(start, ';');
  const size_t length = end ? static_cast<size_t>(end - start) : strlen(start);
  if (length == 0 || draft.textPoolLen + length + 1 > PROGRAM_TEXT_POOL_SIZE) {
    errorMessage = "Ошибка программы: текст Lua пуст или слишком длинный";
    return false;
  }
  const uint16_t offset = draft.textPoolLen;
  memcpy(draft.textPool + offset, start, length);
  draft.textPool[offset + length] = '\0';
  if (!program_validate_lua_text(draft.textPool + offset)) {
    errorMessage = "Ошибка программы: укажите файл .lua; пустой аргумент задаётся как \"\"";
    return false;
  }
  row.LuaTextOffset = offset;
  draft.textPoolLen += length + 1;
  return true;
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
      if (temp == 0.0f && timeMin > 0.0f && noDevice && sensor == 0) return true;
      errorMessage = "Ошибка программы: для типа L нужен тайм-аут и нулевые параметры";
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
            !tokExtra;
  if (ok && parsedType == 'L') {
    ok = row.LuaTextOffset > 0 &&
         parse_bounded_long(tokVolume, 1, UINT16_MAX, volume).ok() &&
         parse_bounded_long(tokCap, 0, 0, cap).ok() &&
         parse_bounded_float(tokTemp, 0.0f, 0.0f, temp).ok() &&
         parse_bounded_float(tokPower, 0.0f, 0.0f, power).ok();
    if (!ok) return false;
    row.WType = parsedType;
    row.Volume = static_cast<uint16_t>(volume);
    row.Time = static_cast<float>(volume);
    return true;
  }
  ok = ok &&
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

inline bool program_parse_threshold_lua_row(
    char* line, bool hasSteamField, WProgram& row, const char*& errorMessage) {
  char* saveTok = nullptr;
  char* tokType = strtok_r(line, ";", &saveTok);
  char* tokTimeout = strtok_r(nullptr, ";", &saveTok);
  char* tokCap = strtok_r(nullptr, ";", &saveTok);
  char* tokText = strtok_r(nullptr, ";", &saveTok);
  char* tokSteam = hasSteamField ? strtok_r(nullptr, ";", &saveTok) : nullptr;
  char* tokExtra = strtok_r(nullptr, ";", &saveTok);
  long timeout = 0;
  long cap = 0;
  float steam = 0.0f;
  const bool ok = tokType && tokType[0] == 'L' && tokType[1] == '\0' &&
      tokTimeout && tokCap && tokText && row.LuaTextOffset > 0 && !tokExtra &&
      parse_bounded_long(tokTimeout, 1, UINT16_MAX, timeout).ok() &&
      parse_bounded_long(tokCap, 0, 0, cap).ok() &&
      (!hasSteamField || (tokSteam &&
       parse_bounded_float(tokSteam, 0.0f, 0.0f, steam).ok()));
  if (!ok) {
    errorMessage = "Ошибка программы: для L нужен тайм-аут 1..65535 секунд и нулевые числовые поля";
    return false;
  }
  row.WType = 'L';
  row.Time = static_cast<float>(timeout);
  row.Speed = static_cast<float>(timeout);
  return true;
}

// Общий разбор первых четырёх полей "Тип;Порог;Ёмкость;Мощность" для DIST и БК
// (program_parse_dist_row/program_parse_bk_row) - границы и типозависимое
// сужение (S/R/A/P/T) идентичны для обоих форматов, поэтому вынесены сюда,
// а не скопированы. saveTok выставлен СРАЗУ ПОСЛЕ поля "Мощность" - у DIST
// дальше полей нет, у БК есть пятое поле "Тпара"; чей это токен - решает
// вызывающая сторона через тот же saveTok. [БК п.9]
inline bool program_parse_threshold_fields(
    char* line,
    char*& saveTok,
    const ProgramParseSpec& spec,
    ProgramType& parsedType,
    float& speed,
    long& cap,
    float& power,
    const char*& errorMessage) {
  char* tokType = strtok_r(line, ";", &saveTok);
  char* tokSpeed = strtok_r(nullptr, ";", &saveTok);
  char* tokCap = strtok_r(nullptr, ";", &saveTok);
  char* tokPower = strtok_r(nullptr, ";", &saveTok);

  parsedType = PROGRAM_TYPE_NONE;
  speed = 0;
  cap = 0;
  power = 0;
  bool ok = parse_program_type(tokType, spec.allowedTypes, parsedType) &&
            tokSpeed && tokCap && tokPower &&
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
  return ok;
}

inline bool program_parse_dist_row(char* line, size_t, uint8_t, WProgram& row, const ProgramParseSpec& spec, const char*& errorMessage) {
  if (line[0] == 'L' && line[1] == ';') {
    return program_parse_threshold_lua_row(line, false, row, errorMessage);
  }
  char* saveTok = nullptr;
  ProgramType parsedType = PROGRAM_TYPE_NONE;
  float speed = 0;
  long cap = 0;
  float power = 0;
  bool ok = program_parse_threshold_fields(line, saveTok, spec, parsedType, speed, cap, power, errorMessage);

  // [Сохранение поведения] fieldCount==4 у DIST уже отбивает 5-е поле ДО вызова
  // parseRow (program_count_char(';') сверяется в program_parse_lines) - этот
  // strtok_r практически недостижим в проде, но был в оригинале (как !tokExtra
  // в общей ok-цепочке ДО типозависимого сужения) - errorMessage=nullptr вместо
  // текста сужения воспроизводит тот же порядок: extra-токен раньше гасил ok
  // до того, как сужение успевало записать свой текст. [БК п.9]
  char* tokExtra = strtok_r(nullptr, ";", &saveTok);
  if (tokExtra) {
    ok = false;
    errorMessage = nullptr;
  }

  if (!ok) return false;

  row.WType = parsedType;
  row.Speed = speed;
  row.capacity_num = (uint8_t)cap;
  row.Power = power;
  return true;
}

// [БК п.9] Формат БК = формат DIST + пятое поле "Тпара" (уставка воды дефлегматора,
// °C): 0 - вручную, иначе строго BK_STEAM_SETPOINT_MIN..MAX (Samovar_ini.h).
// Первые четыре поля - через общий program_parse_threshold_fields, без копии.
inline bool program_parse_bk_row(char* line, size_t, uint8_t, WProgram& row, const ProgramParseSpec& spec, const char*& errorMessage) {
  if (line[0] == 'L' && line[1] == ';') {
    return program_parse_threshold_lua_row(line, true, row, errorMessage);
  }
  char* saveTok = nullptr;
  ProgramType parsedType = PROGRAM_TYPE_NONE;
  float speed = 0;
  long cap = 0;
  float power = 0;
  bool ok = program_parse_threshold_fields(line, saveTok, spec, parsedType, speed, cap, power, errorMessage);

  char* tokTemp = strtok_r(nullptr, ";", &saveTok);
  char* tokExtra = strtok_r(nullptr, ";", &saveTok);
  float temp = 0.0f;
  // 0 - вода дефлегматора вручную; иначе строго BK_STEAM_SETPOINT_MIN..MAX.
  bool tempOk = ok && tokTemp && !tokExtra &&
      parse_bounded_float(tokTemp, 0.0f, BK_STEAM_SETPOINT_MAX, temp).ok() &&
      (temp == 0.0f || temp >= BK_STEAM_SETPOINT_MIN);
  if (ok && !tempOk) {
    errorMessage = "Ошибка программы: Т пара: 0 или 30..100";
    ok = false;
  }

  if (!ok) return false;

  row.WType = parsedType;
  row.Speed = speed;
  row.capacity_num = (uint8_t)cap;
  row.Power = power;
  row.Temp = temp;
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
            !tokExtra;
  if (ok && parsedType == 'L') {
    long timeout = 0;
    ok = row.LuaTextOffset > 0 &&
         parse_bounded_float(tokTemp, 0.0f, 0.0f, temp).ok() &&
         parse_bounded_long(tokTime, 1, UINT16_MAX, timeout).ok() &&
         parse_bounded_long(tokSensor, 0, 0, sensor).ok();
    if (!ok) {
      errorMessage = "Ошибка программы: для L нужен тайм-аут 1..65535 секунд и нулевые числовые поля";
      return false;
    }
    row.WType = parsedType;
    row.Time = static_cast<float>(timeout);
    return true;
  }
  ok = ok &&
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

inline bool program_validate_cheese_row_semantics(
    ProgramType type,
    float temp,
    float timeMin,
    long devType,
    long speed,
    long onTime,
    long offTime,
    long sensor,
    float param,
    const char*& errorMessage) {
  // Сыр: TYPE;VALUE1;VALUE2;VALUE3;MIXER;VALUE4.
  //
  // Контракт WProgram для каждой строки:
  // H: Temp=цель °C, Time=тайм-аут мин, Param=скорость нагрева °C/мин,
  //    TempSensor=датчик температуры.
  // P: Temp=цель °C, Time=выдержка мин, Param=общий тайм-аут мин (не меньше
  //    выдержки), TempSensor=датчик температуры.
  // C: Temp=цель °C, Time=тайм-аут мин, Param=0, TempSensor=датчик температуры.
  // M: Temp=0, Time=длительность мин, Param=0, TempSensor=0.
  // D: Temp=объём мл, Time=тайм-аут мин, Param=код компонента (ручное) либо
  //    скорость мл/мин (локальное), TempSensor=1 (ручное) или 2 (локальное).
  // N: Temp=температура °C, Time=тайм-аут мин, Param=целевой pH,
  //    TempSensor=датчик температуры.
  // W: Temp=0, Time=тайм-аут мин, Param=код ручного действия, TempSensor=0.
  // S/L: Temp=0, Time=тайм-аут мин, Param=0, TempSensor=0.
  // Во всех строках MIXER переводится одинаково: capacity_num=устройство,
  // Speed=RPM и направление, Volume=ON сек, Power=OFF сек.
  const bool noDevice = devType == 0 && speed == 0 && onTime == 0 && offTime == 0;
  const bool validSchedule = (onTime == 0 && offTime == 0) || onTime > 0;
  const bool validRelayMixer = devType == 1 && speed == 0 && validSchedule;
  const bool validI2cMixer = devType == 2 && speed >= INT16_MIN && speed <= INT16_MAX &&
      speed != 0 && validSchedule;
  if (!noDevice && !validRelayMixer && !validI2cMixer) {
    errorMessage = "Ошибка программы: мешалка должна быть 0^0^0^0, реле 1^0 или I2C 2 с ненулевым RPM";
    return false;
  }
  switch (type) {
    case 'H':
      if (temp > 0.0f && temp <= PROGRAM_TEMP_MAX && timeMin > 0.0f &&
          param > 0.0f && sensor >= 0 && sensor <= 4) return true;
      errorMessage = "Ошибка программы: для H нужны Temp, Time, скорость нагрева и датчик";
      return false;
    case 'P':
      if (temp > 0.0f && temp <= PROGRAM_TEMP_MAX && timeMin > 0.0f &&
          param >= timeMin && sensor >= 0 && sensor <= 4) return true;
      errorMessage = "Ошибка программы: для P нужен датчик и Param не меньше Time";
      return false;
    case 'C':
      if (temp > 0.0f && temp <= PROGRAM_TEMP_MAX && timeMin > 0.0f &&
          param == 0.0f && sensor >= 0 && sensor <= 4) return true;
      errorMessage = "Ошибка программы: для C нужны Temp, Time, датчик и Param=0";
      return false;
    case 'M':
      if (temp == 0.0f && timeMin > 0.0f && param == 0.0f && sensor == 0 && !noDevice) return true;
      errorMessage = "Ошибка программы: для M нужны Time, мешалка и нулевые Temp/Param/датчик";
      return false;
    case 'D':
      if (temp > 0.0f && timeMin > 0.0f && param > 0.0f &&
          (sensor == 1 || sensor == 2) &&
          (sensor == 2 || param == (float)(uint8_t)param) &&
          (sensor == 2 || param <= 8.0f)) return true;
      errorMessage = "Ошибка программы: для D нужны объём, Time, способ и код 1..8 либо скорость";
      return false;
    case 'N':
      if (temp > 0.0f && temp <= PROGRAM_TEMP_MAX && timeMin > 0.0f &&
          param > 0.0f && param <= 14.0f && sensor >= 0 && sensor <= 4) return true;
      errorMessage = "Ошибка программы: для N нужны Temp, Time, pH 0..14 и датчик";
      return false;
    case 'W':
      if (temp == 0.0f && timeMin > 0.0f && param >= 1.0f && param <= 8.0f &&
          param == (float)(uint8_t)param && sensor == 0) return true;
      errorMessage = "Ошибка программы: для W нужны Time, код действия 1..8 и TempSensor=0";
      return false;
    case 'S':
      if (temp == 0.0f && timeMin > 0.0f && param == 0.0f && noDevice && sensor == 0) return true;
      errorMessage = "Ошибка программы: для S нужны безопасные выходы, Time и нулевые поля";
      return false;
    case 'L':
      if (temp == 0.0f && timeMin > 0.0f && param == 0.0f && noDevice && sensor == 0) return true;
      errorMessage = "Ошибка программы: для L нужны безопасные выходы, Time и нулевые поля";
      return false;
    default:
      errorMessage = "Ошибка программы: неизвестный тип cheese";
      return false;
  }
}

inline bool program_parse_cheese_row(char* line, size_t, uint8_t, WProgram& row, const ProgramParseSpec& spec, const char*& errorMessage) {
  char* saveTok = nullptr;
  char* tokType = strtok_r(line, ";", &saveTok);
  char* tokTemp = strtok_r(nullptr, ";", &saveTok);
  char* tokTime = strtok_r(nullptr, ";", &saveTok);
  char* tokParam = strtok_r(nullptr, ";", &saveTok);
  char* tokDevice = strtok_r(nullptr, ";", &saveTok);
  char* tokSensor = strtok_r(nullptr, ";", &saveTok);
  char* tokExtra = strtok_r(nullptr, ";", &saveTok);

  ProgramType parsedType = PROGRAM_TYPE_NONE;
  float temp = 0.0f;
  float timeMin = 0.0f;
  float param = 0.0f;
  long sensor = 0;
  bool ok = parse_program_type(tokType, spec.allowedTypes, parsedType) &&
            tokTemp && tokTime && tokDevice && tokSensor && tokParam && !tokExtra;
  if (ok && parsedType == 'L') {
    long timeout = 0;
    ok = row.LuaTextOffset > 0 &&
         parse_bounded_float(tokTemp, 0.0f, 0.0f, temp).ok() &&
         parse_bounded_long(tokTime, 1, UINT16_MAX, timeout).ok() &&
         parse_bounded_float(tokParam, 0.0f, 0.0f, param).ok() &&
         parse_bounded_long(tokSensor, 0, 0, sensor).ok();
    if (!ok) {
      errorMessage = "Ошибка программы: для L нужен тайм-аут 1..65535 секунд и нулевые числовые поля";
      return false;
    }
    row.WType = parsedType;
    row.Time = static_cast<float>(timeout);
    return true;
  }
  ok = ok &&
            parse_bounded_float(tokTemp, PROGRAM_TEMP_MIN, (float)UINT16_MAX, temp).ok() &&
            parse_bounded_float(tokTime, PROGRAM_TIME_MIN, PROGRAM_TIME_MAX, timeMin).ok() &&
            parse_bounded_long(tokSensor, 0, 4, sensor).ok() &&
            parse_bounded_float(tokParam, 0.0f, PROGRAM_TIME_MAX, param).ok();

  long devType = 0;
  long speed = 0;
  long onTime = 0;
  long offTime = 0;
  if (ok && !program_parse_beer_device(tokDevice, devType, speed, onTime, offTime)) {
    errorMessage = "Ошибка программы: неверный шаблон устройства cheese";
    ok = false;
  }
  if (ok && !program_validate_cheese_row_semantics(
      parsedType, temp, timeMin, devType, speed, onTime, offTime,
      sensor, param, errorMessage)) {
    ok = false;
  }
  if (!ok) return false;

  row.WType = parsedType;
  row.Temp = temp;
  row.Time = timeMin;
  row.capacity_num = (uint8_t)devType;
  row.Speed = (float)speed;
  row.Volume = (uint16_t)onTime;
  row.Power = (float)offTime;
  row.TempSensor = (uint8_t)sensor;
  row.Param = param;
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
    if (line[0] == 'L' && line[1] == ';' && strchr(spec.allowedTypes, 'L')) {
#ifndef USE_LUA
      return program_parse_result(
          PROGRAM_PARSE_INVALID_ROW, lineNumber,
          "Ошибка программы: тип L требует USE_LUA");
#else
      if (!program_store_lua_text(line, spec, draft.rows[i], draft, rowErrorMessage)) {
      return program_parse_result(
          PROGRAM_PARSE_INVALID_ROW,
          lineNumber,
          rowErrorMessage ? rowErrorMessage : spec.invalidFormatMessage);
      }
#endif
    }
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
  char textPoolSnapshot[PROGRAM_TEXT_POOL_SIZE];
  portENTER_CRITICAL(&configMux);
  memcpy(snapshot, program, sizeof(snapshot));
  memcpy(textPoolSnapshot, programTextPool, sizeof(textPoolSnapshot));
  portEXIT_CRITICAL(&configMux);
  String out = "";
  for (uint8_t i = start; i < end; i++) {
    if (program_type_empty(snapshot[i].WType)) break;
    serializer(out, snapshot[i], textPoolSnapshot);
  }
  return out;
}

inline void program_append_rect_row(String& out, const WProgram& row, const char* textPool) {
  append_program_type(out, row.WType);
  if (row.WType == 'L') {
    out += ";" + String(static_cast<uint16_t>(row.Time)) + ";";
    out += program_lua_text(row, textPool);
    out += ";0;0;0\n";
    return;
  }
  out += ";";
  out += (String)row.Volume + ";";
  out += (String)row.Speed + ";";
  out += (String)row.capacity_num + ";";
  out += (String)row.Temp + ";";
  out += (String)row.Power + "\n";
}

inline void program_append_dist_row(String& out, const WProgram& row, const char* textPool) {
  append_program_type(out, row.WType);
  if (row.WType == 'L') {
    out += ";" + String(static_cast<uint16_t>(row.Time)) + ";0;";
    out += program_lua_text(row, textPool);
    out += "\n";
    return;
  }
  out += ";";
  out += (String)row.Speed + ";";
  out += (String)(int)row.capacity_num + ";";
  out += (String)row.Power + "\n";
}

// [БК п.9] Формат БК = program_append_dist_row + пятое поле Тпара.
inline void program_append_bk_row(String& out, const WProgram& row, const char* textPool) {
  append_program_type(out, row.WType);
  if (row.WType == 'L') {
    out += ";" + String(static_cast<uint16_t>(row.Time)) + ";0;";
    out += program_lua_text(row, textPool);
    out += ";0\n";
    return;
  }
  out += ";";
  out += (String)row.Speed + ";";
  out += (String)(int)row.capacity_num + ";";
  out += (String)row.Power + ";";
  out += (String)row.Temp + "\n";
}

inline void program_append_beer_row(String& out, const WProgram& row, const char* textPool) {
  append_program_type(out, row.WType);
  if (row.WType == 'L') {
    out += ";0;" + String(static_cast<uint16_t>(row.Time)) + ";";
    out += program_lua_text(row, textPool);
    out += ";0\n";
    return;
  }
  out += ";";
  out += (String)row.Temp + ";";
  out += (String)row.Time + ";";
  out += (String)row.capacity_num + "^" + (int)row.Speed + "^" + row.Volume + "^" + (int)row.Power + ";";
  out += (String)row.TempSensor + "\n";
}

inline void program_append_cheese_row(String& out, const WProgram& row, const char* textPool) {
  append_program_type(out, row.WType);
  if (row.WType == 'L') {
    out += ";0;" + String(static_cast<uint16_t>(row.Time)) + ";0;";
    out += program_lua_text(row, textPool);
    out += ";0\n";
    return;
  }
  out += ";";
  out += String(row.Temp, 6) + ";";
  out += String(row.Time, 6) + ";";
  out += String(row.Param, 6) + ";";
  out += (String)row.capacity_num + "^" + (int)row.Speed + "^" + row.Volume + "^" + (int)row.Power + ";";
  out += (String)row.TempSensor + "\n";
}

inline void program_append_nbk_row(String& out, const WProgram& row, const char*) {
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
    "HBCTPL",
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
    "TASPRL",
    fields,
    static_cast<uint8_t>(sizeof(fields) / sizeof(fields[0])),
    PROGRAM_END,
    nullptr,
    0,
    program_parse_dist_row,
  };
  return spec;
}

// [БК п.9] fieldCount=5 (у DIST - 4): арифметическая проверка числа ';' в
// program_parse_lines сама отбивает 4-польную DIST-строку под этим spec-ом и
// 5-польную БК-строку под dist_program_parse_spec(), без доп. кода.
inline const ProgramParseSpec& bk_program_parse_spec() {
  static const ProgramFieldKind fields[] = {
    PROGRAM_FIELD_TYPE,
    PROGRAM_FIELD_SPEED,
    PROGRAM_FIELD_CAPACITY,
    PROGRAM_FIELD_POWER,
    PROGRAM_FIELD_TEMP,
  };
  static const ProgramParseSpec spec = {
    "Ошибка программы: слишком длинная строка (bk)",
    "Ошибка программы: неверный формат строки bk",
    "Ошибка программы: слишком много строк bk",
    nullptr,
    "TASPRL",
    fields,
    static_cast<uint8_t>(sizeof(fields) / sizeof(fields[0])),
    PROGRAM_END,
    nullptr,
    0,
    program_parse_bk_row,
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

inline const ProgramParseSpec& cheese_program_parse_spec() {
  static const ProgramFieldKind fields[] = {
    PROGRAM_FIELD_TYPE,
    PROGRAM_FIELD_TEMP,
    PROGRAM_FIELD_TIME,
    PROGRAM_FIELD_PARAM,
    PROGRAM_FIELD_BEER_DEVICE,
    PROGRAM_FIELD_TEMP_SENSOR,
  };
  static const ProgramParseSpec spec = {
    "Ошибка программы: слишком длинная строка (cheese)",
    "Ошибка программы: неверный формат строки cheese",
    "Ошибка программы: слишком много строк cheese",
    nullptr,
    "HPCMDNWSL",
    fields,
    static_cast<uint8_t>(sizeof(fields) / sizeof(fields[0])),
    PROGRAM_END,
    nullptr,
    0,
    program_parse_cheese_row,
  };
  return spec;
}

inline const ProgramParseSpec* program_parse_spec_for_mode(SAMOVAR_MODE mode) {
  switch (program_format_for_mode(mode)) {
    case PROGRAM_FORMAT_RECT:
      return &rect_program_parse_spec();
    case PROGRAM_FORMAT_DIST:
      return &dist_program_parse_spec();
    case PROGRAM_FORMAT_BK:
      return &bk_program_parse_spec();
    case PROGRAM_FORMAT_BEER:
      return &beer_program_parse_spec();
    case PROGRAM_FORMAT_NBK:
      return &nbk_program_parse_spec();
    case PROGRAM_FORMAT_CHEESE:
      return &cheese_program_parse_spec();
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
  // "power > порог". Lua делит тот же формат строки, но к этому переходу
  // программу не привязывает - его не проверяем. У БК теперь свой формат
  // (PROGRAM_FORMAT_BK) и своё аналогичное правило - см. блок дистилляции ниже. [БК п.9]
  if (result.ok() && mode == SAMOVAR_RECTIFICATION_MODE && draft.len > 0 &&
      draft.rows[0].WType != 'L' &&
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
  // sensorinit.h именно такой). [БК п.9] У БК теперь собственный формат
  // (PROGRAM_FORMAT_BK) с тем же правилом первой ненулевой мощности, что и у
  // дистилляции - обе исполняют переход строки одинаково (см. 9b:
  // run_bk_program по образцу run_dist_program). Lua делит формат RECT, но к
  // переходу по program[0].Power программу не привязывает - его не проверяем.
  if (result.ok() && (mode == SAMOVAR_DISTILLATION_MODE || mode == SAMOVAR_BK_MODE)) {
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
    case PROGRAM_FORMAT_BK:
      return program_serialize_rows(0, PROGRAM_END, program_append_bk_row);
    case PROGRAM_FORMAT_BEER:
      return program_serialize_rows(0, PROGRAM_END, program_append_beer_row);
    case PROGRAM_FORMAT_NBK:
      return program_serialize_rows(0, PROGRAM_END, program_append_nbk_row);
    case PROGRAM_FORMAT_CHEESE:
      return program_serialize_rows(0, PROGRAM_END, program_append_cheese_row);
    case PROGRAM_FORMAT_UNSUPPORTED:
    default:
      return String();
  }
}
