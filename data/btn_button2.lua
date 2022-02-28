 --|Остановить^
setNumVariable("loop_lua_fl",0)
pinMode(4, OUTPUT) --устанавливаем режим пина
digitalWrite(4, LOW) --устанавливаем на 4 ноге низкий уровень => выключаем насос
setObject("pump_started", "false") --сохраняем признак выключения насоса
