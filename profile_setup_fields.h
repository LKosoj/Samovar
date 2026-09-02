#pragma once

// Единый источник истины для порядка/типа/дефолта полей профиля SetupEEPROM
// в каноническом (NVS) формате. Список используется тремя сайтами в
// NVS_Manager.ino (encode_setup_payload, decode_setup_payload_fields,
// set_default_setup_profile) через локальный #define X(...) / #undef X —
// см. AGENTS.md про инвариант формата хранения NVS.
//
// X(KIND, NAME, SIZE, DEFAULT, SCOPE)
//   KIND    — как поле кодируется: U8, BOOL, U16, FLOAT, I32_MODE,
//             BYTES_U8 (сырой uint8_t[N]), BYTES_CHAR (char[N], с
//             reinterpret_cast на запись/чтение).
//   NAME    — имя поля SetupEEPROM (Samovar.h), порядок строк здесь и есть
//             канонический порядок байт на диске — менять нельзя.
//   SIZE    — размер поля в канонических байтах (для скалярных типов равен
//             sizeof одного значения; для BYTES_* — размер массива).
//             encode/decode сами используют sizeof(candidate.NAME), SIZE тут
//             для перекрёстной проверки smoke-тестом.
//   DEFAULT — самодостаточный C++-стейтмент (без завершающей ';'),
//             устанавливающий дефолт поля в set_default_setup_profile().
//   SCOPE   — ALL (поле участвует в общем decode_setup_payload_fields(),
//             используемом и V1, и V2) или V2ONLY (поле decode_setup_payload_fields
//             пропускает; decode_setup_payload() читает его отдельно после
//             остальных — так SuvidHoldMinutes остаётся вне V1-формата).
//
// BKPower — единственное поле с дефолтом, зависящим от компиляции
// (SAMOVAR_USE_SEM_AVR меняет рабочую мощность БК). Вынесено в именованную
// константу, чтобы список полей ниже не содержал #ifdef построчно.
#ifndef SAMOVAR_USE_SEM_AVR
static const float SAMOVAR_BK_POWER_DEFAULT = 45.0f;
#else
static const float SAMOVAR_BK_POWER_DEFAULT = 200.0f;
#endif

#define SAMOVAR_PROFILE_FIELDS(X) \
  X(U8, flag, 1, candidate.flag = 2, ALL) \
  X(FLOAT, DeltaSteamTemp, 4, candidate.DeltaSteamTemp = 0.1, ALL) \
  X(FLOAT, DeltaPipeTemp, 4, candidate.DeltaPipeTemp = 0.2, ALL) \
  X(FLOAT, DeltaWaterTemp, 4, candidate.DeltaWaterTemp = 0, ALL) \
  X(FLOAT, DeltaTankTemp, 4, candidate.DeltaTankTemp = 0, ALL) \
  X(U16, StepperStepMl, 2, candidate.StepperStepMl = STEPPER_STEP_ML, ALL) \
  X(FLOAT, SetSteamTemp, 4, candidate.SetSteamTemp = 0, ALL) \
  X(FLOAT, SetPipeTemp, 4, candidate.SetPipeTemp = 0, ALL) \
  X(FLOAT, SetWaterTemp, 4, candidate.SetWaterTemp = 0, ALL) \
  X(FLOAT, SetTankTemp, 4, candidate.SetTankTemp = 0, ALL) \
  X(BOOL, UsePreccureCorrect, 1, candidate.UsePreccureCorrect = true, ALL) \
  X(U16, SteamDelay, 2, candidate.SteamDelay = 20, ALL) \
  X(U16, PipeDelay, 2, candidate.PipeDelay = 20, ALL) \
  X(U16, WaterDelay, 2, candidate.WaterDelay = 20, ALL) \
  X(U16, TankDelay, 2, candidate.TankDelay = 20, ALL) \
  X(U8, TimeZone, 1, candidate.TimeZone = 3, ALL) \
  X(FLOAT, HeaterResistant, 4, candidate.HeaterResistant = 15.2, ALL) \
  X(U8, LogPeriod, 1, candidate.LogPeriod = 3, ALL) \
  X(BYTES_CHAR, SteamColor, 20, copyStringSafe(candidate.SteamColor, "#ff0000"), ALL) \
  X(BYTES_CHAR, PipeColor, 20, copyStringSafe(candidate.PipeColor, "#0000ff"), ALL) \
  X(BYTES_CHAR, WaterColor, 20, copyStringSafe(candidate.WaterColor, "#00bfff"), ALL) \
  X(BYTES_CHAR, TankColor, 20, copyStringSafe(candidate.TankColor, "#008000"), ALL) \
  X(BOOL, rele1, 1, candidate.rele1 = false, ALL) \
  X(BOOL, rele2, 1, candidate.rele2 = false, ALL) \
  X(BOOL, rele3, 1, candidate.rele3 = false, ALL) \
  X(BOOL, rele4, 1, candidate.rele4 = false, ALL) \
  X(BYTES_U8, SteamAdress, 8, memset(candidate.SteamAdress, 255, sizeof(candidate.SteamAdress)), ALL) \
  X(BYTES_U8, PipeAdress, 8, memset(candidate.PipeAdress, 255, sizeof(candidate.PipeAdress)), ALL) \
  X(BYTES_U8, WaterAdress, 8, memset(candidate.WaterAdress, 255, sizeof(candidate.WaterAdress)), ALL) \
  X(BYTES_U8, TankAdress, 8, memset(candidate.TankAdress, 255, sizeof(candidate.TankAdress)), ALL) \
  X(BOOL, useautospeed, 1, candidate.useautospeed = false, ALL) \
  X(BOOL, useDetector, 1, candidate.useDetector = false, ALL) \
  X(U8, autospeed, 1, candidate.autospeed = 0, ALL) \
  X(BYTES_CHAR, blynkauth, 33, candidate.blynkauth[0] = '\0', ALL) \
  X(BYTES_CHAR, videourl, 120, candidate.videourl[0] = '\0', ALL) \
  X(FLOAT, DistTemp, 4, candidate.DistTemp = DEFAULT_DIST_TEMP, ALL) \
  X(I32_MODE, Mode, 4, candidate.Mode = SAMOVAR_RECTIFICATION_MODE, ALL) \
  X(BYTES_U8, ACPAdress, 8, memset(candidate.ACPAdress, 255, sizeof(candidate.ACPAdress)), ALL) \
  X(BYTES_CHAR, ACPColor, 20, copyStringSafe(candidate.ACPColor, "#800080"), ALL) \
  X(FLOAT, DeltaACPTemp, 4, candidate.DeltaACPTemp = 0, ALL) \
  X(FLOAT, SetACPTemp, 4, candidate.SetACPTemp = 0, ALL) \
  X(U16, ACPDelay, 2, candidate.ACPDelay = 20, ALL) \
  X(FLOAT, Kp, 4, candidate.Kp = 150.0, ALL) \
  X(FLOAT, Ki, 4, candidate.Ki = 1.4, ALL) \
  X(FLOAT, Kd, 4, candidate.Kd = 1.4, ALL) \
  X(FLOAT, StbVoltage, 4, candidate.StbVoltage = 100.0, ALL) \
  X(BOOL, ChangeProgramBuzzer, 1, candidate.ChangeProgramBuzzer = false, ALL) \
  X(BOOL, UseBuzzer, 1, candidate.UseBuzzer = false, ALL) \
  X(BOOL, CheckPower, 1, candidate.CheckPower = false, ALL) \
  X(BOOL, UseBBuzzer, 1, candidate.UseBBuzzer = false, ALL) \
  X(BOOL, UseWS, 1, candidate.UseWS = true, ALL) \
  X(FLOAT, BVolt, 4, candidate.BVolt = 230.0, ALL) \
  X(BOOL, UseST, 1, candidate.UseST = true, ALL) \
  X(U8, DistTimeF, 1, candidate.DistTimeF = 60, ALL) \
  X(BOOL, UseHLS, 1, candidate.UseHLS = true, ALL) \
  X(FLOAT, MaxPressureValue, 4, candidate.MaxPressureValue = 0, ALL) \
  X(BYTES_CHAR, tg_token, 50, candidate.tg_token[0] = '\0', ALL) \
  X(BYTES_CHAR, tg_chat_id, 14, candidate.tg_chat_id[0] = '\0', ALL) \
  X(FLOAT, NbkIn, 4, candidate.NbkIn = NBK_COLUMN_INERTIA_DEFAULT, ALL) \
  X(FLOAT, NbkDelta, 4, candidate.NbkDelta = NBK_DT_DEFAULT, ALL) \
  X(FLOAT, NbkDM, 4, candidate.NbkDM = NBK_DM_DEFAULT, ALL) \
  X(FLOAT, NbkDP, 4, candidate.NbkDP = NBK_DP_DEFAULT, ALL) \
  X(FLOAT, NbkSteamT, 4, candidate.NbkSteamT = NBK_TP_DEFAULT, ALL) \
  X(FLOAT, NbkOwPress, 4, candidate.NbkOwPress = NBK_OVERFLOW_PRESSURE_DEFAULT, ALL) \
  X(FLOAT, ColDiam, 4, candidate.ColDiam = 2.0f, ALL) \
  X(FLOAT, ColHeight, 4, candidate.ColHeight = 0.5f, ALL) \
  X(U8, PackDens, 1, candidate.PackDens = 80, ALL) \
  X(U16, StepperStepMlI2C, 2, candidate.StepperStepMlI2C = I2C_STEPPER_STEP_ML_DEFAULT, ALL) \
  X(FLOAT, NbkTn, 4, candidate.NbkTn = NBK_TN_DEFAULT, ALL) \
  X(FLOAT, BKPower, 4, candidate.BKPower = SAMOVAR_BK_POWER_DEFAULT, ALL) \
  X(FLOAT, MainsVoltage, 4, candidate.MainsVoltage = 230.0f, ALL) \
  X(FLOAT, SuvidTemp, 4, candidate.SuvidTemp = 0.0f, ALL) \
  X(U16, SuvidHoldMinutes, 2, candidate.SuvidHoldMinutes = 0, V2ONLY)
