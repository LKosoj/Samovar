/*
    Библиотека для асинхронного чтения объектов Stream (Serial итд)
    Документация: 
    GitHub: https://github.com/GyverLibs/AsyncStream
    Возможности:
    - Неблокирующее чтение в свой буфер
    - Указание символа терминатора
    
    AlexGyver, alex@alexgyver.ru
    https://alexgyver.ru/
    MIT License

    Версии:
    v1.0 - релиз
    v1.1 - исправлен баг
*/

#ifndef _AsyncStream_h
#define _AsyncStream_h
#include <Arduino.h>

template < uint16_t SIZE >
class AsyncStream {
public:
    AsyncStream(Stream* port, char ter = ';', uint16_t tout = 50) {
        _port = port;
        _tout = tout;
        _ter = ter;
    }
    
    // установить таймаут
    void setTimeout(uint16_t tout) {
        _tout = tout;
    }
    
    // установить символ конца
    void setEOL(char ter) {
        _ter = ter;
    }
    
    // данные приняты
    bool available() {
        if (_port -> available()) {
            if (!_parseF) {
                _parseF = true;
                _count = 0;
                _tmr = millis();
            }
            char ch = _port -> read();
            if (ch == _ter) {
                buf[_count] = '\0';
                _parseF = false;
                return true;
            } else if (_count < SIZE - 1) buf[_count++] = ch;
            _tmr = millis();
        }
        if (_parseF && millis() - _tmr >= _tout) {
            _parseF = false;
            buf[_count] = '\0';
            return true;
        }
        return false;
    }
    
    // доступ к буферу
    char buf[SIZE];

private:
    Stream* _port;
    char _ter;
    uint16_t _tout, _count = 0;
    uint32_t _tmr = 0;
    bool _parseF = false;
};

#endif