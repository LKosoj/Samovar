ManPw = getObject("ManPw","NUMERIC")+0 --читаем команды от кнопок 
PwRd =getNumVariable("target_power_volt")+0 --читаем мощность/напряжение
-- Rten=16 Pw=Pw*Pw/Rten --перевод напряжения в мощность для не Stab AVR
Pw=PwRd 
if getStrVariable("program_type")=="B" then --если работает строка отбора тела
 S="" PS="" k=1 --масштаб воздействия
 R = getObject("R","NUMERIC")+0 --режим
 CP=getNumVariable("pressure_value")+0 --текущее давление 
 DZ=digitalRead(27) --датчик захлёба
 Pz=getObject("Pz","NUMERIC")+0 --запомненное давление захлёба
 t=getObject("t","NUMERIC")+0 if t>0 then setObject("t",t-1) end --таймер
 --Pold=getObject("Pold","NUMERIC")+0 CP=(CP+Pold)/2 setObject("Pold",CP) --фильтр скачков датчика давления
 
 Pmin=Pz*0.4 --минимальное давление предзахлёба
 if getState()==40 then Pmax=Pz*0.8 else --если пауза загрубляем верхний предел
   Pmax=Pz*0.5 end -- максимальное давление, при паузе 80% от захлебного, при отборе 50%
 dP=5 if CP>Pmax then dP=(CP-Pmax)*k elseif CP<Pmin then dP=(Pmin-CP)*k end --рассчет воздействия 1-5 МВт
 if dP>5 then dP=5 end
 if R==0 then S=S.."Поиск P захлёба,"
   if DZ==0 then Pw=Pw+1 else setObject("R",1) setObject("Pz",CP) S=S.."Захлёб," end
 elseif R==1 then 
   if DZ==1 then S=S.."Захлёб," setObject("Pz",CP) else S=S.."Предзахлёб," end
   if CP<Pmin then --при давлении ниже минимальной уставки
      S=S.."Низкое давление,"  
	  if t<1 then --если таймер не взведен
	     Pw=Pw+dP setObject("t",30) end PS="+" end --добавляем мощность пропорционально отклонению давлениия и взводим таймер на 30 сек
   if CP>Pmax then --при давлении выше максимальной уставки
      S=S.."Высокое давление," 
	  if t<1 then --если таймер не взведен
	     Pw=Pw-dP setObject("t",20) end PS="-" end --убавляем мощность пропорционально отклонению давлениия и взводим таймер на 20 сек
 end 
 S1=string.format("P=%.2f(%.1f-%.1f),", CP, Pmin, Pmax)
 S2=string.format("ТЭН %d%sВт,", math.floor(PwRd), PS )
 --print("@clear@") 
 --print(S1..S2..S) 
 setLuaStatus(S1..S2.." "..S) 
end
if ManPw ~= 0 then Pw=Pw+ManPw setObject("ManPw",0) end --реализуем команды от кнопок
if Pw~=PwRd and Pw>40 and Pw<2000 then --при условии, что на ТЭНе 40-2000Вт и исходную мощность надо менять
-- Pw=(Pw*Rten)^0.5 --перевод мощности в напряжение для не Stab AVR
setCurrentPower(Pw)  end --регулируем ТЭН