
-- RÉGLAGES DU CAPTEUR DE NIVEAU ---------------
local min_bottom_level = 150 -- valeur minimale du capteur quand le liquide atteint le contact inférieur
local delta_top_percent = 40 -- écart minimal (en % de l’inférieur) entre les valeurs des contacts inférieur et supérieur
local bottom_readings_skip = 4 -- combien de valeurs de l’inférieur ignorer avant d’enregistrer le résultat
-- RÉGLAGES DU CAPTEUR DE DÉBIT ---------------
local target_volume = 30 -- volume cible en litres à recueillir
local flow_factor = 1.0 -- coefficient de correction de l’imprécision du capteur de débit

-- CAPTEURS UTILISÉS --------------
local use_level_sensor = true
local use_flow_sensor = false

-- DÉFINITION DES VARIABLES ---
local tank_filled = getObject("tank_filled") -- on lit si le bouilleur est rempli
local pump_started = getNumVariable("pump_started") + 0 -- on lit l’indicateur confirmé de mise en marche de la pompe
local bottom_pin = getObject("bottom_pin", "NUMERIC") + 0 -- on lit le niveau bas enregistré
local bottom_readings_count = getObject("bottom_readings_count", "NUMERIC") + 0 -- on lit le nombre de valeurs déjà ignorées
local start_time = getObject("start_time", "NUMERIC") + 0 -- on lit l’heure de démarrage de la pompe
local last_reading_time = getObject("last_reading_time", "NUMERIC") + 0 -- on lit l’heure de la dernière mesure du débit
local last_reading_flow = getObject("last_reading_flow", "NUMERIC") + 0 -- on lit la dernière mesure du débit
local total_volume = getObject("total_volume", "NUMERIC") + 0 -- on lit le volume total déjà recueilli



local sensor = analogRead() --on lit la valeur analogique de la broche 34 (le capteur de niveau y est branché)

local function verifyVolumeTargets () -- on vérifie la validité des données du capteur de débit
  if (type(target_volume) ~= "number" or target_volume <= 0 or type(flow_factor) ~= "number" or flow_factor <= 0) then
    sendMsg("Erreur dans les paramètres de volume!", -1) --on rend compte dans la console du navigateur
    sendMsg("Erreur dans les paramètres de volume!", 0) --on envoie un message à l’opérateur
    use_flow_sensor = false
  end
end

local function startPump()
  local now = millis() + 0
  if setPumpPwm(1023) ~= ACTUATOR_COMMAND_APPLIED then
    setLuaStatus("Erreur de démarrage de la pompe")
    sendMsg("La pompe n’a pas confirmé le démarrage.", -1)
    sendMsg("La pompe n’a pas confirmé le démarrage.", 0)
    return false
  end
  if start_time <= 0 then setObject("start_time", now) end
  setObject("last_reading_time", now)
  setObject("last_reading_flow", getNumVariable("WFflowRate") + 0)
  setObject("total_volume", total_volume)
  sendMsg("Pompe en marche", -1) --on rend compte dans la console du navigateur
  sendMsg("Pompe en marche", 2) --on envoie un message à l’opérateur
  return true
end


local function stopPump()
  if setPumpPwm(0) ~= ACTUATOR_COMMAND_APPLIED then
    setLuaStatus("Erreur d’arrêt de la pompe")
    sendMsg("La pompe n’a pas confirmé l’arrêt.", -1)
    sendMsg("La pompe n’a pas confirmé l’arrêt.", 0)
    return false
  end
  sendMsg("Pompe arrêtée", -1) --on signale dans la console du navigateur
  sendMsg("Pompe arrêtée", 2) --on envoie un message à l’opérateur
  return true
end



local function check4level()
	if bottom_pin > 0 then
		if sensor > bottom_pin * (1 + delta_top_percent/100) then --le saut à l’atteinte du contact supérieur dépasse le delta minimal
			sendMsg("Capteur de niveau : bouilleur plein.", -1) --on rend compte dans la console du navigateur
			sendMsg("Capteur de niveau : bouilleur plein.", 0) --on envoie un message à l’opérateur
			return true --bouilleur plein
		end
	elseif sensor > min_bottom_level then
		if (bottom_readings_count == bottom_readings_skip) then
			setObject("bottom_pin", sensor) --on enregistre la valeur du contact inférieur
			sendMsg("bottom_pin: " .. sensor, -1)
			else
			setObject("bottom_readings_count", bottom_readings_count + 1) --on incrémente le compteur des valeurs ignorées
		end
	end
	return false	
end




local function check4volume()
  local current_rate = getNumVariable("WFflowRate") + 0
  local now = millis() + 0
  if current_rate < 0 then
    stopPump()
    setLuaStatus("Erreur du capteur de débit")
    sendMsg("Erreur du capteur de débit : débit négatif.", -1)
    sendMsg("Erreur du capteur de débit : débit négatif.", 0)
    return false
  end
  if last_reading_time <= 0 then
    setObject("last_reading_time", now)
    setObject("last_reading_flow", current_rate)
    return false
  end
  if now < last_reading_time then
    stopPump()
    setLuaStatus("Erreur de temps du capteur de débit")
    sendMsg("Erreur du capteur de débit : le temps de mesure a été réinitialisé.", -1)
    sendMsg("Erreur du capteur de débit : le temps de mesure a été réinitialisé.", 0)
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
  setLuaStatus(string.format("Remplissage du bouilleur : %.2f / %.2f l", total_volume, target_volume))
  return total_volume >= target_volume
end



-----------------------------------------
--ACTIONS--------------------------------
-----------------------------------------

local function stopFilling ()
  if not stopPump() then return false end
  setLuaStatus("Bouilleur plein")
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
			sendMsg("Début du remplissage du bouilleur...", -1) --on rend compte dans la console du navigateur
			sendMsg("Début du remplissage du bouilleur...", 2) --on envoie un message à l’opérateur
      		setLuaStatus("Remplissage du bouilleur")
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
      setLuaStatus("Remplissage du bouilleur")
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
  setLuaStatus("Script arrêté")
elseif not use_level_sensor and not use_flow_sensor then
  stopPump()
  setLuaStatus("Erreur : les capteurs de remplissage sont désactivés")
  sendMsg("Erreur : les capteurs de remplissage sont désactivés.", -1)
  sendMsg("Erreur : les capteurs de remplissage sont désactivés.", 0)
else
  --resetFilling ()
  fillTank()
end
-- stopFilling()
