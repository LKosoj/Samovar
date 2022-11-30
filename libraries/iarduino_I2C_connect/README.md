[![](https://iarduino.ru/img/logo.svg)](https://iarduino.ru)[![](https://wiki.iarduino.ru/img/git-shop.svg?3)](https://iarduino.ru) [![](https://wiki.iarduino.ru/img/git-wiki.svg?2)](https://wiki.iarduino.ru) [![](https://wiki.iarduino.ru/img/git-lesson.svg?2)](https://lesson.iarduino.ru)[![](https://wiki.iarduino.ru/img/git-forum.svg?2)](http://forum.trema.ru)

# iarduino\_I2C\_connect

**This is a library for Arduino IDE by iArduino.ru. It allows to connect multiple [arduinos](https://iarduino.ru/shop/boards/Arduino/) together via I2C bus**

**Данная библиотека для Arduino IDE от [iArduino.ru](https://iarduino.ru) позволяет соединять несколько [ардуин](https://iarduino.ru/shop/boards/Arduino/) по шине I2C**

> Подробнее про установку библиотеки читайте в нашей [инструкции](https://wiki.iarduino.ru/page/Installing_libraries/).

> Подробнее про подключение к [Arduino UNO](https://iarduino.ru/shop/boards/arduino-uno-r3.html)/[Piranha UNO](https://iarduino.ru/shop/boards/piranha-uno-r3.html) читайте в нашем уроке [wiki](https://lesson.iarduino.ru/page/urok-26-3-soedinyaem-dve-arduino-po-shine-i2c/)


| Модель | Ссылка на магазин |
|---|---|
| <p>Piranha Uno R3</p> <img src="https://wiki.iarduino.ru/img/resources/973/973.svg" width="235px"></img>| https://iarduino.ru/shop/boards/piranha-uno-r3.html |
| <p>Piranha Ultra R3</p> <img src="https://wiki.iarduino.ru/img/resources/1181/1181.svg" width="235px"></img>| https://iarduino.ru/shop/boards/piranha-ultra.html |
| <p>Piranha Pro Mini (без пинов)</p> <img src="https://wiki.iarduino.ru/img/resources/1099/1099.svg" width="150px"></img>| https://iarduino.ru/shop/boards/piranha-pro-mini-bez-nog.html |
| <p>Piranha Pro Mini (с пинами)</p> <img src="https://wiki.iarduino.ru/img/resources/1098/1098.svg" width="191px"></img>| https://iarduino.ru/shop/boards/piranha-pro-mini-s-nogami.html |


## Назначение функций:

**Подробное описание работы с библиотекой и примеры смотрите на [нашем сайте](https://lesson.iarduino.ru/page/urok-26-3-soedinyaem-dve-arduino-po-shine-i2c/)**

### Подключение библиотеки:

```C++
#include <Wire.h>
#include <iarduino_I2C_connect.h>
iarduino_I2C_connect ОБЪЕКТ; //Создание объекта библиотеки
```
### В библиотеке реализованы 4 функции:

**ДЛЯ ВЕДОМОГО:**

```C++
ОБЪЕКТ.begin()
```

- Назначение: указание массива, элементы которого будут доступны для чтения/записи по шине I2C
- Синтаксис: **begin**(массив);
- Параметр: массив (тип **byte**)
- Возвращаемые значения: Нет
- Примечание: Вызывается 1 раз в начале кода.

```C++
ОБЪЕКТ.writeMask()
```

- Назначение: указание маскировочного массива, значение **true** элемента данного массива - разрешает менять значение соответствующего элемента в массиве, объявленном в функции begin()
- Синтаксис: **writeMask**(маскировочный\_массив);
- Параметр: маскировочный массив (тип **bool**)
- Возвращаемые значения: Нет
- Примечание: Вызывается 1 раз в начале кода.

Если указать массив, который состоит из 5 ячеек {0,1,1,1,0}, то мастер не сможет изменить значения 0 и 4 элементов массива доступного по шине I2C, который был объявлен в функции **begin**(). Но все элементы массива будут доступны для чтения

Если указать массив, который состоит из 5 ячеек, в то время как массив доступный по шине I2C содержит 10 ячеек, то мастер не сможет изменить значения последних 5 ячеек, а значения первых сможет изменить только если соответствующие ячейки маскировочного массива равны 1 или **true**

Если не объявлять маскировочный массив (не вызывать функцию **writeMask** ), то все элементы массива, доступного по шине I2C, который был объявлен в функции **begin**(), будут доступны мастеру для записи и чтения.

**ДЛЯ ВЕДУЩЕГО:**

```C++
ОБЪЕКТ.readByte()
```

- Назначение: Чтение одного байта данных из устройства на шине I2C
- Синтаксис: **readByte**(адрес\_устройства, адрес\_регистра);
- Параметры: 
  - адрес\_устройства - данные которого требуется получить (число от **0x00** до **0x7F**)
  - адрес\_регистра - данные которого требуется получить (число от **0x00** до **0xFF**) // адрес регистра соответствует номеру элемента массива объявленного ведомым устройством функцией begin
- Возвращаемые значения: uint8\_t **байт** - данные считанные из указанного адреса, указанного устройства

```C++
ОБЪЕКТ.writeByte()
```

- Назначение: Запись одного байта данных в устройство на шине I2C
- Синтаксис: **writeByte**(адрес\_устройства, адрес\_регистра, байт\_данных);
- Параметры: 
  - адрес\_устройства - которому предназначены отправляемые данные (число от **0x00** до **0x7F**)
  - адрес\_регистра - которому предназначены отправляемые данные (число от **0x00** до **0xFF**) // адрес регистра соответствует номеру элемента массива объявленного ведомым устройством функцией begin
  - байт\_данных - который требуется записать в указанный регистр, указанного устройства
- Возвращаемые значения: uint8\_t **байт** - результат операции записи, соответствует значению возвращаемому функцией Wire.endTransmission()
  - 0 - успех
  - 1 - переполнение буфера передачи данных
  - 2 - получен NACK на переданный адрес устройства
  - 3 - получен NACK на переданный адрес регистра
  - 4 - неизвестная ошибка
