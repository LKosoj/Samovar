#pragma once

#include <Arduino.h>
#include "Samovar.h"
#include "samovar_api.h"

void open_valve(bool Val, bool msg = true) {
  if (Val && !alarm_event) {
    valve_status = true;
    if (msg) {
      SendMsg(("Откройте подачу воды!"), WARNING_MSG);
    } else {
      SendMsg(("Открыт клапан воды охлаждения!"), NOTIFY_MSG);
    }
    digitalWrite(RELE_CHANNEL3, SamSetup.rele3);
  } else {
    valve_status = false;
    if (msg) {
      SendMsg(("Закройте подачу воды!"), WARNING_MSG);
    } else {
      SendMsg(("Закрыт клапан воды охлаждения!"), NOTIFY_MSG);
    }
    digitalWrite(RELE_CHANNEL3, !SamSetup.rele3);
  }
}

// Обработка пищалки в основном цикле
void process_buzzer() {
  if (!buzzer_active) {
    return;
  }

  unsigned long current_time = millis();

  // [C-13] overflow-safe: buzzer_next_time — deadline, используем разность
  if ((int32_t)(current_time - buzzer_next_time) >= 0) {
    if (buzzer_state) {
      // Пищалка включена, выключаем её
      digitalWrite(BZZ_PIN, LOW);
      buzzer_state = false;
      buzzer_beep_count++;

      // Проверяем, нужно ли продолжать пищать
      if (buzzer_beep_count >= 5) {
        buzzer_active = false;
        buzzer_beep_count = 0;
      } else {
        // Планируем следующее включение через 600 мс
        buzzer_next_time = current_time + 600;
      }
    } else {
      // Пищалка выключена, включаем её
      digitalWrite(BZZ_PIN, HIGH);
      buzzer_state = true;
      // Планируем выключение через 400 мс
      buzzer_next_time = current_time + 400;
    }
  }
}

void set_buzzer(bool fl) {
  if (fl && SamSetup.UseBuzzer) {
    // Активируем пищалку
    buzzer_active = true;
    buzzer_beep_count = 0;
    buzzer_state = false;
    buzzer_next_time = millis(); // Начинаем сразу
  } else {
    // Деактивируем пищалку
    buzzer_active = false;
    buzzer_beep_count = 0;
    buzzer_state = false;
    digitalWrite(BZZ_PIN, LOW);
  }
}
