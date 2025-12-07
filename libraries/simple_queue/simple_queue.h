#ifndef SIMPLE_QUEUE_H
#define SIMPLE_QUEUE_H

#include <Arduino.h>

// Используем существующее объявление MESSAGE_TYPE из основного кода
// extern enum MESSAGE_TYPE; // Раскомментировать если нужно

// Определение структуры для хранения сообщения и его типа
struct Message {
    char text[301]; // 300 byte + нулевой терминатор
    uint8_t type;   // Используем uint8_t вместо enum для совместимости
};

class SimpleQueue {
private:
    Message* buffer;
    uint16_t capacity;
    uint16_t head;
    uint16_t tail;
    uint16_t count;
    bool initialized;

public:
    SimpleQueue(uint16_t queueCapacity) : capacity(queueCapacity), head(0), tail(0), count(0), initialized(false) {
        buffer = new Message[capacity];
        if (buffer != nullptr) {
            initialized = true;
        }
    }

    SimpleQueue(uint16_t queueCapacity, void* externalBuffer, size_t bufferSize) : 
        capacity(queueCapacity), head(0), tail(0), count(0), initialized(false) {
        if (externalBuffer != nullptr && bufferSize >= capacity * sizeof(Message)) {
            buffer = (Message*)externalBuffer;
            initialized = true;
        } else {
            buffer = new Message[capacity];
            if (buffer != nullptr) {
                initialized = true;
            }
        }
    }

    ~SimpleQueue() {
        // Не удаляем внешний буфер
        if (initialized && buffer != nullptr) {
            // Проверяем, был ли буфер выделен нами
            bool isExternal = false;
            // Простая эвристика: если capacity соответствует PSRAM_BUFFER_SIZE, вероятно внешний
            if (capacity == 10) { // PSRAM_BUFFER_SIZE
                isExternal = true;
            }
            if (!isExternal) {
                delete[] buffer;
            }
        }
    }

    bool isInitialized() const { return initialized; }
    bool push(const Message* item) {
        if (!initialized || count >= capacity) return false;
        
        memcpy(&buffer[tail], item, sizeof(Message));
        tail = (tail + 1) % capacity;
        count++;
        return true;
    }

    bool pop(Message* item) {
        if (!initialized || count == 0) return false;
        
        memcpy(item, &buffer[head], sizeof(Message));
        head = (head + 1) % capacity;
        count--;
        return true;
    }

    bool peek(Message* item) const {
        if (!initialized || count == 0) return false;
        
        memcpy(item, &buffer[head], sizeof(Message));
        return true;
    }

    void flush() {
        head = 0;
        tail = 0;
        count = 0;
    }

    bool isEmpty() const { return count == 0; }
    bool isFull() const { return count >= capacity; }
    uint16_t getCount() const { return count; }
    uint16_t getRemainingCount() const { return capacity - count; }
    uint16_t getCapacity() const { return capacity; }
};

// Простая очередь для строк (для Telegram)
class SimpleStringQueue {
private:
    char** buffer;
    uint8_t capacity;
    uint8_t head;
    uint8_t tail;
    uint8_t count;
    bool initialized;

public:
    SimpleStringQueue(uint8_t queueCapacity, size_t stringSize) : 
        capacity(queueCapacity), head(0), tail(0), count(0), initialized(false) {
        buffer = new char*[capacity];
        if (buffer != nullptr) {
            for (uint8_t i = 0; i < capacity; i++) {
                buffer[i] = new char[stringSize];
                if (buffer[i] == nullptr) {
                    initialized = false;
                    return;
                }
            }
            initialized = true;
        }
    }

    ~SimpleStringQueue() {
        if (buffer != nullptr) {
            for (uint8_t i = 0; i < capacity; i++) {
                if (buffer[i] != nullptr) {
                    delete[] buffer[i];
                }
            }
            delete[] buffer;
        }
    }

    bool isInitialized() const { return initialized; }
    bool push(const char* item) {
        if (!initialized || count >= capacity) return false;
        
        strncpy(buffer[tail], item, 511);
        buffer[tail][511] = '\0';
        tail = (tail + 1) % capacity;
        count++;
        return true;
    }

    bool pop(char* item) {
        if (!initialized || count == 0) return false;
        
        strncpy(item, buffer[head], 512);
        head = (head + 1) % capacity;
        count--;
        return true;
    }

    bool isEmpty() const { return count == 0; }
    bool isFull() const { return count >= capacity; }
    uint8_t getCount() const { return count; }
};

#endif