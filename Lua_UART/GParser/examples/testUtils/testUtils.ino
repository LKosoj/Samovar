// тест утилит для парсинга
#include <GParser.h>

void setup() {
  Serial.begin(9600);

  // список. Данные разделены запятой
  char list[] = "123,456,789,abc,def";
  
  // =====================  
  Serial.println("Split test");
  char* p = list;
  GP_splitList(NULL);
  while ((p = GP_splitList(list)) != NULL) {
    Serial.println(p);
  }
  Serial.println();

  // =====================
  Serial.println("InList test");
  Serial.println(GP_inList("abc", list));
  Serial.println(GP_inList("kek", list));
  Serial.println();

  // =====================
  Serial.println("Num list test");
  Serial.println(GP_numFromList(list, 2));
  Serial.println();

  // =====================
  Serial.println("Array list test");
  int data[3];
  GP_listToNum(list, data, 3);
  for (int i = 0; i < 3; i++) {
    Serial.print(data[i]);
    Serial.print(',');
  }
  Serial.println();
  Serial.println();

  // =====================
  Serial.println("Num to char test");
  char st[30];
  
  GP_numToChar(0x123abc, st, HEX);
  Serial.println(st);
  
  GP_numToChar(123456, st, DEC);
  Serial.println(st);
  
  GP_numToChar(0b11100011, st, BIN);
  Serial.println(st);
  
  GP_floatToChar(3.1415, st, 3);
  Serial.println(st);
  Serial.println();

  // =====================
  Serial.println("Char to num test");
  int32_t val;
  
  val = GP_charToNum("AAFF", HEX);
  Serial.println(val, HEX);
  
  val = GP_charToNum("123456", DEC);
  Serial.println(val, DEC);

  val = GP_charToNum("11000011", BIN);
  Serial.println(val, BIN);

  float valf = GP_charToFloat("3.14");
  Serial.println(valf);
  Serial.println();

  // =====================
  Serial.println("Color test");
  Serial.println(GP_decodeColor("0xFF22"), HEX);
  Serial.println(GP_decodeColor("#FF22"), HEX);
  Serial.println(GP_decodeColor("FF22"), HEX);
}

void loop() {
}
