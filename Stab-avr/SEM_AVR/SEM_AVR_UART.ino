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
//Обратите внимание! При использовании с Самоваром на стабилизатор будет передаваться не напряжение, а мощность.

#define SAMOVAR_LEGACY_UTF8_AT "\xD0\x90\xD0\xA2"
#define SAMOVAR_LEGACY_UTF8_AT_CMD(suffix) SAMOVAR_LEGACY_UTF8_AT suffix

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
    if (inputString == F(SAMOVAR_LEGACY_UTF8_AT_CMD("+VO?"))) {
      Serial.print(Pust);
      Serial.print('\r');
    } else if (inputString == F(SAMOVAR_LEGACY_UTF8_AT_CMD("+VS?"))) {
      Serial.print(Pust);
      Serial.print('\r');
    } else if (inputString == F(SAMOVAR_LEGACY_UTF8_AT_CMD("+SS?"))) {
      if (fl.razg_on) {
        Serial.print(1);
      } else if (fl.Ulow || fl.Udown || fl.NotZero) {
        Serial.print(3);
      } else if (PDMust == 0) {
        Serial.print(2);
      } else {
        Serial.print(0);
      }
      Serial.print('\r');
    } else if (inputString.substring(0, 8) == F(SAMOVAR_LEGACY_UTF8_AT_CMD("+VS="))) {
      uint32_t p;
      //выключаем разгон, на всякий случай
      fl.razg_on = 0;     //выключим режим разгона
      fl.TRelay  = 0;     //выключим контактное реле
      p = inputString.substring(8).toInt();
      if (p > Pnom) p = Pnom;
      //показывает заданную мощность
      //Pust = p;
      p = p * CICLE / Pnom;
      PDMust = p;
      //показывает расчитанную мощность
      Pust = Pnom << 1; Pust *= PDMust; Pust /= CICLE;  Pust++; Pust = Pust >> 1; // Считаем Pust с округлением
      fl.DisplayOut = 1;  //Обновление информации на дисплее
    } else if (inputString == F(SAMOVAR_LEGACY_UTF8_AT_CMD("+ON=0"))) {
      PDMust = 0;
      fl.razg_on = 0;     //выключим режим разгона
      fl.TRelay  = 0;     //выключим контактное реле
      Pust = 0;
      fl.DisplayOut = 1;  //Обновление информации на дисплее
    } else if (inputString == F(SAMOVAR_LEGACY_UTF8_AT_CMD("+ON=1"))) {
      if ((!fl.NotZero) & (!fl.Udown)) {
        fl.razg_on = 1;
        fl.razg = 1;
      }
      Pust = Pnom;
      fl.DisplayOut = 1;  //Обновление информации на дисплее
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
