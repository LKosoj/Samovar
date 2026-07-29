 -- ОПРЕДЕЛЕНИЕ ПЕРЕМЕННЫХ ---
pump_start = getObject("pump_start", "NUMERIC") + 0  -- флаг состояния кнопки включения насоса: 0 или 1
pump_up = getObject("pump_up", "NUMERIC") + 0        -- флаг состояния кнопки увеличения скорости насоса: 0 или 1
pump_down = getObject("pump_down", "NUMERIC") + 0    -- флаг состояния кнопки уменьшения скорости насоса: 0 или 1
pump_speed = getNumVariable("water_pump_speed") + 0  -- значение скорости насоса: от 0 до 1023
	pump_started = getNumVariable("pump_started")        -- фактический read-only статус насоса

local function applyPumpSpeed(target_speed, request_name)
  local result = setPumpPwm(target_speed)
  if result ~= ACTUATOR_COMMAND_APPLIED then
    setLuaStatus("Ошибка изменения скорости насоса; запрос сохранён для повтора")
    sendMsg("Насос не подтвердил изменение скорости.", 1)
    return false
  end
  setObject(request_name, 0)
  setLuaStatus(" Скорость насоса "..target_speed.."/1023")
  return true
end

 -- РАБОТА ---
if pump_start == 1 and pump_started == 0 then  -- если нажата кнопка включения и насос не работает
  local result = setPumpPwm(1023)
  if result ~= ACTUATOR_COMMAND_APPLIED then
    setLuaStatus("Ошибка включения насоса; запрос сохранён для повтора")
    sendMsg("Насос не подтвердил включение.", 1)
  else
    setObject("pump_start", 0)              -- сброс флага только после подтверждения
    sendMsg("Насос включен", 2)             -- отправляем сообщение оператору
  end
end

if pump_started == 1 and pump_up == 1 and pump_speed < 975 then
  applyPumpSpeed(pump_speed + 51, "pump_up")
elseif pump_started == 1 and pump_down == 1 and pump_speed > 250 then
  applyPumpSpeed(pump_speed - 51, "pump_down")
elseif pump_started == 1 then
  setLuaStatus(" Скорость насоса "..pump_speed.."/1023")
end
