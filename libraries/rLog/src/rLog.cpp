#include "rLog.h"
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <time.h>

#ifdef ARDUINO_ARCH_AVR
  #define __RLOG_SERIAL__ 1
  #define __RLOG_LOCKS_ENABLED__ 0
  #define __RLOG_FREERTOS__ 0
  #include <Arduino.h>
#else
  #define __RLOG_SERIAL__ 0

  #if __has_include("sys/lock.h")
  #define __RLOG_LOCKS_ENABLED__ 1
  #include "sys/lock.h"
  #else 
  #define __RLOG_LOCKS_ENABLED__ 0
  #endif

  #if __has_include("freertos/semphr.h") 
  #define __RLOG_FREERTOS__ 1
  #else 
  #define __RLOG_FREERTOS__ 0
  #endif
#endif

#if __RLOG_FREERTOS__

/* FreeRTOS enabled */

#include "freertos/FreeRTOS.h" 
#include "freertos/semphr.h" 

static xSemaphoreHandle _rlog_mutex;

void _rlog_lock()
{
  if (!_rlog_mutex) {
    _rlog_mutex = xSemaphoreCreateMutex();
  }
  xSemaphoreTake(_rlog_mutex, portMAX_DELAY);
}

void _rlog_unlock()
{
  xSemaphoreGive(_rlog_mutex);
} 
#endif // __RLOG_FREERTOS__

int _rlog_printf(const char *format, ...)
{
  // Due to the fact that vprintf does not work on some sdk, you have to be perverted
  static char loc_buf[256];
  char * temp = loc_buf;
  uint32_t len;
  va_list arg1, arg2;
  
  #if __RLOG_FREERTOS__
  _rlog_lock();
  #endif
  // Get the list of arguments
  va_start(arg1, format);
  // Calculate the length of the resulting message
  va_copy(arg2, arg1);
  len = vsnprintf(NULL, 0, format, arg2);
  va_end(arg2);
  // If the length exceeds the buffer size, allocate memory for a larger buffer
  if (len >= sizeof(loc_buf)) {
    temp = (char*)malloc(len+1);
    if (temp == NULL) {
      return 0;
    }
  }
  // We get the resulting string into the buffer
  vsnprintf(temp, len+1, format, arg1);
  va_end(arg1);
  // And finally we can print a message
  #if __RLOG_SERIAL__
  Serial.print(temp);
  #else
  printf("%s", temp);
  #endif
  // Delete the buffer if it was allocated
  if (len >= sizeof(loc_buf)) {
    free(temp);
  }
  #if __RLOG_FREERTOS__
  _rlog_unlock();
  #endif
 
  return len; 
}

const char * _rlog_system_timestamp(void)
{
  #if __RLOG_LOCKS_ENABLED__
  static _LOCK_T bufferLock = 0;
  #endif
  static char buffer[18] = {0};
  struct tm timeinfo;
  
  time_t now = time(NULL);
  localtime_r(&now, &timeinfo);

  #if __RLOG_LOCKS_ENABLED__
  if (bufferLock == 0) __lock_init(bufferLock);
  __lock_acquire(bufferLock);
  #endif
  snprintf(buffer, sizeof(buffer), "%02d:%02d:%02d", timeinfo.tm_hour, timeinfo.tm_min, timeinfo.tm_sec);
  #if __RLOG_LOCKS_ENABLED__
  __lock_release(bufferLock);
  #endif

  return buffer;
}

const char * _rlog_filename(const char * path)
{
  size_t i = 0;
  size_t pos = 0;
  char * p = (char *)path;
  while (*p) {
    i++;
    if (*p == '/' || *p == '\\') {
      pos = i;
    }
    p++;
  }
  return path+pos;
} 
