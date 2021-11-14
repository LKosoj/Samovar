#ifndef _RMVK_UART_H_
#define _RMVK_UART_H_
#include <sys/types.h>
#include <stdint.h>
#include "driver/uart.h"

#define RMVK_DEFAULT_READ_TIMEOUT 50
#define RMVK_BAUD_RATE 9600
#define RMVK_TASK_DELAY 5000
#define RMVK_READ_DELAY 200
#define RMVK_TXD 17
#define RMVK_RXD 16
uart_port_t RMVK_UART=UART_NUM_1;



#define MAX_VOLTAGE (230)
#define MIN_VOLTAGE (40)

typedef enum {
    RMVK_INT=0,
    RMVK_OK,
    RMVK_ON
} rmvk_res_t;

typedef struct  {
    uint8_t conn;
    uint8_t on;
    uint8_t VI;
    uint8_t VO;
    uint8_t VS;
} rmvk_t;

extern rmvk_t rmvk;

void RMVK_init(void);
void rmvk_read();
void rmvkFn(void* arg);

uint8_t RMVK_cmd(const char* cmd,rmvk_res_t res);
uint16_t RMVK_set_out_voltge(uint16_t voltge);
uint16_t RMVK_set_state(uint16_t new_state);
uint16_t RMVK_set_on(uint16_t state);
uint16_t RMVK_select_mem(uint16_t sm);

uint16_t RMVK_get_in_voltge();
uint16_t RMVK_get_out_voltge();
bool RMVK_get_state();
bool RMVK_get_conn();

uint8_t get_rmvk_state();
uint8_t get_rmvk_conn();




#endif
/*
1. "АТ+VI?" - возвращает напряжение в сети
2. "АТ+VO?" - возвращает реальное напряжение на выходе РМВ-К
3. "АТ+VS?" - возвращает значение, которое установлено на выходе
4. "АТ+VS=xxx" - устанавливает напряжение на выходе: если успешно, то возвращает посланное значение,
иначе возвращает "error". Напряжение вводится ххх - т.е. обязательно с незначащими нулями, например -
АТ+VS=087. Напряжение изменяется в рабочем диапазоне от 40 до 230 Вольт.
5. "АТ+ON?" - возвращает ON, если разрешено напряжение на выходе и OFF, если выход отключен.
6. "АТ+ON={1 or 0} - команда управляет напряжением на выходе: =0 выключает , =1 включает. Команда
выключения блокирует РМВ-К, на дисплее OFF. Блокировка сохраняется даже после отключения и
повторного включения РМВ-К. Для снятия блокировки необходимо подать команду АТ+ON=1 или нажать
кнопки К1.
7. "AT+SM=х", где х от 0 до 9 (select from memory). Ответ "ок". Выбрать установленное напряжение из
ячейки памяти.
7
*/
