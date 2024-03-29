#include <Wire.h>

#include "ASOLED.h"

#include "mice.c"

static const unsigned char PROGMEM Logo_BMP[] =
{ 0x10, 0x10, 0xff, 0x01,
  B00000000,  B00000001,  B00000001,  B00000011,  B11110011,  B11111110,  B01111110,  B00110011,
  B00011111,  B00001101,  B00011011,  B00111111,  B00111111,  B01111100,  B01110000,  B00000000,
  B11000000,  B11000000,  B11000000,  B11100000,  B11100000,  B11111000,  B11111111,  B10011111,
  B11111100,  B01110000,  B10100000,  B11100000,  B11110000,  B11110000,  B01110000,  B00110000 };

const uint8_t pacman[] PROGMEM={
  0x14, 0x18, 0x00, 0x01,
0x80, 0xE0, 0xF0, 0xF8, 0xFC, 0xFE, 0xFE, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x7E, 0x3E, 0x1C,   // 0x0010 (16) pixels
0x0C, 0x00, 0x00, 0x00, 0x1F, 0x7F, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xF9,   // 0x0020 (32) pixels
0xF0, 0xE0, 0xC0, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x03, 0x07, 0x07, 0x0F,   // 0x0030 (48) pixels
0x0F, 0x0F, 0x0F, 0x0F, 0x0F, 0x07, 0x07, 0x03, 0x03, 0x00, 0x00, 0x00, 

0x80, 0xE0, 0xF0, 0xF8, 0xFC, 0xFE, 0xFE, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFE, 0xFE, 0x7C,   // 0x0010 (16) pixels
0x7C, 0x38, 0x20, 0x00, 0x1F, 0x7F, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xF9,   // 0x0020 (32) pixels
0xF9, 0xF0, 0xF0, 0xE0, 0xE0, 0xC0, 0x40, 0x00, 0x00, 0x00, 0x00, 0x01, 0x03, 0x07, 0x07, 0x0F,   // 0x0030 (48) pixels
0x0F, 0x0F, 0x0F, 0x0F, 0x0F, 0x07, 0x07, 0x03, 0x03, 0x01, 0x00, 0x00, 

0x80, 0xE0, 0xF0, 0xF8, 0xFC, 0xFE, 0xFE, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFE, 0xFE, 0xFC,   // 0x0010 (16) pixels
0xF8, 0xF0, 0xE0, 0x80, 0x1F, 0x7F, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,   // 0x0020 (32) pixels
0xFF, 0xFF, 0xFF, 0xFF, 0xFB, 0xF9, 0x79, 0x19, 0x00, 0x00, 0x00, 0x01, 0x03, 0x07, 0x07, 0x0F,   // 0x0030 (48) pixels
0x0F, 0x0F, 0x0F, 0x0F, 0x0F, 0x07, 0x07, 0x03, 0x01, 0x00, 0x00, 0x00, 
};   

const uint8_t pacman_clear[] PROGMEM={
  0x03, 0x18, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};

const uint8_t pill[] PROGMEM={
  0x05, 0x08, 0x00, 0x01,
0x0E, 0x1F, 0x1F, 0x1F, 0x0E, 
};
 
int State = 0;
long NewTime, OldTime;

void setup()
{
  OldTime = millis();
  LD.init();  //initialze OLED display
  LD.clearDisplay(); 
}


void loop()
{
  int n0 = 123;
  int n1 = -321;
//  byte i;
  float d0 = 456.789;
  float d1 = -0.00789;
  NewTime = millis();
  if ((NewTime - OldTime) > 5000)
  {
    OldTime = NewTime;
    State = ++State % 6;
    LD.clearDisplay();
  }
  byte phase = NewTime/150%4;
  if (phase == 3) phase = 1;
  byte Xpacman = (NewTime-OldTime)/50 + 8;
//  State = 5;
  switch (State)
  {
    case 0:
        LD.printString_6x8("0123456789!\"#$%&'()*+", 0, 0);
        LD.printString_6x8(",-./:;<=>?@[\\]^_`{|}~", 0, 1);
        LD.printString_6x8("ABCDEFGHIJKLMNOPQRSTU", 0, 2);
        LD.printString_6x8("VWXYZabcdefghijklmnop",0, 3);
        LD.printString_6x8("qrstuvwxyzАБВГДЕЁЖЗИЙ", 0, 4);
        LD.printString_6x8("КЛМНОПРСТУФХЦЧШЩЪЫЬЭЮ", 0, 5);
        LD.printString_6x8("Яабвгдеёжзийклмнопрст", 0, 6);
        LD.printString_6x8("уфхцчшщъыьэюяЇїЎў§°±µ", 0, 7);
        break;
    case 1:
        LD.printString_12x16("012345%&'+", 0, 0);
        LD.printString_12x16("ABCDEFGHIJ", 0, 2);
        LD.printString_12x16("vwxyzАБВЕЁ", 0, 4);
        LD.printString_12x16("юяЇїЎў§°±µ", 0, 6);
        break;
    case 2:
        for (int i = 0; i < 128; i++){
          int j = (int)(sin(i*0.09 + 0.2)*35) + 45;
          LD.VertBar(i, j, 0, 90);
        }
        break;
    case 3:
        LD.printNumber((long)n0, 0, 0);  // 123
        LD.printNumber((long)n1, 0, 2); // -321
        LD.printNumber(d0, 6, 60, 2);     // 456.789
        LD.printNumber(-d0, 6, 48, 0);   // -456.789
        LD.printNumber(d1, 8, 0, 6);     // 0.00789
        LD.printNumber((long)10, 28, 4);        // 10
        LD.printString_6x8("3"); //, 0, 4);  // ^3
        LD.printString_12x16("="); //, 0, 4); // =
        LD.printNumber((long)1000); //, 0, 4);  // 1000
        break;
    case 4 :
        LD.drawBitmap(mice, 0, 0, 128, 8);
        break;
    case 5 :
        for(byte i = 0; i < 5; i++)
          if (i*24 > Xpacman)
            LD.drawBitmap(pill,  26 + i*24, 1, 5, 1);
        LD.drawBitmap(pacman_clear,  Xpacman-3, 0, 3, 2);
        LD.drawBitmap(&pacman[phase*60],  Xpacman, 0, 20, 3);
        LD.drawBitmap(Logo_BMP, 100, 6); //, 16, 2);
        LD.printString_6x8("Small ", 0, 4);  // ^3
        LD.printNumber((long)n0);  // 123
        LD.printNumber(-d0);   // -456.789
        LD.printString_12x16("Big ", 0, 6); // =
        LD.printNumber((long)n0);  // 123
        break;
  }
}
