print("@clear@") 
print()
dTopt = 3 
dPmax = 12
MS = getObject("MS","NUMERIC")+0 
dStSt = getObject("dStSt","NUMERIC")+0 
MP = getObject("MP","NUMERIC")+0 
StP = getObject("StP","NUMERIC")+0 
R = getObject("R","NUMERIC")+0 
BTB = getObject("BTB","NUMERIC") + 0 
St=getObject("St","NUMERIC")+0

StT=getNumVariable("SteamTemp")+0 StT=72
TCC=getNumVariable("ACPTemp")+0 --TCC = 20
WT =getNumVariable("WaterTemp")+0 --WT = 25
BT =getNumVariable("TankTemp")+0  BT = 83
dT =BTB-BT+0 
Pw =getNumVariable("target_power_volt")+0 
CP =getNumVariable("pressure_value")+0 --CP = 13
print("BardaTB= " .. BTB .. " | dT= "..dT.." | BardaT= "..BT)
print("SteamT = "..StT.." | CC_T= "..TCC.." | WaterT= "..WT)
print("P = " .. CP.." | Step= "..St.." | Power= "..Pw) 
if R == 0 then 
	  setPower(1) 
	  setCurrentPower(MP) 
	  R = 1
elseif R == 1 then 
 print("Прогрев")
    if StT>60 then 
		R = 2 
		BTB=BT 
		setObject("BTB",BTB) 
		--set_stepper_target(dStSt, 0, 10) 
		setObject("St",dStSt)
		--sendMsg("Колонна прогрета, включаем воду и подачу браги", 0)
		end 
elseif R == 2 then 
   print("Режим")
	if ((getTimer(6)==0) and (dT<dTopt))  then 
		if St<MS then
			St=St+dStSt
			set_stepper_target(St, 0, 999999999) 
			setObject("St",St)
			setTimer(6,30) 
		end
	end
		if ((getTimer(6)==0) and (dT>dTopt)) then  
			if St>0 then
			St=St-dStSt+0 
			set_stepper_target(St, 0, 1000)
			setObject("St",St)
			setTimer(6,10) 
			end
		end
	if StT > 90  then
		print("Закончилась брага")
		--Stop() 
	end
	if BT < 70 then
		print("Прекратилась подача пара")
		--Stop() 
	end 
end
setObject("R",R+0) 
--Аварии
	if (CP >= dPmax) then
	  print("Захлёб")
		if getTimer(2)==0 then 
			if getTimer(1)>0 and getTimer(1)<10 then 
				if Pw > StP-1 then 
				Pw=Pw-StP+0
				setCurrentPower(Pw+0) 
				setTimer(2,3) 
				end 
			end 
		if getTimer(1)==0 then 
		setTimer(1,10) 
		end
		end
	else 
	setTimer(1,0) 
	setTimer(2,0) 
	end
     
	if (TCC > 50 or WT>60) then 
		if getTimer(5)==0 then 
			if getTimer(4)>0 and getTimer(4)<10 then 
			print("Недостаточное охлаждение, останов") 
			--Stop() 
			end
		end
		if getTimer(4)==0 then 
		setTimer(4,40) 
		end
	else 
	setTimer(4,0)
	setTimer(5,0)
	end


setObject("R",R+0) 

