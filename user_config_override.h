#ifndef _USER_CONFIG_OVERRIDE_H_
#define _USER_CONFIG_OVERRIDE_H_

#undef SAMOVAR_USE_POWER
#undef SAMOVAR_USE_RMVK

#undef SERVO_PIN
#undef USE_WATER_PUMP
//#undef WATER_PUMP_PIN
#define USE_WATER_VALVE HIGH                 //использовать управление клапаном для регулировки напора воды

#undef BLYNK_SAMOVAR_TOOL

#define BLYNK_SAMOVAR_TOOL "zorrodeoro.es"

#endif  // _USER_CONFIG_OVERRIDE_H_
