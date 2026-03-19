#ifndef __SAMOVAR_BEER_PROGRAM_CODEC_H_
#define __SAMOVAR_BEER_PROGRAM_CODEC_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"
#include "support/safe_parse.h"
#include "support/process_math.h"
#include "support/program_parse_helpers.h"

String get_beer_program() {
  String Str = "";
  int k = CAPACITY_NUM * 2;
  for (uint8_t i = 0; i < k; i++) {
    if (program[i].WType.length() == 0) {
      i = CAPACITY_NUM * 2 + 1;
    } else {
      Str += program[i].WType + ";";
      Str += (String)program[i].Temp + ";";
      Str += (String)(int)program[i].Time + ";";
      Str += (String)program[i].capacity_num + "^" + program[i].Speed + "^" + program[i].Volume + "^" + program[i].Power + ";";
      Str += (String)program[i].TempSensor + "\n";
    }
  }
  return Str;
}

void set_beer_program(String WProgram) {
  program_clear();

  if (WProgram.length() == 0) return;
  if (WProgram.length() > MAX_PROGRAM_INPUT_LEN) {
    SendMsg("Ошибка программы: слишком длинная строка (beer)", ALARM_MSG);
    return;
  }

  char input[MAX_PROGRAM_INPUT_LEN + 1] = {0};
  copyStringSafe(input, WProgram);

  int i = 0;
  char* saveLine = nullptr;
  char* line = strtok_r(input, "\n", &saveLine);
  while (line && i < CAPACITY_NUM * 2) {
    size_t lineLen = trim_line_end(line);
    if (lineLen == 0) {
      line = strtok_r(NULL, "\n", &saveLine);
      continue;
    }

    char* saveTok = nullptr;
    char* tokType = strtok_r(line, ";", &saveTok);
    char* tokTemp = strtok_r(NULL, ";", &saveTok);
    char* tokTime = strtok_r(NULL, ";", &saveTok);
    char* tokDevice = strtok_r(NULL, ";", &saveTok);
    char* tokSensor = strtok_r(NULL, ";", &saveTok);
    char* tokExtra = strtok_r(NULL, ";", &saveTok);

    float temp = 0.0f;
    float timeMin = 0.0f;
    long sensor = 0;
    bool ok = tokType && tokType[0] != '\0' &&
              tokTemp && tokTime && tokDevice && tokSensor &&
              !tokExtra &&
              parseFloatSafe(tokTemp, temp) &&
              parseFloatSafe(tokTime, timeMin) &&
              parseLongSafe(tokSensor, sensor) &&
              sensor >= 0 && sensor <= 4 &&
              timeMin >= 0.0f;

    if (!ok) {
      program_fail("Ошибка программы: неверный формат строки beer");
      return;
    }

    String device = tokDevice;
    long devType = 0;
    long speed = 0;
    long onTime = 0;
    long offTime = 0;
    ok = parseLongSafe(getValue(device, '^', 0).c_str(), devType) &&
         parseLongSafe(getValue(device, '^', 1).c_str(), speed) &&
         parseLongSafe(getValue(device, '^', 2).c_str(), onTime) &&
         parseLongSafe(getValue(device, '^', 3).c_str(), offTime) &&
         devType >= 0 && devType <= 255 &&
         onTime >= 0 && onTime <= 65535 &&
         offTime >= 0 && offTime <= 65535;

    if (!ok) {
      program_fail("Ошибка программы: неверный шаблон устройства beer");
      return;
    }

    program[i].WType = tokType;
    program[i].Temp = temp;
    program[i].Time = timeMin;
    program[i].capacity_num = (uint8_t)devType;
    program[i].Speed = (float)speed;
    program[i].Volume = (uint16_t)onTime;
    program[i].Power = (uint16_t)offTime;
    program[i].TempSensor = (uint8_t)sensor;

    i++;
    ProgramLen = i;
    line = strtok_r(NULL, "\n", &saveLine);
  }

  if (i < CAPACITY_NUM * 2) {
    program[i].WType = "";
  }
}

#endif
