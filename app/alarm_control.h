#ifndef __SAMOVAR_ALARM_CONTROL_H_
#define __SAMOVAR_ALARM_CONTROL_H_

#include <Arduino.h>

#include "io/actuators.h"
#include "state/globals.h"

void set_power(bool On);
void stopService(void);
bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target);
void SendMsg(const String& m, MESSAGE_TYPE msg_type);

#ifdef USE_WATER_PUMP
void set_pump_pwm(float duty);
#endif

inline void set_alarm() {
  if (PowerOn) {
    sam_command_sync = SAMOVAR_POWER;
  }
  set_power(false);
  alarm_event = true;
  open_valve(false, true);
  stopService();
  set_stepper_target(0, 0, 0);
#ifdef USE_WATER_PUMP
  set_pump_pwm(0);
#endif
  SendMsg(("Аварийное отключение!"), ALARM_MSG);
}

inline void process_buzzer() {
  if (!buzzer_active) {
    return;
  }

  unsigned long current_time = millis();

  if (current_time >= buzzer_next_time) {
    if (buzzer_state) {
      digitalWrite(BZZ_PIN, LOW);
      buzzer_state = false;
      buzzer_beep_count++;

      if (buzzer_beep_count >= 5) {
        buzzer_active = false;
        buzzer_beep_count = 0;
      } else {
        buzzer_next_time = current_time + 600;
      }
    } else {
      digitalWrite(BZZ_PIN, HIGH);
      buzzer_state = true;
      buzzer_next_time = current_time + 400;
    }
  }
}

inline void set_buzzer(bool fl) {
  if (fl && SamSetup.UseBuzzer) {
    buzzer_active = true;
    buzzer_beep_count = 0;
    buzzer_state = false;
    buzzer_next_time = millis();
  } else {
    buzzer_active = false;
    buzzer_beep_count = 0;
    buzzer_state = false;
    digitalWrite(BZZ_PIN, LOW);
  }
}

#endif
