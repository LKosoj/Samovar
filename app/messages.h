#ifndef __SAMOVAR_MESSAGES_H_
#define __SAMOVAR_MESSAGES_H_

void SendMsg(const String& m, MESSAGE_TYPE msg_type) {
  if (m.length() < 5) return;
  String MsgPl;
#ifdef USE_MQTT
  MsgPl = m;
  MsgPl.replace(",", ";");
  MqttSendMsg(MsgPl + "," + msg_type, "msg");
#endif
#ifdef USE_TELEGRAM
  switch (msg_type) {
    case 0: MsgPl = F("*Тревога!*\n"); break;
    case 1: MsgPl = F("*Предупреждение!*\n"); break;
    case 2: MsgPl = ""; break;
    default: MsgPl = "";
  }
  MsgPl += " Самовар - " + m;
  if (xSemaphoreTake(xMsgSemaphore, (TickType_t)(50 / portTICK_RATE_MS)) == pdTRUE) {
    msg_q.push(MsgPl.c_str());
    xSemaphoreGive(xMsgSemaphore);
  }
#endif

  if (Msg.length() > 0) {
    Msg += "; ";
    if (msg_level > msg_type) msg_level = msg_type;
  } else msg_level = msg_type;

  Msg += m;

  if (Msg.length() > 250) {
    Msg = m;
    msg_level = msg_type;
  }
}

void WriteConsoleLog(String StringLogMsg) {

  for (size_t i = 0; i < StringLogMsg.length(); i++) {
    if (StringLogMsg[i] == '"') StringLogMsg[i] = '\'';
    else if (StringLogMsg[i] == '\r') StringLogMsg[i] = '^';
    else if (StringLogMsg[i] == '\n') StringLogMsg[i] = ' ';
  }
  if (LogMsg.length() > 0) {
    LogMsg = LogMsg + "; " + StringLogMsg;
  } else LogMsg = StringLogMsg;

  if (LogMsg.length() > 10000) {
    LogMsg = StringLogMsg;
  }

#ifdef USE_WEB_SERIAL
  WebSerial.println(StringLogMsg);
  Serial.println(StringLogMsg);
#else
  Serial.println(StringLogMsg);
#endif
}

#endif
