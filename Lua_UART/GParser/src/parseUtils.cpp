#include "parseUtils.h"

// количество подстрок в списке list с разделителем div
uint8_t GP_listSize(char* list, char div) {
    uint16_t i = 0, count = 0;
    while (list[i]) if (list[i++] == div) count++;
    return ++count;
}

// разделить список list с разделителем div на подстроки
char* GP_splitList(char* list, char div) {
    static uint8_t prev, end;
    if (list == NULL) prev = end = 0;
    else {
        if (prev) *(list + prev - 1) = div;
        char* cur = strchr(list + prev, div);
        if (cur) {
            *cur = '\0';
            uint8_t b = prev;
            prev = cur - list + 1;
            return list + b;
        } else if (!end) {
            end = 1;
            return list + prev;
        }
    }
    return NULL;
}

// получить номер, под которым name входит в list с разделителем div
int8_t GP_inList(char* name, char* list, char div) {
    char* str = list;
    int8_t count = 0, pos = -1;
    GP_splitList(NULL);
    while ((str = GP_splitList(list, div)) != NULL) {
        if (!strcmp(str, name)) pos = count;
        count++;
    }
    return pos;
}

// преобразовать int в строку
// DEC - 46, HEX/BIN - 17 (ltoa: BIN - 480, HEX - 125, DEC - 150)
void GP_numToChar(int32_t n, char* buf, uint8_t base) {
    uint8_t l = 2;
    if (base != DEC) {
        int32_t nn = n;
        uint8_t b = (base == HEX) ? 4 : 1;
        while (nn >>= b) l++;
        char *str = &buf[l];
        *--str = '\0';
        do {
            char c = n & (base - 1);
            n >>= b;
            *--str = (c < 10) ? (c + '0') : (c + 'A' - 10);
        } while(n);
    } else {
        uint8_t s = 0;
        if (n < 0) n = -n, s = 1;
        int32_t nn = n;
        while (nn /= base) l++;
        char *str = &buf[l + s];
        *--str = '\0';
        do {
            _GP_div10 res(n);
            n = res.quot;
            *--str = (res.rem < 10) ? (res.rem + '0') : (res.rem + 'A' - 10);
        } while(n);
        if (s) *--str = '-';
    }
}

// преобразовать float в строку
void GP_floatToChar(double f, char *buf, uint8_t decimals) {
    dtostrf(f, decimals + 2, decimals, buf);
}

// преобразовать строку в число
int32_t GP_charToNum(char* buf, uint8_t base) {
    if (base == DEC) return atol(buf);
    else return strtol(buf, NULL, base);
}

// преобразовать строку в float
double GP_charToFloat(char* buf) {
    return atof(buf);
}

// получить число под индексом idx в списке list с разделителем div
int GP_numFromList(char* list, int idx, char div) {
    uint8_t count = 0;
    char* p = list;
    while (1) {
        if (count++ == idx) return atoi(p);
        p = strchr(p, div);
        if (!p++) break;
    }
    return 0;
}

// переписать список list с разделителем div в массив чисел data размером size
uint8_t GP_listToNum(char* list, int* data, uint8_t size, char div) {
    uint8_t count = 0;
    char* offset = list;
    while (1) {
        if (count >= size) break;
        data[count++] = atoi(offset);
        offset = strchr(offset, div);
        if (!offset++) break;
    }
    return count;
}

// преобразовать текстовый цвет (0x, #) в число
uint32_t GP_decodeColor(char* hex) {
    uint32_t val = 0;
    uint8_t i = (hex[0] == '#') ? 1 : ((hex[1] == 'x') ? 2 : 0);
    for (; i < strlen(hex); i++) {
        val <<= 4;
        uint8_t d = hex[i];
        d -= (d <= '9') ? 48 : ((d <= 'F') ? 55 : 87);
        val |= d;
    }
    return val;
}
