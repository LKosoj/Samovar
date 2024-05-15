BT =getNumVariable("TankTemp")+0
if BT>92 then  
setNextProgram()
setNumVariable("loop_lua_fl",0)
end
setLuaStatus(string.format("Тк= %.2f | Pк= %.2f", BT, getNumVariable("pressure_value"))) 