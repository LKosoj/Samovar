[![latest](https://img.shields.io/github/v/release/GyverLibs/GParser.svg?color=brightgreen)](https://github.com/GyverLibs/GParser/releases/latest/download/GParser.zip)
[![Foo](https://img.shields.io/badge/Website-AlexGyver.ru-blue.svg?style=flat-square)](https://alexgyver.ru/)
[![Foo](https://img.shields.io/badge/%E2%82%BD$%E2%82%AC%20%D0%9D%D0%B0%20%D0%BF%D0%B8%D0%B2%D0%BE-%D1%81%20%D1%80%D1%8B%D0%B1%D0%BA%D0%BE%D0%B9-orange.svg?style=flat-square)](https://alexgyver.ru/support_alex/)
[![Foo](https://img.shields.io/badge/README-ENGLISH-blueviolet.svg?style=flat-square)](https://github-com.translate.goog/GyverLibs/GParser?_x_tr_sl=ru&_x_tr_tl=en)  

[![Foo](https://img.shields.io/badge/ПОДПИСАТЬСЯ-НА%20ОБНОВЛЕНИЯ-brightgreen.svg?style=social&logo=telegram&color=blue)](https://t.me/GyverLibs)

|⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️<br><br>**ВНИМАНИЕ, БИБЛИОТЕКА УСТАРЕЛА! ИСПОЛЬЗУЙ БИБЛИОТЕКУ [StringUtils](https://github.com/GyverLibs/StringUtils), ОНА ИМЕЕТ БОЛЬШЕ ВОЗМОЖНОСТЕЙ**<br><br>⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️⚠️|
| --- |

# GParser
Простой и быстрый парсер строк в отдельные подстроки и числа для Arduino
- Работает с указанным буфером (строкой), не создаёт свой
- Разделяет строку на подстроки по указанному символу
- Позволяет обращаться к подстрокам, переводить их в числа и сравнивать со строками
- Доступ к подстрокам через []
- Может распарсить строку в массив int или byte

### Совместимость
Совместима со всеми Arduino платформами (используются Arduino-функции)

## Содержание
- [Установка](#install)
- [Инициализация](#init)
- [Использование](#usage)
- [Пример](#example)
- [Версии](#versions)
- [Баги и обратная связь](#feedback)

<a id="install"></a>
## Установка
- Библиотеку можно найти по названию **GParser** и установить через менеджер библиотек в:
    - Arduino IDE
    - Arduino IDE v2
    - PlatformIO
- [Скачать библиотеку](https://github.com/GyverLibs/GParser/archive/refs/heads/main.zip) .zip архивом для ручной установки:
    - Распаковать и положить в *C:\Program Files (x86)\Arduino\libraries* (Windows x64)
    - Распаковать и положить в *C:\Program Files\Arduino\libraries* (Windows x32)
    - Распаковать и положить в *Документы/Arduino/libraries/*
    - (Arduino IDE) автоматическая установка из .zip: *Скетч/Подключить библиотеку/Добавить .ZIP библиотеку…* и указать скачанный архив
- Читай более подробную инструкцию по установке библиотек [здесь](https://alexgyver.ru/arduino-first/#%D0%A3%D1%81%D1%82%D0%B0%D0%BD%D0%BE%D0%B2%D0%BA%D0%B0_%D0%B1%D0%B8%D0%B1%D0%BB%D0%B8%D0%BE%D1%82%D0%B5%D0%BA)
### Обновление
- Рекомендую всегда обновлять библиотеку: в новых версиях исправляются ошибки и баги, а также проводится оптимизация и добавляются новые фичи
- Через менеджер библиотек IDE: найти библиотеку как при установке и нажать "Обновить"
- Вручную: **удалить папку со старой версией**, а затем положить на её место новую. "Замену" делать нельзя: иногда в новых версиях удаляются файлы, которые останутся при замене и могут привести к ошибкам!


<a id="init"></a>
## Инициализация
```cpp
// передать char array строку, можно указать символ разделитель (по умолч ',')
GParser (char* data);
GParser (char* data, char newDiv = ',');
```

<a id="usage"></a>
## Использование
### Класс GParser
```cpp
void setDiv(char newDiv);       // указать символ разделитель
void clear();                   // освободить буфер
int amount();                   // количество разделённых данных в пакете
int split();                    // разделить строку на подстроки
int32_t getInt(int num);        // получить инт из выбранной подстроки
float getFloat(int num);        // получить float из выбранной подстроки
bool equals(int num, const char* comp); // сравнить подстроку с другой строкой
int parseBytes(byte* data);     // распарсить на байты
int parseInts(int* data);       // распарсить на инты
int parseLongs(long* data);     // распарсить на лонги
void restore();                 // восстановить исходный вид строки (вернуть разделители)
```

### Отдельные функции парсинга
См. пример **testUtils**

```cpp
// количество подстрок в списке list с разделителем div
uint8_t GP_listSize(char* list, char div = ',');

// разделить список list с разделителем div на подстроки (см. пример)
char* GP_splitList(char* list, char div = ',');

// получить номер, под которым name входит в list с разделителем div. -1 если не входит
int8_t GP_inList(char* name, char* list, char div = ',');

// преобразовать int в строку (работает в 3-10 раз быстрее ltoa + основание)
void GP_numToChar(int32_t n, char* buf, uint8_t base);

// преобразовать float в строку
void GP_floatToChar(double f, char *buf, uint8_t decimals);

// преобразовать строку в число
int32_t GP_charToNum(char* buf, uint8_t base);

// преобразовать строку в float
double GP_charToFloat(char* buf);

// получить число под индексом idx в списке list с разделителем div
int GP_numFromList(char* list, int idx, char div = ',');

// переписать список list с разделителем div в массив чисел data размером size
uint8_t GP_listToNum(char* list, int* data, uint8_t size, char div = ',');

// преобразовать текстовый цвет (0x, #) в число
uint32_t GP_decodeColor(char* hex);
```

### Unicode
См. пример **testUnicode**

```cpp
char* GP_uniencode(int32_t c, char* s);     // код unicode в char[5]
String GP_uniencode(uint16_t c);            // код unicode в String
uint16_t GP_unistrlen(char* data);          // длина unicode строки в кол-ве символов
```

### Url encode/decode
См. пример **testUrl**

```cpp
void GP_urlencode(const String& s, String& dest);       // urlencode из String в String
String GP_urlencode(const String& s);                   // urlencode из String в String (возврат)
String GP_urldecode(const String& s, String& dest);     // urldecode из String в String
String GP_urldecode(const String& s);                   // urldecode из String в String (возврат)
```

<a id="example"></a>
## Пример
Остальные примеры смотри в **examples**!
```cpp
// тест парсера строк
#include <GParser.h>

void setup() {
  Serial.begin(9600);

  // ==================== ПРИМЕР 1 ======================
  // строка для примера
  // данные разделены разделителем, например запятой
  // могут быть получены из Serial/UDP/TCP/MQTT итд
  char str[] = "1234,3.14,hello,4567,lolkek,qwerty";

  // кормим строку парсеру, указываем разделитель (умолч. запятая)
  GParser data(str, ',');

  // разделяем
  // ВНИМАНИЕ! Операция "ломает" строку, заменяя разделители на NULL
  int am = data.split();
  // получаем количество данных

  Serial.println(am); // выводим количество

  // можем обратиться к полученным строкам как data[i] или data.str[i]
  for (byte i = 0; i < am; i++) Serial.println(data[i]);

  // также можно получить их в виде int и float чисел
  // передав индекс строки
  Serial.println(data.getInt(0));
  Serial.println(data.getFloat(1));

  // можно сравнить со строкой (номер парс строки, строка для сравнения)
  if (data.equals(2, "hello")) Serial.println("true");
  else Serial.println("false");
  
  Serial.println();
  
  // ==================== ПРИМЕР 2 ======================
  // быстрый парсинг целочисленных данных с разделителем
  char str2[] = "123,456,789,222,333,444";
  GParser data2(str2);   // кормим строку парсеру

  // создаём массив с количеством ячеек data2.amount() - столько данных в пакете
  int ints[data2.amount()];
  
  int am2 = data2.parseInts(ints);  // раскидает в указанный массив и вернёт количество
  // фактически тут am2 == data2.amount() - количество данных
  // выводим
  for (byte i = 0; i < am; i++) Serial.println(ints[i]);
}

void loop() {
}

```

<a id="versions"></a>
## Версии
- v1.0
- v1.1 - добавлены отдельные инструменты для парсинга
- v1.2 - добавлены ещё инструменты для парсинга
- v1.3 - добавлена возможность восстановить строку
- v1.3.1 - фикс warning
- v1.4 - добавил url и unicode кодирование
- v1.5 - getInt теперь возвращает int32_t

<a id="feedback"></a>
## Баги и обратная связь
При нахождении багов создавайте **Issue**, а лучше сразу пишите на почту [alex@alexgyver.ru](mailto:alex@alexgyver.ru)  
Библиотека открыта для доработки и ваших **Pull Request**'ов!


При сообщении о багах или некорректной работе библиотеки нужно обязательно указывать:
- Версия библиотеки
- Какой используется МК
- Версия SDK (для ESP)
- Версия Arduino IDE
- Корректно ли работают ли встроенные примеры, в которых используются функции и конструкции, приводящие к багу в вашем коде
- Какой код загружался, какая работа от него ожидалась и как он работает в реальности
- В идеале приложить минимальный код, в котором наблюдается баг. Не полотно из тысячи строк, а минимальный код
