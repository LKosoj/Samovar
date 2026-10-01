
-- 液位传感器设置 ---------------
local min_bottom_level = 150 -- 液体到达下触点时传感器的最小读数
local delta_top_percent = 40 -- 下触点与上触点读数之间的最小差值（单位 %，占下触点读数的比例）
local bottom_readings_skip = 4 -- 记录结果前要跳过的下触点读数个数
-- 流量传感器设置 ---------------
local target_volume = 30 -- 需要收集的目标体积，单位升
local flow_factor = 1.0 -- 流量传感器误差修正系数

-- 使用的传感器 --------------
local use_level_sensor = true
local use_flow_sensor = false

-- 变量定义 ---
local tank_filled = getObject("tank_filled") -- 读取釜是否已装满
local pump_started = getNumVariable("pump_started") + 0 -- 读取已确认的泵启动标志
local bottom_pin = getObject("bottom_pin", "NUMERIC") + 0 -- 读取已保存的下限液位
local bottom_readings_count = getObject("bottom_readings_count", "NUMERIC") + 0 -- 读取已跳过的读数个数
local start_time = getObject("start_time", "NUMERIC") + 0 -- 读取泵启动时间
local last_reading_time = getObject("last_reading_time", "NUMERIC") + 0 -- 读取上次流量测量的时间
local last_reading_flow = getObject("last_reading_flow", "NUMERIC") + 0 -- 读取最近一次流量测量值
local total_volume = getObject("total_volume", "NUMERIC") + 0 -- 读取目前已收集的总体积



local sensor = analogRead() --读取引脚34的模拟值(液位传感器接在该引脚上)

local function verifyVolumeTargets () -- 检查流量传感器数据是否正确
  if (type(target_volume) ~= "number" or target_volume <= 0 or type(flow_factor) ~= "number" or flow_factor <= 0) then
    sendMsg("体积参数错误!", -1) --向浏览器控制台报告
    sendMsg("体积参数错误!", 0) --向操作员发送消息
    use_flow_sensor = false
  end
end

local function startPump()
  local now = millis() + 0
  if setPumpPwm(1023) ~= ACTUATOR_COMMAND_APPLIED then
    setLuaStatus("泵启动错误")
    sendMsg("泵未确认启动.", -1)
    sendMsg("泵未确认启动.", 0)
    return false
  end
  if start_time <= 0 then setObject("start_time", now) end
  setObject("last_reading_time", now)
  setObject("last_reading_flow", getNumVariable("WFflowRate") + 0)
  setObject("total_volume", total_volume)
  sendMsg("泵已开启", -1) --向浏览器控制台报告
  sendMsg("泵已开启", 2) --向操作员发送消息
  return true
end


local function stopPump()
  if setPumpPwm(0) ~= ACTUATOR_COMMAND_APPLIED then
    setLuaStatus("泵停止错误")
    sendMsg("泵未确认停止.", -1)
    sendMsg("泵未确认停止.", 0)
    return false
  end
  sendMsg("泵已关闭", -1) --通知浏览器控制台
  sendMsg("泵已关闭", 2) --向操作员发送消息
  return true
end



local function check4level()
	if bottom_pin > 0 then
		if sensor > bottom_pin * (1 + delta_top_percent/100) then --到达上触点时的跳变大于最小差值
			sendMsg("液位传感器：釜已装满.", -1) --向浏览器控制台报告
			sendMsg("液位传感器：釜已装满.", 0) --向操作员发送消息
			return true --釜已装满
		end
	elseif sensor > min_bottom_level then
		if (bottom_readings_count == bottom_readings_skip) then
			setObject("bottom_pin", sensor) --保存下触点的值
			sendMsg("bottom_pin: " .. sensor, -1)
			else
			setObject("bottom_readings_count", bottom_readings_count + 1) --增加已跳过计数
		end
	end
	return false	
end




local function check4volume()
  local current_rate = getNumVariable("WFflowRate") + 0
  local now = millis() + 0
  if current_rate < 0 then
    stopPump()
    setLuaStatus("流量传感器错误")
    sendMsg("流量传感器错误：流量为负.", -1)
    sendMsg("流量传感器错误：流量为负.", 0)
    return false
  end
  if last_reading_time <= 0 then
    setObject("last_reading_time", now)
    setObject("last_reading_flow", current_rate)
    return false
  end
  if now < last_reading_time then
    stopPump()
    setLuaStatus("流量传感器时间错误")
    sendMsg("流量传感器错误：测量时间已重置.", -1)
    sendMsg("流量传感器错误：测量时间已重置.", 0)
    return false
  end
  local elapsed_min = (now - last_reading_time) / 60000.0
  local avg_rate = (last_reading_flow + current_rate) / 2.0
  total_volume = total_volume + avg_rate * elapsed_min * flow_factor
  last_reading_time = now
  last_reading_flow = current_rate
  setObject("last_reading_time", last_reading_time)
  setObject("last_reading_flow", last_reading_flow)
  setObject("total_volume", total_volume)
  setLuaStatus(string.format("釜装料：%.2f / %.2f l", total_volume, target_volume))
  return total_volume >= target_volume
end



-----------------------------------------
--ACTIONS--------------------------------
-----------------------------------------

local function stopFilling ()
  if not stopPump() then return false end
  setLuaStatus("釜已装满")
	setObject("bottom_pin", 0)
	setObject("tank_filled", "true")
	sendMsg("Done: filling stopped.", -1)
	sendMsg("Done: filling stopped.", 0)
  return true
end



local function fillTank ()
  sendMsg("tank_filled: " .. tank_filled, -1)
  sendMsg("bottom_pin: " .. bottom_pin, -1)
  sendMsg("sensor: " .. sensor, -1)
	if tank_filled ~= "true" then
	  sendMsg("pump_started: " .. pump_started, -1)
	  if pump_started == 0 then
			sendMsg("开始向釜装料...", -1) --向浏览器控制台报告
			sendMsg("开始向釜装料...", 2) --向操作员发送消息
      		setLuaStatus("釜装料")
			if not startPump() then return false end
		else
      if use_level_sensor and check4level() then
        stopFilling()
        return
      end
      if use_flow_sensor then
        if check4volume() then stopFilling() end
        return
      end
      setLuaStatus("釜装料")
		end
  else 
    sendMsg("NOTHING 2 DO: tank_filled: " .. tank_filled, -1)
    sendMsg("NOTHING 2 DO: tank_filled: " .. tank_filled, 0)
	end
end



local function resetFilling ()
		sendMsg("tank_filled: " .. tank_filled, 0)
		setObject("tank_filled", "false")
	  setObject("bottom_pin", 0)
	  setObject("bottom_readings_count", 0)
	  setObject("start_time", 0)
	  setObject("last_reading_time", 0)
	  setObject("last_reading_flow", 0)
	  setObject("total_volume", 0)
		sendMsg("Done: filling reset.", -1)
		sendMsg("Done: filling reset.", 0)
	end



--RUN--------------------------------

verifyVolumeTargets()
if getNumVariable("SetScriptOff") + 0 == 1 then
  stopPump()
  setLuaStatus("脚本已停止")
elseif not use_level_sensor and not use_flow_sensor then
  stopPump()
  setLuaStatus("错误：装料传感器已禁用")
  sendMsg("错误：装料传感器已禁用.", -1)
  sendMsg("错误：装料传感器已禁用.", 0)
else
  --resetFilling ()
  fillTank()
end
-- stopFilling()
