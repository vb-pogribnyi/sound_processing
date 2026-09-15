#include <main.h>

uint16_t bsy_hi_time = 0;
uint8_t read_active = 0;
uint8_t firsts[8] = {0};
uint16_t values[4] = {0};
float fvalues[4] = {0};
uint8_t cycle = 0;
uint16_t tmp;
//void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef* htim) {
////		HAL_GPIO_TogglePin(LED2_GPIO_Port, LED2_Pin);
////		HAL_GPIO_TogglePin(CLK_GPIO_Port, CLK_Pin);
//
//
//
//}
