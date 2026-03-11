#ifndef __SAMOVAR_SESSION_LOGS_H_
#define __SAMOVAR_SESSION_LOGS_H_

#include <Arduino.h>

#include "Samovar.h"
#include "SPIFFSEditor.h"
#include "modes/beer/beer_program_codec.h"
#include "modes/dist/dist_program_codec.h"
#include "modes/nbk/nbk_program_codec.h"
#include "modes/rect/rect_program_codec.h"
#include "state/globals.h"
#include "support/process_math.h"

int get_liquid_volume();
inline String format_float(float v, int d);
void SendMsg(const String& m, MESSAGE_TYPE msg_type);
inline String append_data();

inline void create_data() {
  if (fileToAppend) {
    fileToAppend.close();
  }

  //Если режим ректификация, запишем в файл текущую программу отбора
  if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
    File filePrg = SPIFFS.open("/prg.csv", FILE_WRITE);
    if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
      filePrg.println(get_program(CAPACITY_NUM * 2));
      Serial.println(get_program(CAPACITY_NUM * 2));
    } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
      filePrg.println(get_beer_program());
      Serial.println(get_beer_program());
    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
      filePrg.println(get_dist_program());
      Serial.println(get_dist_program());
    } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
      filePrg.println(get_nbk_program());
      Serial.println(get_nbk_program());
    }
    filePrg.close();
  }

  //Удаляем старый файл с архивным логом
  if (SPIFFS.exists("/data_old.csv")) {
    SPIFFS.remove("/data_old.csv");
  }
  //Переименовываем файл с логом в архивный (на всякий случай)
  if (SPIFFS.exists("/data.csv")) {
    if (fileToAppend) {
      fileToAppend.close();
    }

    SPIFFS.rename("/data.csv", "/data_old.csv");
  }
  File fileToWrite = SPIFFS.open("/data.csv", FILE_WRITE);
  String str = "Date,Steam,Pipe,Water,Tank,Pressure";
#ifdef WRITE_PROGNUM_IN_LOG
  str += ",ProgNum";
#endif
  fileToWrite.println(str);

  fileToWrite.close();

  SteamSensor.PrevTemp = 0;
  PipeSensor.PrevTemp = 0;
  WaterSensor.PrevTemp = 0;
  TankSensor.PrevTemp = 0;
  bme_prev_pressure = 0;

  fileToAppend = SPIFFS.open("/data.csv", FILE_APPEND);
  append_data();
}

inline String append_data() {
  bool w = false;
  if (!fileToAppend) {
    fileToAppend = SPIFFS.open("/data.csv", FILE_APPEND);
  }
  //Если режим ректификация и идет отбор, запишем в файл текущий статус
  STcnt++;
  if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) && STcnt > 10) {
    File fileState = SPIFFS.open("/state.csv", FILE_WRITE);
    String sapd = "P=" + String(ProgramNum + 1);
    if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
      sapd += ";V=" + String(get_liquid_volume());
    } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
      sapd += ";T=" + WthdrwTimeS;
    }
    fileState.println(sapd);
    //Serial.println(sapd);
    fileState.close();
    STcnt = 0;
  }

  //Если значения лога совпадают с предыдущим - в файл писать не будем
  if (SteamSensor.avgTemp != SteamSensor.LogPrevTemp) {
    SteamSensor.LogPrevTemp = SteamSensor.avgTemp;
    w = true;
  } else if (PipeSensor.avgTemp != PipeSensor.LogPrevTemp) {
    PipeSensor.LogPrevTemp = PipeSensor.avgTemp;
    w = true;
  } else if (WaterSensor.avgTemp != WaterSensor.LogPrevTemp) {
    WaterSensor.LogPrevTemp = WaterSensor.avgTemp;
    w = true;
  } else if (TankSensor.avgTemp != TankSensor.LogPrevTemp) {
    TankSensor.LogPrevTemp = TankSensor.avgTemp;
    w = true;
  } else if (bme_prev_pressure != bme_pressure) {
    bme_prev_pressure = bme_pressure;
    w = true;
#ifdef WRITE_PROGNUM_IN_LOG
  } else if (prev_ProgramNum != ProgramNum) {
    prev_ProgramNum = ProgramNum;
    w = true;
#endif
  }

  if (w) {
    String str;
    str = Crt + ",";
    str += format_float(SteamSensor.avgTemp, 3);
    str += ",";
    str += format_float(PipeSensor.avgTemp, 3);
    str += ",";
    str += format_float(WaterSensor.avgTemp, 3);
    str += ",";
    str += format_float(TankSensor.avgTemp, 3);
    str += ",";
    str += format_float(bme_pressure, 2);

#ifdef WRITE_PROGNUM_IN_LOG
    str += ",";
    str += ProgramNum + 1;
#endif
    fileToAppend.println(str);

    {
      static bool memory_warning_sent = false;
      used_byte = SPIFFS.usedBytes();
      if (total_byte - used_byte < 400) {
        //Кончилось место, удалим старый файл. Надо было сохранять раньше
        if (SPIFFS.exists("/data_old.csv")) {
          SPIFFS.remove("/data_old.csv");
        }
      }
      vTaskDelay(10 / portTICK_PERIOD_MS);
      if (total_byte - used_byte < 50) {
        if (!memory_warning_sent) {
          SendMsg("Заканчивается память! Всего: " + String(total_byte) + ", использовано: " + String(used_byte), ALARM_MSG);
          memory_warning_sent = true;
        }
      } else {
        // Сбрасываем флаг, если память освободилась
        memory_warning_sent = false;
      }
    }

    return str;
  }
  return "";
}

#endif
