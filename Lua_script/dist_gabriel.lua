--Скрипт для проведения дистилляции с разбиением по трем емкостям.
--Дистилляция начитается с 0 емкости. Запоминаем температуру в кубе в начале кипения.
--При повышении Т в кубе на заданную уставку, переключаем сервопривод на заданную позицию.

--НАЧАЛЬНЫЕ УСТАНОВКИ
t_delta1 = 4 --первая уставка температуры в кубе, при превышении сменится емкость
t_delta2 = 4 --вторая уставка температуры в кубе, при превышении сменится емкость
power_delta = 10 -- на столько процентов снизится текущая мощность, если 0 - не снижаем
use_temp = 0 --если 1 - то использовать переход на следующую емкость по температуре, если 0 - то по спиртуозности

-- ОПРЕДЕЛЕНИЕ ПЕРЕМЕННЫХ
b_temp = getNumVariable("boil_temp") + 0 --получаем запомненную температуру кипения
alcohol = getNumVariable("alcohol") + 0 --получаем текущую спиртуозность, посчитанную по температуре куба
alcohol_s = getNumVariable("alcohol_s") + 0 --получаем спиртуозность на момент закипания куба
TankTemp = getNumVariable("TankTemp") + 0 --получаем текущую Т куба
PowerOn = getNumVariable("PowerOn") + 0 --получаем статус подачи мощности
target_power_volt = getNumVariable("target_power_volt") + 0 --получаем текущую мощность
capacity_num = getNumVariable("capacity_num") + 0 --получаем текущую емкость
sg = getObject("sg", "NUMERIC") + 0 -- получаем статус начала работы скрипта
gb = getObject("gb", "NUMERIC") + 0 -- получаем статус реакции на начало кипения

local function changeCapacity(num)
  setCapacity(num) --устанавливаем емкость №num
  sendMsg("Установлена емкость "..num.."!", -1) --пишем в консоль браузера
  sendMsg("Установлена емкость "..num.."!", 2) --пишем оператору
end

-- скрипт начал работу
if (sg == 0) then
  setObject("sg", 1)
  changeCapacity(0)
  setPower(1)
  setLuaStatus("Начата дистилляция по Габриелю")
  sendMsg("Начата дистилляция по Габриелю!", 2) --пишем оператору
end

-- среагировали в скрипте на начало кипения
if (gb == 0 and b_temp > 0) then
  setObject("gb", 1)
  sendMsg("Начат отбор в емкость №0!", 2) --пишем оператору
  --началось кипение - снижаем мощность на power_delta процентов
  if (PowerOn + 0 == 1 and target_power_volt == 0) then
    --если режим разгона, в котором не известно текущее напряжение
    target_power_volt = 220
  end
  --если power_delta > 0 меняем целевое напряжение
  if (power_delta > 0) then
    target_power_volt = target_power_volt - target_power_volt/100*power_delta
    setCurrentPower(target_power_volt)
  end
end

--Обрабатываем логику переключения емкостей
if b_temp > 0 then
setLuaStatus(string.format("Текущая спиртуозность  = %.2f; Т начала кипения = %.2f", alcohol, b_temp))
  if (use_temp == 1) then
  --логика по температуре
    if ((capacity_num + 0 == 0) and ((b_temp + t_delta1) <= TankTemp)) then
      changeCapacity(1)
    elseif ((capacity_num + 0 == 1) and ((b_temp + t_delta1 + t_delta2) <= TankTemp)) then
      changeCapacity(2)
    end
  else
  --логика по спиртуозности
    if (capacity_num + 0 == 0) and (alcohol <= alcohol_s / 2) then
      --спирта осталась половина - переключаем на 1 емкость
      changeCapacity(1)
    elseif (capacity_num + 0 == 1) and (alcohol <= alcohol_s / 4) then
      --спирта осталась четверть - переключаем на 2 емкость
      changeCapacity(2)
    end
  end
end