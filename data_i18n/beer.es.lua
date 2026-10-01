--Script de control de la temperatura de fermentación

--AJUSTES INICIALES
Tmin = 19 --temperatura mínima del calderín por debajo de la cual el script no funciona
dACP = 2 -- delta del sensor de la TCA
dWater = 1 -- delta del sensor de agua.
Time1 = 10 -- tiempo de retardo del script en segundos
Time2 = 3 --  Tiempo de funcionamiento de la válvula en segundos

-- DEFINICIÓN DE VARIABLES
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

status = string.format("ACPT = %.2f; TankT = %.2f; WaterTemp = %.2f; Válvula %.0f", ACPTemp, TankTemp, WaterTemp, ValveStatus)
setLuaStatus(status)

--comprobamos el indicador de fin del script; si está establecido, terminamos el trabajo
SetScriptOff = getNumVariable("SetScriptOff") + 0

if SetScriptOff == 1 then
  setLuaStatus("Script detenido")
  openValve(0)
end
