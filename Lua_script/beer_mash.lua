--Скрипт для контроля температуры брожения

--НАЧАЛЬНЫЕ УСТАНОВКИ
T = 19 -- температура, ниже которой скрипт не работает
Time = 600 -- время задержки скрипта в секундах (чтобы реле реже щелкало)

-- ОПРЕДЕЛЕНИЕ ПЕРЕМЕННЫХ
TankTemp = getNumVariable("TankTemp") + 0
ACPTemp = getNumVariable("ACPTemp") + 0
ValveStatus = getNumVariable("valve_status") + 0
Timer = getTimer(1) + 0

if TankTemp < T and ValveStatus == 1 and Timer == 0 then
   openValve(0)
   setTimer(1, Time)
else
   if ACPTemp < TankTemp and ValveStatus == 0 and Timer == 0 then
      openValve(1)
      setTimer(1, Time)
   elseif ValveStatus == 1 and Timer == 0
      openValve(0)
      setTimer(1, Time)
   end
end

ValveStatus = getNumVariable("valve_status") + 0

status = string.format("ACPT = %.2f; TankT = %.2f; Клапан %.0f", ACPTemp, TankTemp, ValveStatus)

setLuaStatus(status)
--sendMsg(status, 2) --пишем оператору