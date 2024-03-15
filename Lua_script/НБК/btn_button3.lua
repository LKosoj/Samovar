 --|Насос --^
dStSt = getObject("dStSt","NUMERIC")+0 
St=getObject("St","NUMERIC")+0
St=St-dStSt+0
if St<dStSt then
CurrentStepper = 0 
end
if St>=0 then
setObject("St",St)
end
set_stepper_target(St, 0, 99999999) 