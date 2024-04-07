// тест утилит для парсинга
#include <GParser.h>

void setup() {
  Serial.begin(9600);
  String enc = GP_urlencode("https://kek.ru/#абвг");
  Serial.println(enc);
  Serial.println(GP_urldecode(enc));
}

void loop() {
}
