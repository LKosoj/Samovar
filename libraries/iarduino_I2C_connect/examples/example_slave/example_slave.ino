// Библиотека iarduino_I2C_connect разработана для удобства соединения нескольких arduino по шине I2C
// Данная Arduino является ведомым устройством на шине I2C с адресом 0x01
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
      byte           REG_Array[2];                    // объявляем массив из двух элементов, данные которого будут доступны мастеру (для чтения/записи) по шине I2C

void setup(){
//Wire.setClock(400000);                              // устанавливаем скорость передачи данных по шине I2C = 400кБит/с
  Wire.begin(0x01);                                   // инициируем подключение к шине I2C в качестве ведомого (slave) устройства, с указанием своего адреса на шине.
  I2C2.begin(REG_Array);                              // инициируем возможность чтения/записи данных по шине I2C, из/в указываемый массив
  pinMode(PIN_Button, INPUT);                         // Устанавливаем режим работы вывода кнопки, как вход
  pinMode(PIN_LED, OUTPUT);                           // Устанавливаем режим работы вывода светодиода, как выход
}

void loop(){
  REG_Array[0] = digitalRead(PIN_Button);             // Сохраняем состояние кнопки в 0 ячейку массива REG_Array
  digitalWrite(PIN_LED, REG_Array[1]);                // Управляем светодиодом в соответствии со значением 1 ячейки массива REG_Array
}

