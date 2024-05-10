--|Start/Stop^
--setNumVariable("show_lua_script",1) -- включаем отладку в сом порт
print ("Запуск скрипта")
if (getNumVariable("loop_lua_fl", "NUMERIC") + 0) == 0 then
MS=2000 --максимальное количество шагов в минуту перистальтического насоса подбирается экспериментально
dStSt=MS/50 --Приращение шагов перистальтического насоса при регулировке 1%
print("dStSt" .. dStSt)
MP=3000 --максимальная мощность либо напряжение регулятора
StP=MP/100 --шаг изменения мощности либо напряжения регулятора

setObject("MP",MP+0)
setObject("StP",StP+0)
setObject("St",0)
setObject("BTB",80)
setObject("dStSt",dStSt+0)
setObject("MS",MS)
setObject("R",0)

setNumVariable("loop_lua_fl", 1) -- включаем циклическое исполнение луа-скриптов
else
setNumVariable("loop_lua_fl",0)    -- выключаем циклическое исполнение луа-скриптов
set_stepper_target(0, 0, 0)
set_stepper_target(0, 0, 0) --Отключаем перистальтический насос.
setPower(0) -- Выключаем нагрев ТЭН.
print ("Останов скрипта")
end
