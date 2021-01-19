# Samovar
Скетч для ESP32.
Предназначен для управления ректификационной колонной. Необходимые библиотеки выложены в каталоге library, остальные грузятся из репозитория библиотек через Arduino IDE

Устройство контролирует 4 температуры, управляет 4 реле (пока задействовано одно, включает через пускатель нагрев куба), управляет шаговиком с перистальтическим насосом для отбора из РК, управляет сервоприводом для раздельного отбора (10 + 1 емкость), работает с экраном и энкодером, работает через веб-сервер ESP32, сохраняет у себя лог погона, на своем веб-сервере рисует графики по логу (4 температуры и давление), работает через Blynk  - можно удаленно с телефона контролировать основные параметры и управлять основными функциями. Реализовано аварийное отключение в случае выхода температуры за заданные параметры.

Больше деталей на форуме
https://alcodistillers.ru/forum/viewtopic.php?id=1812

Схема
![alt text](https://github.com/LKosoj/Samovar/blob/master/Fritzing%20scheme/Samovar_bb.png)

Еще одна возможность: можно задавать программу отбора на весь погон. В программе отбора можно указать в какую емкость, какой объем, в каком температурном режиме отбирать текущую часть погона.

Для работы всего функционала необходимо подключение к интернету. Без интернета не будет работать Blynk и не будут строиться графики (библиотека для графиков грузится из сети, она большая, ее на внутренней памяти не сохранить). Все остальное будет работать. 

Обратите внимание!!! Не смотря на то, что теоретически все автоматизировано (или может быть автоматизировано), присутствие оператора рядом с колонной обязательно! Автоматика позволяет упростить отбор, но сама ничего не сделает. Без понимания процессов оператором это просто прикольная (на мой взгляд) штука.

Разводка платы: https://easyeda.com/lkosoj/samovar

Детали для 3D печати: https://www.thingiverse.com/thing:4649872

Как выглядит реализованное - можно посмотреть тут https://yadi.sk/d/PHXuocI2XKfTzQ

В проекте использовались:

ESP32 30 pin https://aliexpress.ru/item/4000152270368.html?spm=a2g0s.9042311.0.0.264d33edS8Ocll

Servo SG90 https://aliexpress.ru/item/32898600185.html

Encoder https://aliexpress.ru/item/32921057267.html

Stepper drive https://aliexpress.ru/item/4001014132747.html?spm=a2g0s.9042311.0.0.264d33edS8Ocll

Toggle switch https://aliexpress.ru/item/32956377097.html?spm=a2g0s.9042311.0.0.264d33edS8Ocll

Perestaltic pomp https://aliexpress.ru/item/4000068635951.html?spm=a2g0s.9042311.0.0.264d33edvCWw1i

Contactor https://aliexpress.ru/item/32825390593.html?spm=a2g0s.9042311.0.0.264d33edjx26pD

Wattmeter https://aliexpress.ru/item/4000843144448.html?spm=a2g0s.9042311.0.0.264d33edjx26pD

DS18b20 x 4 https://aliexpress.ru/item/4000895660165.html

GX16-3 (3A+3B) x 4 https://aliexpress.ru/item/4001357537092.html?spm=a2g0s.9042311.0.0.493433edCwWIto

Silicone tube https://aliexpress.ru/item/4000159962222.html?spm=a2g0s.9042311.0.0.493433edCwWIto

BME680 (можно заменить на BME180, BME280, надо будет заменить библиотеки) https://aliexpress.ru/item/4000049700826.html

LCD 2004 I2C https://aliexpress.ru/item/32652739134.html

Stepper driver A4988 https://aliexpress.ru/item/32963690420.html

DC-DC converter https://aliexpress.ru/item/32261885063.html?spm=a2g0s.9042311.0.0.264d33ed8ASDhI

Button https://aliexpress.ru/item/Black-Push-Button-Switch-4-Pin-12mm-Waterproof-illuminated-Led-Light-Metal-Flat-Momentary-Switches-with/33014419878.html?spm=a2g0s.9042311.0.0.264d33edM5K5ib

Flow sensor https://aliexpress.ru/item/G1-4-0-3-3L-min-Water-Coffee-Flow-Hall-Sensor-Switch-Meter-Flowmeter-Counter/2052754204.html?spm=a2g0s.9042311.0.0.264d33ed0tHl0a&sku_id=51948482384

Adum https://aliexpress.ru/item/Magnetic-Isolator-Board-Module-Replace-Optocouplers-CJMCU-1201-ADUM1201-Isolator-ADUM1201ARZ-SOIC-8-Isolator-SPI-Interface/32789240308.html?spm=a2g0s.9042311.0.0.264d33ed0hX3vj&sku_id=63584285301

