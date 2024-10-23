if getTimer(1)<1 then -- раз в 5 сек
dTopt = 0.5 Pmax = 24 Pmin=2 StTmax=98.5 StTmin=80 dSt = 40 dP=10 Z = 0 PS="" BS="" S="" 
R = getObject("R","NUMERIC")+0  
BTB = getObject("BTB","NUMERIC") + 0 
ManSt = getObject("ManSt","NUMERIC") + 0 
ManPw = getObject("ManPw","NUMERIC") + 0 
St1=getObject("St","NUMERIC")+0 St=St1 
Pw= getObject("Pw","NUMERIC")+0
WFl=getObject("WFl","NUMERIC")+0 
StT=getNumVariable("SteamTemp")+0 
TCC=getNumVariable("ACPTemp")+0 
WT =getNumVariable("WaterTemp")+0 
BT =getNumVariable("TankTemp")+0 
PwRd =getNumVariable("target_power_volt")+0 
CP =getNumVariable("pressure_value")+0 
DZ = digitalRead(27) 
WLev=digitalRead(34)
Tmax=BTB Tmin=BTB-dTopt

-- BT=89.6 StT=96 CP=9
dT=BTB-BT 
local function Stop() setNumVariable("loop_lua_fl",0) set_stepper_target(0, 0, 0) setPower(0) print("Останов.") end	

if DZ==1 then S=S.."Работа датчика захлёба," Z=Z+1 Pw=Pw-100 PS="--"  end

if R == 0 then setObject("R",1) St=3000 Pw=3000 end
if R == 1 then S=S.."Прогрев " if StT>85 then setObject("R",2) setTimer(2,300) St=18000 Pw=2400	end end
if R == 2 then  t1=getTimer(2) S=S.."Стабилизация "..t1
  if t1==0 then setObject("R",3) setObject("BTB",BT) end end
if R == 3 then S=S.."Перв. подача браги. " 
  if dT<dTopt then
    if St<20000 then St=St+100 BS="++" else St=St+50 BS="+" end
    else setObject("R",4)
    end end
if R == 4 then S=S.."Мощ.+брага до 9 мм.р.ст. " 
   if dT<dTopt then St=St+15 BS="+" end 
   if CP<20 then Pw=Pw+5  PS="+" else Pw=Pw-100 setObject("R",5) end end
if R == 5 then S=S.."Работа "
   if dT<dTopt then St=St+5 BS="+" end
   if dT>dTopt then St=St-5 BS="-" end
end 

if R>2 then --аварии
  if CP>Pmax then S=S.."Высокое давление," Pw=Pw-10 PS="-" end   
  if StT>98 then S=S.."Закончилась брага," Stop() end
  if (TCC>60 or WT>70) then S=S.."Недостаточное охлаждение," Stop() end
end

if WLev==1 then S=S.."Мало воды "..WFl if WFl==0 then Stop() else WFl=WFl-5 setObject("WFl",WFl+0) end end
  if WLev~=1 then setObject("WFl",60) end  
  
if ManSt ~= 0 then St=St+ManSt setObject("ManSt",0) end 
if ManPw ~= 0 then Pw=Pw+ManPw setObject("ManPw",0) end
if St<0 then St=0 end
S1=string.format("tB=%.2f(%.1f-%.1f),tSt=%.2f(%.1f-%.1f),P=%.2f(%.1f-%.1f),", BT, Tmin, Tmax, StT, StTmin, StTmax, CP, Pmin, Pmax)
S2=string.format("Брага %.1f%sл/ч, ТЭН %d%sВт,", St/1000, BS, math.floor(PwRd), PS )
S3=string.format("tAlc=%.1f tW=%.1f,",TCC, WT) --print("@clear@") 
--print(S1..S3..S2..S..",")
setLuaStatus(S1..S2.." "..S) 
if St1~=St and St<28001 then set_stepper_target(math.floor(St*0.2008), 0, 0) set_stepper_target(math.floor(St*0.2008), 0, 0) setObject("St",St+0) end --крутим насос
if Pw~=PwRd and Pw>40 and Pw<3001 then setCurrentPower(Pw) setObject("Pw",Pw+0) end --регулируем ТЭН
setTimer(1, 5)
end