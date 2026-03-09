#ifndef __SAMOVAR_GLOBALS_H_
#define __SAMOVAR_GLOBALS_H_

extern SemaphoreHandle_t xSemaphore;
extern SemaphoreHandle_t xMsgSemaphore;
extern StaticSemaphore_t xMsgSemaphoreBuffer;

extern SemaphoreHandle_t xI2CSemaphore;
extern StaticSemaphore_t xI2CSemaphoreBuffer;

#ifdef SAMOVAR_USE_SEM_AVR
extern SemaphoreHandle_t xSemaphoreAVR;
extern StaticSemaphore_t xSemaphoreBufferAVR;
#endif

extern uint8_t multiplier;

extern char tst[20];
extern char ipst[16];
extern char welcomeStrArr1[20];
extern char welcomeStrArr2[20];
extern char welcomeStrArr3[20];
extern char welcomeStrArr4[20];
extern char* welcomeStr1;
extern char* welcomeStr2;
extern char* welcomeStr3;
extern char* welcomeStr4;

extern char* timestr;
extern char* ipstr;
extern char startval_text_val[20];
extern char* startval_text;
extern char* power_text_ptr;
extern char* calibrate_text_ptr;
extern char* pause_text_ptr;
extern String StrCrt;
extern String Crt;
extern uint8_t CurMin;
extern uint8_t OldMin;

extern TaskHandle_t SysTickerTask1;
extern TaskHandle_t GetClockTask1;
extern TaskHandle_t GetBMPTask;

extern volatile bool buzzer_active;
extern volatile uint8_t buzzer_beep_count;
extern volatile unsigned long buzzer_next_time;
extern volatile bool buzzer_state;

#ifdef SAMOVAR_USE_POWER
extern TaskHandle_t PowerStatusTask;
#endif

extern AsyncWebServer server;
extern AsyncEventSource events;

extern OneWire oneWire;
extern DallasTemperature sensors;
extern DeviceAddress DSAddr[6];

extern LiquidCrystal_I2C lcd;

extern Encoder encoder;

extern GStepper2< STEPPER2WIRE> stepper;

extern iarduino_I2C_connect I2C2;

extern File fileToAppend;

#ifdef SERVO_PIN
extern Servo servo;
#endif

#ifdef BTN_PIN
extern GButton btn;
#endif

#ifdef ALARM_BTN_PIN
extern GButton alarm_btn;
#endif

#ifdef USE_EXPANDER
extern PCF8575 expander;
#endif

#ifdef USE_ANALOG_EXPANDER
extern PCF8591 analog_expander;
#endif

extern double Input;
extern double Output;
extern double Setpoint;
extern double Kp;
extern double Ki;
extern double Kd;

extern PID heaterPID;
extern int periodInSeconds;

extern uint8_t ATuneModeRemember;
extern double aTuneStep;
extern double aTuneNoise;
extern unsigned int aTuneLookBack;
extern boolean tuning;

extern PID_ATune aTune;

#ifdef USE_HEAD_LEVEL_SENSOR
extern GButton whls;
#endif

extern GButton nbkls;

extern LiquidMenu main_menu1;

extern volatile SamovarCommands sam_command_sync;

extern volatile SAMOVAR_MODE Samovar_Mode;
extern volatile SAMOVAR_MODE Samovar_CR_Mode;

extern volatile MESSAGE_TYPE msg_type;

extern SetupEEPROM SamSetup;
extern ImpurityDetector impurityDetector;

extern DSSensor SteamSensor;
extern DSSensor PipeSensor;
extern DSSensor WaterSensor;
extern DSSensor TankSensor;
extern DSSensor ACPSensor;

extern WProgram program[30];

extern const char* host;
extern const float EVAPORATION_FACTOR;

extern uint8_t DScnt;
extern uint8_t STcnt;
extern bool bmefound;
extern volatile bool PowerOn;
extern volatile bool PauseOn;
extern volatile bool StepperMoving;
extern volatile bool program_Pause;
extern volatile bool program_Wait;
extern volatile bool heater_state;
extern volatile bool loop_lua_fl;
extern volatile bool show_lua_script;
extern volatile bool is_self_test;
extern volatile bool SetScriptOff;
extern bool boil_started;
extern bool valve_status;
extern bool pump_started;
extern bool msgfl;
extern bool mixer_status;
extern bool alarm_event;
extern bool acceleration_heater;
extern bool send_mqtt;
extern bool is_reboot;
extern bool lcd_found;
extern bool wetting_autostart;
extern bool reg_online;
extern volatile bool ota_running;
extern unsigned long last_reg_online;

extern volatile float bme_temp;
extern volatile float start_pressure;
extern volatile float bme_pressure;
extern volatile float bme_prev_pressure;
extern String SamovarStatus;
extern volatile int16_t SamovarStatusInt;
extern volatile uint8_t capacity_num;

extern volatile uint8_t prev_ProgramNum;
extern volatile uint8_t ProgramNum;
extern volatile uint8_t ProgramLen;
extern volatile uint8_t WthdrwlProgress;
extern volatile int16_t startval;
extern volatile int currentstepcnt;
extern volatile unsigned long prev_time_ms;
extern volatile float ActualVolumePerHour;
extern volatile uint16_t CurrrentStepperSpeed;
extern volatile uint16_t I2CStepperSpeed;
extern volatile uint16_t I2CPumpCmdSpeed;
extern volatile uint32_t I2CPumpTargetSteps;
extern volatile float I2CPumpTargetMl;
extern volatile bool I2CPumpCalibrating;
extern volatile unsigned int CurrrentStepps;
extern volatile unsigned int TargetStepps;
extern String program_Wait_Type;
extern unsigned long begintime;
extern unsigned long t_min;
extern unsigned long alarm_t_min;
extern unsigned long alarm_h_min;
extern float d_s_temp_prev;
extern float d_s_temp_finish;
extern unsigned long d_s_time_min;
extern float boil_temp;
extern float b_t_temp_prev;
extern unsigned long b_t_time_min;
extern unsigned long b_t_time_delay;
extern float alcohol_s;
extern volatile uint16_t WFpulseCount;
extern volatile uint16_t WFflowMilliLitres;
extern volatile uint32_t WFtotalMilliLitres;
extern volatile float WFflowRate;
extern volatile int WFAlarmCount;
extern uint16_t acceleration_temp;
extern volatile float WthdrwTimeAll;
extern volatile float WthdrwTime;
extern String WthdrwTimeAllS;
extern String WthdrwTimeS;
extern String jsonstr;
extern String Msg;
extern String LogMsg;
extern uint8_t msg_level;
extern int bk_pwm;
extern uint32_t chipId;
extern String SessionDescription;
extern volatile float test_num_val;
extern float pressure_value;
extern float old_pressure_value;
extern bool use_pressure_sensor;

extern volatile float BoilerVolume;
extern volatile float CurrentHeatLoss;
extern volatile float CalculatedTargetFR;
extern unsigned long heatStartMillis;
extern float heatStartTemp;
extern bool heatLossCalculated;

extern String test_str_val;
extern String Lua_status;
extern uint32_t total_byte;
extern uint32_t used_byte;
extern uint8_t use_I2C_dev;
extern uint16_t water_pump_speed;

extern String current_power_mode;
extern volatile float target_power_volt;
extern volatile float current_power_volt;
extern unsigned long alarm_c_min;
extern unsigned long alarm_c_low_min;

#ifdef SAMOVAR_USE_POWER
extern volatile float prev_target_power_volt;
extern volatile uint16_t current_power_p;
extern uint8_t power_err_cnt;
#endif

#ifdef USE_WATER_PUMP
extern uint8_t wp_count;
#endif

#endif
