 --|Мощность --^
StP = getObject("StP","NUMERIC")+0 
MP = getObject("MP","NUMERIC")+0 
Pw = getNumVariable("target_power_volt") + 0 
Pw=Pw-StP+0
if Pw>=0 then
setCurrentPower(Pw)
end