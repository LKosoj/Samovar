 -- ОПРЕДЕЛЕНИЕ ПЕРЕМЕННЫХ ---
pump_start = getObject("pump_start", "NUMERIC") + 0  -- флаг состояния кнопки включения насоса: 0 или 1
pump_up = getObject("pump_up", "NUMERIC") + 0        -- флаг состояния кнопки увеличения скорости насоса: 0 или 1
pump_down = getObject("pump_down", "NUMERIC") + 0    -- флаг состояния кнопки уменьшения скорости насоса: 0 или 1
pump_speed = getNumVariable("water_pump_speed") + 0  -- значение скорости насоса: от 0 до 1023
pump_started = getNumVariable("pump_started")        -- флаг работы насоса: 0 или 1

 -- РАБОТА ---
if pump_start == 1 and pump_started == 0 then  -- если нажата кнопка включения и насос не работает
	pump_speed = 1023                       -- устанавливаем скорость на 1023/1023
	setNumVariable("pump_started", 1)       -- состояние насоса: включен
	digitalWrite(4, HIGH)                   -- устанавливаем на 4 ноге высокий уровень => включаем насос
	setObject("pump_start", 0)              -- сброс флага необходимости включения насоса
	sendMsg("Насос включен", 2)             -- отправляем сообщение оператору
end

if pump_up == 1 and pump_speed < 975 then  -- обработка нажатия кнопки увеличения скорости
  pump_speed = pump_speed + 51             -- увеличиваем скорость на 51/1023
  setObject("pump_up", 0)                  -- опускаем флаг увеличения скорости
end

if pump_down == 1 and pump_speed > 250 then  -- обработка нажатия кнопки уменьшения скорости
  pump_speed = pump_speed - 51               -- уменьшаем скорость на 51/1023
  setObject("pump_down", 0)                  -- опускаем флаг уменьшения скорости
end

if pump_started == 1 then                                  -- обработка изменения скорости насоса
  setPumpPwm(pump_speed)                                   -- устанавливаем значение скорости насоса
  setLuaStatus(" Скорость насоса "..pump_speed.."/1023")   -- выводим скорость насоса в статус
end