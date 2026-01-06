#include "crash_handler.h"

#ifdef USE_CRASH_HANDLER

// Буфер для стектрейса
static char stacktrace_buffer[STACKTRACE_MAX_SIZE];
static bool crash_occurred = false;
static bool fs_available = false;

// Функция для получения строки с причиной сбоя
// Основано на официальной документации ESP32: esp_reset_reason_t
String get_reset_reason_string() {
  esp_reset_reason_t reason = esp_reset_reason();
  switch (reason) {
    case ESP_RST_UNKNOWN:   return "Неизвестная причина перезагрузки (0)";
    case ESP_RST_POWERON:   return "Перезагрузка из-за подачи питания (1)";
    case ESP_RST_EXT:       return "Внешний сброс через пин RESET (2)";
    case ESP_RST_SW:        return "Программный сброс, вызванный esp_restart() (3)";
    case ESP_RST_PANIC:     return "Сброс из-за паники или необработанного исключения (4)";
    case ESP_RST_INT_WDT:   return "Сброс из-за срабатывания внутреннего сторожевого таймера (5)";
    case ESP_RST_TASK_WDT:  return "Сброс из-за срабатывания сторожевого таймера задачи (6)";
    case ESP_RST_WDT:       return "Сброс из-за срабатывания любого из сторожевых таймеров (7)";
    case ESP_RST_DEEPSLEEP: return "Сброс после выхода из режима глубокого сна (8)";
    case ESP_RST_BROWNOUT:  return "Сброс из-за детектирования пониженного напряжения питания (9)";
    case ESP_RST_SDIO:      return "Сброс по причине ошибки SDIO (10)";
    default:                return "Неизвестный код причины: " + String((int)reason);
  }
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
  
  esp_reset_reason_t reason = esp_reset_reason();
  
  // Проверяем, был ли это сбой (не обычная перезагрузка)
  bool is_crash = (reason == ESP_RST_PANIC || reason == ESP_RST_INT_WDT || 
                   reason == ESP_RST_TASK_WDT || reason == ESP_RST_WDT || 
                   reason == ESP_RST_BROWNOUT);
  
  if (is_crash) {
    String crash_info = "System crash detected. Reason: " + get_reset_reason_string();
    save_stacktrace_to_file(crash_info.c_str());
  }
}

// Инициализация обработчика сбоев
void init_crash_handler() {
  Serial.println("[CRASH] Initializing crash handler...");
  
  // Проверяем, была ли файловая система уже смонтирована
  fs_available = SPIFFS.begin(false);
  Serial.print("[CRASH] Filesystem status: ");
  Serial.println(fs_available ? "OK" : "FAILED");
  
  // Регистрируем обработчик завершения системы
  esp_register_shutdown_handler(shutdown_handler);
  
  esp_reset_reason_t reason = esp_reset_reason();
  String reasonStr = get_reset_reason_string();
  
  Serial.print("[CRASH] Reset Reason: "); 
  Serial.println(reasonStr);
  
  // Считаем сбоем всё, кроме питания, кнопки, программного рестарта и сна
  bool was_crash = (reason != ESP_RST_POWERON && reason != ESP_RST_EXT && 
                    reason != ESP_RST_SW && reason != ESP_RST_DEEPSLEEP && 
                    reason != ESP_RST_UNKNOWN);
  
  if (was_crash) {
    Serial.println("[CRASH] Crash detected! Saving log...");
    // Сохраняем информацию о предыдущем сбое
    String crash_info = "Previous crash detected at startup. Reason: " + reasonStr;
    save_stacktrace_to_file(crash_info.c_str());
  } else {
    Serial.println("[CRASH] Normal boot detected.");
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
