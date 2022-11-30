#include "iarduino_I2C_connect.h"
#include "Wire.h"

volatile	iarduino_I2C_connect_volatile_class I2C2VC;

void		I2C_func_ON_DATA(int i){																//	количество принятых байт по шине I2C
				bool k;																				//	флаг разрешающий запись
				I2C2VC.I2C_index_REG=Wire.read();													//	первый байт данных, полученный от мастера, является номером элемента массива (типа адресом регистра)
				for(int j=1; j<i; j++){																//	если получено более 1 байта данных, значит производится запись в массив (регистры)
					k=0; if(I2C2VC.I2C_flag_MASK){if(I2C2VC.I2C_length_MASK<I2C2VC.I2C_index_REG){if(I2C2VC.I2C_array_MASK[I2C2VC.I2C_index_REG]){k=1;}}}else{k=1;}	//	разрешаем запись если маскирующий массив не указывался, или если он указывался и значение его элемента позволяет записывать данные в соответствующий элемент массива I2C2VC.I2C_array_REG
					if(k){                                                                          //  если маскировочный массив I2C2VC.I2C_array_MASK разрешает запись в очередную ячейку массива I2C2VC.I2C_array_REG
						I2C2VC.I2C_array_REG[I2C2VC.I2C_index_REG]=Wire.read();                     //  записываем данные полученный байт данных в ячейку массива I2C2VC.I2C_array_REG
						I2C2VC.I2C_index_REG++;														//	увеличиваем значение индекса активного элемента массива I2C2VC.I2C_array_REG
						if(I2C2VC.I2C_index_REG>=I2C2VC.I2C_length_REG){I2C2VC.I2C_index_REG=0;}	//	корректируем значение индекса активного элемента массива I2C2VC.I2C_array_REG, если он вышел за его пределы
					}
				}		if(I2C2VC.I2C_index_REG>=I2C2VC.I2C_length_REG){I2C2VC.I2C_index_REG=0;}	//	корректируем значение индекса активного элемента массива I2C2VC.I2C_array_REG, если он вышел за его пределы
}

void		I2C_func_REQUEST(){																		//	без параметра
				if(I2C2VC.I2C_index_REG>=I2C2VC.I2C_length_REG){I2C2VC.I2C_index_REG=0;}			//	корректируем значение индекса активного элемента массива I2C2VC.I2C_array_REG, если он вышел за его пределы
				Wire.write(I2C2VC.I2C_array_REG[I2C2VC.I2C_index_REG]);								//	читаем значение активного элемента массива I2C2VC.I2C_array_REG (элемент на который указывает индекс I2C2VC.I2C_index_REG)
				I2C2VC.I2C_index_REG++;																//	увеличиваем значение индекса активного элемента массива I2C2VC.I2C_array_REG
}

//			указание массива
void		iarduino_I2C_connect::I2C_func_BEGIN(uint8_t *i, uint8_t j){							//	указатель на массив, длина массива
				I2C2VC.I2C_array_REG=i;																//	сохраняем указатель
				I2C2VC.I2C_length_REG=j;															//	сохраняем длину
				Wire.onReceive(I2C_func_ON_DATA);													//	назначаем функцию для обработки принятых по шине I2C данных
				Wire.onRequest(I2C_func_REQUEST);													//	назначаем функцию для обработки запрошенных по шине I2C данных

}

//			указание маскировочного массива
void		iarduino_I2C_connect::I2C_func_MASK(bool *i, uint8_t j){								//	указатель на маскировочный массив, длина маскировочного массива
				I2C2VC.I2C_array_MASK=i;															//	сохраняем указатель
				I2C2VC.I2C_length_MASK=j;															//	сохраняем длину
				I2C2VC.I2C_flag_MASK=1;																//	устанавливаем флаг указания маскировочного массива
}

//			чтение одного байта данных из устройства с указанием
uint8_t		iarduino_I2C_connect::readByte(uint8_t i, uint8_t j){									//	адрес устройства, адрес регистра
				uint8_t k=0;																		//	переменная для ответа
				Wire.beginTransmission(i);															//	инициируем передачу данных по шине I2C к устройству с адресом i (При этом сама передача не начинается)
				Wire.write(j);																		//	указываем, что требуется передать байт j - адрес регистра из которого требуется прочитать данные
				Wire.endTransmission(true);															//	выполняем инициированную передачу данных (бит RW=0 => запись)
				if(Wire.requestFrom(i,uint8_t(1))){													//	запрашиваем 1 байт данных от устройства с адресом i, функция Wire.requestFrom() возвращает количество принятых байтов
					while(Wire.available()){k=Wire.read();}											//	читаем очередной принятый байт, если таковой имеется в буфере для чтения
				}	return k;																		//	возвращаем последний принятый байт данных
}

//			запись одного байта
uint8_t		iarduino_I2C_connect::writeByte(uint8_t i, uint8_t j, uint8_t k){						//	адрес устройства, адрес регистра, байт для записи
				Wire.beginTransmission(i);															//	инициируем передачу данных по шине I2C к устройству с адресом i (При этом сама передача не начинается)
				Wire.write(j);																		//	указываем, что требуется передать байт j - адрес регистра из которого требуется прочитать данные
				Wire.write(k);																		//	указываем, что требуется передать байт k - данные для записи в регистр j устройства i
				return Wire.endTransmission();														//	выполняем инициированную передачу данных (бит RW=0 => запись)
}
