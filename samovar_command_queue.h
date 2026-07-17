#pragma once

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include "Samovar.h"

bool mode_switch_in_progress();

struct SamovarCommandMsg {
  SamovarCommands command;
};

constexpr UBaseType_t SAMOVAR_COMMAND_QUEUE_LENGTH = 8;

extern QueueHandle_t samovar_command_queue;
extern StaticQueue_t samovar_command_queue_buffer;
extern uint8_t samovar_command_queue_storage[SAMOVAR_COMMAND_QUEUE_LENGTH * sizeof(SamovarCommandMsg)];
extern SemaphoreHandle_t samovar_command_queue_mutex;
extern StaticSemaphore_t samovar_command_queue_mutex_buffer;

inline bool init_samovar_command_queue() {
  samovar_command_queue = xQueueCreateStatic(SAMOVAR_COMMAND_QUEUE_LENGTH,
                                             sizeof(SamovarCommandMsg),
                                             samovar_command_queue_storage,
                                             &samovar_command_queue_buffer);
  samovar_command_queue_mutex = xSemaphoreCreateMutexStatic(&samovar_command_queue_mutex_buffer);
  return samovar_command_queue != nullptr && samovar_command_queue_mutex != nullptr;
}

inline bool queue_samovar_command(SamovarCommands command, TickType_t timeout = 0) {
  if (samovar_command_queue == nullptr || samovar_command_queue_mutex == nullptr ||
      command == SAMOVAR_NONE) return false;
  if (xSemaphoreTake(samovar_command_queue_mutex, timeout) != pdTRUE) return false;
  if (mode_switch_in_progress()) {
    xSemaphoreGive(samovar_command_queue_mutex);
    return false;
  }
  SamovarCommandMsg msg = {command};
  bool queued = xQueueSend(samovar_command_queue, &msg, timeout) == pdTRUE;
  xSemaphoreGive(samovar_command_queue_mutex);
  return queued;
}

inline bool discard_samovar_commands(TickType_t timeout = 0) {
  if (samovar_command_queue == nullptr || samovar_command_queue_mutex == nullptr) return false;
  if (xSemaphoreTake(samovar_command_queue_mutex, timeout) != pdTRUE) return false;
  const bool discarded = xQueueReset(samovar_command_queue) == pdPASS;
  xSemaphoreGive(samovar_command_queue_mutex);
  return discarded;
}

inline bool receive_samovar_command(SamovarCommandMsg& msg, TickType_t timeout = 0) {
  if (samovar_command_queue == nullptr) return false;
  return xQueueReceive(samovar_command_queue, &msg, timeout) == pdTRUE;
}

inline bool samovar_command_queue_idle(TickType_t timeout = 0) {
  if (samovar_command_queue == nullptr || samovar_command_queue_mutex == nullptr) return false;
  if (xSemaphoreTake(samovar_command_queue_mutex, timeout) != pdTRUE) return false;
  const bool idle = uxQueueMessagesWaiting(samovar_command_queue) == 0;
  xSemaphoreGive(samovar_command_queue_mutex);
  return idle;
}

inline bool queue_samovar_reset_command(TickType_t timeout = 0) {
  if (samovar_command_queue == nullptr || samovar_command_queue_mutex == nullptr) return false;
  if (xSemaphoreTake(samovar_command_queue_mutex, timeout) != pdTRUE) return false;
  if (mode_switch_in_progress()) {
    xSemaphoreGive(samovar_command_queue_mutex);
    return false;
  }
  xQueueReset(samovar_command_queue);
  SamovarCommandMsg msg = {SAMOVAR_RESET};
  bool queued = xQueueSendToFront(samovar_command_queue, &msg, timeout) == pdTRUE;
  xSemaphoreGive(samovar_command_queue_mutex);
  return queued;
}
