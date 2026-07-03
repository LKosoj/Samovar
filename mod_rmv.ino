#include "freertos/FreeRTOS.h"
#include "esp_log.h"
#include "driver/uart.h"
#include <Arduino.h>
//#include "app_config.h"
//#include "sdkconfig.h"
//#include "driver/gpio.h"
#include "mod_rmvk.h"
#include "Samovar.h"

#define BUF_SIZE (1024)
#define RD_BUF_SIZE (BUF_SIZE)

StaticSemaphore_t xSemaphoreBuffer;
rmvk_t rmvk;

static bool rmvk_is_space(char c) {
  return c == ' ' || c == '\t' || c == '\r' || c == '\n';
}

static bool rmvk_response_equals(const char* response, const char* expected) {
  while (rmvk_is_space(*response)) response++;
  const char* pc = response;
  const char* pe = expected;
  while (*pe != '\0' && *pc == *pe) {
    pc++;
    pe++;
  }
  if (*pe != '\0') return false;
  while (rmvk_is_space(*pc)) pc++;
  return *pc == '\0';
}

static bool rmvk_parse_uint8_response(const char* response, uint8_t& value) {
  while (rmvk_is_space(*response)) response++;
  if (*response < '0' || *response > '9') return false;
  uint16_t parsed = 0;
  while (*response >= '0' && *response <= '9') {
    parsed = parsed * 10 + (*response - '0');
    if (parsed >= RMVK_ERROR) return false;
    response++;
  }
  while (rmvk_is_space(*response)) response++;
  if (*response != '\0') return false;
  value = parsed;
  return true;
}

uint8_t RMVK_cmd(const char* cmd, rmvk_res_t res) {
  size_t cmd_len;
  int len;
  cmd_len = strlen(cmd);
  char cmd_buf[cmd_len + 2];
  const char * pc = cmd_buf;
  uint8_t buf[10];//10*8=80 бит, при плохом раскладе  получим за 80*1000/9600 ~ 8,5 ms
  String s;
  if ( xSemaphore != NULL )
  {
    //Serial.print("cmd = ");
    //Serial.println(cmd);
    if ( xSemaphoreTake( xSemaphore, ( TickType_t ) ((RMVK_DEFAULT_READ_TIMEOUT * 7) / portTICK_RATE_MS)) == pdTRUE)
    {
      size_t copyLen = strnlen(cmd, sizeof(cmd_buf) - 2);
      memcpy(cmd_buf, cmd, copyLen);
      cmd_buf[copyLen] = '\r';
      cmd_buf[copyLen + 1] = '\0';
      uart_flush(RMVK_UART);
      cmd_len = uart_write_bytes(RMVK_UART, pc, strlen(pc));
      len = uart_read_bytes(RMVK_UART, buf, sizeof(buf) - 1, RMVK_DEFAULT_READ_TIMEOUT / portTICK_RATE_MS);
      if (len < 0) len = 0;
      buf[len] = '\0';
      //Serial.print("buf = ");
      //Serial.println((const char *)&buf);
      xSemaphoreGive( xSemaphore );
      if (len > 0) {
        const char* response = (const char *)&buf;
        uint8_t value = RMVK_ERROR;
        switch (res)
        {
          case RMVK_INT:
            if (rmvk_parse_uint8_response(response, value)) {
              rmvk.conn = 1;
              return value;
            }
            break;
          case RMVK_OK:
            if (rmvk_response_equals(response, "OK")) {
              rmvk.conn = 1;
              return 1;
            }
            break;
          case RMVK_ON:
            if (rmvk_response_equals(response, "ON")) {
              rmvk.conn = 1;
              return 1;
            }
            if (rmvk_response_equals(response, "OFF")) {
              rmvk.conn = 1;
              return 0;
            }
            break;
          default:
            if (rmvk_parse_uint8_response(response, value)) {
              rmvk.conn = 1;
              return value;
            }
            break;
        }
      }
      rmvk.conn = 0;

      return RMVK_ERROR;
	    }
	    else
	    {
	      rmvk.conn = 0;
	      Serial.print("UART RMVK  = BUSY");//увидим что не получили семафор
	    }
	  }
  return RMVK_ERROR;
}

uint16_t RMVK_get_in_voltge() {
	  char cmd[] = "AT+VI?";
	  uint8_t ret = RMVK_cmd(cmd, RMVK_INT);
	  if (ret != RMVK_ERROR) rmvk.VI = ret;
	  return rmvk.VI;
}

uint16_t RMVK_get_out_voltge() {
	  char cmd[] = "AT+VO?";
	  //    char cmd[]="AT+VI?";
	  uint8_t ret = RMVK_cmd(cmd, RMVK_INT);
	  if (ret != RMVK_ERROR) {
	    rmvk.VO = ret;
	    reg_online = true;
	    last_reg_online = millis();
	  }
	  return rmvk.VO;
}

uint16_t RMVK_get_store_out_voltge() {
	  char cmd[] = "AT+VS?";
	  uint8_t ret = RMVK_cmd(cmd, RMVK_INT);
	  if (ret != RMVK_ERROR) {
	    rmvk.VS = ret;
	    reg_online = true;
	    last_reg_online = millis();
	  }
	  return rmvk.VS;
	}
	bool RMVK_get_state() {
	  char cmd[] = "AT+ON?";
	  uint8_t ret = RMVK_cmd(cmd, RMVK_ON);
	  if (ret != RMVK_ERROR) {
	    rmvk.on = ret > 0;
	    reg_online = true;
	    last_reg_online = millis();
	  }
	  return rmvk.on;
}
uint16_t RMVK_set_out_voltge(uint16_t voltge) {
  uint16_t ret;
  char cmd[20];
  if (!rmvk.on)RMVK_set_on(1);
  if (voltge > MAX_VOLTAGE)voltge = MAX_VOLTAGE;
  snprintf(cmd, sizeof(cmd), "AT+VS=%03d", voltge);
  ret = RMVK_cmd(cmd, RMVK_INT);
  return ret;
}


bool RMVK_get_conn() {
  return (rmvk.conn > 0);
}

uint16_t RMVK_set_on(uint16_t state) {
  uint16_t ret;
  char cmd[20];
  if (state > 0)state = 1;
  else state = 0;
  snprintf(cmd, sizeof(cmd), "AT+ON=%d", state);
  ret = RMVK_cmd(cmd, RMVK_ON);
  return ret;
}
uint16_t RMVK_select_mem(uint16_t sm) {
  int ret;
  char cmd[20];
  snprintf(cmd, sizeof(cmd), "AT+SM=%d", sm);
  ret = RMVK_cmd(cmd, RMVK_OK);
  return ret;
}

void rmvk_read()
{
  rmvk.VI = RMVK_get_in_voltge();
  vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
  rmvk.VO = RMVK_get_out_voltge();
  vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
  rmvk.VS = RMVK_get_store_out_voltge();
  vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
  rmvk.on = RMVK_get_state() > 0;
}

uint8_t get_rmvk_state() {
  return rmvk.on;
}
uint8_t get_rmvk_conn() {
  return rmvk.conn;
}


void RMVK_init(void) {
  uart_config_t uart_config = {};
  uart_config.baud_rate = RMVK_BAUD_RATE;
  uart_config.data_bits = UART_DATA_8_BITS;
  uart_config.parity = UART_PARITY_DISABLE;
  uart_config.stop_bits = UART_STOP_BITS_1;
  uart_config.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
  uart_config.rx_flow_ctrl_thresh = 122;
  uart_param_config(RMVK_UART, &uart_config);
  uart_set_pin(RMVK_UART, RMVK_TXD, RMVK_RXD, -1, -1);
  uart_driver_install(RMVK_UART, BUF_SIZE * 2, BUF_SIZE * 2,  0, NULL, 0);

  xSemaphore = xSemaphoreCreateBinaryStatic( &xSemaphoreBuffer );
  xSemaphoreGive( xSemaphore );
  RMVK_set_on(0);
  rmvk_read();
}
