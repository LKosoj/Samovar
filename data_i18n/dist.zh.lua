--分三个容器进行蒸馏的脚本.
--蒸馏从容器0开始。记住开始沸腾时的釜温.
--当釜温上升达到设定值时，将伺服切换到指定位置.

--初始设置
t_delta1 = 4 --釜温第一设定值，超过后更换容器
t_delta2 = 4 --釜温第二设定值，超过后更换容器
power_delta = 10 -- 当前功率将降低的百分比，为0则不降低
use_temp = 0 --为1时按温度切换到下一个容器，为0时按酒精度切换

-- 变量定义
b_temp = getNumVariable("boil_temp") + 0 --获取已记住的沸腾温度
alcohol = getNumVariable("alcohol") + 0 --获取按釜温计算出的当前酒精度
alcohol_s = getNumVariable("alcohol_s") + 0 --获取釜开始沸腾时的酒精度
TankTemp = getNumVariable("TankTemp") + 0 --获取当前釜温
PowerOn = getNumVariable("PowerOn") + 0 --获取供电状态
target_power_volt = getNumVariable("target_power_volt") + 0 --获取当前功率
capacity_num = getNumVariable("capacity_num") + 0 --获取当前容器
sg = getObject("sg", "NUMERIC") + 0 -- 获取脚本启动状态
gb = getObject("gb", "NUMERIC") + 0 -- 获取沸腾开始响应状态
alcohol_invalid = getObject("alcohol_invalid", "NUMERIC") + 0 -- 获取酒精度不可用状态

local function changeCapacity(num)
  setCapacity(num) --设置容器 №num
  sendMsg("已设置容器 "..num.."!", -1) --写入浏览器控制台
  sendMsg("已设置容器 "..num.."!", 2) --向操作员发送消息
end

-- 脚本已开始运行
if (sg == 0) then
  setObject("sg", 1)
  changeCapacity(0)
  setPower(1)
  setLuaStatus("已开始加布里埃尔蒸馏")
  sendMsg("已开始加布里埃尔蒸馏!", 2) --向操作员发送消息
end

-- 脚本已对沸腾开始作出响应
if (gb == 0 and b_temp > 0) then
  setObject("gb", 1)
  sendMsg("已开始采出到容器 №0!", 2) --向操作员发送消息
  --沸腾已开始，将功率降低power_delta百分比
  if (PowerOn + 0 == 1 and target_power_volt == 0) then
    --如果处于加速升温模式，当前电压未知
    target_power_volt = 220
  end
  --如果 power_delta > 0 更改目标电压
  if (power_delta > 0) then
    target_power_volt = target_power_volt - target_power_volt/100*power_delta
    setCurrentPower(target_power_volt)
  end
end

--处理容器切换逻辑
if b_temp > 0 then
setLuaStatus(string.format("当前酒精度 = %.2f；开始沸腾时温度 = %.2f", alcohol, b_temp))
  if (use_temp == 1) then
  --按温度的逻辑
    if ((capacity_num + 0 == 0) and ((b_temp + t_delta1) <= TankTemp)) then
      changeCapacity(1)
    elseif ((capacity_num + 0 == 1) and ((b_temp + t_delta1 + t_delta2) <= TankTemp)) then
      changeCapacity(2)
    end
  else
  --按酒精度的逻辑
    if alcohol >= 0 and alcohol_s >= 0 then
      setObject("alcohol_invalid", 0)
      if (capacity_num + 0 == 0) and (alcohol <= alcohol_s / 2) then
        --酒精剩下一半，切换到容器1
        changeCapacity(1)
      elseif (capacity_num + 0 == 1) and (alcohol <= alcohol_s / 4) then
        --酒精剩下四分之一，切换到容器2
        changeCapacity(2)
      end
    elseif alcohol_invalid == 0 then
      setObject("alcohol_invalid", 1)
      sendMsg("酒精度不可用：容器切换已推迟", 1)
    end
  end
end
