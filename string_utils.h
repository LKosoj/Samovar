#pragma once

#include <Arduino.h>
#include <errno.h>
#include <stdlib.h>
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

inline bool parseLongSafe(const char* token, long& out) {
  if (!token || token[0] == '\0') return false;
  errno = 0;
  char* end = nullptr;
  long value = strtol(token, &end, 10);
  if (errno != 0 || end == token || *end != '\0') return false;
  out = value;
  return true;
}

inline bool parseFloatSafe(const char* token, float& out) {
  if (!token || token[0] == '\0') return false;
  errno = 0;
  char* end = nullptr;
  float value = strtof(token, &end);
  if (errno != 0 || end == token || *end != '\0') return false;
  out = value;
  return true;
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
