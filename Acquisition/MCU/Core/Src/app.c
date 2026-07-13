#include "main.h"
#include "cmsis_os.h"
#include "SEGGER_SYSVIEW.h"
#include "SEGGER_RTT.h"

#define N_MICS 4

extern SPI_HandleTypeDef hspi1;
extern SPI_HandleTypeDef hspi3;
extern TIM_HandleTypeDef htim1;
extern TIM_HandleTypeDef htim4;
extern DMA_HandleTypeDef hdma_tim1_ch1;
extern PCD_HandleTypeDef hpcd_USB_OTG_HS;
extern TaskHandle_t task_retr_main;
extern TaskHandle_t task_retr_periodic;
extern SemaphoreHandle_t capture_semaphore;
extern SRAM_HandleTypeDef hsram1;

int16_t sound[SOUND_ITEMS];
extern uint8_t is_sound_requested;
int ncallbacks = 0;
int16_t adc_values[4] = {0};
extern uint8_t adc_fstatus;

uint8_t usb_sound_response[4];
#define PERIODIC_BUFFER 1024*2
#define SEGGER_BUFFER 1024*4
uint8_t segger_usb_buf[SEGGER_BUFFER] = {0};
uint16_t periodic_signal[PERIODIC_BUFFER*2*2]; // Double buffer, each PERIODIC_BUFFER large of 2-byte values.
uint16_t pbuff_idx = 0;

//typedef enum SRetrieval {
//  SLEEPING = 0,
//  READY,
//	REQUESTED,
//	CAPTURED,
//	SENT
//} SRetrieval;
SRetrieval state = SLEEPING;
SeggerStatus segger_state = SEGGER_SLEEPING;
PeriodicStatus periodic_state = SEGGER_SLEEPING;


int ncaptures = 0;
int captures_requested = 0;
int is_failed = 0;
uint8_t is_periodic_overflow = 0;
int is_periodic_transmitting = 0;

//void setup_capture(int ncaptures) {
//	captures_requested = ncaptures;
//	ncaptures = 0;
//}
//
//void request_capture() {
//  adc_fstatus = 43;
//  hspi1.Instance->DR = 25;
//}

uint16_t current_sample = 0;

uint8_t red = 0;   // 0..15, frame-averaged
uint8_t green = 0;
uint8_t tim_cnt = 0;


void drive_cam_indicator() {
	if (tim_cnt >= green) HAL_GPIO_WritePin(LED_G_GPIO_Port, LED_G_Pin, SET);
	else HAL_GPIO_WritePin(LED_G_GPIO_Port, LED_G_Pin, RESET);

	if (tim_cnt >= red) HAL_GPIO_WritePin(LED_R_GPIO_Port, LED_R_Pin, SET);
	else HAL_GPIO_WritePin(LED_R_GPIO_Port, LED_R_Pin, RESET);

	tim_cnt++;
	if (tim_cnt >= 16) tim_cnt = 0;
}


//void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin) {
//	if (captures_requested > 0) {
//		int captures_remaining = captures_requested / N_MICS - ncaptures;
//		// Only ADC_BSY__2 have this interrupt configured
//		  uint32_t data_remaining = htim1.hdma[1]->Instance->NDTR;
//		  int dma_captures_remaining = data_remaining / 8;
//		  if (/*adc_fstatus != 192 ||*/ dma_captures_remaining != captures_remaining) { // Check previous status
//			  is_failed += 1;
////			  HAL_TIM_IC_Stop_DMA(&htim1, TIM_CHANNEL_1);
//			  __HAL_TIM_DISABLE_DMA(&htim1, TIM_DMA_CC1);
//			  if (htim1.hdma[1]->State == HAL_DMA_STATE_BUSY) {
//				  HAL_DMA_Abort_IT(htim1.hdma[TIM_DMA_ID_CC1]);
//			  }
//
//			  __HAL_TIM_DISABLE(&htim1);
//			    TIM_CHANNEL_STATE_SET(&htim1, TIM_CHANNEL_1, HAL_TIM_CHANNEL_STATE_READY);
//			    TIM_CHANNEL_N_STATE_SET(&htim1, TIM_CHANNEL_1, HAL_TIM_CHANNEL_STATE_READY);
//			  __HAL_TIM_SET_COUNTER(&htim1, 0);
//			  __HAL_TIM_CLEAR_FLAG(&htim1, TIM_FLAG_CC1 | TIM_FLAG_UPDATE);
//			  __HAL_TIM_ENABLE(&htim1);
//			  if (HAL_TIM_IC_Start_DMA(&htim1, TIM_CHANNEL_1, (uint32_t*)sound, captures_requested*2) == HAL_OK) {
//				  ncaptures = 0;
//			  }
//		  }
//		  ncaptures++;
//	  }
//	  if (state != SLEEPING) {
//		  current_sample = GPIOD->IDR;
//		  request_capture();
//	  }
//}
//
//void HAL_TIM_IC_CaptureCallback(TIM_HandleTypeDef *htim) {
////	BaseType_t xHigherPriorityTaskWoken = pdFALSE;
////	xTaskNotifyFromISR(task_retr_main, 1 << CAPTURED, eSetBits, &xHigherPriorityTaskWoken);
//	captures_requested = 0;
////	portYIELD_FROM_ISR(xHigherPriorityTaskWoken);
//}
//
int is_suspend_signal(uint32_t notification, BaseType_t result) {
	if (result == pdFAIL) return 1;
	if (notification == 1 << SLEEPING) return 1;
	return 0;
}

#define PSRAM_BASE_ADDR   0x60000000UL
#define BASE   ((volatile uint8_t *)PSRAM_BASE_ADDR)
#define PSRAM_PTR(addr)   ((volatile uint8_t *)(PSRAM_BASE_ADDR + (addr)))
#define ST_DATA_READY   0x08            // status bit3

static inline uint16_t psram_read_word(void) {
    volatile uint8_t *p = (volatile uint8_t *)PSRAM_BASE_ADDR;
    while (!(p[4] & ST_DATA_READY)) { }  // wait until a word is prefetched
    uint16_t w =  (p[0] & 0xF);
    w |= (uint16_t)(p[1] & 0xF) << 4;
    w |= (uint16_t)(p[2] & 0xF) << 8;
    w |= (uint16_t)(p[3] & 0xF) << 12;
    return w;
}

void task_retr_main_func(void* pvParameters) {
////	vTaskSuspend(NULL);	// Do not start execution until requested
	uint32_t notification = 0;
	BaseType_t result;
	const TickType_t xMaxBlockTime = pdMS_TO_TICKS( 500 );
	uint16_t buf[2] = {0};
	uint16_t data = 333;

	BASE[0xF] = 1;                   // adc_sel

	for (;;) {
		__IO uint8_t *psramaddress = (uint8_t *)PSRAM_PTR(0x00);

//		uint8_t *pdestbuff = buf;
//		HAL_SRAM_Read_8b(&hsram1, (uint32_t *)PSRAM_PTR(address), buffer, length);
//		HAL_SRAM_Read_8b(&hsram1, (uint32_t *)PSRAM_PTR(0x15), buf, 32);

//		while (!(BASE[0xF] & 0x8)) {}          // poll data-ready
//		for (int n=0;n<2;n++) buf[n] = 0;
//		for (int n=0;n<8;n++) buf[n>>2] |= (BASE[n]&0xF) << (4*(n&3));
//
//		current_sample = (BASE[0xB]&0xF) | (BASE[0xC]&0xF)<<4 | (BASE[0xD]&0xF)<<8 | (BASE[0xE]&0xF)<<12;
//		red   = (BASE[0x9] & 0xF) * 2;
//		green = (BASE[0xA] & 0xF) * 2;

//	    for (int i = 0; i < 1024; i++)
//	    {
//	    	__IO uint8_t *psramaddress_w = (uint8_t *)PSRAM_PTR(0x00);
//		    for (int j = 0; j < 4; j++)
//		    {
//				uint8_t data2 = data >> j * 4;
//			    *psramaddress_w = data2;
//			    psramaddress_w++;
//			}
//		    data += 1;
//	    }
//
//	    for (int i = 0; i < 1024; i++)
//	        buf[i] = psram_read_word();
//
//		HAL_Delay(500);

		// -------------------------- Wait for request -----------------------------
		switch (state) {
		case SLEEPING:
//			HAL_GPIO_WritePin(ADC_AUX_1_GPIO_Port, ADC_AUX_1_Pin, RESET);
//			HAL_GPIO_WritePin(ADC_AUX_2_GPIO_Port, ADC_AUX_2_Pin, RESET);
			xTaskNotifyWait(0, 0xFFFFFFFF, &notification, portMAX_DELAY);
			if (notification != 1 << READY) {
				notification = 0;
				break;	// This should never happen
			}
			state = READY;

		case READY:
//			HAL_GPIO_WritePin(ADC_AUX_1_GPIO_Port, ADC_AUX_1_Pin, RESET);
//			HAL_GPIO_WritePin(ADC_AUX_2_GPIO_Port, ADC_AUX_2_Pin, RESET);

			xTaskNotifyWait(0, 0xFFFFFFFF, &notification, portMAX_DELAY);
			if (is_suspend_signal(notification, pdPASS)) {
				state = SLEEPING;
				break;
			}
			if (notification != 1 << REQUESTED) {
				break;	// This should never happen
			}
//			if (xSemaphoreTake(capture_semaphore, xMaxBlockTime) != pdTRUE) {
//				state = SLEEPING;
//				break;
//			}
//			state = REQUESTED;



			// Activate sound transmission
			state = CAPTURED;
			uint16_t transfer_len = SOUND_ITEMS*2;
			HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x81, (uint8_t*)(sound), transfer_len);

		case CAPTURED:
//			HAL_GPIO_WritePin(ADC_AUX_1_GPIO_Port, ADC_AUX_1_Pin, RESET);
//			HAL_GPIO_WritePin(ADC_AUX_2_GPIO_Port, ADC_AUX_2_Pin, RESET);
			result = xTaskNotifyWait(0, 0xFFFFFFFF, &notification, xMaxBlockTime);
			if (is_suspend_signal(notification, result)) {
				state = SLEEPING;
				xSemaphoreGive(capture_semaphore);
				break;
			}
			if (notification != 1 << SENT) {
				break;	// This should never happen
			}
			state = SENT;
			xSemaphoreGive(capture_semaphore);
			break;

		case SENT:
			state = READY;
			break;
		}
	}
}

void capture_periodic() {

	current_sample = (BASE[0xB]&0xF) | (BASE[0xC]&0xF)<<4 | (BASE[0xD]&0xF)<<8 | (BASE[0xE]&0xF)<<12;
	red   = (BASE[0x9] & 0xF);
	green = (BASE[0xA] & 0xF);

	if (state != SLEEPING) {
//		if (state != REQUESTED) current_sample = GPIOD->IDR;
		periodic_signal[pbuff_idx++] = current_sample;
//		if (current_sample < 35000) {
//			current_sample++;
//		}
		if (pbuff_idx >= PERIODIC_BUFFER*2) pbuff_idx = 0;
////		if (pbuff_idx == 128 || pbuff_idx == 0) {
//////			if (hpcd_USB_OTG_HS.IN_ep[4].xfer_len > hpcd_USB_OTG_HS.IN_ep[4].xfer_count) return;
////			if (is_periodic_transmitting) is_periodic_overflow++;
////			is_periodic_transmitting = 1;
////			HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x84, (uint8_t*)(&(periodic_signal[128-pbuff_idx])), 256);
////		}
	} else {
		pbuff_idx = 0;
	}
}

//const int16_t err_response = -5;
//const int16_t dummy_periodic = -33;
////uint16_t per_bytes_read = 0;
//void task_retr_periodic_func(void* pvParameters) {
//	uint32_t notification = 0;
//	const TickType_t xMaxBlockTime = pdMS_TO_TICKS( 50 );
//	BaseType_t result;
//	periodic_state = PERIODIC_SLEEPING;
//	for (;;) {
//		xTaskNotifyWait(0, 0xFFFFFFFF, &notification, portMAX_DELAY);
//		if (notification != 1 << PERIODIC_REQUESTED) {
//			continue;	// This should never happen
//		}
//		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0, (uint8_t*)&dummy_periodic, 2); // Respond to the control request
//		periodic_state = PERIODIC_REQUESTED;
////		uint8_t is_first_half_ready = pbuff_idx >= PERIODIC_BUFFER ? 0 : 1;
////		if (is_first_half_ready) {
////			per_bytes_read = pbuff_idx*2;
////			HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x84, (uint8_t*)(&(periodic_signal[0])), per_bytes_read);
////			pbuff_idx = PERIODIC_BUFFER;
////		} else {
////			per_bytes_read = (pbuff_idx - PERIODIC_BUFFER) * 2;
////			HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x84, (uint8_t*)(&(periodic_signal[PERIODIC_BUFFER])), per_bytes_read);
////			pbuff_idx = 0;
////		}
//////		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0, (uint8_t*)&per_bytes_read, 2); // Respond to the control request
////
////		result = xTaskNotifyWait(0, 0xFFFFFFFF, &notification, xMaxBlockTime);
////		if (result == pdFAIL) {
////			periodic_state = PERIODIC_FAIL;
////			break;
////		}
////		if (notification == 1 << PERIODIC_REQUESTED) HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0, (uint8_t*)&err_response, 2); // Respond to the control request
////		if (notification == 1 << PERIODIC_SENT) {
//////			is_segger_tx = 0;
////			periodic_state = PERIODIC_SENT;
////			continue;
////		}
//	}
//}


uint16_t bytes_read = 0;
uint8_t is_segger_tx = 1;
uint16_t transmit_segger_data() {
//	uint32_t USBx_BASE = (uint32_t)(hpcd_USB_OTG_HS.Instance);
	if (!is_segger_tx) bytes_read = SEGGER_RTT_ReadUpBufferNoLock(1, (void*)segger_usb_buf, SEGGER_BUFFER);
	else bytes_read = 0;
	if (bytes_read > 0) {
		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x83, segger_usb_buf, bytes_read);
		is_segger_tx = 1;
	}
	return bytes_read;
}

//void task_send_segger_func(void* pvParameters) {
//	uint32_t notification = 0;
//	const TickType_t xMaxBlockTime = pdMS_TO_TICKS( 50 );
//	BaseType_t result;
//	segger_state = SEGGER_SLEEPING;
//	for (;;) {
//		xTaskNotifyWait(0, 0xFFFFFFFF, &notification, portMAX_DELAY);
//		if (notification == 1 << SEGGER_REQUESTED) HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0, (uint8_t*)&err_response, 2); // Respond to the control request
//		if (notification != 1 << SEGGER_STARTED) {
//			continue;	// This should never happen
//		}
//		segger_state = SEGGER_STARTED;
//		SEGGER_SYSVIEW_Start();
//		is_segger_tx = 0;
//		for (;;) {
//			xTaskNotifyWait(0, 0xFFFFFFFF, &notification, portMAX_DELAY);
//			if (notification != 1 << SEGGER_REQUESTED) {
//				continue;	// This should never happen
//			}
//			bytes_read = transmit_segger_data();
//			HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0, (uint8_t*)&bytes_read, 2); // Respond to the control request
//
//			result = xTaskNotifyWait(0, 0xFFFFFFFF, &notification, xMaxBlockTime);
//			if (result == pdFAIL) {
//				segger_state = SEGGER_FAIL;
//				break;
//			}
//			if (notification == 1 << SEGGER_REQUESTED) HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0, (uint8_t*)&err_response, 2); // Respond to the control request
//			if (notification == 1 << SEGGER_STARTED) {
//				continue; // This should never happen
//			} else if (notification == 1 << SEGGER_ENDED) {
//				break;
//			} else if (notification == 1 << SEGGER_SENT) {
//				is_segger_tx = 0;
//				segger_state = SEGGER_SENT;
//				continue;
//			}
//		}
//		if (segger_state != SEGGER_FAIL) segger_state = SEGGER_ENDED;
//		SEGGER_SYSVIEW_Stop();
//	}
//}

//void task_retr_periodic_func(void* pvParameters) {
//	uint16_t current_sample[N_MICS];
//	uint32_t notification = 0;
//	const TickType_t xMaxBlockTime = pdMS_TO_TICKS( 50 );
//	BaseType_t result;
//	for ( ; ; ) {
//		xTaskNotifyWait(0, 0xFFFFFFFF, &notification, portMAX_DELAY);
//		if (notification != 1 << REQUESTED) {
//			continue;	// This should never happen
//		}
////		if (pbuff_idx >= PBUFF_LEN) continue;
//		if (pbuff_idx >= PBUFF_LEN) pbuff_idx = 0;
//		if (state == SLEEPING) continue;
//		if (xSemaphoreTake(capture_semaphore, xMaxBlockTime) == pdTRUE) {
//			// Request a sample.
//			setup_capture(N_MICS);
////			hspi1.Instance->DR = 25;
//			result = xTaskNotifyWait(0, 0xFFFFFFFF, &notification, xMaxBlockTime);
//			periodic_buffer[pbuff_idx++] = sound[PROBE_MIC_IDX];
//			xSemaphoreGive(capture_semaphore);
//		} else {
//			// Infer the sample from DMA state.
//			uint32_t data_remaining = htim1.hdma[1]->Instance->NDTR;
//			uint32_t last_capture_byte = SOUND_ITEMS*2 - data_remaining - N_MICS * 2;
//			uint32_t last_capture_idx = last_capture_byte / 2;
//			periodic_buffer[pbuff_idx++] = sound[last_capture_idx + PROBE_MIC_IDX];
//		}
//	}
//}
