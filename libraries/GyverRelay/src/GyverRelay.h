/*
    GyverRelay - библиотека классического релейного регулятора для Arduino
    Документация: https://alexgyver.ru/gyverrelay/
    GitHub: https://github.com/GyverLibs/GyverRelay
    Возможности:
    - Обратная связь по скорости изменения величины
    - Настройка гистерезиса, коэффициента усиления ОС, направления регулирования
    - Возвращает результат по встроенному таймеру или в ручном режиме
    
    AlexGyver, alex@alexgyver.ru
    https://alexgyver.ru/
    MIT License

    Версии:
    v2.1 - исправлена getResultTimer
    v2.2 - улучшен и упрощён алгоритм
*/

#ifndef _GyverRelay_h
#define _GyverRelay_h
#include <Arduino.h>

enum GR_dir {
    NORMAL,
    REVERSE,
};

class GyverRelay {
public:
    // принимает установку, ширину гистерезиса, направление (NORMAL, REVERSE)
    // NORMAL - включаем нагрузку при переходе через значение снизу (пример: охлаждение)
    // REVERSE - включаем нагрузку при переходе через значение сверху (пример: нагрев)
    GyverRelay(GR_dir dir);
    
    // расчёт возвращает состояние для управляющего устройства (реле, транзистор) (1 вкл, 0 выкл)
    bool compute(float dt = 0);		    // моментальный расчёт. Принимает dt в секундах для режима с ОС
    bool getResult();				    // моментальный расчёт. Встроенный таймер для режима с ОС
    bool getResultTimer();			    // расчёт по встроенному таймеру

    void setDirection(GR_dir dir);		// направление регулирования (NORMAL, REVERSE)
    
    float input = 0;					// сигнал с датчика (например температура, которую мы регулируем)
    float setpoint = 0;					// заданная величина, которую должен поддерживать регулятор (температура)
    bool output = 0;					// выход регулятора (0 или 1)
    
    float hysteresis = 0;				// ширина окна гистерезиса
    float k = 0;						// коэффициент усиления	по скорости (по умолч. 0)	
    int16_t dT = 1000;					// время итерации, мс (по умолч. секунда)
    
private:	
    uint32_t prevTime = 0;
    float prevInput = 0.0;
    GR_dir _dir = REVERSE;
};
#endif