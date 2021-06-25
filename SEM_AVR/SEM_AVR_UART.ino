//Управление регулятором ТЭНа через UART
//За основу взято управление по UART РМВК. Команды АТ+VO?, АТ+VS? возвращают текущую мощность, АТ+VS=X устанавливает мощность X, АТ+ON=0 выключает стабилизатор, АТ+ON=1 включает разгон, AT+SS? возвращает статус работы регулятора:
//0 рабочий режим
//1 разгон
//2 стабилизатор выключен
//3 ошибка
//Для подключения необходимо подключить контакты Rx и Tx стабилизатора и ведущего устройства крест накрест (RX1-TX2, TX1-RX2) через гальваническую развязку (выполнена на плате, использующей Adum1201).
//Для использования скетча необходимо его скопировать в каталог со скетчем регулятора и добавить
//в конец функции setup() строку uart_begin();
//в начало функции loop() строку  uart_event();
//Обратите внимание! При использовании с Самоваром на стабилизатор будет передаваться будет не напряжение, а мощность.

String inputString;
bool stringComplete;

void uart_begin(void) {
  stringComplete = false;
  Serial.begin(9600, SERIAL_8N1);
  //Pnom = 3000; //можно задать мощность тена по умолчанию
}

void uart_event(void) {
  if (stringComplete) {
    stringComplete = false;
    if (inputString == "АТ+VO?") {
      Serial.print(Pust);
      Serial.print('\r');
    } else if (inputString == "АТ+VS?") {
      Serial.print(Pust);
      Serial.print('\r');
    } else if (inputString == "АТ+SS?") {
      if (fl.razg_on){
        Serial.print(1);
      } else if (fl.Ulow || fl.Udown || fl.NotZero) {
        Serial.print(3);
      } else if (PDMust == 0) {
        Serial.print(2);
      } else {
        Serial.print(0);
      }
      Serial.print('\r');
    } else if (inputString.substring(0, 8) == "АТ+VS=") {
      uint32_t p;
      //выключаем разгон, на всякий случай
      fl.razg_on = 0;
      fl.razg    = 0;
      fl.TRelay  = 0;      //выключим контактное реле
      p = inputString.substring(8).toInt();
      //показывает заданную мощность
      //Pust = p;
      p = p * CICLE / Pnom;
      PDMust = p;
      //показывает расчитанную мощность
      Pust = Pnom << 1; Pust *= PDMust; Pust /= CICLE;  Pust++; Pust = Pust >> 1; // Считаем Pust с округлением
      fl.DisplayOut = 1; //Обновление информации на дисплее
    } else if (inputString == "АТ+ON=0") {
      PDMust = 0;
      fl.razg_on = 0;     //выключим режим разгона
      pdm = 0;            //выключим твердотельное реле
      fl.TRelay = 0;      //выключим контактное реле
      fl.DisplayOut = 1; //Обновление информации на дисплее
    } else if (inputString == "АТ+ON=1") {
      PDMust = CICLE;
      fl.razg_on = 1;
      fl.razg    = 1;
      fl.TRelay  = 1;
      fl.DisplayOut = 1; //Обновление информации на дисплее
    }
    inputString = "";
  }
}

void serialEvent() {
  while (Serial.available()) {
    char inChar = (char)Serial.read();
    if (inChar == '\r') {
      stringComplete = true;
    }
    if (!stringComplete) {
      inputString += inChar;
    }
  }
}
