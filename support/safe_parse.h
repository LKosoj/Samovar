#ifndef __SAMOVAR_SAFE_PARSE_H_
#define __SAMOVAR_SAFE_PARSE_H_

#include <Arduino.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>

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

#endif
