#ifndef __SAMOVAR_RECT_PROGRAM_CODEC_H_
#define __SAMOVAR_RECT_PROGRAM_CODEC_H_

#include <Arduino.h>
#include <string.h>

#include "Samovar.h"
#include "state/globals.h"
#include "support/safe_parse.h"

void SendMsg(const String& m, MESSAGE_TYPE msg_type);

inline void set_program(String WProgram) {
  for (int j = 0; j < CAPACITY_NUM * 2; j++) {
    program[j].WType = "";
  }
  ProgramLen = 0;

  if (WProgram.length() == 0) return;
  if (WProgram.length() > MAX_PROGRAM_INPUT_LEN) {
    SendMsg("Ошибка программы: слишком длинная строка (rect)", ALARM_MSG);
    return;
  }

  char input[MAX_PROGRAM_INPUT_LEN + 1] = {0};
  copyStringSafe(input, WProgram);

  int i = 0;
  char* saveLine = nullptr;
  char* line = strtok_r(input, "\n", &saveLine);
  while (line && i < CAPACITY_NUM * 2) {
    size_t lineLen = strlen(line);
    while (lineLen > 0 && (line[lineLen - 1] == '\r' || line[lineLen - 1] == ' ' || line[lineLen - 1] == '\t')) {
      line[--lineLen] = '\0';
    }
    if (lineLen == 0) {
      line = strtok_r(NULL, "\n", &saveLine);
      continue;
    }

    char* saveTok = nullptr;
    char* tokType = strtok_r(line, ";", &saveTok);
    char* tokVolume = strtok_r(NULL, ";", &saveTok);
    char* tokSpeed = strtok_r(NULL, ";", &saveTok);
    char* tokCap = strtok_r(NULL, ";", &saveTok);
    char* tokTemp = strtok_r(NULL, ";", &saveTok);
    char* tokPower = strtok_r(NULL, ";", &saveTok);
    char* tokExtra = strtok_r(NULL, ";", &saveTok);

    long volume = 0;
    long cap = 0;
    float speed = 0;
    float temp = 0;
    float power = 0;
    bool ok = tokType && tokType[0] != '\0' &&
              tokVolume && tokSpeed && tokCap && tokTemp && tokPower &&
              !tokExtra &&
              parseLongSafe(tokVolume, volume) &&
              parseFloatSafe(tokSpeed, speed) &&
              parseLongSafe(tokCap, cap) &&
              parseFloatSafe(tokTemp, temp) &&
              parseFloatSafe(tokPower, power) &&
              volume >= 0 && volume <= 65535 &&
              cap >= 0 && cap <= CAPACITY_NUM;

    if (ok && strcmp(tokType, "P") != 0 && speed <= 0.0f) {
      ok = false;
    }

    if (!ok) {
      for (int j = 0; j < CAPACITY_NUM * 2; j++) program[j].WType = "";
      ProgramLen = 0;
      SendMsg("Ошибка программы: неверный формат строки rect", ALARM_MSG);
      return;
    }

    program[i].WType = tokType;
    program[i].Volume = (uint16_t)volume;
    program[i].Speed = speed;
    program[i].capacity_num = (uint8_t)cap;
    program[i].Temp = temp;
    program[i].Power = power;
    if (program[i].WType == "P") {
      program[i].Time = program[i].Volume / 60.0f / 60.0f;
    } else {
      program[i].Time = program[i].Volume / program[i].Speed / 1000.0f;
    }

    i++;
    ProgramLen = i;
    line = strtok_r(NULL, "\n", &saveLine);
  }

  if (i < CAPACITY_NUM * 2) {
    program[i].WType = "";
  }
}

inline String get_program(uint8_t s) {
  String Str = "";
  uint8_t k = CAPACITY_NUM * 2;
  if (s == CAPACITY_NUM * 2) {
    s = 0;
  } else {
    k = s + 1;
  }
  for (uint8_t i = s; i < k; i++) {
    if (program[i].WType.length() == 0) {
      i = CAPACITY_NUM * 2 + 1;
    } else {
      Str += program[i].WType + ";";
      Str += (String)program[i].Volume + ";";
      Str += (String)program[i].Speed + ";";
      Str += (String)program[i].capacity_num + ";";
      Str += (String)program[i].Temp + ";";
      Str += (String)program[i].Power + "\n";
    }
  }
  return Str;
}

#endif
