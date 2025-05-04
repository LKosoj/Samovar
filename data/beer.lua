--Скрипт для контроля температуры брожения

--НАЧАЛЬНЫЕ УСТАНОВКИ
Tmin = 19 --минимальная температура куба,  ниже которой скрипт не работает
dACP = 2 -- дельта датчика ТСА
dWater = 1 -- дельта датчика воды.
Time1 = 10 -- время задержки скрипта в секундах
Time2 = 3 --  Время работы клапана в секундах

-- ОПРЕДЕЛЕНИЕ ПЕРЕМЕННЫХ
TankTemp = getNumVariable("TankTemp") + 0
WaterTemp = getNumVariable("WaterTemp") + 0
ACPTemp = getNumVariable("ACPTemp") + 0
ValveStatus = getNumVariable("valve_status") + 0
Timer1 = getTimer(1) + 0
Timer2 = getTimer(2) + 0

if Timer1 == 0 then
  if TankTemp < Tmin and ValveStatus == 1 and Timer1 == 0 then
      openValve(0)
      setTimer(1, Time1)
  else
  if TankTemp < ACPTemp + dACP and ValveStatus == 1 and Timer1 == 0 then
      openValve(0)
      setTimer(1, Time1)
  else
  if ACPTemp + dACP < TankTemp and ValveStatus == 0 and Timer2 == 0 then
         openValve(1)
         setTimer(2, Time2)
  else
  if WaterTemp + dWater < TankTemp and ValveStatus == 0 and ACPTemp + dACP < TankTemp and Timer2 == 0 then
         openValve(1)
         setTimer(2, Time2)
      elseif WaterTemp + dWater >= TankTemp and ValveStatus == 1 and Timer2 == 0 then
         openValve(0)
         setTimer(2, Time1)
         end
      end
  end
end
end

ValveStatus = getNumVariable("valve_status") + 0

setLuaStatus(status)

--проверяем признак завершения работы скрипта, если он установлен, то завершаем работу
SetScriptOff = getNumVariable("SetScriptOff") + 0
status = string.format("ACPT = %.2f; TankT = %.2f; WaterTemp = %.2f; Клапан %.0f", ACPTemp, TankTemp, WaterTemp, ValveStatus)

if SetScriptOff == 1 then
  setLuaStatus("Скрипт остановлен")
  openValve(0)
end