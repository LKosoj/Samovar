
-- LEVEL SENSOR SETTINGS ---------------
local min_bottom_level = 150 -- minimum sensor reading when the liquid reaches the lower contact
local delta_top_percent = 40 -- minimum difference (in % of the lower one) between the lower and upper contact readings
local bottom_readings_skip = 4 -- how many lower readings to skip before recording the result
-- FLOW SENSOR SETTINGS ---------------
local target_volume = 30 -- target volume in liters to collect
local flow_factor = 1.0 -- flow sensor inaccuracy correction factor

-- SENSORS IN USE --------------
local use_level_sensor = true
local use_flow_sensor = false

-- VARIABLE DEFINITIONS ---
local tank_filled = getObject("tank_filled") -- read whether the boiler is filled
local pump_started = getNumVariable("pump_started") + 0 -- read the confirmed pump start flag
local bottom_pin = getObject("bottom_pin", "NUMERIC") + 0 -- read the stored lower level
local bottom_readings_count = getObject("bottom_readings_count", "NUMERIC") + 0 -- read the number of readings already skipped
local start_time = getObject("start_time", "NUMERIC") + 0 -- read the pump start time
local last_reading_time = getObject("last_reading_time", "NUMERIC") + 0 -- read the time of the last flow measurement
local last_reading_flow = getObject("last_reading_flow", "NUMERIC") + 0 -- read the last flow measurement
local total_volume = getObject("total_volume", "NUMERIC") + 0 -- read the total volume collected so far



local sensor = analogRead() --read the analog value of pin 34 (the level sensor is connected to it)

local function verifyVolumeTargets () -- check the flow sensor data for correctness
  if (type(target_volume) ~= "number" or target_volume <= 0 or type(flow_factor) ~= "number" or flow_factor <= 0) then
    sendMsg("Volume parameters error!", -1) --report to the browser console
    sendMsg("Volume parameters error!", 0) --send a message to the operator
    use_flow_sensor = false
  end
end

local function startPump()
  local now = millis() + 0
  if setPumpPwm(1023) ~= ACTUATOR_COMMAND_APPLIED then
    setLuaStatus("Pump start error")
    sendMsg("Pump did not confirm start.", -1)
    sendMsg("Pump did not confirm start.", 0)
    return false
  end
  if start_time <= 0 then setObject("start_time", now) end
  setObject("last_reading_time", now)
  setObject("last_reading_flow", getNumVariable("WFflowRate") + 0)
  setObject("total_volume", total_volume)
  sendMsg("Pump on", -1) --report to the browser console
  sendMsg("Pump on", 2) --send a message to the operator
  return true
end


local function stopPump()
  if setPumpPwm(0) ~= ACTUATOR_COMMAND_APPLIED then
    setLuaStatus("Pump stop error")
    sendMsg("Pump did not confirm stop.", -1)
    sendMsg("Pump did not confirm stop.", 0)
    return false
  end
  sendMsg("Pump off", -1) --report to the browser console
  sendMsg("Pump off", 2) --send a message to the operator
  return true
end



local function check4level()
	if bottom_pin > 0 then
		if sensor > bottom_pin * (1 + delta_top_percent/100) then --jump on reaching the upper contact is larger than the minimum delta
			sendMsg("Level sensor: boiler is full.", -1) --report to the browser console
			sendMsg("Level sensor: boiler is full.", 0) --send a message to the operator
			return true --boiler is full
		end
	elseif sensor > min_bottom_level then
		if (bottom_readings_count == bottom_readings_skip) then
			setObject("bottom_pin", sensor) --save the value for the lower contact
			sendMsg("bottom_pin: " .. sensor, -1)
			else
			setObject("bottom_readings_count", bottom_readings_count + 1) --increment the skipped counter
		end
	end
	return false	
end




local function check4volume()
  local current_rate = getNumVariable("WFflowRate") + 0
  local now = millis() + 0
  if current_rate < 0 then
    stopPump()
    setLuaStatus("Flow sensor error")
    sendMsg("Flow sensor error: negative flow.", -1)
    sendMsg("Flow sensor error: negative flow.", 0)
    return false
  end
  if last_reading_time <= 0 then
    setObject("last_reading_time", now)
    setObject("last_reading_flow", current_rate)
    return false
  end
  if now < last_reading_time then
    stopPump()
    setLuaStatus("Flow sensor time error")
    sendMsg("Flow sensor error: measurement time was reset.", -1)
    sendMsg("Flow sensor error: measurement time was reset.", 0)
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
  setLuaStatus(string.format("Boiler filling: %.2f / %.2f l", total_volume, target_volume))
  return total_volume >= target_volume
end



-----------------------------------------
--ACTIONS--------------------------------
-----------------------------------------

local function stopFilling ()
  if not stopPump() then return false end
  setLuaStatus("Boiler full")
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
			sendMsg("Starting to fill the boiler...", -1) --report to the browser console
			sendMsg("Starting to fill the boiler...", 2) --send a message to the operator
      		setLuaStatus("Boiler filling")
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
      setLuaStatus("Boiler filling")
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
  setLuaStatus("Script stopped")
elseif not use_level_sensor and not use_flow_sensor then
  stopPump()
  setLuaStatus("Error: filling sensors are disabled")
  sendMsg("Error: filling sensors are disabled.", -1)
  sendMsg("Error: filling sensors are disabled.", 0)
else
  --resetFilling ()
  fillTank()
end
-- stopFilling()
