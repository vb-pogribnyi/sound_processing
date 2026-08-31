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
uint16_t sound_buff_idx = 0;
extern uint8_t is_sound_requested;
int ncallbacks = 0;
int16_t adc_values[4] = {0};
extern uint8_t adc_fstatus;

uint8_t usb_sound_response[4];
uint8_t num_adcs = 16;
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

// --- Debug counters for the request/response protocol (watch live in debugger).
// Healthy invariants: n_tx81 == n_sent (every transmitted chunk is read) and
// n_req advances 1:1 with served chunks. A divergence localizes the stall.
volatile uint32_t n_req      = 0;   // 0x01 requests received (USB DataOut ep2)
volatile uint32_t n_tx81     = 0;   // main-sound chunks transmitted on 0x81
volatile uint32_t n_sent     = 0;   // 0x81 reads confirmed (USB DataIn ep1)
volatile uint32_t n_captured = 0;   // new captures armed
volatile uint32_t n_sleep    = 0;   // transitions to SLEEPING


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
	if (notification & (1 << SLEEPING)) return 1;   // bit test, not exact match
	return 0;
}

#define PSRAM_BASE_ADDR   0x60000000UL
#define BASE   ((volatile uint8_t *)PSRAM_BASE_ADDR)
#define PSRAM_PTR(addr)   ((volatile uint8_t *)(PSRAM_BASE_ADDR + (addr)))
// Status nibble is read at FSMC address 0xF (STAT_ADDR in FSMC.v). Reading any
// other address (e.g. 0x4) returns FIFO-entry data nibbles, NOT these bits.
//   bit0 = FIFO empty   bit1 = acq_full (sticky: capture auto-stopped when the
//   FPGA FIFO filled)   bit2 = is_valid (PSRAM self-test ok)   bit3 = data_ready
#define STATUS_ADDR     0xFF
#define ST_FIFO_EMPTY   0x01            // status bit0
#define ST_FIFO_FULL    0x02            // status bit1 (acq_full: capture stopped)
#define ST_IS_VALID     0x04            // status bit2
#define ST_DATA_READY   0x08            // status bit3

// --- FPGA/FSMC access serialization -----------------------------------------
// One logical FPGA read spans several byte accesses that share a single holding
// register inside the FPGA (only addr 0x0 reloads it; 0x1.. replay it). If the
// TIM3 periodic ISR reads the FPGA (0x9-0xE) in the middle of the drain task's
// nibble reads it overwrites that register and corrupts the in-progress sample.
// Bracket every multi-access FPGA read so no other context can interleave. Uses
// PRIMASK save/restore, so it is safe from both task and ISR context and keeps
// TIM3 running (it is delayed by at most one bracketed read, ~1 us).
#define FPGA_LOCK()    uint32_t _fpga_primask = __get_PRIMASK(); __disable_irq()
#define FPGA_UNLOCK()  __set_PRIMASK(_fpga_primask)

// SystemView marker for the sound task entering CAPTURED (named in usb.c).
#define SVM_STATE_CAPTURED 7u

static inline uint16_t psram_read_word(void) {
    volatile uint8_t *p = (volatile uint8_t *)PSRAM_BASE_ADDR;
    while (!(p[STATUS_ADDR] & ST_DATA_READY)) { }  // wait until a word is prefetched
    uint16_t w =  (p[0] & 0xF);
    w |= (uint16_t)(p[1] & 0xF) << 4;
    w |= (uint16_t)(p[2] & 0xF) << 8;
    w |= (uint16_t)(p[3] & 0xF) << 12;
    return w;
}

void task_retr_main_func(void* pvParameters) {
////	vTaskSuspend(NULL);	// Do not start execution until requested
	uint32_t notification = 0;
	uint8_t is_done = 0;
	uint8_t capture_active = 0;   // 0 -> next request arms a new capture
	BaseType_t result;
	const TickType_t xMaxBlockTime = pdMS_TO_TICKS( 500 );


	while (!HAL_GPIO_ReadPin(FPGA_Done_GPIO_Port, FPGA_Done_Pin)) taskYIELD();

	BASE[0xFD] = 0;					  // Capture 1 ADC at start
	BASE[0xFF] = 0;                   // Select ADC to be reported as periodic

	// The sub-ms drain timeout below uses the DWT cycle counter; ensure it runs
	// (SEGGER_SYSVIEW_Conf() also enables it, but do not depend on that here).
	CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
	DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

	for (;;) {
		// -------------------------- Wait for request -----------------------------
		switch (state) {
		case SLEEPING:
			// TODO: Tell FPGA we're not interested in values, buffer may be not contiguous
			xTaskNotifyWait(0, 0xFFFFFFFF, &notification, portMAX_DELAY);
			if (!(notification & (1 << READY))) {
				notification = 0;
				break;	// ignore anything that is not a wake
			}
			capture_active = 0;   // fresh session: next request arms a new capture
			state = READY;

		case READY:
			// 1:1 protocol: wait for ONE request, then serve exactly ONE chunk.
			xTaskNotifyWait(0, 0xFFFFFFFF, &notification, portMAX_DELAY);
			if (is_suspend_signal(notification, pdPASS)) {
				state = SLEEPING;
				n_sleep++;
				break;
			}
			if (!(notification & (1 << REQUESTED))) {
				break;	// not a request (e.g. a stray SENT) - keep waiting
			}
			if (!capture_active) {          // start a NEW capture on the first request
				uint8_t log2n = 0;          // tell FPGA the effective channel count:
				for (uint8_t t = num_adcs; t > 1u; t >>= 1) log2n++;  // floor(log2(num_adcs))
				BASE[0xFD] = log2n;          // EFF = 1<<log2n; masks absent-channel checks in FPGA
				BASE[0xFE] = 1;              // arm: rewind FPGA FIFO, enable polling
				sound_buff_idx = 0;
				is_done = 0;
				capture_active = 1;
				n_captured++;
			}
			state = REQUESTED;


//			if (xSemaphoreTake(capture_semaphore, xMaxBlockTime) != pdTRUE) {
//				state = SLEEPING;
//				break;
//			}


		case REQUESTED:
		{
			// 1:1 protocol: serve exactly ONE chunk for THIS request. Drain whatever
			// the FPGA FIFO has available right now (0 .. one buffer), then respond;
			// never free-run - the next chunk waits for the next request.
			volatile uint8_t *p = (volatile uint8_t *)PSRAM_BASE_ADDR;
			sound_buff_idx = 0;
			// Drain until the buffer is full. When the FPGA has not produced the next
			// sample yet (e.g. prefetch latency), wait for it - but never block more than
			// 1 ms on a single gap. If the capture has finished (acq_full and FIFO drained)
			// no more data will ever come, so flag is_done and stop immediately.
			const uint32_t drain_gap_timeout = SystemCoreClock / 1000u;   // 1 ms in CPU cycles
			uint32_t last_sample_cycles = DWT->CYCCNT;
			while (sound_buff_idx + num_adcs <= 256*16) {
//			while (sound_buff_idx + num_adcs <= SOUND_ITEMS) {
				uint8_t status = p[STATUS_ADDR];
				if (status & ST_DATA_READY) {
					// One FIFO entry holds ALL num_adcs channels as 4*num_adcs
					// nibbles. Reading p[0] loads the whole entry into the FPGA's
					// holding register (and prefetches the next); p[1..] just
					// replay the remaining nibbles of THIS entry. So read every
					// channel here (must stay atomic vs the TIM3 ISR, which would
					// clobber the holding register with the live value) and store
					// them interleaved: sound[] = ch0,ch1,..,chN-1,ch0,ch1,..
					FPGA_LOCK();                   // atomic vs the TIM3 periodic ISR's FPGA reads
					for (uint8_t ch = 0; ch < num_adcs; ch++) {
						uint16_t w =  (p[ch*2 + 0]);
						w |= (uint16_t)(p[ch*2 + 1]) << 8;
						sound[sound_buff_idx++] = (int16_t)w;
					}
					FPGA_UNLOCK();
					last_sample_cycles = DWT->CYCCNT;   // reset the gap timer on each entry
				} else if ((status & ST_FIFO_FULL) && (status & ST_FIFO_EMPTY)) {
					is_done = 1;                    // capture finished and fully drained
					capture_active = 0;             // next request re-arms a fresh capture
					break;                          // no more data will ever come - stop now
				} else if ((DWT->CYCCNT - last_sample_cycles) > drain_gap_timeout) {
					break;                          // no new sample for 1 ms - stop waiting
				}
			}
			// Capture is finished once the FPGA auto-stopped (acq_full) and the FIFO is
			// fully drained; the NEXT request then re-arms a fresh capture.
			uint8_t status = p[STATUS_ADDR];
			if (!(status & ST_DATA_READY) && (status & ST_FIFO_FULL) && (status & ST_FIFO_EMPTY)) {
				is_done = 1;
				capture_active = 0;
			}
			SEGGER_SYSVIEW_Mark(SVM_STATE_CAPTURED);
			// Respond: main data on 0x81 (only when non-empty), status on 0x82.
			if (sound_buff_idx > 0) {
				n_tx81++;
				HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x81, (uint8_t*)(sound), sound_buff_idx*2);
			}
			*(uint16_t*)(usb_sound_response) = sound_buff_idx*2;
			*(usb_sound_response + 2) = is_done;
			*(usb_sound_response + 3) = num_adcs;
			HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x82, usb_sound_response, 4);
			// If we sent main data, wait for the host to read it (back-pressure) before
			// serving the next request; if empty, just wait for the next request.
			state = (sound_buff_idx > 0) ? CAPTURED : READY;
			break;
		}


//			xTaskNotifyWait(0, 0xFFFFFFFF, &notification, portMAX_DELAY);
//			if (is_suspend_signal(notification, pdPASS)) {
//				state = SLEEPING;
//				break;
//			}
//			if (notification != 1 << CAPTURED) {
//				break;	// This should never happen
//			}

		case CAPTURED:
			// Back-pressure: wait for the host to read the chunk (DataIn ep1 -> SENT),
			// then wait for the next request. 1:1 - never free-run to the next chunk.
			result = xTaskNotifyWait(0, 0xFFFFFFFF, &notification, xMaxBlockTime);
			if (is_suspend_signal(notification, result)) {
				state = SLEEPING;
				n_sleep++;
				break;
			}
			if (notification & (1 << SENT)) {   // bit test: the chunk was read
				state = READY;
			}
			// otherwise (timeout handled above) stay in CAPTURED and re-wait
			break;

		case SENT:
			state = READY;   // 1:1 flow returns to READY directly; kept for completeness
			break;
		}
	}
}

void capture_periodic() {
	if (!HAL_GPIO_ReadPin(FPGA_Done_GPIO_Port, FPGA_Done_Pin)) return;

	FPGA_LOCK();                           // atomic vs the sound-drain task's FPGA reads
	current_sample = (BASE[0xFD]) | (BASE[0xFE])<<8;
//	red   = (BASE[0x9] & 0xF);
//	green = (BASE[0xA] & 0xF);
	FPGA_UNLOCK();

	if (state != SLEEPING) {
		if (pbuff_idx >= 0 && pbuff_idx < PERIODIC_BUFFER) {
			periodic_signal[pbuff_idx++] = current_sample;
		} else if (pbuff_idx >= PERIODIC_BUFFER && pbuff_idx < PERIODIC_BUFFER*2) {
			periodic_signal[pbuff_idx++] = current_sample;
		}
		if (pbuff_idx >= PERIODIC_BUFFER*2)
			pbuff_idx = 0;
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
