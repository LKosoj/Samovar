
-- AJUSTES DEL SENSOR DE NIVEL ---------------
local min_bottom_level = 150 -- lectura mínima del sensor cuando el líquido alcanza el contacto inferior
local delta_top_percent = 40 -- diferencia mínima (en % del inferior) entre las lecturas de los contactos inferior y superior
local bottom_readings_skip = 4 -- cuántas lecturas del inferior omitir antes de registrar el resultado
-- AJUSTES DEL SENSOR DE CAUDAL ---------------
local target_volume = 30 -- volumen objetivo en litros que hay que reunir
local flow_factor = 1.0 -- coeficiente de corrección de la imprecisión del sensor de caudal

-- SENSORES UTILIZADOS --------------
local use_level_sensor = true
local use_flow_sensor = false

-- DEFINICIÓN DE VARIABLES ---
local tank_filled = getObject("tank_filled") -- leemos si el calderín está lleno
local pump_started = getNumVariable("pump_started") + 0 -- leemos el indicador confirmado de encendido de la bomba
local bottom_pin = getObject("bottom_pin", "NUMERIC") + 0 -- leemos el nivel inferior guardado
local bottom_readings_count = getObject("bottom_readings_count", "NUMERIC") + 0 -- leemos el número de lecturas ya omitidas
local start_time = getObject("start_time", "NUMERIC") + 0 -- leemos la hora de inicio de la bomba
local last_reading_time = getObject("last_reading_time", "NUMERIC") + 0 -- leemos la hora de la última medición de caudal
local last_reading_flow = getObject("last_reading_flow", "NUMERIC") + 0 -- leemos la última medición de caudal
local total_volume = getObject("total_volume", "NUMERIC") + 0 -- leemos el volumen total reunido hasta ahora



local sensor = analogRead() --leemos el valor analógico del pin 34 (a él está conectado el sensor de nivel)

local function verifyVolumeTargets () -- comprobamos que los datos del sensor de caudal sean correctos
  if (type(target_volume) ~= "number" or target_volume <= 0 or type(flow_factor) ~= "number" or flow_factor <= 0) then
    sendMsg("Error en los parámetros de volumen!", -1) --informamos en la consola del navegador
    sendMsg("Error en los parámetros de volumen!", 0) --enviamos un mensaje al operador
    use_flow_sensor = false
  end
end

local function startPump()
  local now = millis() + 0
  if setPumpPwm(1023) ~= ACTUATOR_COMMAND_APPLIED then
    setLuaStatus("Error al encender la bomba")
    sendMsg("La bomba no confirmó el encendido.", -1)
    sendMsg("La bomba no confirmó el encendido.", 0)
    return false
  end
  if start_time <= 0 then setObject("start_time", now) end
  setObject("last_reading_time", now)
  setObject("last_reading_flow", getNumVariable("WFflowRate") + 0)
  setObject("total_volume", total_volume)
  sendMsg("Bomba encendida", -1) --informamos en la consola del navegador
  sendMsg("Bomba encendida", 2) --enviamos un mensaje al operador
  return true
end


local function stopPump()
  if setPumpPwm(0) ~= ACTUATOR_COMMAND_APPLIED then
    setLuaStatus("Error al apagar la bomba")
    sendMsg("La bomba no confirmó el apagado.", -1)
    sendMsg("La bomba no confirmó el apagado.", 0)
    return false
  end
  sendMsg("Bomba apagada", -1) --avisamos en la consola del navegador
  sendMsg("Bomba apagada", 2) --enviamos un mensaje al operador
  return true
end



local function check4level()
	if bottom_pin > 0 then
		if sensor > bottom_pin * (1 + delta_top_percent/100) then --el salto al alcanzar el contacto superior supera el delta mínimo
			sendMsg("Sensor de nivel: calderín lleno.", -1) --informamos en la consola del navegador
			sendMsg("Sensor de nivel: calderín lleno.", 0) --enviamos un mensaje al operador
			return true --calderín lleno
		end
	elseif sensor > min_bottom_level then
		if (bottom_readings_count == bottom_readings_skip) then
			setObject("bottom_pin", sensor) --guardamos el valor del contacto inferior
			sendMsg("bottom_pin: " .. sensor, -1)
			else
			setObject("bottom_readings_count", bottom_readings_count + 1) --aumentamos el contador de omitidas
		end
	end
	return false	
end




local function check4volume()
  local current_rate = getNumVariable("WFflowRate") + 0
  local now = millis() + 0
  if current_rate < 0 then
    stopPump()
    setLuaStatus("Error del sensor de caudal")
    sendMsg("Error del sensor de caudal: caudal negativo.", -1)
    sendMsg("Error del sensor de caudal: caudal negativo.", 0)
    return false
  end
  if last_reading_time <= 0 then
    setObject("last_reading_time", now)
    setObject("last_reading_flow", current_rate)
    return false
  end
  if now < last_reading_time then
    stopPump()
    setLuaStatus("Error de tiempo del sensor de caudal")
    sendMsg("Error del sensor de caudal: se reinició el tiempo de medición.", -1)
    sendMsg("Error del sensor de caudal: se reinició el tiempo de medición.", 0)
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
  setLuaStatus(string.format("Llenado del calderín: %.2f / %.2f l", total_volume, target_volume))
  return total_volume >= target_volume
end



-----------------------------------------
--ACTIONS--------------------------------
-----------------------------------------

local function stopFilling ()
  if not stopPump() then return false end
  setLuaStatus("Calderín lleno")
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
			sendMsg("Empezamos a llenar el calderín...", -1) --informamos en la consola del navegador
			sendMsg("Empezamos a llenar el calderín...", 2) --enviamos un mensaje al operador
      		setLuaStatus("Llenado del calderín")
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
      setLuaStatus("Llenado del calderín")
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
  setLuaStatus("Script detenido")
elseif not use_level_sensor and not use_flow_sensor then
  stopPump()
  setLuaStatus("Error: los sensores de llenado están desactivados")
  sendMsg("Error: los sensores de llenado están desactivados.", -1)
  sendMsg("Error: los sensores de llenado están desactivados.", 0)
else
  --resetFilling ()
  fillTank()
end
-- stopFilling()
