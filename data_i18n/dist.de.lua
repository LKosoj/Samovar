--Skript für die Destillation mit Aufteilung auf drei Behälter.
--Die Destillation beginnt mit Behälter 0. Wir merken uns die Kesseltemperatur zu Beginn des Siedens.
--Steigt die Kessel-T um den vorgegebenen Sollwert, schalten wir den Servoantrieb auf die vorgegebene Position.

--ANFANGSEINSTELLUNGEN
t_delta1 = 4 --erster Sollwert der Kesseltemperatur, bei Überschreitung wechselt der Behälter
t_delta2 = 4 --zweiter Sollwert der Kesseltemperatur, bei Überschreitung wechselt der Behälter
power_delta = 10 -- um so viele Prozent sinkt die aktuelle Leistung, bei 0 wird nicht gesenkt
use_temp = 0 --bei 1 Wechsel zum nächsten Behälter nach Temperatur, bei 0 nach Alkoholgehalt

-- DEFINITION DER VARIABLEN
b_temp = getNumVariable("boil_temp") + 0 --gemerkte Siedetemperatur holen
alcohol = getNumVariable("alcohol") + 0 --aktuellen, aus der Kesseltemperatur berechneten Alkoholgehalt holen
alcohol_s = getNumVariable("alcohol_s") + 0 --Alkoholgehalt im Moment des Siedebeginns im Kessel holen
TankTemp = getNumVariable("TankTemp") + 0 --aktuelle Kessel-T holen
PowerOn = getNumVariable("PowerOn") + 0 --Status der Leistungszufuhr holen
target_power_volt = getNumVariable("target_power_volt") + 0 --aktuelle Leistung holen
capacity_num = getNumVariable("capacity_num") + 0 --aktuellen Behälter holen
sg = getObject("sg", "NUMERIC") + 0 -- Status des Skriptbeginns holen
gb = getObject("gb", "NUMERIC") + 0 -- Status der Reaktion auf den Siedebeginn holen
alcohol_invalid = getObject("alcohol_invalid", "NUMERIC") + 0 -- Status nicht verfügbarer Alkoholgehalt holen

local function changeCapacity(num)
  setCapacity(num) --Behälter setzen №num
  sendMsg("Behälter gesetzt "..num.."!", -1) --in die Browser-Konsole schreiben
  sendMsg("Behälter gesetzt "..num.."!", 2) --an den Bediener schreiben
end

-- Skript hat die Arbeit begonnen
if (sg == 0) then
  setObject("sg", 1)
  changeCapacity(0)
  setPower(1)
  setLuaStatus("Destillation nach Gabriel gestartet")
  sendMsg("Destillation nach Gabriel gestartet!", 2) --an den Bediener schreiben
end

-- das Skript hat auf den Siedebeginn reagiert
if (gb == 0 and b_temp > 0) then
  setObject("gb", 1)
  sendMsg("Abnahme in Behälter gestartet №0!", 2) --an den Bediener schreiben
  --Sieden hat begonnen - Leistung um power_delta Prozent senken
  if (PowerOn + 0 == 1 and target_power_volt == 0) then
    --wenn Aufheizmodus, in dem die aktuelle Spannung unbekannt ist
    target_power_volt = 220
  end
  --wenn power_delta > 0 Zielspannung ändern
  if (power_delta > 0) then
    target_power_volt = target_power_volt - target_power_volt/100*power_delta
    setCurrentPower(target_power_volt)
  end
end

--Logik des Behälterwechsels verarbeiten
if b_temp > 0 then
setLuaStatus(string.format("Aktueller Alkoholgehalt  = %.2f; T Siedebeginn = %.2f", alcohol, b_temp))
  if (use_temp == 1) then
  --Logik nach Temperatur
    if ((capacity_num + 0 == 0) and ((b_temp + t_delta1) <= TankTemp)) then
      changeCapacity(1)
    elseif ((capacity_num + 0 == 1) and ((b_temp + t_delta1 + t_delta2) <= TankTemp)) then
      changeCapacity(2)
    end
  else
  --Logik nach Alkoholgehalt
    if alcohol >= 0 and alcohol_s >= 0 then
      setObject("alcohol_invalid", 0)
      if (capacity_num + 0 == 0) and (alcohol <= alcohol_s / 2) then
        --die Hälfte des Alkohols ist übrig - auf Behälter 1 umschalten
        changeCapacity(1)
      elseif (capacity_num + 0 == 1) and (alcohol <= alcohol_s / 4) then
        --ein Viertel des Alkohols ist übrig - auf Behälter 2 umschalten
        changeCapacity(2)
      end
    elseif alcohol_invalid == 0 then
      setObject("alcohol_invalid", 1)
      sendMsg("Alkoholgehalt nicht verfügbar: Behälterwechsel verschoben", 1)
    end
  end
end
