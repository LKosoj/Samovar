 --|Насос ++^
MS = getObject("MS","NUMERIC")+0 
dStSt = getObject("dStSt","NUMERIC")+0 
St=getObject("St","NUMERIC")+0

St=St+dStSt+0
if St<=MS then
setObject("St",St)
end
set_stepper_target(St, 0, 99999999) 