--Script de contrôle de la température de fermentation

--RÉGLAGES INITIAUX
Tmin = 19 --température minimale du bouilleur en dessous de laquelle le script ne fonctionne pas
dACP = 2 -- delta du capteur de la TCA
dWater = 1 -- delta du capteur d’eau.
Time1 = 10 -- temps de retard du script en secondes
Time2 = 3 --  Durée de fonctionnement de la vanne en secondes

-- DÉFINITION DES VARIABLES
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

status = string.format("ACPT = %.2f; TankT = %.2f; WaterTemp = %.2f; Vanne %.0f", ACPTemp, TankTemp, WaterTemp, ValveStatus)
setLuaStatus(status)

--on vérifie l’indicateur de fin du script, s’il est positionné, on termine le travail
SetScriptOff = getNumVariable("SetScriptOff") + 0

if SetScriptOff == 1 then
  setLuaStatus("Script arrêté")
  openValve(0)
end
