
-- EINSTELLUNGEN FÜR DEN FÜLLSTANDSSENSOR ---------------
local min_bottom_level = 150 -- minimaler Sensorwert, wenn die Flüssigkeit den unteren Kontakt erreicht
local delta_top_percent = 40 -- minimaler Unterschied (in % des unteren) zwischen den Werten des unteren und oberen Kontakts
local bottom_readings_skip = 4 -- wie viele Werte des unteren Kontakts übersprungen werden, bevor das Ergebnis gespeichert wird
-- EINSTELLUNGEN FÜR DEN DURCHFLUSSSENSOR ---------------
local target_volume = 30 -- Zielvolumen in Litern, das aufgefangen werden soll
local flow_factor = 1.0 -- Korrekturfaktor für die Ungenauigkeit des Durchflusssensors

-- VERWENDETE SENSOREN --------------
local use_level_sensor = true
local use_flow_sensor = false

-- DEFINITION DER VARIABLEN ---
local tank_filled = getObject("tank_filled") -- lesen, ob der Kessel gefüllt ist
local pump_started = getNumVariable("pump_started") + 0 -- bestätigtes Pumpen-Einschaltkennzeichen lesen
local bottom_pin = getObject("bottom_pin", "NUMERIC") + 0 -- gespeicherten unteren Pegel lesen
local bottom_readings_count = getObject("bottom_readings_count", "NUMERIC") + 0 -- Anzahl bereits übersprungener Werte lesen
local start_time = getObject("start_time", "NUMERIC") + 0 -- Startzeit der Pumpe lesen
local last_reading_time = getObject("last_reading_time", "NUMERIC") + 0 -- Zeit der letzten Durchflussmessung lesen
local last_reading_flow = getObject("last_reading_flow", "NUMERIC") + 0 -- letzte Durchflussmessung lesen
local total_volume = getObject("total_volume", "NUMERIC") + 0 -- bisher aufgefangenes Gesamtvolumen lesen



local sensor = analogRead() --Analogwert von Pin 34 lesen (daran hängt der Füllstandssensor)

local function verifyVolumeTargets () -- Daten des Durchflusssensors auf Korrektheit prüfen
  if (type(target_volume) ~= "number" or target_volume <= 0 or type(flow_factor) ~= "number" or flow_factor <= 0) then
    sendMsg("Fehler in den Volumenparametern!", -1) --in die Browser-Konsole berichten
    sendMsg("Fehler in den Volumenparametern!", 0) --Meldung an den Bediener senden
    use_flow_sensor = false
  end
end

local function startPump()
  local now = millis() + 0
  if setPumpPwm(1023) ~= ACTUATOR_COMMAND_APPLIED then
    setLuaStatus("Fehler beim Einschalten der Pumpe")
    sendMsg("Pumpe hat das Einschalten nicht bestätigt.", -1)
    sendMsg("Pumpe hat das Einschalten nicht bestätigt.", 0)
    return false
  end
  if start_time <= 0 then setObject("start_time", now) end
  setObject("last_reading_time", now)
  setObject("last_reading_flow", getNumVariable("WFflowRate") + 0)
  setObject("total_volume", total_volume)
  sendMsg("Pumpe ein", -1) --in die Browser-Konsole berichten
  sendMsg("Pumpe ein", 2) --Meldung an den Bediener senden
  return true
end


local function stopPump()
  if setPumpPwm(0) ~= ACTUATOR_COMMAND_APPLIED then
    setLuaStatus("Fehler beim Ausschalten der Pumpe")
    sendMsg("Pumpe hat das Ausschalten nicht bestätigt.", -1)
    sendMsg("Pumpe hat das Ausschalten nicht bestätigt.", 0)
    return false
  end
  sendMsg("Pumpe aus", -1) --in die Browser-Konsole melden
  sendMsg("Pumpe aus", 2) --Meldung an den Bediener senden
  return true
end



local function check4level()
	if bottom_pin > 0 then
		if sensor > bottom_pin * (1 + delta_top_percent/100) then --Sprung beim Erreichen des oberen Kontakts ist größer als das minimale Delta
			sendMsg("Füllstandssensor: Kessel ist voll.", -1) --in die Browser-Konsole berichten
			sendMsg("Füllstandssensor: Kessel ist voll.", 0) --Meldung an den Bediener senden
			return true --Kessel ist voll
		end
	elseif sensor > min_bottom_level then
		if (bottom_readings_count == bottom_readings_skip) then
			setObject("bottom_pin", sensor) --Wert für den unteren Kontakt speichern
			sendMsg("bottom_pin: " .. sensor, -1)
			else
			setObject("bottom_readings_count", bottom_readings_count + 1) --Zähler der übersprungenen Werte erhöhen
		end
	end
	return false	
end




local function check4volume()
  local current_rate = getNumVariable("WFflowRate") + 0
  local now = millis() + 0
  if current_rate < 0 then
    stopPump()
    setLuaStatus("Fehler des Durchflusssensors")
    sendMsg("Fehler des Durchflusssensors: negativer Durchfluss.", -1)
    sendMsg("Fehler des Durchflusssensors: negativer Durchfluss.", 0)
    return false
  end
  if last_reading_time <= 0 then
    setObject("last_reading_time", now)
    setObject("last_reading_flow", current_rate)
    return false
  end
  if now < last_reading_time then
    stopPump()
    setLuaStatus("Zeitfehler des Durchflusssensors")
    sendMsg("Fehler des Durchflusssensors: Messzeit wurde zurückgesetzt.", -1)
    sendMsg("Fehler des Durchflusssensors: Messzeit wurde zurückgesetzt.", 0)
    return false
  end
  local elapsed_min = (now - last_reading_time) / 60000.0
  local avg_rate = (last_reading_flow + current_rate) / 2.0
  total_volume = total_volume + avg_rate * elapsed_min * flow_factor
  last_reading_time = now
  last_reading_flow = current_rate
  setObject("last_reading_time", last_reading_time)
  setObject("last_reading_flow", last_reading_flow)
  setObject("total_volume", total_volume)
  setLuaStatus(string.format("Kesselfüllung: %.2f / %.2f l", total_volume, target_volume))
  return total_volume >= target_volume
end



-----------------------------------------
--ACTIONS--------------------------------
-----------------------------------------

local function stopFilling ()
  if not stopPump() then return false end
  setLuaStatus("Kessel voll")
	setObject("bottom_pin", 0)
	setObject("tank_filled", "true")
	sendMsg("Done: filling stopped.", -1)
	sendMsg("Done: filling stopped.", 0)
  return true
end



local function fillTank ()
  sendMsg("tank_filled: " .. tank_filled, -1)
  sendMsg("bottom_pin: " .. bottom_pin, -1)
  sendMsg("sensor: " .. sensor, -1)
	if tank_filled ~= "true" then
	  sendMsg("pump_started: " .. pump_started, -1)
	  if pump_started == 0 then
			sendMsg("Kesselfüllung wird gestartet...", -1) --in die Browser-Konsole berichten
			sendMsg("Kesselfüllung wird gestartet...", 2) --Meldung an den Bediener senden
      		setLuaStatus("Kesselfüllung")
			if not startPump() then return false end
		else
      if use_level_sensor and check4level() then
        stopFilling()
        return
      end
      if use_flow_sensor then
        if check4volume() then stopFilling() end
        return
      end
      setLuaStatus("Kesselfüllung")
		end
  else 
    sendMsg("NOTHING 2 DO: tank_filled: " .. tank_filled, -1)
    sendMsg("NOTHING 2 DO: tank_filled: " .. tank_filled, 0)
	end
end



local function resetFilling ()
		sendMsg("tank_filled: " .. tank_filled, 0)
		setObject("tank_filled", "false")
	  setObject("bottom_pin", 0)
	  setObject("bottom_readings_count", 0)
	  setObject("start_time", 0)
	  setObject("last_reading_time", 0)
	  setObject("last_reading_flow", 0)
	  setObject("total_volume", 0)
		sendMsg("Done: filling reset.", -1)
		sendMsg("Done: filling reset.", 0)
	end



--RUN--------------------------------

verifyVolumeTargets()
if getNumVariable("SetScriptOff") + 0 == 1 then
  stopPump()
  setLuaStatus("Skript gestoppt")
elseif not use_level_sensor and not use_flow_sensor then
  stopPump()
  setLuaStatus("Fehler: Füllsensoren sind abgeschaltet")
  sendMsg("Fehler: Füllsensoren sind abgeschaltet.", -1)
  sendMsg("Fehler: Füllsensoren sind abgeschaltet.", 0)
else
  --resetFilling ()
  fillTank()
end
-- stopFilling()
