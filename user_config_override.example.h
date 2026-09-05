#ifndef _USER_CONFIG_OVERRIDE_H_
#define _USER_CONFIG_OVERRIDE_H_

/*****************************************************************************************************\
 * Локальные настройки пользователя.
 *
 * flash_windows.bat создаёт рядом файл user_config_override.h. Этот локальный файл
 * не отслеживается Git, поэтому в нём можно хранить SSID и пароль Wi-Fi.
 *
 ******************************************************************************************************/

#define SAMOVAR_WIFI_SSID ""
#define SAMOVAR_WIFI_PASSWORD ""

//#define USE_LUA
//#define SAMOVAR_USE_POWER_START_TIME 1000
//#define USE_MQTT
//#define USE_BODY_TEMP_AUTOSET
//#define USE_EXPANDER 0x20
//#define USE_ANALOG_EXPANDER 0x48
//#define USE_TELEGRAM
//#define SAMOVAR_USE_BLYNK

#endif  // _USER_CONFIG_OVERRIDE_H_
