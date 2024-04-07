#include "unicode.h"
char* GP_uniencode(int32_t c, char* s) {
    if (c < 0x80) {
        s[0] = (c & 0x7F) | 0x00;
        s[1] = 0;
    } else if (c < 0x0800) {
        s[0] = (c >> 6 & 0x1F) | 0xC0;
        s[1] = (c & 0x3F) | 0x80;
        s[2] = 0;
    } else if (c < 0x010000) {
        s[0] = (c >> 12 & 0x0F) | 0xE0;
        s[1] = (c >> 6 & 0x3F) | 0x80;
        s[2] = (c & 0x3F) | 0x80;
        s[3] = 0;
    } else if (c < 0x110000) {
        s[0] = (c >> 18 & 0x07) | 0xF0;
        s[1] = (c >> 12 & 0x3F) | 0x80;
        s[2] = (c >> 6 & 0x3F) | 0x80;
        s[3] = (c & 0x3F) | 0x80;
        s[4] = 0;
    }
    return s;
}

String GP_uniencode(uint16_t c) {
    char str[5];
    return String(GP_uniencode(c, str));
}

uint16_t GP_unistrlen(char* data) {
    uint16_t i = 0, count = 0;
    while (data[i]) {
        if ((data[i] & 0xc0) != 0x80) count++;
        i++;
    }
    return count;
}