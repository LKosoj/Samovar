#pragma once
#include <Arduino.h>

// количество подстрок в списке list с разделителем div
uint8_t GP_listSize(char* list, char div = ',');

// разделить список list с разделителем div на подстроки (см. пример)
char* GP_splitList(char* list, char div = ',');

// получить номер, под которым name входит в list с разделителем div. -1 если не входит
int8_t GP_inList(char* name, char* list, char div = ',');

// преобразовать int в строку
void GP_numToChar(int32_t n, char* buf, uint8_t base);

// преобразовать float в строку
void GP_floatToChar(double f, char *buf, uint8_t decimals);

// преобразовать строку в число
int32_t GP_charToNum(char* buf, uint8_t base);

// преобразовать строку в float
double GP_charToFloat(char* buf);

// получить число под индексом idx в списке list с разделителем div
int GP_numFromList(char* list, int idx, char div = ',');

// переписать список list с разделителем div в массив чисел data размером size
uint8_t GP_listToNum(char* list, int* data, uint8_t size, char div = ',');

// преобразовать текстовый цвет (0x, #) в число
uint32_t GP_decodeColor(char* hex);


// http://we.easyelectronics.ru/Soft/preobrazuem-v-stroku-chast-1-celye-chisla.html
struct _GP_div10 {
    _GP_div10(uint32_t n) {
        quot = n >> 1;
        quot += quot >> 1;
        quot += quot >> 4;
        quot += quot >> 8;
        quot += quot >> 16;
        uint32_t qq = quot;
        quot >>= 3;
        rem = uint8_t(n - ((quot << 1) + (qq & ~7ul)));
        if (rem > 9) rem -= 10, quot++;
    }
    uint32_t quot;
    uint8_t rem;
};