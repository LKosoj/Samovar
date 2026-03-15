#ifndef __SAMOVAR_RUNTIME_TYPES_H_
#define __SAMOVAR_RUNTIME_TYPES_H_

#include <Arduino.h>
#include <OneWire.h>
#include "src/core/state/mode_codes.h"
#include "src/core/state/status_codes.h"

enum MESSAGE_TYPE {ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, NONE_MSG = 100};

enum get_web_type {GET_CONTENT, SAVE_FILE_OVERRIDE, SAVE_FILE_IF_NOT_EXIST};

struct ImpurityDetector {
  float tempHistory[30];        // Кольцевой буфер (60 сек при опросе раз в 2 сек)
  uint8_t historyIndex;         // Текущий индекс в буфере
  uint8_t historySize;          // Фактически заполненный размер
  unsigned long lastSampleTime; // Время последнего замера
  float currentTrend;           // Текущий тренд (°C/мин)
  uint8_t detectorStatus;       // Статус: 0=Stable, 1=Correction, 2=Breakthrough
  float correctionFactor;       // Коэффициент коррекции скорости (0.7-1.0)
  unsigned long lastCorrectionTime; // Время последней корректировки
  float tempStdDev;             // Дисперсия температуры за период
  uint8_t consecutiveRises;     // Счетчик последовательных повышений температуры
  float lastTemp;               // Предыдущее значение температуры для отслеживания последовательных повышений
};

struct DSSensor {
  DeviceAddress Sensor;                                        //адрес датчика температуры
  float avgTemp;                                               //средняя температура с датчика
  float SetTemp;                                               //уставка по температуре, при достижении которой требуется реакция
  float BodyTemp;                                              //температура, с которой начался отбор тела
  uint16_t Delay;                                              //Время задержки включения насоса в секундах при выходе температуры за значение уставки
  float PrevTemp;                                              //Предыдущая температура
  float Start_Pressure;                                        //Стартовое давление при начале отбора
  int ErrCount;                                                //Счетчик ошибок для оповещения о не возможности провести чтение с датчика
  float LogPrevTemp;                                           //Хранение предыдущей температуры для записи лога
  float StartProgTemp;                                         //Хранение температуры, которая была на начало строки программы
};

struct WProgram {
  String WType;                                                //тип отбора - головы или тело
  uint16_t Volume;                                             //объем отбора в мл
  float Speed;                                                 //скорость отбора в л/ч
  uint8_t capacity_num;                                        //номер емкости для отбора
  float Temp;                                                  //температура, при которой отбирается эта часть погона. 0 - определяется автоматически
  uint16_t Power;                                              //напряжение, при которой отбирается эта часть погона.
  uint8_t TempSensor;                                          //температурный сенсор, используемый в программе Пиво для контроля нагрева
  float Time;                                                  //время, необходимое для отбора программы
};

#endif
