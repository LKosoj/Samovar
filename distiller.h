#include <Arduino.h>
#include "Samovar.h"
#include "state/globals.h"
#include "app/alarm_control.h"
#include "app/process_common.h"
#include "io/actuators.h"
#include "io/power_control.h"
#include "modes/dist/dist_runtime.h"
#include "support/safe_parse.h"
#include "support/process_math.h"

/**
 * @brief Установить программу дистилляции из строки.
 * @param WProgram Строка с программой
 */
void set_dist_program(String WProgram);

/**
 * @brief Получить текущую программу дистилляции в виде строки.
 * @return Строка с программой
 */
String get_dist_program();

/**
 * @brief Отправить сообщение пользователю.
 * @param m Текст сообщения
 * @param msg_type Тип сообщения
 */
void SendMsg(const String& m, MESSAGE_TYPE msg_type);

TimePredictor timePredictor = {0, 0, 0, 0, 0, 0, 0, 0};

void set_dist_program(String WProgram) {
  for (int j = 0; j < CAPACITY_NUM * 2; j++) {
    program[j].WType = "";
  }
  ProgramLen = 0;

  if (WProgram.length() == 0) return;
  if (WProgram.length() > MAX_PROGRAM_INPUT_LEN) {
    SendMsg("Ошибка программы: слишком длинная строка (dist)", ALARM_MSG);
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
    char* tokSpeed = strtok_r(NULL, ";", &saveTok);
    char* tokCap = strtok_r(NULL, ";", &saveTok);
    char* tokPower = strtok_r(NULL, ";", &saveTok);
    char* tokExtra = strtok_r(NULL, ";", &saveTok);

    float speed = 0;
    float power = 0;
    long cap = 0;
    bool ok = tokType && tokType[0] != '\0' &&
              tokSpeed && tokCap && tokPower &&
              !tokExtra &&
              parseFloatSafe(tokSpeed, speed) &&
              parseLongSafe(tokCap, cap) &&
              parseFloatSafe(tokPower, power) &&
              cap >= 0 && cap <= CAPACITY_NUM;

    if (!ok) {
      for (int j = 0; j < CAPACITY_NUM * 2; j++) program[j].WType = "";
      ProgramLen = 0;
      SendMsg("Ошибка программы: неверный формат строки dist", ALARM_MSG);
      return;
    }

    program[i].WType = tokType;
    program[i].Speed = speed;
    program[i].capacity_num = (uint8_t)cap;
    program[i].Power = power;

    i++;
    ProgramLen = i;
    line = strtok_r(NULL, "\n", &saveLine);
  }

  if (i < CAPACITY_NUM * 2) {
    program[i].WType = "";
  }
}

String get_dist_program() {
  String Str = "";
  int k = CAPACITY_NUM * 2;
  for (uint8_t i = 0; i < k; i++) {
    if (program[i].WType.length() == 0) {
      i = CAPACITY_NUM * 2 + 1;
    } else {
      Str += program[i].WType + ";";
      Str += (String)program[i].Speed + ";";
      Str += (String)(int)program[i].capacity_num + ";";
      Str += (String)program[i].Power + "\n";
    }
  }
  return Str;
}
