#include "crash_handler.h"

#ifdef USE_CRASH_HANDLER

// Буфер для стектрейса
static char stacktrace_buffer[STACKTRACE_MAX_SIZE];
static bool crash_occurred = false;
static bool fs_available = false;

// Функция для получения строки с причиной сбоя
String get_reset_reason_string() {
  String reason = "";
  
  RESET_REASON reason0 = rtc_get_reset_reason(0);
  RESET_REASON reason1 = rtc_get_reset_reason(1);
  
  reason += "Core 0: ";
  switch (reason0) {
    case NO_MEAN: reason += "NO_MEAN"; break;
    case POWERON_RESET: reason += "POWERON_RESET"; break;
    case SW_RESET: reason += "SW_RESET"; break;
    case OWDT_RESET: reason += "OWDT_RESET"; break;
    case DEEPSLEEP_RESET: reason += "DEEPSLEEP_RESET"; break;
    case SDIO_RESET: reason += "SDIO_RESET"; break;
    case TG0WDT_SYS_RESET: reason += "TG0WDT_SYS_RESET"; break;
    case TG1WDT_SYS_RESET: reason += "TG1WDT_SYS_RESET"; break;
    case RTCWDT_SYS_RESET: reason += "RTCWDT_SYS_RESET"; break;
    case INTRUSION_RESET: reason += "INTRUSION_RESET"; break;
    case TGWDT_CPU_RESET: reason += "TGWDT_CPU_RESET"; break;
    case SW_CPU_RESET: reason += "SW_CPU_RESET"; break;
    case RTCWDT_CPU_RESET: reason += "RTCWDT_CPU_RESET"; break;
    case EXT_CPU_RESET: reason += "EXT_CPU_RESET"; break;
    case RTCWDT_BROWN_OUT_RESET: reason += "RTCWDT_BROWN_OUT_RESET"; break;
    case RTCWDT_RTC_RESET: reason += "RTCWDT_RTC_RESET"; break;
    default: reason += "UNKNOWN"; break;
  }
  
  reason += " | Core 1: ";
  switch (reason1) {
    case NO_MEAN: reason += "NO_MEAN"; break;
    case POWERON_RESET: reason += "POWERON_RESET"; break;
    case SW_RESET: reason += "SW_RESET"; break;
    case OWDT_RESET: reason += "OWDT_RESET"; break;
    case DEEPSLEEP_RESET: reason += "DEEPSLEEP_RESET"; break;
    case SDIO_RESET: reason += "SDIO_RESET"; break;
    case TG0WDT_SYS_RESET: reason += "TG0WDT_SYS_RESET"; break;
    case TG1WDT_SYS_RESET: reason += "TG1WDT_SYS_RESET"; break;
    case RTCWDT_SYS_RESET: reason += "RTCWDT_SYS_RESET"; break;
    case INTRUSION_RESET: reason += "INTRUSION_RESET"; break;
    case TGWDT_CPU_RESET: reason += "TGWDT_CPU_RESET"; break;
    case SW_CPU_RESET: reason += "SW_CPU_RESET"; break;
    case RTCWDT_CPU_RESET: reason += "RTCWDT_CPU_RESET"; break;
    case EXT_CPU_RESET: reason += "EXT_CPU_RESET"; break;
    case RTCWDT_BROWN_OUT_RESET: reason += "RTCWDT_BROWN_OUT_RESET"; break;
    case RTCWDT_RTC_RESET: reason += "RTCWDT_RTC_RESET"; break;
    default: reason += "UNKNOWN"; break;
  }
  
  return reason;
}

// Функция для сохранения стектрейса в файл
void save_stacktrace_to_file(const char* info) {
  // Очищаем буфер
  memset(stacktrace_buffer, 0, sizeof(stacktrace_buffer));
  
  // Формируем заголовок с информацией о сбое
  String crash_log = "=== CRASH REPORT ===\n";
  crash_log += "Time: " + String(millis()) + " ms\n";
  crash_log += "Info: " + String(info) + "\n";
  crash_log += "Reset Reason: " + get_reset_reason_string() + "\n";
  crash_log += "Free Heap: " + String(ESP.getFreeHeap()) + " bytes\n";
  crash_log += "Largest Free Block: " + String(ESP.getMaxAllocHeap()) + " bytes\n";
  crash_log += "Chip Model: " + String(ESP.getChipModel()) + "\n";
  crash_log += "Chip Revision: " + String(ESP.getChipRevision()) + "\n";
  crash_log += "CPU Frequency: " + String(ESP.getCpuFreqMHz()) + " MHz\n";
  crash_log += "\n=== STACKTRACE ===\n";
  
  // Получаем информацию о задачах
  crash_log += "Task Stack Info:\n";
  UBaseType_t numTasks = uxTaskGetNumberOfTasks();
  crash_log += "Total Tasks: " + String(numTasks) + "\n";
  
  // Добавляем информацию о стеке текущей задачи
  TaskHandle_t currentTask = xTaskGetCurrentTaskHandle();
  if (currentTask != NULL) {
    UBaseType_t stackHighWaterMark = uxTaskGetStackHighWaterMark(currentTask);
    crash_log += "Current Task Stack High Water Mark: " + String(stackHighWaterMark) + " words\n";
    
    // Получаем имя задачи
    const char* taskName = pcTaskGetName(currentTask);
    if (taskName) {
      crash_log += "Current Task Name: " + String(taskName) + "\n";
    }
  }
  
  // Добавляем информацию о памяти
  crash_log += "\n=== MEMORY INFO ===\n";
  crash_log += "Free Heap: " + String(ESP.getFreeHeap()) + " bytes\n";
  crash_log += "Largest Free Block: " + String(ESP.getMaxAllocHeap()) + " bytes\n";
  crash_log += "Min Free Heap: " + String(ESP.getMinFreeHeap()) + " bytes\n";
  
  // Пытаемся сохранить в файл
  bool fs_was_mounted = fs_available;
  if (!fs_was_mounted) {
    fs_was_mounted = SPIFFS.begin(false);
  }
  
  if (fs_was_mounted) {
    // Генерируем имя файла с временной меткой
    String filename = "/crash_";
    filename += String(millis());
    filename += ".txt";
    
    File file = SPIFFS.open(filename, FILE_WRITE);
    if (file) {
      file.print(crash_log);
      file.close();
      Serial.println("Crash log saved to: " + filename);
    } else {
      Serial.println("Failed to open crash log file");
      // Выводим в Serial как резервный вариант
      Serial.println(crash_log);
    }
  } else {
    Serial.println("Failed to mount SPIFFS for crash log");
    // Выводим в Serial как резервный вариант
    Serial.println(crash_log);
  }
}

// Обработчик завершения системы
void shutdown_handler() {
  if (crash_occurred) {
    return; // Уже обработали
  }
  
  crash_occurred = true;
  
  // Получаем причину сбоя
  RESET_REASON reason0 = rtc_get_reset_reason(0);
  RESET_REASON reason1 = rtc_get_reset_reason(1);
  
  // Проверяем, был ли это сбой (не обычная перезагрузка)
  bool is_crash = (reason0 == TG0WDT_SYS_RESET || reason0 == TG1WDT_SYS_RESET || 
                   reason0 == RTCWDT_SYS_RESET || reason0 == TGWDT_CPU_RESET ||
                   reason0 == RTCWDT_CPU_RESET || reason0 == RTCWDT_BROWN_OUT_RESET ||
                   reason1 == TG0WDT_SYS_RESET || reason1 == TG1WDT_SYS_RESET ||
                   reason1 == RTCWDT_SYS_RESET || reason1 == TGWDT_CPU_RESET ||
                   reason1 == RTCWDT_CPU_RESET || reason1 == RTCWDT_BROWN_OUT_RESET);
  
  if (is_crash) {
    String crash_info = "System crash detected. Reason: " + get_reset_reason_string();
    save_stacktrace_to_file(crash_info.c_str());
  }
}

// Обработчик паники (вызывается при исключении)
// Примечание: в Arduino framework прямой доступ к обработчику паники может быть ограничен
// Поэтому мы полагаемся на проверку причины перезагрузки при старте

// Инициализация обработчика сбоев
void init_crash_handler() {
  // Проверяем, была ли файловая система уже смонтирована
  fs_available = SPIFFS.begin(false);
  
  // Регистрируем обработчик завершения системы
  // Примечание: esp_register_shutdown_handler вызывается при нормальном завершении,
  // а не при панике. Для перехвата паники мы проверяем причину перезагрузки при старте.
  esp_register_shutdown_handler(shutdown_handler);
  
  Serial.println("Crash handler initialized");
  
  // Проверяем причину перезагрузки при старте
  RESET_REASON reason0 = rtc_get_reset_reason(0);
  RESET_REASON reason1 = rtc_get_reset_reason(1);
  
  // Проверяем, был ли это сбой
  bool was_crash = (reason0 == TG0WDT_SYS_RESET || reason0 == TG1WDT_SYS_RESET || 
                    reason0 == RTCWDT_SYS_RESET || reason0 == TGWDT_CPU_RESET ||
                    reason0 == RTCWDT_CPU_RESET || reason0 == RTCWDT_BROWN_OUT_RESET ||
                    reason1 == TG0WDT_SYS_RESET || reason1 == TG1WDT_SYS_RESET ||
                    reason1 == RTCWDT_SYS_RESET || reason1 == TGWDT_CPU_RESET ||
                    reason1 == RTCWDT_CPU_RESET || reason1 == RTCWDT_BROWN_OUT_RESET);
  
  if (was_crash) {
    // Сохраняем информацию о предыдущем сбое
    String crash_info = "Previous crash detected at startup. Reason: " + get_reset_reason_string();
    save_stacktrace_to_file(crash_info.c_str());
  }
  
  // Проверяем наличие сохраненных логов сбоев при старте
  check_and_load_crash_log();
}

// Проверка и загрузка сохраненного лога сбоя при старте
void check_and_load_crash_log() {
  if (!SPIFFS.begin(false)) {
    return;
  }
  
  // Ищем файлы с префиксом /crash_
  File root = SPIFFS.open("/");
  if (!root || !root.isDirectory()) {
    return;
  }
  
  File file = root.openNextFile();
  bool found_crash = false;
  
  while (file) {
    String filename = file.name();
    if (filename.startsWith("/crash_")) {
      found_crash = true;
      Serial.println("\n=== FOUND CRASH LOG ===");
      Serial.println("File: " + filename);
      Serial.println("Size: " + String(file.size()) + " bytes");
      Serial.println("Content:");
      Serial.println("-------------------");
      
      // Читаем и выводим содержимое
      while (file.available()) {
        Serial.write(file.read());
      }
      Serial.println("\n-------------------\n");
      
      file.close();
      break; // Показываем только последний файл
    }
    file = root.openNextFile();
  }
  
  root.close();
  
  if (!found_crash) {
    Serial.println("No crash logs found");
  }
}

// Функция для принудительного сохранения стектрейса (можно вызывать вручную)
void force_save_stacktrace(const char* reason) {
  save_stacktrace_to_file(reason);
}

#endif // USE_CRASH_HANDLER

