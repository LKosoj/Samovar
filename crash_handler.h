#ifndef CRASH_HANDLER_H
#define CRASH_HANDLER_H

#ifdef USE_CRASH_HANDLER

#include <Arduino.h>
#include "Samovar.h"
#include <esp_system.h>
#include <rom/rtc.h>

// Максимальный размер стектрейса
#define STACKTRACE_MAX_SIZE 2048

// Инициализация обработчика сбоев
void init_crash_handler();

// Сохранение стектрейса в файл
void save_stacktrace_to_file(const char* info);

// Получение информации о причине сбоя
String get_reset_reason_string();

// Проверка и загрузка сохраненного стектрейса при старте
void check_and_load_crash_log();

#else // USE_CRASH_HANDLER

// Заглушки для случая, когда функционал отключен
inline void init_crash_handler() {}
inline void save_stacktrace_to_file(const char* info) {}
inline String get_reset_reason_string() { return String(""); }
inline void check_and_load_crash_log() {}
inline void force_save_stacktrace(const char* reason) {}

#endif // USE_CRASH_HANDLER

#endif // CRASH_HANDLER_H

