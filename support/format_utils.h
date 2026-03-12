#ifndef __SAMOVAR_SUPPORT_FORMAT_UTILS_H_
#define __SAMOVAR_SUPPORT_FORMAT_UTILS_H_

#include <Arduino.h>

inline String format_float(float v, int d) {
  char outstr[15];
  dtostrf(v, 1, d, outstr);
  return outstr;
}

#endif
