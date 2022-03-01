
-- УСТАНОВКИ ДЛЯ ДАТЧИКА УРОВНЯ ---------------
min_bottom_level = 150 -- минимальные показания датчика при достижении жидкостью нижнего контакта
delta_top_percent = 40 -- минимальная разница (в % от нижнего) между показаниями нижнего и верхнего контактов
bottom_readings_skip = 4 -- сколько показаний нижнего пропустить, прежде чем записать итог
-- УСТАНОВКИ ДЛЯ ДАТЧИКА ПОТОКА ---------------
target_volume = 30 -- целевой объём в литрах, который требуется набрать
flow_factor = 1.0 -- коэффициент корректировки неточности датчика потока 

-- ИСПОЛЬЗУЕМЫЕ ДАТЧИКИ --------------
use_level_sensor = true
use_flow_sensor = false

-- ОПРЕДЕЛЕНИЕ ПЕРЕМЕННЫХ ---
tank_filled = getObject("tank_filled") -- читаем, наполнен ли куб
pump_started = getObject("pump_started") -- читаем признак включения насоса
bottom_pin = getObject("bottom_pin", "NUMERIC") + 0 -- читаем сохранённый нижний уровень
bottom_readings_count = getObject("bottom_readings_count", "NUMERIC") + 0 -- читаем количество уже пропущенных показаний
start_time = getObject("start_time", "NUMERIC") + 0 -- читаем время начала работы насоса
last_reading_time = getObject("last_reading_time", "NUMERIC") + 0 -- читаем время последнего измерения потока
last_reading_flow = getObject("last_reading_flow", "NUMERIC") + 0 -- читаем последнее измерение потока
total_volume = getObject("total_volume", "NUMERIC") + 0 -- читаем общий уже набранный объём



sensor = analogRead() --читаем аналоговое значение пина 34 (к нему подключён датчик уровня)

local function verifyVolumeTargets () -- проверяем корректность данных для датчика потока
  if (target_volume == nil or target_volume == 0 or type(target_volume) ~= "number" or  flow_factor == nil or flow_factor == 0 or type(flow_factor) ~= "number") then
    sendMsg("Ошибка в параметрах объёма!", -1) --отчитываемся в консоль браузера
    sendMsg("Ошибка в параметрах объёма!", 0) --отправляем сообщение оператору
    use_flow_sensor = false
  end
end

local function startPump()
  pinMode(4, OUTPUT) --устанавливаем режим пина
	digitalWrite(4, HIGH) --устанавливаем на 4 ноге высокий уровень => включаем насос
	setObject("pump_started", "true") --сохраняем признак включения насоса
	sendMsg("Насос включён", -1) --отчитываемся в консоль браузера
	sendMsg("Насос включён", 2) --отправляем сообщение оператору
end


local function stopPump()
  pinMode(4, OUTPUT) --устанавливаем режим пина
	digitalWrite(4, LOW) --устанавливаем на 4 ноге низкий уровень => выключаем насос
	setObject("pump_started", "false") --сохраняем признак выключения насоса
	sendMsg("Насос выключен", -1) --сообщаем в консоль браузера
	sendMsg("Насос выключен", 2) --отправляем сообщение оператору
end



local function check4level()
	if bottom_pin > 0 then
		if sensor > bottom_pin * (1 + delta_top_percent/100) then --скачок при достижении верхнего контакта больше минимальной дельты
			sendMsg("Датчик уровня: куб заполнен.", -1) --отчитываемся в консоль браузера
			sendMsg("Датчик уровня: куб заполнен.", 0) --отправляем сообщение оператору
			return true --куб заполнен
		end
	elseif sensor > min_bottom_level then
		if (bottom_readings_count == bottom_readings_skip) then
			setObject("bottom_pin", sensor) --сохраняем значение для нижнего контакта
			sendMsg("bottom_pin: " .. sensor, -1)
			else
			setObject("bottom_readings_count", bottom_readings_count + 1) --увеличиваем счётчик пропущенных
		end
	end
	return false	
end




local function check4volume()
  current_rate = getNumVariable(WFflowRate)
  
end



-----------------------------------------
--ACTIONS--------------------------------
-----------------------------------------

local function stopFilling ()
	stopPump()
  setLuaStatus("Куб заполнен")
	setObject("bottom_pin", 0)
	setObject("tank_filled", "true")
	sendMsg("Done: filling stopped.", -1)
	sendMsg("Done: filling stopped.", 0)
end



local function fillTank ()
  sendMsg("tank_filled: " .. tank_filled, -1)
  sendMsg("bottom_pin: " .. bottom_pin, -1)
  sendMsg("sensor: " .. sensor, -1)
	if tank_filled ~= "true" then
	  sendMsg("pump_started: " .. pump_started, -1)
	  if pump_started ~= "true" then
			sendMsg("Начинаем заполнение куба...", -1) --отчитываемся в консоль браузера
			sendMsg("Начинаем заполнение куба...", 2) --отправляем сообщение оператору
      		setLuaStatus("Заполнение куба")
      		startPump()
		else
      if use_level_sensor and check4level() then stopFilling() end
      if use_flow_sensor and check4volume() then stopFilling() end
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
	sendMsg("Done: filling reset.", -1)
	sendMsg("Done: filling reset.", 0)
end



--RUN--------------------------------

--resetFilling ()
 fillTank()
-- stopFilling()



