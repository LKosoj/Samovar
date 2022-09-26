#include "GyverRelay.h"

GyverRelay::GyverRelay(GR_dir dir = REVERSE) {
    _dir = dir;
    output = !_dir;   // выключить реле сразу
}

void GyverRelay::setDirection(GR_dir dir) {
    _dir = dir;
}

// вернёт выход, принимает время итерации в секундах
bool GyverRelay::compute(float dt) {
    float signal;
    if (dt != 0 && k != 0) {
        signal = input + (input - prevInput) * k / dt;
        prevInput = input;
    } else signal = input;
    
    if (signal < (setpoint - hysteresis / 2)) output = _dir;
    else if (signal > (setpoint + hysteresis / 2)) output = !_dir;
    return output;
}

bool GyverRelay::getResult() {
    compute((millis() - prevTime) / 1000.0f);
    prevTime = millis();
    return output;
}

bool GyverRelay::getResultTimer() {
    if (millis() - prevTime > dT) {
        prevTime = millis();
        compute(dT / 1000.0);
    }
    return output;
}