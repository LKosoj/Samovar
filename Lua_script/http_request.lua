setLuaStatus(http_request("http://web.samovar-tool.ru/6.0/version.txt"))

print(http_request("http://httpbin.org/post", "POST", "Content-Type: application/x-www-form-urlencoded", "key1=value1&key2=value2"))
