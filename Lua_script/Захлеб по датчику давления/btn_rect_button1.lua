--|Start/Stop^
--setNumVariable("show_lua_script",0) -- включаем отладку в сом порт
if (getNumVariable("loop_lua_fl", "NUMERIC") + 0) == 0 then
setObject("ManPw",0) --ручной задатчик ТЭНа
setObject("R",0) --включить режим поиска давления захлёба
setObject("Pz",55) --давление захлёба, предварительно
setObject("Pold",0) --предыдущий замер давления для фильтра
setObject("t",0) --таймер
setNumVariable("loop_lua_fl", 1) 
--setObject("otl",60) -- отладочная
else
setNumVariable("loop_lua_fl",0) -- выключаем циклическое исполнение луа-скриптов
print ("Ручной останов скрипта")
end
