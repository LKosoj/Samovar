--Script para destilar repartiendo en tres recipientes.
--La destilación empieza con el recipiente 0. Guardamos la temperatura del calderín al empezar a hervir.
--Cuando la T del calderín sube en la cantidad indicada, pasamos el servo a la posición indicada.

--AJUSTES INICIALES
t_delta1 = 4 --primera consigna de temperatura del calderín, al superarla cambia el recipiente
t_delta2 = 4 --segunda consigna de temperatura del calderín, al superarla cambia el recipiente
power_delta = 10 -- en cuántos por ciento bajará la potencia actual, si es 0 no se baja
use_temp = 0 --si es 1, pasar al siguiente recipiente por temperatura, si es 0, por graduación

-- DEFINICIÓN DE VARIABLES
b_temp = getNumVariable("boil_temp") + 0 --obtenemos la temperatura de ebullición guardada
alcohol = getNumVariable("alcohol") + 0 --obtenemos la graduación actual, calculada por la temperatura del calderín
alcohol_s = getNumVariable("alcohol_s") + 0 --obtenemos la graduación en el momento en que el calderín empezó a hervir
TankTemp = getNumVariable("TankTemp") + 0 --obtenemos la T actual del calderín
PowerOn = getNumVariable("PowerOn") + 0 --obtenemos el estado de la entrega de potencia
target_power_volt = getNumVariable("target_power_volt") + 0 --obtenemos la potencia actual
capacity_num = getNumVariable("capacity_num") + 0 --obtenemos el recipiente actual
sg = getObject("sg", "NUMERIC") + 0 -- obtenemos el estado de inicio del script
gb = getObject("gb", "NUMERIC") + 0 -- obtenemos el estado de la reacción al inicio de la ebullición
alcohol_invalid = getObject("alcohol_invalid", "NUMERIC") + 0 -- obtenemos el estado de graduación no disponible

local function changeCapacity(num)
  setCapacity(num) --establecemos el recipiente №num
  sendMsg("Recipiente establecido "..num.."!", -1) --escribimos en la consola del navegador
  sendMsg("Recipiente establecido "..num.."!", 2) --escribimos al operador
end

-- el script empezó a funcionar
if (sg == 0) then
  setObject("sg", 1)
  changeCapacity(0)
  setPower(1)
  setLuaStatus("Se inició la destilación según Gabriel")
  sendMsg("Se inició la destilación según Gabriel!", 2) --escribimos al operador
end

-- el script reaccionó al inicio de la ebullición
if (gb == 0 and b_temp > 0) then
  setObject("gb", 1)
  sendMsg("Se inició la extracción al recipiente №0!", 2) --escribimos al operador
  --empezó la ebullición: bajamos la potencia en power_delta por ciento
  if (PowerOn + 0 == 1 and target_power_volt == 0) then
    --si es el modo de aceleración, en el que no se conoce la tensión actual
    target_power_volt = 220
  end
  --si power_delta > 0 cambiamos la tensión objetivo
  if (power_delta > 0) then
    target_power_volt = target_power_volt - target_power_volt/100*power_delta
    setCurrentPower(target_power_volt)
  end
end

--Procesamos la lógica de cambio de recipientes
if b_temp > 0 then
setLuaStatus(string.format("Graduación actual  = %.2f; T de inicio de ebullición = %.2f", alcohol, b_temp))
  if (use_temp == 1) then
  --lógica por temperatura
    if ((capacity_num + 0 == 0) and ((b_temp + t_delta1) <= TankTemp)) then
      changeCapacity(1)
    elseif ((capacity_num + 0 == 1) and ((b_temp + t_delta1 + t_delta2) <= TankTemp)) then
      changeCapacity(2)
    end
  else
  --lógica por graduación
    if alcohol >= 0 and alcohol_s >= 0 then
      setObject("alcohol_invalid", 0)
      if (capacity_num + 0 == 0) and (alcohol <= alcohol_s / 2) then
        --queda la mitad del alcohol: pasamos al recipiente 1
        changeCapacity(1)
      elseif (capacity_num + 0 == 1) and (alcohol <= alcohol_s / 4) then
        --queda un cuarto del alcohol: pasamos al recipiente 2
        changeCapacity(2)
      end
    elseif alcohol_invalid == 0 then
      setObject("alcohol_invalid", 1)
      sendMsg("Graduación no disponible: cambio de recipiente aplazado", 1)
    end
  end
end
