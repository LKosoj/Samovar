--|Start/Stop^
--setNumVariable("show_lua_script",0) -- включаем отладку в сом порт
if (getNumVariable("loop_lua_fl", "NUMERIC") + 0) == 0 then
setObject("ManSt",0) --ручной задатчик насоса
setObject("ManPw",0) --ручной задатчик ТЭНа
setObject("St",0) -- подача мл/час
setObject("Pw",0) -- целевая мощность ТЭНа
setObject("BTB",92) -- базовая температура барды
setObject("R",0) --включить режим прогрева
setObject("BFl",60) -- флаг отслеживания конца браги, сек
setObject("StFl",20) -- флаг отслеживания конца пара, сек
setObject("TWFl",20) -- флаг отслеживания t воды и спирта, сек
setObject("WFl",20) -- флаг отслеживания подпитки
setNumVariable("loop_lua_fl", 1) 
setPower(1) --включаем нагрев
setPower(1) --включаем нагрев
pinMode(34, INPUT) --LUA пин цифровой режим 
setObject("otl",60) -- отладочная
else
setNumVariable("loop_lua_fl",0) -- выключаем циклическое исполнение луа-скриптов
set_stepper_target(0, 0, 0)
set_stepper_target(0, 0, 0) --Отключаем перистальтический насос.
setPower(0) -- Выключаем нагрев ТЭН.
setLuaStatus ("Ручной останов скрипта")
end
