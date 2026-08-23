#pragma once

#include <Arduino.h>
#include <string.h>

#ifndef MAX_PROGRAM_INPUT_LEN
#define MAX_PROGRAM_INPUT_LEN 1024
#endif

template <size_t N>
inline void copyStringSafe(char (&dst)[N], const String& src) {
  size_t n = src.length();
  if (n >= N) n = N - 1;
  if (n > 0) {
    memcpy(dst, src.c_str(), n);
  }
  dst[n] = '\0';
}

/** Раскрытие caret-экранирования Lua-строки из /command?luastr=.
    Соглашение UI старше URL-кодирования: одиночный '^' означает пробел. Двойной '^^'
    даёт сам символ '^' — оператор возведения в степень, который иначе записать нельзя.
    Проход строго однократный: два replace() подряд свернули бы "^^" в пробел. */
inline String expandLuaCaretEscapes(const String& s) {
  String out;
  out.reserve(s.length());
  for (unsigned int i = 0; i < s.length(); i++) {
    char c = s.charAt(i);
    if (c != '^') {
      out += c;
    } else if (i + 1 < s.length() && s.charAt(i + 1) == '^') {
      out += '^';
      i++;
    } else {
      out += ' ';
    }
  }
  return out;
}

/** Записывает [text, text+length) в out как содержимое JSON-строки (без внешних кавычек):
    экранирует " \ и управляющие байты <0x20 (\b \f \n \r \t — именованно, остальные —
    \u00XX), плюс '<' -> \u003c (иначе "</script>" внутри <script>-блока рвёт HTML-страницу).
    DEL (0x7F) и байты >=0x80 (продолжения многобайтных UTF-8-последовательностей, в т.ч.
    кириллицы) не трогает - RFC 8259 требует эскейпить только U+0000..U+001F, а порезать
    байт посередине UTF-8-символа испортило бы кодировку.
    Возвращает false при первой же неполной записи в out - вызывающий код (потоковые
    ответы) обязан прервать формирование ответа. */
inline bool json_write_escaped(Print& out, const char* text, size_t length) {
  static const char hexDigits[] = "0123456789ABCDEF";
  size_t plainStart = 0;
  for (size_t index = 0; index < length; index++) {
    const char character = text[index];
    const uint8_t byte = static_cast<uint8_t>(character);
    const char* escaped = nullptr;
    size_t escapedLength = 0;
    char unicodeEscape[6];
    if (character == '"') { escaped = "\\\""; escapedLength = 2; }
    else if (character == '\\') { escaped = "\\\\"; escapedLength = 2; }
    else if (character == '<') { escaped = "\\u003c"; escapedLength = 6; }
    else if (character == '\n') { escaped = "\\n"; escapedLength = 2; }
    else if (character == '\r') { escaped = "\\r"; escapedLength = 2; }
    else if (character == '\t') { escaped = "\\t"; escapedLength = 2; }
    else if (character == '\b') { escaped = "\\b"; escapedLength = 2; }
    else if (character == '\f') { escaped = "\\f"; escapedLength = 2; }
    else if (byte < 0x20) {
      unicodeEscape[0] = '\\'; unicodeEscape[1] = 'u';
      unicodeEscape[2] = '0'; unicodeEscape[3] = '0';
      unicodeEscape[4] = hexDigits[byte >> 4];
      unicodeEscape[5] = hexDigits[byte & 0x0F];
      escaped = unicodeEscape; escapedLength = sizeof(unicodeEscape);
    }
    if (!escaped) continue;
    if (index > plainStart &&
        out.write(reinterpret_cast<const uint8_t*>(text + plainStart), index - plainStart)
            != index - plainStart) return false;
    if (out.write(reinterpret_cast<const uint8_t*>(escaped), escapedLength) != escapedLength)
      return false;
    plainStart = index + 1;
  }
  return plainStart == length ||
         out.write(reinterpret_cast<const uint8_t*>(text + plainStart), length - plainStart)
             == length - plainStart;
}

/** Тонкий Print-приёмник поверх String - мост между потоковым json_write_escaped()
    и функциями, которым нужна String (toJsonString, spiffsEditorJsonEscape).
    concat() у Arduino String атомарен: при нехватке памяти под reserve()/realloc()
    строка не трогается и concat() возвращает false, частичной записи внутри одного
    вызова concat() не бывает. Поэтому write() ниже зовёт concat() напрямую (а не
    operator+=, который этот результат отбрасывает) и честно возвращает фактическое
    число дописанных байт (0 при немедленном отказе) - toJsonString и
    spiffsEditorJsonEscape обязаны проверять возврат json_write_escaped().
    write(buffer, size) копирует данные через локальный буфер с явным нулевым байтом,
    а не зовёт String::concat(cstr, size) напрямую на чужом buffer: реальная
    String::concat(const char*, unsigned) в ядре Arduino-ESP32 (WString.cpp) всегда
    делает memcpy_P(dst, cstr, length + 1) - читает на один байт БОЛЬШЕ, чем size,
    рассчитывая на нулевой терминатор сразу после данных. write() - переопределение
    виртуального Print::write(), buffer сюда может прийти от любого вызывающего кода
    без гарантии терминатора (например, char unicodeEscape[6] в json_write_escaped
    без завершающего нуля) - без копии в терминированный буфер это было бы чтением за
    границей массива. */
class JsonStringPrint : public Print {
 public:
  explicit JsonStringPrint(String& target) : target_(target) {}
  size_t write(uint8_t value) override {
    return target_.concat(static_cast<char>(value)) ? 1 : 0;
  }
  size_t write(const uint8_t* buffer, size_t size) override {
    size_t written = 0;
    while (written < size) {
      char chunk[64];
      size_t n = size - written;
      if (n > sizeof(chunk) - 1) n = sizeof(chunk) - 1;
      memcpy(chunk, buffer + written, n);
      chunk[n] = '\0';
      if (!target_.concat(chunk, n)) break;
      written += n;
    }
    return written;
  }
 private:
  String& target_;
};

/** JSON-строка (включая внешние кавычки) для вставки в <script type="application/json"> или JSON.parse. */
inline String toJsonString(const String& s) {
  String out;
  out.reserve(s.length() + 8);
  out += '"';
  JsonStringPrint sink(out);
  if (!json_write_escaped(sink, s.c_str(), s.length())) {
    Serial.println(F("toJsonString: строка обрезана, не хватило памяти"));
  }
  out += '"';
  return out;
}
