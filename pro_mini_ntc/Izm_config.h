// Основные настройки проекта
#define ENABLE_OTA             // OTA-обновление
#define ENABLE_WIFI            // Работа с WiFi
#define ENABLE_WEB_SERVER      // Веб-сервер
#define ENABLE_MQTT            // Управление через MQTT
#define ENABLE_OLED_DISPLAY
#define FIRST_DISP 100          // Первый выводимый дисплей 0 - три температуры и давление, 1 - остальные температуры, 99-зуммер, 100 - все Т и Р

// Настройки по умолчанию для WiFi
#define defaultSSID "" // Ссид и пароль по умолчанию, позволяет использовать два набора, первый можно сохранить в EEPROM 
#define defaultPass "" // через WEB интерфейс, это второй по ходу загрузки

// Настройки по умолчанию для MQTT
#define MQTT_SERVER "192.168.0.150"     // Адрес брокера или IP
#define MQTT_PORT 1883                    // Порт
#define MQTT_USER ""
#define MQTT_PASSWORD ""
#define MQTT_ATTEMPTS 2                   // Попытки подключения при инициализации
#define MQTT_RECONNECTION false           // Пытаться переподключиться при потере соединения
#define MQTT_TIME_PUBLICATION 1000       // Период публикаций, миллисекунд
#define MQTT_TOPIC_TEMP "izm/temp" // Топик для температур
#define MQTT_TOPIC_PRESS "izm/pressure" // Топик для давлений
#define MQTT_TOPIC_ALC "izm/alc"   // Топик для спиртометра
#define MQTT_TOPIC_STATUS "izm/status"   // Топик текущего статуса

// Константы для пинов
#define pin_spk 16          // пин зуммера
#define BtnEnter 0          // кнопка действия: на 1 экране отображения сброс дрейфа нуля датчика давления
#define BtnSel 2            // кнопка переключения экранов отображения
#define BtnUp 1             // кнопка +
#define BtnDwn 3            // кнопка -
#define Pin040DR1 15        // перемычка для определения наличия 040DR1
#define PinSCLK 12          // Ноги для 040DR1
#define PinDOUT 13
#define pin_onewire 14      // Pin передачи по протоколу 1Ware 

//1 и 3 - TX0/RX0, 4 и 5 I2C. Свободные пины: A0 (0-1В)
#define XGZP6897D_K 512 
/*pressure_range (kPa)   K value
  131<P≤260               32
  65<P≤131                64
  32<P≤65                 128
  16<P≤32                 256
  8<P≤16                  512
  4<P≤8                   1024
  2≤P≤4                   2048
  1≤P<2                   4096
  P<1                     8192*/
#define PRESSURE_MPX_ENABLE 0 // Наличие подключенного датчика MPX
#define PRESSURE_HX710B_ENABLE 0 // -||- 40DR
#define DEFAULT_PRESSURE 0 // Датчик д. по умолчанию 0- нет, XGZP6897D = 1, MPX10DP = 2, HX710B =3
//EEPROM
#define EEPROM_SIZE 512
//----------------------------------------- Работа с EEPROM ---------------------------------------------------------------
 #define EepromKey 2      // ключ EEPROM 0-255, менять для сброса EEPROM
 #define  U33_EAdr 1              // 4 байт float
 #define  Uref_EAdr 5             // 4 байт float
 #define  R62_EAdr 9              // 4 байт float
 #define  R10_EAdr 13             // 4 байт float
 #define  B25_EAdr 17             // 4 байт float
 #define  dPress_1_EAdr 21        // 4 байт float
 #define  KTemp_1_EAdr 25         // 4 байт float
 #define  BaseTemp_1_EAdr 29      // 4 байт float
 #define  PressureBaseADS_EAdr 33 // 4 байт float
 #define  PressureQ_EAdr 37       // 4 байт float
 #define  KTemp_2_EAdr 41         // 4 байт float
 #define  BaseTemp_2_EAdr 45      // 4 байт float
 #define  HX710B_Mult_EAdr 49     // 4 байт float
 #define  KTemp_3_EAdr 53         // 4 байт float
 #define  BaseTemp_3_EAdr 57      // 4 байт float
 #define  dPress_3_EAdr 61        // 4 байт float
 #define  m_adc_EAdr 65           // 302 байт 151*2
 #define  N_dPressAlc_EAdr 367    // 4 байт float
 #define  k_Alc_T_EAdr 371        // 4 байт float
 #define  k_Alc_EAdr 375          // 4 байт float
 
// Адреса EEPROM для Wi-Fi
#define SSID_ADDR 379             // 9 байта (SSID + нулевой символ)
#define PASS_ADDR 388             // 9 байта (пароль + нулевой символ)
#define WIFI_SAVED_FLAG_VALUE 1   // Значение флага, указывающее, что параметры WIFI были сохранены
#define WIFI_SAVED_FLAG_ADDR 483        // 1 байт (флаг сохранения MQTT)

// Адреса EEPROM для MQTT
#define MQTT_SERVER_ADDR 397            // 32 байта (адрес сервера + нулевой символ)
#define MQTT_PORT_ADDR 429              // 4 байт (порт MQTT, максимум 65535)
#define MQTT_USER_ADDR 433              // 9 байта (пользователь + нулевой символ)
#define MQTT_PASSWORD_ADDR 442          // 9 байта (пароль + нулевой символ)
#define MQTT_ATTEMPTS_ADDR 451          // 1 байт (количество попыток подключения)
#define MQTT_RECONNECTION_ADDR 452      // 1 байт (флаг переподключения)
#define MQTT_TIME_PUBLICATION_ADDR 453  // 4 байта (период публикаций, long)
#define MQTT_SAVED_FLAG_ADDR 457        // 1 байт (флаг сохранения MQTT)
#define MQTT_SAVED_FLAG_VALUE 1         // Значение флага, указывающее, что параметры MQTT были сохранены

#define R25_EAdr 458
#define R100_EAdr  462
#define Alc_tar_EAdr     466  // Пример адреса, подберите под свою конфигурацию
#define T_target_EAdr    470
#define spk_max_count_EAdr 474
#define spk_on_EAdr      478
#define PRESSURE_MPX_ENABLE_ADDR 482
#define PRESSURE_HX710B_ENABLE_ADDR 484
#define DEFAULT_PRESSURE_ADDR 485
#define XGZP6897D_K_ADDR 486
// Адрес свободной ячейки EEPROM 488

#if defined(ENABLE_WEB_SERVER) || defined(ENABLE_MQTT) || defined(ENABLE_OTA)
#define ENABLE_WIFI 
#endif