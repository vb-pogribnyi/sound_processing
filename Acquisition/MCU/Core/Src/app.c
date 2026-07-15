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

	BASE[0xF] = 1;                   // Select ADC to be reported as periodic

	for (;;) {
		// -------------------------- Wait for request -----------------------------
		switch (state) {
		case SLEEPING:
			// TODO: Tell FPGA we're not interested in values, buffer may be not contiguous
			xTaskNotifyWait(0, 0xFFFFFFFF, &notification, portMAX_DELAY);
			if (notification != 1 << READY) {
				notification = 0;
				break;	// This should never happen
			}
			state = READY;

		case READY:
			xTaskNotifyWait(0, 0xFFFFFFFF, &notification, portMAX_DELAY);
			if (is_suspend_signal(notification, pdPASS)) {
				state = SLEEPING;
				break;
			}
			if (notification != 1 << REQUESTED) {
				break;	// This should never happen
			}

			state = REQUESTED;
			BASE[0xE] = 1; // Reset PSRAM FIFO and request polling


//			if (xSemaphoreTake(capture_semaphore, xMaxBlockTime) != pdTRUE) {
//				state = SLEEPING;
//				break;
//			}


		case REQUESTED:
			xTaskNotifyWait(0, 0xFFFFFFFF, &notification, portMAX_DELAY);
			if (is_suspend_signal(notification, pdPASS)) {
				state = SLEEPING;
				break;
			}
			if (notification != 1 << CAPTURED) {
				break;	// This should never happen
			}

			// Activate sound transmission
			state = CAPTURED;
			uint16_t transfer_len = SOUND_ITEMS*2;
			HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x81, (uint8_t*)(sound), transfer_len);

		case CAPTURED:
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
		periodic_signal[pbuff_idx++] = current_sample;
		if (pbuff_idx >= PERIODIC_BUFFER*2) pbuff_idx = 0;
	} else {
		pbuff_idx = 0;
	}
}

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
