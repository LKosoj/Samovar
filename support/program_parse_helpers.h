#ifndef __SAMOVAR_PROGRAM_PARSE_HELPERS_H_
#define __SAMOVAR_PROGRAM_PARSE_HELPERS_H_

#include <Arduino.h>
#include <string.h>

#include "Samovar.h"
#include "state/globals.h"
#include "app/messages.h"

inline void program_clear() {
  for (int j = 0; j < CAPACITY_NUM * 2; j++) {
    program[j].WType = "";
  }
  ProgramLen = 0;
}

inline size_t trim_line_end(char* line) {
  size_t len = strlen(line);
  while (len > 0 && (line[len - 1] == '\r' || line[len - 1] == ' ' || line[len - 1] == '\t')) {
    line[--len] = '\0';
  }
  return len;
}

inline void program_fail(const char* msg) {
  program_clear();
  SendMsg(msg, ALARM_MSG);
}

#endif
