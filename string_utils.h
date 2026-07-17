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

/** JSON-строка (включая внешние кавычки) для вставки в <script type="application/json"> или JSON.parse. */
inline String toJsonString(const String& s) {
  String out;
  out.reserve(s.length() + 8);
  out += '"';
  for (unsigned int i = 0; i < s.length(); i++) {
    char c = s.charAt(i);
    switch (c) {
      case '\\':
        out += "\\\\";
        break;
      case '"':
        out += "\\\"";
        break;
      case '\b':
        out += "\\b";
        break;
      case '\f':
        out += "\\f";
        break;
      case '\n':
        out += "\\n";
        break;
      case '\r':
        out += "\\r";
        break;
      case '\t':
        out += "\\t";
        break;
      case '<':
        // В HTML внутри <script> последовательность "</script>" закрывает тег и ломает разбор страницы.
        out += "\\u003c";
        break;
      default:
        if ((unsigned char)c < 0x20u) {
          out += ' ';
        } else {
          out += c;
        }
        break;
    }
  }
  out += '"';
  return out;
}
