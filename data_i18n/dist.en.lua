--Script for distillation split across three containers.
--Distillation starts with container 0. Remember the boiler temperature at the start of boiling.
--When the boiler T rises by the set amount, switch the servo to the given position.

--INITIAL SETTINGS
t_delta1 = 4 --first boiler temperature setpoint, when exceeded the container changes
t_delta2 = 4 --second boiler temperature setpoint, when exceeded the container changes
power_delta = 10 -- by this many percent the current power will drop, if 0 - do not reduce
use_temp = 0 --if 1 - switch to the next container by temperature, if 0 - by ABV

-- VARIABLE DEFINITIONS
b_temp = getNumVariable("boil_temp") + 0 --get the stored boiling temperature
alcohol = getNumVariable("alcohol") + 0 --get the current ABV calculated from the boiler temperature
alcohol_s = getNumVariable("alcohol_s") + 0 --get the ABV at the moment the boiler started boiling
TankTemp = getNumVariable("TankTemp") + 0 --get the current boiler T
PowerOn = getNumVariable("PowerOn") + 0 --get the power supply status
target_power_volt = getNumVariable("target_power_volt") + 0 --get the current power
capacity_num = getNumVariable("capacity_num") + 0 --get the current container
sg = getObject("sg", "NUMERIC") + 0 -- get the script start status
gb = getObject("gb", "NUMERIC") + 0 -- get the boiling start reaction status
alcohol_invalid = getObject("alcohol_invalid", "NUMERIC") + 0 -- get the ABV unavailable status

local function changeCapacity(num)
  setCapacity(num) --set the container №num
  sendMsg("Container set "..num.."!", -1) --write to the browser console
  sendMsg("Container set "..num.."!", 2) --write to the operator
end

-- script started
if (sg == 0) then
  setObject("sg", 1)
  changeCapacity(0)
  setPower(1)
  setLuaStatus("Gabriel distillation started")
  sendMsg("Gabriel distillation started!", 2) --write to the operator
end

-- the script reacted to the start of boiling
if (gb == 0 and b_temp > 0) then
  setObject("gb", 1)
  sendMsg("Take-off to container started №0!", 2) --write to the operator
  --boiling started - reduce power by power_delta percent
  if (PowerOn + 0 == 1 and target_power_volt == 0) then
    --if heat-up mode, in which the current voltage is unknown
    target_power_volt = 220
  end
  --if power_delta > 0 change the target voltage
  if (power_delta > 0) then
    target_power_volt = target_power_volt - target_power_volt/100*power_delta
    setCurrentPower(target_power_volt)
  end
end

--Handle the container switching logic
if b_temp > 0 then
setLuaStatus(string.format("Current ABV = %.2f; boiling start T = %.2f", alcohol, b_temp))
  if (use_temp == 1) then
  --temperature logic
    if ((capacity_num + 0 == 0) and ((b_temp + t_delta1) <= TankTemp)) then
      changeCapacity(1)
    elseif ((capacity_num + 0 == 1) and ((b_temp + t_delta1 + t_delta2) <= TankTemp)) then
      changeCapacity(2)
    end
  else
  --ABV logic
    if alcohol >= 0 and alcohol_s >= 0 then
      setObject("alcohol_invalid", 0)
      if (capacity_num + 0 == 0) and (alcohol <= alcohol_s / 2) then
        --half of the alcohol is left - switch to container 1
        changeCapacity(1)
      elseif (capacity_num + 0 == 1) and (alcohol <= alcohol_s / 4) then
        --a quarter of the alcohol is left - switch to container 2
        changeCapacity(2)
      end
    elseif alcohol_invalid == 0 then
      setObject("alcohol_invalid", 1)
      sendMsg("ABV unavailable: container switch postponed", 1)
    end
  end
end
