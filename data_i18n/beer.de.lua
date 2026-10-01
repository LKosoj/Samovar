--Skript zur Kontrolle der Gärtemperatur

--ANFANGSEINSTELLUNGEN
Tmin = 19 --minimale Kesseltemperatur, unterhalb derer das Skript nicht arbeitet
dACP = 2 -- Delta des ADR-Sensors
dWater = 1 -- Delta des Wassersensors.
Time1 = 10 -- Verzögerungszeit des Skripts in Sekunden
Time2 = 3 --  Laufzeit des Ventils in Sekunden

-- DEFINITION DER VARIABLEN
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

status = string.format("ACPT = %.2f; TankT = %.2f; WaterTemp = %.2f; Ventil %.0f", ACPTemp, TankTemp, WaterTemp, ValveStatus)
setLuaStatus(status)

--wir prüfen das Beendigungs-Flag des Skripts; ist es gesetzt, beenden wir die Arbeit
SetScriptOff = getNumVariable("SetScriptOff") + 0

if SetScriptOff == 1 then
  setLuaStatus("Skript gestoppt")
  openValve(0)
end
