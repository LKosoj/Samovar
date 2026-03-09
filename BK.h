#ifndef __SAMOVAR_BK_H_
#define __SAMOVAR_BK_H_

#include <Arduino.h>
#include "Samovar.h"
#include "state/globals.h"
#include "app/process_common.h"

#ifdef USE_WATER_PUMP
#include "pumppwm.h"
#endif

/**
 * @brief Завершить работу бражной колонны, отправить уведомление, выключить нагрев и сбросить счетчики.
 */
void bk_finish();

/**
 * @brief Сбросить счетчик датчиков.
 */
void reset_sensor_counter();

/**
 * @brief Установить ШИМ для насоса.
 * @param duty Значение ШИМ
 */
void set_pump_pwm(float duty);

/**
 * @brief Установить скорость насоса по ПИД-регулированию.
 * @param temp Целевая температура
 */
void set_pump_speed_pid(float temp);

/**
 * @brief Отправить сообщение пользователю.
 * @param m Текст сообщения
 * @param msg_type Тип сообщения
 */
void SendMsg(const String& m, MESSAGE_TYPE msg_type);

/**
 * @brief Установить температуру воды (ШИМ).
 * @param duty Значение ШИМ
 */
void set_water_temp(float duty) {
#ifdef USE_WATER_PUMP
  bk_pwm = duty;
  if (pump_started) {
    pump_pwm.write(bk_pwm);
    water_pump_speed = bk_pwm;
  }
#else
  SendMsg(("Управление насосом не поддерживается вашим оборудованием"), NOTIFY_MSG);
#endif
}

void bk_finish() {
  stop_process("Работа бражной колонны завершена");
}

#endif
