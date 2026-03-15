#ifndef __SAMOVAR_STATUS_TEXT_H_
#define __SAMOVAR_STATUS_TEXT_H_

#include <Arduino.h>

#include "src/core/state/mode_codes.h"
#include "src/core/state/status_codes.h"
#include "modes/beer/beer_support.h"
#include "state/globals.h"
#include "support/format_utils.h"
#include "support/process_math.h"

inline String get_Samovar_Status() {
  SamovarStatus.clear();
  // Если питание выключено и нет активного режима - показываем "Выключено"
  if (!PowerOn && SamovarStatusInt == SAMOVAR_STATUS_OFF) {
    SamovarStatus = F("Выключено");
  } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING && !PauseOn && !program_Wait) {
    SamovarStatus = "Прг №" + String(ProgramNum + 1);
    SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_RUN;
  } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING && program_Wait) {
    int s = 0;
    if (t_min > (millis() + 10)) {
      s = (t_min - millis()) / 1000;
    }
    SamovarStatus = "Прг №" + String(ProgramNum + 1) + " пауза " + program_Wait_Type + ". Продолжение через " + (String)s + " сек.";
    SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_WAIT;
  } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE) {
    SamovarStatus = F("Выполнение программы завершено");
    SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_COMPLETE;
  } else if (PowerOn && startval == SAMOVAR_STARTVAL_CALIBRATION) {
    SamovarStatus = F("Калибровка");
    SamovarStatusInt = SAMOVAR_STATUS_CALIBRATION;
  } else if (PauseOn) {
    SamovarStatus = F("Пауза");
    SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_PAUSE;
  } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_IDLE && !stepper.getState()) {
    if (SamovarStatusInt != SAMOVAR_STATUS_RECTIFICATION_STABILIZING &&
        SamovarStatusInt != SAMOVAR_STATUS_RECTIFICATION_STABILIZED) {
      SamovarStatus = F("Разгон колонны");
      SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_WARMUP;
    } else if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_STABILIZING) {
      SamovarStatus = F("Разгон завершен. Стабилизация/Работа на себя");
    } else if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_STABILIZED) {
      SamovarStatus = F("Стабилизация завершена/Работа на себя");
    }
  } else if (SamovarStatusInt == SAMOVAR_STATUS_DISTILLATION) {
    SamovarStatus = "Прг №" + String(ProgramNum + 1) + "; Режим дистилляции";
    //SamovarStatus += "; Осталось:" + String(get_dist_remaining_time(), 1) + " мин";
    //SamovarStatus += "; Общее:" + String(get_dist_predicted_total_time(), 1) + " мин";
  } else if (SamovarStatusInt == SAMOVAR_STATUS_BK) {
    SamovarStatus = F("Режим бражной колонны");
  } else if (SamovarStatusInt == SAMOVAR_STATUS_NBK) {
    if (startval == SAMOVAR_STARTVAL_NBK_PROGRAM_RUNNING) {
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
  } else if (SamovarStatusInt == SAMOVAR_STATUS_BEER) {
#ifdef SAM_BEER_PRG
    SamovarStatus = "Прг №" + String(ProgramNum + 1) + "; ";
#else
    SamovarStatus = "";
#endif
    if (startval == SAMOVAR_STARTVAL_BEER_MALT_HEATING && program[ProgramNum].WType == "M") {
      float currentTemp = getBeerCurrentTemp();
      SamovarStatus = SamovarStatus + "Разогрев до температуры засыпи солода";
      if (currentTemp < program[ProgramNum].Temp - 0.5) {
        SamovarStatus += "; Текущая Т: " + String(currentTemp) + "°";
      }
    } else if (startval == SAMOVAR_STARTVAL_BEER_MALT_WAIT && program[ProgramNum].WType == "M") {
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

  if (samovar_status_has_rectification_program_progress(SamovarStatusInt) ||
      (SamovarStatusInt == SAMOVAR_STATUS_BEER && PowerOn)) {
    SamovarStatus += "; Осталось:" + WthdrwTimeS + "|" + WthdrwTimeAllS;
  }
  if (SteamSensor.BodyTemp > 0) {
    SamovarStatus += ";Т тела пар:" + format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure), 3) + ";Т тела царга:" + format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, PipeSensor.BodyTemp, bme_pressure), 3);
  }

  return SamovarStatus;
}

#endif
