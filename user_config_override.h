#ifndef _USER_CONFIG_OVERRIDE_H_
#define _USER_CONFIG_OVERRIDE_H_

/*****************************************************************************************************\
 * USAGE:
 *   To modify the stock configuration without changing the Samovar.h and Samovar_ini.h files
 *   define your own settings below
 *
 ******************************************************************************************************/

//#define USE_LUA
//#define SAMOVAR_USE_POWER_START_TIME 1000
//#define USE_MQTT                    //использовать сохранение логов в облако. Для этого необходимо зарегистрироваться на сайте www.samovar-tool.ru и в редактировании своего профиля указать токен Blynk.
//#define USE_BODY_TEMP_AUTOSET       //использовать автоматическую коррекцию Т тела для первой программы отбора тела или предзахлеба после хвостов, а так же для программы предзахлеба, если она стоит раньше предпоследней программы отбора тела или предзахлеба

//#define USE_EXPANDER 0x20                    //использовать расширитель портов PCF8575
//#define USE_ANALOG_EXPANDER 0x48             //использовать расширитель аналоговых портов PCF8591
//#define USE_TELEGRAM                          //отправлять уведомления в телеграм, для этого в настройках необходимо указать токен бота и идентификатор пользователя. 
//#define SAMOVAR_USE_BLYNK                    //использовать Blynk в проекте

#endif  // _USER_CONFIG_OVERRIDE_H_
