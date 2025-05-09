#include <pgmspace.h>

const uint8_t SmallFont[] PROGMEM = {
0x05, 0x08, 0x20, 0xb1,
0x00, 0x00, 0x00, 0x00, 0x00,   // sp
0x00, 0x00, 0x2f, 0x00, 0x00,   // !
0x00, 0x07, 0x00, 0x07, 0x00,   // "
0x14, 0x7f, 0x14, 0x7f, 0x14,   // #
0x24, 0x2a, 0x7f, 0x2a, 0x12,   // $
0x23, 0x13, 0x08, 0x64, 0x62,   // %
0x36, 0x49, 0x55, 0x22, 0x50,   // &
0x00, 0x05, 0x03, 0x00, 0x00,   // '
0x00, 0x1c, 0x22, 0x41, 0x00,   // (
0x00, 0x41, 0x22, 0x1c, 0x00,   // )
0x14, 0x08, 0x3E, 0x08, 0x14,   // *
0x08, 0x08, 0x3E, 0x08, 0x08,   // +
0x00, 0x00, 0xA0, 0x60, 0x00,   // ,
0x08, 0x08, 0x08, 0x08, 0x08,   // -
0x00, 0x60, 0x60, 0x00, 0x00,   // .
0x20, 0x10, 0x08, 0x04, 0x02,   // /

0x3E, 0x51, 0x49, 0x45, 0x3E,   // 0
0x00, 0x42, 0x7F, 0x40, 0x00,   // 1
0x42, 0x61, 0x51, 0x49, 0x46,   // 2
0x21, 0x41, 0x45, 0x4B, 0x31,   // 3
0x18, 0x14, 0x12, 0x7F, 0x10,   // 4
0x27, 0x45, 0x45, 0x45, 0x39,   // 5
0x3C, 0x4A, 0x49, 0x49, 0x30,   // 6
0x01, 0x71, 0x09, 0x05, 0x03,   // 7
0x36, 0x49, 0x49, 0x49, 0x36,   // 8
0x06, 0x49, 0x49, 0x29, 0x1E,   // 9
0x00, 0x36, 0x36, 0x00, 0x00,   // :
0x00, 0x56, 0x36, 0x00, 0x00,   // ;
0x08, 0x14, 0x22, 0x41, 0x00,   // <
0x14, 0x14, 0x14, 0x14, 0x14,   // =
0x00, 0x41, 0x22, 0x14, 0x08,   // >
0x02, 0x01, 0x51, 0x09, 0x06,   // ?

0x32, 0x49, 0x59, 0x51, 0x3E,   // @
0x7C, 0x12, 0x11, 0x12, 0x7C,   // A
0x7F, 0x49, 0x49, 0x49, 0x36,   // B
0x3E, 0x41, 0x41, 0x41, 0x22,   // C
0x7F, 0x41, 0x41, 0x22, 0x1C,   // D
0x7F, 0x49, 0x49, 0x49, 0x41,   // E
0x7F, 0x09, 0x09, 0x09, 0x01,   // F
0x3E, 0x41, 0x49, 0x49, 0x7A,   // G
0x7F, 0x08, 0x08, 0x08, 0x7F,   // H
0x00, 0x41, 0x7F, 0x41, 0x00,   // I
0x20, 0x40, 0x41, 0x3F, 0x01,   // J
0x7F, 0x08, 0x14, 0x22, 0x41,   // K
0x7F, 0x40, 0x40, 0x40, 0x40,   // L
0x7F, 0x02, 0x0C, 0x02, 0x7F,   // M
0x7F, 0x04, 0x08, 0x10, 0x7F,   // N
0x3E, 0x41, 0x41, 0x41, 0x3E,   // O

0x7F, 0x09, 0x09, 0x09, 0x06,   // P
0x3E, 0x41, 0x51, 0x21, 0x5E,   // Q
0x7F, 0x09, 0x19, 0x29, 0x46,   // R
0x46, 0x49, 0x49, 0x49, 0x31,   // S
0x01, 0x01, 0x7F, 0x01, 0x01,   // T
0x3F, 0x40, 0x40, 0x40, 0x3F,   // U
0x1F, 0x20, 0x40, 0x20, 0x1F,   // V
0x3F, 0x40, 0x38, 0x40, 0x3F,   // W
0x63, 0x14, 0x08, 0x14, 0x63,   // X
0x07, 0x08, 0x70, 0x08, 0x07,   // Y
0x61, 0x51, 0x49, 0x45, 0x43,   // Z
0x00, 0x7F, 0x41, 0x41, 0x00,   // [
0x01, 0x06, 0x08, 0x30, 0x40,   // Backslash
0x00, 0x41, 0x41, 0x7F, 0x00,   // ]
0x04, 0x02, 0x01, 0x02, 0x04,   // ^
0x40, 0x40, 0x40, 0x40, 0x40,   // _

0x00, 0x03, 0x05, 0x00, 0x00,   // `
0x20, 0x54, 0x54, 0x54, 0x78,   // a
0x7F, 0x48, 0x44, 0x44, 0x38,   // b
0x38, 0x44, 0x44, 0x44, 0x20,   // c
0x38, 0x44, 0x44, 0x48, 0x7F,   // d
0x38, 0x54, 0x54, 0x54, 0x18,   // e
0x08, 0x7E, 0x09, 0x01, 0x02,   // f
0x18, 0xA4, 0xA4, 0xA4, 0x7C,   // g
0x7F, 0x08, 0x04, 0x04, 0x78,   // h
0x00, 0x44, 0x7D, 0x40, 0x00,   // i
0x40, 0x80, 0x84, 0x7D, 0x00,   // j
0x7F, 0x10, 0x28, 0x44, 0x00,   // k
0x00, 0x41, 0x7F, 0x40, 0x00,   // l
0x7C, 0x04, 0x18, 0x04, 0x78,   // m
0x7C, 0x08, 0x04, 0x04, 0x78,   // n
0x38, 0x44, 0x44, 0x44, 0x38,   // o

0xFC, 0x24, 0x24, 0x24, 0x18,   // p
0x18, 0x24, 0x24, 0x18, 0xFC,   // q
0x7C, 0x08, 0x04, 0x04, 0x08,   // r
0x48, 0x54, 0x54, 0x54, 0x20,   // s
0x04, 0x3F, 0x44, 0x40, 0x20,   // t
0x3C, 0x40, 0x40, 0x20, 0x7C,   // u
0x1C, 0x20, 0x40, 0x20, 0x1C,   // v
0x3C, 0x40, 0x30, 0x40, 0x3C,   // w
0x44, 0x28, 0x10, 0x28, 0x44,   // x
0x1C, 0xA0, 0xA0, 0xA0, 0x7C,   // y
0x44, 0x64, 0x54, 0x4C, 0x44,   // z
0x00, 0x10, 0x7C, 0x82, 0x00,   // {
0x00, 0x00, 0xFF, 0x00, 0x00,   // |
0x00, 0x82, 0x7C, 0x10, 0x00,   // }
0x08, 0x04, 0x08, 0x10, 0x08,   // 7E    126   ~
0x7C, 0x12, 0x11, 0x12, 0x7C,   // А

0x7F, 0x49, 0x49, 0x49, 0x31,   // Б
0x7F, 0x45, 0x45, 0x45, 0x3A,   // В
0x7F, 0x01, 0x01, 0x01, 0x03,   // Г
0x60, 0x3F, 0x21, 0x3F, 0x60,   // Д
0x7F, 0x49, 0x49, 0x49, 0x41,   // Е
0x73, 0x0C, 0x7F, 0x0C, 0x73,   // Ж
0x21, 0x41, 0x49, 0x4D, 0x33,   // З
0x7F, 0x10, 0x08, 0x04, 0x7F,   // И
0x7E, 0x20, 0x11, 0x08, 0x7E,   // Й
0x7F, 0x08, 0x14, 0x22, 0x41,   // К
0x40, 0x3F, 0x01, 0x01, 0x7F,   // Л
0x7F, 0x06, 0x08, 0x06, 0x7F,   // М
0x7F, 0x08, 0x08, 0x08, 0x7F,   // Н
0x3E, 0x41, 0x41, 0x41, 0x3E,   // О
0x7F, 0x01, 0x01, 0x01, 0x7F,   // П
0x7F, 0x09, 0x09, 0x09, 0x06,   // Р

0x3E, 0x41, 0x41, 0x41, 0x22,   // С
0x03, 0x01, 0x7F, 0x01, 0x03,   // Т
0x61, 0x26, 0x18, 0x06, 0x01,   // У
0x1C, 0x22, 0x7F, 0x22, 0x1C,   // Ф
0x63, 0x14, 0x08, 0x14, 0x63,   // Х
0x3F, 0x20, 0x20, 0x3F, 0x60,   // Ц
0x07, 0x08, 0x08, 0x08, 0x7F,   // Ч
0x7F, 0x40, 0x7F, 0x40, 0x7F,   // Ш
0x3F, 0x20, 0x3F, 0x20, 0x7F,   // Щ
0x01, 0x7F, 0x48, 0x48, 0x30,   // Ъ
0x7F, 0x48, 0x78, 0x00, 0x7F,   // Ы
0x7F, 0x48, 0x48, 0x30, 0x00,   // Ь
0x41, 0x49, 0x49, 0x2A, 0x1C,   // Э
0x7F, 0x10, 0x3E, 0x41, 0x3E,   // Ю
0x66, 0x19, 0x09, 0x09, 0x7F,   // Я
0x20, 0x54, 0x54, 0x78, 0x40,   // а

0x3E, 0x49, 0x45, 0x45, 0x38,   // б
0x7E, 0x4A, 0x4A, 0x34, 0x00,   // в
0x7C, 0x04, 0x04, 0x0C, 0x00,   // г
0x38, 0x45, 0x45, 0x49, 0x3E,   // д
0x38, 0x54, 0x54, 0x54, 0x18,   // е
0x4C, 0x30, 0x7C, 0x30, 0x4C,   // ж
0x24, 0x42, 0x4A, 0x34, 0x00,   // з
0x7C, 0x20, 0x10, 0x7C, 0x00,   // и
0x7C, 0x21, 0x11, 0x7C, 0x00,   // й
0x7C, 0x10, 0x28, 0x44, 0x00,   // к
0x40, 0x3C, 0x04, 0x04, 0x7C,   // л
0x7C, 0x08, 0x10, 0x08, 0x7C,   // м
0x7C, 0x10, 0x10, 0x7C, 0x00,   // н
0x38, 0x44, 0x44, 0x44, 0x38,   // о
0x7C, 0x04, 0x04, 0x7C, 0x00,   // п
0xFC, 0x18, 0x24, 0x24, 0x18,   // р

0x38, 0x44, 0x44, 0x44, 0x28,   // с
0x04, 0x04, 0x7C, 0x04, 0x04,   // т
0x4C, 0x90, 0x90, 0x90, 0x7C,   // у
0x18, 0x24, 0x7E, 0x24, 0x18,   // ф
0x44, 0x28, 0x10, 0x28, 0x44,   // х
0x3C, 0x20, 0x20, 0x3C, 0x60,   // ц
0x1C, 0x10, 0x10, 0x7C, 0x00,   // ч
0x7C, 0x40, 0x7C, 0x40, 0x7C,   // ш
0x3C, 0x20, 0x3C, 0x20, 0x7C,   // щ
0x04, 0x7C, 0x50, 0x70, 0x00,   // ъ
0x7C, 0x50, 0x70, 0x00, 0x7C,   // ы
0x7C, 0x50, 0x70, 0x00, 0x00,   // ь
0x42, 0x42, 0x52, 0x52, 0x3C,   // э
0x7C, 0x10, 0x38, 0x44, 0x38,   // ю
0x40, 0x2C, 0x12, 0x7E, 0x00,   // я
0x7E, 0x4B, 0x4A, 0x4B, 0x42,   //            Ё   D0 81

0x38, 0x55, 0x54, 0x55, 0x18,   //            ё   D1 91
0x7C, 0x04, 0x05, 0x04, 0x00,   //81    129   Ѓ   D0 83
0x00, 0x78, 0x0A, 0x09, 0x00,   //83    131   ѓ   D1 93
0x3E, 0x49, 0x49, 0x41, 0x22,   //AA    170   Є   D0 84
0x38, 0x54, 0x54, 0x44, 0x28,   //BA    186   є   D1 94
0x00, 0x41, 0x7F, 0x41, 0x00,   //B2    178   І   D0 86
0x00, 0x44, 0x7D, 0x40, 0x00,   //B3    179   і   D1 96
0x00, 0x45, 0x7C, 0x45, 0x00,   //AF    175   Ї   D0 87
0x00, 0x45, 0x7C, 0x41, 0x00,   //BF    191   ї   D1 97
0x23, 0x44, 0x39, 0x04, 0x03,   //A1    161   Ў   D0 8E
0x24, 0x49, 0x32, 0x09, 0x04,   //A2    162   ў   D1 9E
0x7E, 0x02, 0x02, 0x02, 0x01,   //A5    165   Ґ   D2 90
0x7C, 0x04, 0x04, 0x02, 0x00,   //B4    180   ґ   D2 91
0x00, 0x4A, 0x55, 0x29, 0x00,   //A7    167   §   C2 A7
0x00, 0x06, 0x09, 0x09, 0x06,   //            °   C2 B0
0x44, 0x44, 0x5F, 0x44, 0x44,   //B1    177   ±   C2 B1

0x7C, 0x10, 0x10, 0x3C, 0x40,   //B5    181   µ   C2 B5
};


