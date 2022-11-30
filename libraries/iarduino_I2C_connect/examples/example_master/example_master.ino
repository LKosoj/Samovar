// Библиотека iarduino_I2C_connect разработана для удобства соединения нескольких arduino по шине I2C
// Данная Arduino является ведущим устройством на шине I2C
// Arduino                                            http://iarduino.ru/shop/arduino/
// Trema кнопка                                       http://iarduino.ru/shop/Expansion-payments/knopka-trema-modul.html
// Trema светодиод                                    http://iarduino.ru/shop/Expansion-payments/svetodiod---zelenyy-trema-modul.html
//
// Светодиод нужно подключить к цифровому выводу D13, а кнопку к цифровому выводу D2

// Подключаем библиотеки:
#include <Wire.h>                                     // подключаем библиотеку для работы с шиной I2C
#include <iarduino_I2C_connect.h>                     // подключаем библиотеку для соединения arduino по шине I2C

// Объявляем переменные и константы:
iarduino_I2C_connect I2C2;                            // объявляем объект I2C2 для работы c библиотекой iarduino_I2C_connect
const byte           PIN_Button = 2;                  // объявляем константу с указанием номера цифрового вывода, к которому подключена кнопка
const byte           PIN_LED    = 13;                 // объявляем константу с указанием номера цифрового вывода, к которому подключен светодиод

void setup(){
//Wire.setClock(400000);                              // устанавливаем скорость передачи данных по шине I2C = 400кБит/с
  Wire.begin();                                       // инициируем подключение к шине I2C в качестве ведущего (master) устройства.
  pinMode(PIN_Button, INPUT);                         // Устанавливаем режим работы вывода кнопки, как вход
  pinMode(PIN_LED, OUTPUT);                           // Устанавливаем режим работы вывода светодиода, как выход
}

void loop(){
//Отправляем данные:
  bool i = digitalRead(PIN_Button);                   // Читаем состояние собственной кнопки с вывода PIN_Button
  I2C2.writeByte(0x01, 1, i);                         // Отправляем состояние собственной кнопки ведомому (адрес ведомого 0x01, номер регистра 1, состояние кнопки i)
  byte j = I2C2.readByte(0x01,0);                     // Читаем значение 0 ячейки массива ведомого с адресом 0x01
  digitalWrite(PIN_LED, j);                           // Управляем светодиодом в соответствии c прочитанным значением
}
