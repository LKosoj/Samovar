// тест утилит для парсинга
#include <GParser.h>

void setup() {
  Serial.begin(9600);
  // неправильно посчитает длину строки
  Serial.println(strlen("Привет!"));
  // правильно посчитает длину строки
  Serial.println(GP_unistrlen("Привет!"));

  Serial.println(GP_uniencode(0x27A1));
}

void loop() {
}
