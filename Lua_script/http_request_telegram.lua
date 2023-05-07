--Скрипт для отправки сообщения в телеграмм

--НАЧАЛЬНЫЕ УСТАНОВКИ
token = "ххххх:ххххххх"  -- токен вашего бота. Как создать бота в телеграмм - смотреть в интернете.
chat_id = "123456788" -- id пользователя, которому бот отправит сообщение. Как определить id пользователя телеграмм - смотреть в интернете.

local char_to_hex = function(c)
  return string.format("%%%02X", string.byte(c))
end
 
local function urlencode(url)
  if url == nil then
    return
  end
  url = url:gsub("\n", "\r\n")
  url = url:gsub("([^%w ])", char_to_hex)
  url = url:gsub(" ", "+")
  return url
end
 
local hex_to_char = function(x)
  return string.char(tonumber(x, 16))
end
 
function SendTelegram(text)
  http_request("http://212.237.16.93/bot" .. token .. "/sendMessage?chat_id=" .. chat_id .. "&text=" .. urlencode(text))
end
 
local text = "Текущая температура куба = " .. getNumVariable("TankTemp")
 
SendTelegram(text)
--setNumVariable("loop_lua_fl",0)
