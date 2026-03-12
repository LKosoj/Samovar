#ifndef __SAMOVAR_STATUS_TEXT_H_
#define __SAMOVAR_STATUS_TEXT_H_

#include <Arduino.h>

#include "modes/beer/beer_support.h"
#include "state/globals.h"
#include "support/format_utils.h"
#include "support/process_math.h"

inline String get_Samovar_Status() {
  SamovarStatus.clear();
  // Если питание выключено и нет активного режима - показываем "Выключено"
  if (!PowerOn && SamovarStatusInt == 0) {
    SamovarStatus = F("Выключено");
  } else if (PowerOn && startval == 1 && !PauseOn && !program_Wait) {
    SamovarStatus = "Прг №" + String(ProgramNum + 1);
    SamovarStatusInt = 10;
  } else if (PowerOn && startval == 1 && program_Wait) {
    int s = 0;
    if (t_min > (millis() + 10)) {
      s = (t_min - millis()) / 1000;
    }
    SamovarStatus = "Прг №" + String(ProgramNum + 1) + " пауза " + program_Wait_Type + ". Продолжение через " + (String)s + " сек.";
    SamovarStatusInt = 15;
  } else if (PowerOn && startval == 2) {
    SamovarStatus = F("Выполнение программы завершено");
    SamovarStatusInt = 20;
  } else if (PowerOn && startval == 100) {
    SamovarStatus = F("Калибровка");
    SamovarStatusInt = 30;
  } else if (PauseOn) {
    SamovarStatus = F("Пауза");
    SamovarStatusInt = 40;
  } else if (PowerOn && startval == 0 && !stepper.getState()) {
    if (SamovarStatusInt != 51 && SamovarStatusInt != 52) {
      SamovarStatus = F("Разгон колонны");
      SamovarStatusInt = 50;
    } else if (SamovarStatusInt == 51) {
      SamovarStatus = F("Разгон завершен. Стабилизация/Работа на себя");
    } else if (SamovarStatusInt == 52) {
      SamovarStatus = F("Стабилизация завершена/Работа на себя");
    }
  } else if (SamovarStatusInt == 1000) {
    SamovarStatus = "Прг №" + String(ProgramNum + 1) + "; Режим дистилляции";
    //SamovarStatus += "; Осталось:" + String(get_dist_remaining_time(), 1) + " мин";
    //SamovarStatus += "; Общее:" + String(get_dist_predicted_total_time(), 1) + " мин";
  } else if (SamovarStatusInt == 3000) {
    SamovarStatus = F("Режим бражной колонны");
  } else if (SamovarStatusInt == 4000) {
    if (startval == 4001) {
      SamovarStatus = "Прг №" + String(ProgramNum + 1) + "; ";
      if (program[ProgramNum].WType == "H") {
        SamovarStatus = SamovarStatus + "Прогрев";
      } else if (program[ProgramNum].WType == "S") {
        SamovarStatus = SamovarStatus + "Настройка";
      } else if (program[ProgramNum].WType == "O") {
        SamovarStatus = SamovarStatus + "Оптимизация";
      } else if (program[ProgramNum].WType == "W") {
        SamovarStatus = SamovarStatus + "Работа";
      }
    }
  } else if (SamovarStatusInt == 2000) {
#ifdef SAM_BEER_PRG
    SamovarStatus = "Прг №" + String(ProgramNum + 1) + "; ";
#else
    SamovarStatus = "";
#endif
    if (startval == 2001 && program[ProgramNum].WType == "M") {
      float currentTemp = getBeerCurrentTemp();
      SamovarStatus = SamovarStatus + "Разогрев до температуры засыпи солода";
      if (currentTemp < program[ProgramNum].Temp - 0.5) {
        SamovarStatus += "; Текущая Т: " + String(currentTemp) + "°";
      }
    } else if (startval == 2002 && program[ProgramNum].WType == "M") {
      SamovarStatus = SamovarStatus + "Ожидание засыпи солода";
    } else if (program[ProgramNum].WType == "P") {
      if (begintime == 0) {
        float currentTemp = getBeerCurrentTemp();
        SamovarStatus = SamovarStatus + "Пауза " + String(program[ProgramNum].Temp) + "°; Разогрев";
        if (currentTemp < program[ProgramNum].Temp - 0.5) {
          SamovarStatus += "; Текущая Т: " + String(currentTemp) + "°";
        }
      } else {
        SamovarStatus = SamovarStatus + "Пауза " + String(program[ProgramNum].Temp) + "°";
      }
    } else if (program[ProgramNum].WType == "C") {
      float currentTemp = getBeerCurrentTemp();
      SamovarStatus = SamovarStatus + "Охлаждение до " + String(program[ProgramNum].Temp);
      if (currentTemp > program[ProgramNum].Temp + 0.5) {
        SamovarStatus += "; Текущая Т: " + String(currentTemp) + "°";
      }
    } else if (program[ProgramNum].WType == "W") {
      SamovarStatus = SamovarStatus + "Ожидание. Нажмите 'Следующая программа'; ";
    } else if (program[ProgramNum].WType == "A") {
      SamovarStatus = SamovarStatus + "Автокалибровка. После завершения питание будет выключено";
    } else if (program[ProgramNum].WType == "B") {
      if (begintime == 0) {
        SamovarStatus = SamovarStatus + "Кипячение - нагрев";
      } else {
        SamovarStatus = SamovarStatus + "Кипячение " + String(program[ProgramNum].Time) + " мин";
      }
    } else if (program[ProgramNum].WType == "F") {
      if (PowerOn) {
        float currentTemp = getBeerCurrentTemp();
        SamovarStatus = SamovarStatus + "Ферментация; Поддерж. Т=" + String(program[ProgramNum].Temp) + "°";
        SamovarStatus += "; Тек: " + String(currentTemp) + "°";
        if (heater_state) {
          SamovarStatus += " (Нагрев)";
        } else {
          SamovarStatus += " (Термостатирование)";
        }
      } else {
        SamovarStatus = SamovarStatus + "Ферментация (остановлена)";
      }
    } else if (program[ProgramNum].WType == "L") {
      SamovarStatus = SamovarStatus + "Выполнение Lua скрипта";
    }

    if (PowerOn && (program[ProgramNum].WType == "P" || program[ProgramNum].WType == "B") && begintime > 0) {
      float progress = ((float)(millis() - begintime) / (program[ProgramNum].Time * 60 * 1000)) * 100;
      if (progress > 100) progress = 100;
      SamovarStatus += "; Прогресс: " + String(progress, 1) + "%";
    }
  }

  if (SamovarStatusInt == 10 || SamovarStatusInt == 15 || (SamovarStatusInt == 2000 && PowerOn)) {
    SamovarStatus += "; Осталось:" + WthdrwTimeS + "|" + WthdrwTimeAllS;
  }
  if (SteamSensor.BodyTemp > 0) {
    SamovarStatus += ";Т тела пар:" + format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure), 3) + ";Т тела царга:" + format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, PipeSensor.BodyTemp, bme_pressure), 3);
  }

  return SamovarStatus;
}

#endif
