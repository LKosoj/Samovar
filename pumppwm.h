#pragma once
#include "Samovar.h"
#include "safety_transition.h"
#ifdef USE_WATER_PUMP
#include <Arduino.h>
//#define PID_OPTIMIZED_I
#include <GyverPID.h>

#ifndef PUMP_PWM_FREQ
#define PUMP_PWM_FREQ 15
#else
#pragma message ("CUSTOM PUMP_PWM_FREQ")
#endif

static ESP32PWM pump_pwm;
static GyverPID pump_regulator(6.5, 0.3, 30, 1023);

void init_pump_pwm(uint8_t pin, int freq) {
  pump_pwm.attachPin(pin, freq, 10);
  pump_regulator.setDirection(REVERSE);                // направление регулирования (NORMAL/REVERSE). ПО УМОЛЧАНИЮ СТОИТ NORMAL
  pump_regulator.setLimits(PWM_LOW_VALUE * 10, 1023);  // пределы (ставим для 8 битного ШИМ). ПО УМОЛЧАНИЮ СТОЯТ 0 И 255
  //pump_regulator.setMode(ON_RATE);
  pump_regulator.setpoint = SamSetup.SetWaterTemp;     // сообщаем регулятору температуру, которую он должен поддерживать
  pump_started = false;
}

ActuatorCommandResult set_pump_pwm(float duty) {
  duty = constrain(duty, 0, 1023);

  // Во время смены режима приводами распоряжается только процедура переключения (см.
  // valve_buzzer.h::open_valve): иначе check_alarm_bk (BK.h) включает насос охлаждения
  // наперегонки со stop_local_mode_actuators() из loop(), а mode_actuators_idle()
  // (!pump_started && water_pump_speed == 0) не сходится — переключение срывается в
  // принудительное завершение по дедлайну. Выключение (duty == 0) проходит всегда.
  if (duty > 0 && mode_switch_barrier_active) return ACTUATOR_COMMAND_FAILED;

  // [П14] Раньше решение "держать соло на стартовом значении или писать
  // полную мощность" принималось по глобальному bk_pwm (уставка водяного
  // насоса режима БК), а не по duty - аргументу ЭТОГО вызова. Для БК это
  // было незаметно (BK.h всегда вызывает set_pump_pwm(bk_pwm), т.е. duty ==
  // bk_pwm), но для остальных вызывающих (Пиво, самотест) плавный пуск
  // либо сходился не к запрошенной мощности, а к произвольному оставшемуся
  // с прошлого режима bk_pwm, либо (когда bk_pwm случайно равен дефолту
  // PWM_LOW_VALUE * 40 = 400, выставленному sensorinit.h при старте)
  // пропускался целиком - насос сразу получал полную мощность, минуя
  // защитный стартовый порог. Сравниваем и пишем duty - тогда поведение
  // определяется тем, что реально запросил вызывающий, а не наследием БК.
	  if (!pump_started && duty > 0) {
	    wp_count = 0;
	    pump_pwm.write(PWM_START_VALUE * 10);
	    water_pump_speed = PWM_START_VALUE * 10;
	    pump_started = true;
	    if (duty != PWM_LOW_VALUE * 40) {
	      return ACTUATOR_COMMAND_APPLIED;
	    }
	    pump_pwm.write(duty);
	    water_pump_speed = duty;
	    return ACTUATOR_COMMAND_APPLIED;
	  }
  if (duty > 0 && wp_count < 10 && pump_started) {
    if (duty != PWM_LOW_VALUE * 40) {
      pump_pwm.write(duty);
      water_pump_speed = duty;
    } else {
      pump_pwm.write(PWM_START_VALUE * 10);
      water_pump_speed = PWM_START_VALUE * 10;
    }
    wp_count++;
    return ACTUATOR_COMMAND_APPLIED;
  }
  if (duty == 0) pump_started = false;
  pump_pwm.write(duty);
  water_pump_speed = duty;
  return ACTUATOR_COMMAND_APPLIED;
}

	void set_pump_speed_pid(float temp) {
	  pump_regulator.setpoint = SamSetup.SetWaterTemp;
	  pump_regulator.input = temp;
	  set_pump_pwm(pump_regulator.getResultNow());
	}
#endif
