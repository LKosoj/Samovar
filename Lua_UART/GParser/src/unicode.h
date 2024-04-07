#pragma once
#include <Arduino.h>
char* GP_uniencode(int32_t c, char* s);
String GP_uniencode(uint16_t c);
uint16_t GP_unistrlen(char* data);