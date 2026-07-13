#include "stm32f4xx_hal.h"
#include "main.h"
#include "cmsis_os.h"
#include <stdio.h>
#include "string.h"
#include "usb.h"
#include "SEGGER_SYSVIEW.h"
#include "SEGGER_RTT.h"

extern PCD_HandleTypeDef hpcd_USB_OTG_HS;
uint8_t is_usb_configured = 0;
uint8_t is_reads_started = 0;
extern uint16_t sound[SOUND_ITEMS];
extern TIM_HandleTypeDef htim1;
extern TIM_HandleTypeDef htim2;
extern SPI_HandleTypeDef hspi3;
extern SPI_HandleTypeDef hspi1;
uint8_t stand_cmd[4] = {0};
uint32_t half1 = 1;
uint32_t half2 = 2;
//SEGGER_SYSVIEW_DATA_SAMPLE sample_avail_1 = { .ID = 41, .pValue = &half1 };
//SEGGER_SYSVIEW_DATA_SAMPLE sample_avail_2 = { .ID = 41, .pValue = &half2 };
//SEGGER_SYSVIEW_DATA_SAMPLE sample_grab_1 = { .ID = 42, .pValue = &half1 };
//SEGGER_SYSVIEW_DATA_SAMPLE sample_grab_2 = { .ID = 42, .pValue = &half2 };
extern TaskHandle_t task_retr_main;
extern TaskHandle_t task_send_segger;
extern TaskHandle_t task_retr_periodic;
extern uint8_t is_segger_tx;

extern uint16_t periodic_signal[]; // Double buffer, each PERIODIC_BUFFER large of 2-byte values.
extern uint16_t pbuff_idx;
uint16_t per_bytes_read = 0;
uint16_t trace_bytes_read = 0;

__ALIGN_BEGIN static uint8_t device_descriptor[] __ALIGN_END = {
		0x12,		// Length
		0x01,		// Descriptor type
		0x00, 0x02,	// USB version
		0x00,		// Device class
		0x00,		// Device subclass
		0x00,		// Device protocol
		0x40,		// Max Packet Size
		0x77, 0x04,	// idVendor
		0x22, 0x11,	// idProduct
		0x01, 0x01,	// Device version
		0x01,		// iManufacturer
		0x02,		// iProduct
		0x03,		// iSerialNumber
		0x01		// Num configurations
};

__ALIGN_BEGIN static uint8_t configuration_descriptor[] __ALIGN_END = {
		0x09,		// Length
		0x02, 		// Descriptor type
		0x00, 0x00, // Total length, to be filled later
		0x01,		// Num interfaces
		0x01,		// Configuration number
		0x00,		// iConfiguration
		0xc0,		// Attributes. SELF-POWERED, NO-REMOTE-WAKEUP
		0x19,		// Max power. 50 mA
		// Interface descriptor
		0x09,		// Length
		0x04,		// Descriptor type
		0x00,		// Interface number
		0x00, 		// Alternate setting
		0x05,		// Endpoints number
		0xfe,		// Interface class. Custom
		0xff,		// Interface Subclass. Custom
		0xff,		// Interface Protocol. Custom
		0x04,		// iInterface
		// Bulk endpoint descriptor. Main signal
		0x07,		// Length
		0x05,		// Descriptor type
		0x81,		// Address. IN 1
		0x02,		// Type. Bulk
		0x00, 0x02,		// Max packet size
		0x03,
		// Interrupt endpoint descriptor. Signal Ready
		0x07,		// Length
		0x05,		// Descriptor type
		0x02,		// Address. OUT 2
		0x03,		// Type. Interrupt
		0x20, 0x00,		// Max packet size
		0x03,
		// Interrupt endpoint descriptor
		0x07,		// Length
		0x05,		// Descriptor type
		0x82,		// Address. IN 2
		0x03,		// Type. Interrupt
		0x20, 0x00,		// Max packet size
		0x03,
		// Bulk endpoint descriptor. Trace
		0x07,		// Length
		0x05,		// Descriptor type
		0x83,		// Address. IN 3
		0x02,		// Type. Bulk
		0x00, 0x02,		// Max packet size
		0x03,
		// Bulk endpoint descriptor. Periodic Signal
		0x07,		// Length
		0x05,		// Descriptor type
		0x84,		// Address. IN 4
		0x02,		// Type. Bulk
		0x00, 0x02,		// Max packet size
		0x03,
};

uint8_t lang_string_descriptor[] = {
		0x08,		// Length
		0x03,		// Descriptor type
		0x09,		// en_US
		0x04,
//		0x22,		// uk_UA
//		0x04
};
uint8_t string_descriptor[255] = {
		0x00,		// Length (to be filled later)
		0x03 		// Descriptor type
};

uint8_t is_half1_available = 0;
uint8_t is_half2_available = 0;
uint8_t is_overrun = 0;
uint8_t is_sound_requested = 0;
uint8_t is_myrtt_active = 0;
//uint8_t usb_sound_response[4];
uint16_t transfer_len = 0;
//extern uint16_t sound[SOUND_ITEMS];
uint8_t is_transmitting_half = 0;
//void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef* hadc)
//{
//	if (is_reads_started) SEGGER_SYSVIEW_RecordU32(SYSVIEW_EVTID_ISR_ENTER, 72);
//	if (is_reads_started) SEGGER_SYSVIEW_SampleData(&sample_avail_2);
//
//	if (is_half1_available) is_overrun = 1;
//	is_half1_available = 0;
//	is_half2_available = 1;
//	if (is_reads_started) SEGGER_SYSVIEW_RecordExitISR();
//	if (is_sound_requested && is_transmitting_half == 0) {
//		is_sound_requested = 0;
//		transfer_len = SOUND_ITEMS;
//		SEGGER_SYSVIEW_OnTaskStartExec(81);
//		is_transmitting_half = 2;
//		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x81, (uint8_t*)(sound) + SOUND_ITEMS, transfer_len);
//		*(uint16_t*)(usb_sound_response) = transfer_len;
//		*(usb_sound_response + 2) = is_overrun;
//		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x82, usb_sound_response, 4);
//		is_overrun = 0;
//	}
//}
//
//void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef* hadc)
//{
//	if (is_reads_started) SEGGER_SYSVIEW_RecordU32(SYSVIEW_EVTID_ISR_ENTER, 71);
//	if (is_reads_started) SEGGER_SYSVIEW_SampleData(&sample_avail_1);
//	if (is_half2_available) is_overrun = 1;
//	is_half1_available = 1;
//	is_half2_available = 0;
//	if (is_reads_started) SEGGER_SYSVIEW_RecordExitISR();
//	if (is_sound_requested && is_transmitting_half == 0) {
//		is_sound_requested = 0;
//		transfer_len = SOUND_ITEMS;
//		SEGGER_SYSVIEW_OnTaskStartExec(81);
//		is_transmitting_half = 1;
//		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x81, (uint8_t*)(sound), transfer_len);
//		*(uint16_t*)(usb_sound_response) = transfer_len;
//		*(usb_sound_response + 2) = is_overrun;
//		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x82, usb_sound_response, 4);
//		is_overrun = 0;
//	}
//}
//extern int ncaptures;
//extern int is_failed;
//void HAL_TIM_IC_CaptureCallback(TIM_HandleTypeDef *htim) {
////	if (is_reads_started) SEGGER_SYSVIEW_RecordU32(SYSVIEW_EVTID_ISR_ENTER, 71);
////	if (is_reads_started) SEGGER_SYSVIEW_SampleData(&sample_avail_1);
//	is_failed = 0;
//
//	if (is_sound_requested && is_transmitting_half == 0) {
//		is_transmitting_half = 1;
//		HAL_TIM_IC_Stop_DMA(&htim1, TIM_CHANNEL_1);
//		HAL_TIM_Base_Stop_IT(&htim2);
//		transfer_len = SOUND_ITEMS*2;
//		SEGGER_SYSVIEW_OnTaskStartExec(81);
//		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x81, (uint8_t*)(sound), transfer_len);
//		*(uint16_t*)(usb_sound_response) = transfer_len;
//		*(usb_sound_response + 2) = is_overrun;
//		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x82, usb_sound_response, 4);
//		is_overrun = 0;
//
//		HAL_GPIO_WritePin(LED2_GPIO_Port, LED2_Pin, SET);
//	}
//
////	if (is_reads_started) SEGGER_SYSVIEW_RecordExitISR();
//}

#define STANDARD 0x80
#define STANDARD_HTD 0x00
#define GET_DESCRIPTOR 6
#define DESCRIPTOR_DEVICE 1
#define DESCRIPTOR_STRING 3
#define DESCRIPTOR_DEVICE_QUALIFIER 6
#define DESCRIPTOR_CONFIGURATION 2
#define SET_CONFIGURATION 9
#define SET_ADDRESS 5

#define MY_CUSTOM_IN_REQUEST_TYPE 0xCC
#define MY_CUSTOM_OUT_REQUEST_TYPE 0x4C
#define MY_CUSTOM_REQUEST 0x25
#define MOTORS_SPEED_REQUEST 0x27
#define START_SOUND_TRANSMIT 0x25
#define END_SOUND_TRANSMIT 0x26
#define START_SEGGER_TRANSFER 0x27
#define END_SEGGER_TRANSFER 0x28

#define REQUEST_SEGGER_TRACE 0x31
#define REQUEST_PERIODIC_SIGNAL 0x32
//xTaskNotifyFromISR(task_send_segger, 1 << READY, eSetBits, &xHigherPriorityTaskWoken);


void HAL_PCD_ResetCallback(PCD_HandleTypeDef *hpcd) {
	printf("In Reset handler\n");
	// Open OUT endpoint 0
	HAL_PCD_EP_Flush(hpcd, 0x00);
	HAL_PCD_EP_Open(hpcd, 0x00, 64, 0);

//	HAL_GPIO_WritePin(LED_GPIO_Port, LED_Pin, RESET);

	// Open IN endpoint 0
	HAL_PCD_EP_Flush(hpcd, 0x80);
	HAL_PCD_EP_Open(hpcd, 0x80, 64, 0);
	((uint16_t*)configuration_descriptor)[1] = sizeof(configuration_descriptor);
}

int utf8_to_codepoint(const unsigned char *utf8, int *out_len) {
    if (utf8[0] < 0x80) {  // 1-byte ASCII
        *out_len = 1;
        return utf8[0];
    } else if ((utf8[0] & 0xE0) == 0xC0) {  // 2-byte sequence
        *out_len = 2;
        return ((utf8[0] & 0x1F) << 6) |
               (utf8[1] & 0x3F);
    } else if ((utf8[0] & 0xF0) == 0xE0) {  // 3-byte sequence
        *out_len = 3;
        return ((utf8[0] & 0x0F) << 12) |
               ((utf8[1] & 0x3F) << 6) |
               (utf8[2] & 0x3F);
    } else if ((utf8[0] & 0xF8) == 0xF0) {  // 4-byte sequence
        *out_len = 4;
        return ((utf8[0] & 0x07) << 18) |
               ((utf8[1] & 0x3F) << 12) |
               ((utf8[2] & 0x3F) << 6) |
               (utf8[3] & 0x3F);
    } else {
        *out_len = 1;
        return -1; // invalid
    }
}

uint8_t USB_Encode_String(uint8_t *buff, const char *string) {
	int result = 0;
	int in_idx = 0;
	int out_len = 0;
	for (int i = 0; i < strlen(string); i++) {
		if (in_idx >= strlen(string)) break;
		int string_code = utf8_to_codepoint((uint8_t*)(string + in_idx), &out_len);
		if (string_code > 0) {
			memcpy(buff + result, &string_code, out_len);
			result += 2;
			in_idx += out_len;
		} else {
			break;
		}
	}
	return result;

//	uint8_t out_idx = 0;
//	for (int i = 0; i < strlen(string); i++) {
//		uint8_t lo = string[i];
//		uint8_t hi = 0x00;
//		if (!is_ascii) {
//			hi = string[++i];
//		}
//		buff[out_idx++] = lo;
//		buff[out_idx++] = hi;
//	}
//
//	return out_idx;
}

uint16_t dummy_periodic2 = -700;
int last_tick = 0;
void HAL_PCD_SetupStageCallback(PCD_HandleTypeDef *hpcd) {
	uint8_t request_type = ((uint8_t*)hpcd->Setup)[0];
	uint8_t request = ((uint8_t*)hpcd->Setup)[1];
	uint8_t data1 = ((uint8_t*)hpcd->Setup)[2];
	uint8_t data2 = ((uint8_t*)hpcd->Setup)[3];
	uint16_t index = ((uint16_t*)hpcd->Setup)[2];
	uint8_t requested_length = ((uint16_t*)hpcd->Setup)[3];

	if (request_type == STANDARD && request == GET_DESCRIPTOR && data2 == DESCRIPTOR_DEVICE) {
		printf("Sending device descriptor\n");
		HAL_PCD_EP_Transmit(hpcd, 0x00, device_descriptor, sizeof(device_descriptor));
//		HAL_PCD_EP_Transmit(hpcd, 0x00, configuration_descriptor, sizeof(device_descriptor));
	} else if (request_type == STANDARD && request == GET_DESCRIPTOR && data2 == DESCRIPTOR_CONFIGURATION) {
//		printf("Sending configuration descriptor\n");

		if (requested_length > sizeof(configuration_descriptor)) requested_length = sizeof(configuration_descriptor);

		HAL_PCD_EP_Transmit(hpcd, 0x00, configuration_descriptor, requested_length);
	} else if (request_type == STANDARD && request == GET_DESCRIPTOR && data2 == DESCRIPTOR_DEVICE_QUALIFIER) {
//		printf("Sending qualifier descriptor\n");




		HAL_PCD_EP_Transmit(hpcd, 0x00, 0, 0);



	} else if (request_type == STANDARD_HTD && request == SET_ADDRESS) {
		printf("Setting address: %i\n", data1);
		HAL_PCD_SetAddress(hpcd, data1);
		HAL_PCD_EP_Transmit(hpcd, 0, 0, 0);
	} else if (request_type == STANDARD_HTD && request == SET_CONFIGURATION) {
		printf("Setting configuration, %i\n", data1);

		// Open  bulk endpoint
		HAL_PCD_EP_Flush(hpcd, 0x81);
		HAL_PCD_EP_Flush(hpcd, 0x82);
		HAL_PCD_EP_Flush(hpcd, 0x02);
		HAL_PCD_EP_Flush(hpcd, 0x83);
		HAL_PCD_EP_Flush(hpcd, 0x84);
		HAL_PCD_EP_Open(hpcd, 0x81, 512, EP_TYPE_BULK);
		HAL_PCD_EP_Open(hpcd, 0x02, 32, EP_TYPE_INTR);
		HAL_PCD_EP_Open(hpcd, 0x82, 32, EP_TYPE_INTR);
		HAL_PCD_EP_Open(hpcd, 0x83, 512, EP_TYPE_BULK);
		HAL_PCD_EP_Open(hpcd, 0x84, 512, EP_TYPE_BULK);
//		HAL_PCD_EP_Transmit(hpcd, 0x81, 0, 0);
//		HAL_PCD_EP_Transmit(hpcd, 0x83, 0, 0);

		HAL_PCD_EP_Receive(hpcd, 2, 0, 0);
		HAL_PCD_EP_Transmit(hpcd, 0, 0, 0);
		is_usb_configured = 1;
	} else if (request_type == STANDARD && request == GET_DESCRIPTOR && data2 == DESCRIPTOR_STRING) {
		printf("Sending string %i with index %i of size %i\n", data1, index, requested_length);
		switch(data1) {
		case 0:
			lang_string_descriptor[0] = sizeof(lang_string_descriptor);
			if (requested_length > sizeof(lang_string_descriptor)) requested_length = sizeof(lang_string_descriptor);
			HAL_PCD_EP_Transmit(hpcd, 0x00, lang_string_descriptor, requested_length);
//			printf("Sending string descriptor of size %i\n", sizeof(lang_string_descriptor));
			break;
		case 1:
			const char* manufacturer_name = "Виробник!!";
			string_descriptor[0] = 2 + USB_Encode_String(string_descriptor + 2, manufacturer_name);
			HAL_PCD_EP_Transmit(hpcd, 0x00, string_descriptor, string_descriptor[0]);
//			printf("Sending string descriptor of size %i\n", string_descriptor[0]);
			break;
		case 2:
			//			const char* product_name = "Пристрій!!";
			const char* product_name = "Hello!";
			string_descriptor[0] = 2 + USB_Encode_String(string_descriptor + 2, product_name);
			HAL_PCD_EP_Transmit(hpcd, 0x00, string_descriptor, string_descriptor[0]);
//			printf("Sending string descriptor of size %i\n", string_descriptor[0]);
			break;
		case 3:
			const char* serial_name = "Серійний номер!";
			string_descriptor[0] = 2 + USB_Encode_String(string_descriptor + 2, serial_name);
			HAL_PCD_EP_Transmit(hpcd, 0x00, string_descriptor, string_descriptor[0]);
//			printf("Sending string descriptor of size %i\n", string_descriptor[0]);
			break;
		case 4:
			const char* interface_name = "Інтерфейс!";
			string_descriptor[0] = 2 + USB_Encode_String(string_descriptor + 2, interface_name);
			HAL_PCD_EP_Transmit(hpcd, 0x00, string_descriptor, string_descriptor[0]);
//			printf("Sending string descriptor of size %i\n", string_descriptor[0]);
			break;
		case 5:
			const char* segger_interface_name = "SEGGER Інтерфейс!";
			string_descriptor[0] = 2 + USB_Encode_String(string_descriptor + 2, segger_interface_name);
			HAL_PCD_EP_Transmit(hpcd, 0x00, string_descriptor, string_descriptor[0]);
//			printf("Sending string descriptor of size %i\n", string_descriptor[0]);
			break;
		}

	} else {
		printf("Unknown request!\n");
	}


	// Custom requests start here
	if (request_type == MY_CUSTOM_OUT_REQUEST_TYPE && request == MY_CUSTOM_REQUEST) {
		HAL_GPIO_TogglePin(LED_GPIO_Port, LED_Pin);
		HAL_PCD_EP_Transmit(hpcd, 0, 0, 0);
	}
	if (request_type == MY_CUSTOM_OUT_REQUEST_TYPE && request == MOTORS_SPEED_REQUEST) {

		HAL_GPIO_WritePin(LED_GPIO_Port, LED_Pin, RESET);
		uint16_t value = ((uint16_t*)hpcd->Setup)[1];
		stand_cmd[0] = value / 100 * 2;
		stand_cmd[1] = value % 100 * 2;
		stand_cmd[2] = 1;
		stand_cmd[3] = 0;
		HAL_SPI_Transmit(&hspi3, stand_cmd, 4, 10);
		for (int i = 0; i < 5000; i++);
		HAL_SPI_Receive(&hspi3, stand_cmd+2, 2, 10);
		if (stand_cmd[0] == stand_cmd[2] && stand_cmd[1] == stand_cmd[3]) {
			HAL_GPIO_WritePin(LED_GPIO_Port, LED_Pin, SET);
			HAL_PCD_EP_Transmit(hpcd, 0, 0, 0);
		}
	}




	if (request_type == MY_CUSTOM_IN_REQUEST_TYPE && request == START_SOUND_TRANSMIT) {
//		SEGGER_SYSVIEW_RecordU32(SYSVIEW_EVTID_ISR_ENTER, 73);
//		is_sound_requested = 1;
//		is_transmitting_half = 4;  // Do not initiate transmit until interrupt request arrives
		BaseType_t xHigherPriorityTaskWoken = pdFALSE;
		xTaskNotifyFromISR(task_retr_main, 1 << READY, eSetBits, &xHigherPriorityTaskWoken);

		portYIELD_FROM_ISR(xHigherPriorityTaskWoken);

//		SEGGER_SYSVIEW_OnTaskStartReady(81);
		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0, 0, 0);

//		SEGGER_SYSVIEW_RecordExitISR();
	}
	if (request_type == MY_CUSTOM_IN_REQUEST_TYPE && request == END_SOUND_TRANSMIT) {
//		SEGGER_SYSVIEW_RecordU32(SYSVIEW_EVTID_ISR_ENTER, 73);
//		is_sound_requested = 0;
//		is_transmitting_half = 4;

		BaseType_t xHigherPriorityTaskWoken = pdFALSE;
		xTaskNotifyFromISR(task_retr_main, 1 << SLEEPING, eSetBits, &xHigherPriorityTaskWoken);
		portYIELD_FROM_ISR(xHigherPriorityTaskWoken);

//		SEGGER_SYSVIEW_OnTaskStartReady(81);
		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0, 0, 0);

//		SEGGER_SYSVIEW_RecordExitISR();
	}

	if (request_type == MY_CUSTOM_IN_REQUEST_TYPE && request == START_SEGGER_TRANSFER) {
//		BaseType_t xHigherPriorityTaskWoken = pdFALSE;
//		xTaskNotifyFromISR(task_send_segger, 1 << SEGGER_STARTED, eSetBits, &xHigherPriorityTaskWoken);
//		portYIELD_FROM_ISR(xHigherPriorityTaskWoken);

		SEGGER_SYSVIEW_Start();
		is_segger_tx = 0;

		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0, 0, 0);
	}
	if (request_type == MY_CUSTOM_IN_REQUEST_TYPE && request == END_SEGGER_TRANSFER) {
//		BaseType_t xHigherPriorityTaskWoken = pdFALSE;
//		xTaskNotifyFromISR(task_send_segger, 1 << SEGGER_ENDED, eSetBits, &xHigherPriorityTaskWoken);
//		portYIELD_FROM_ISR(xHigherPriorityTaskWoken);
		SEGGER_SYSVIEW_Stop();

		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0, 0, 0);
	}

	if (request_type == MY_CUSTOM_IN_REQUEST_TYPE && request == REQUEST_SEGGER_TRACE) {
//		BaseType_t xHigherPriorityTaskWoken = pdFALSE;
//		xTaskNotifyFromISR(task_send_segger, 1 << SEGGER_REQUESTED, eSetBits, &xHigherPriorityTaskWoken);
//		portYIELD_FROM_ISR(xHigherPriorityTaskWoken);


		trace_bytes_read = transmit_segger_data();
		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0, (uint8_t*)&trace_bytes_read, 2); // Respond to the control request


	}
	if (request_type == MY_CUSTOM_IN_REQUEST_TYPE && request == REQUEST_PERIODIC_SIGNAL) {
//		BaseType_t xHigherPriorityTaskWoken = pdFALSE;
//		xTaskNotifyFromISR(task_retr_periodic, 1 << PERIODIC_REQUESTED, eSetBits, &xHigherPriorityTaskWoken);
//		portYIELD_FROM_ISR(xHigherPriorityTaskWoken);


		uint8_t is_first_half_ready = pbuff_idx >= 1024*2 ? 0 : 1;
		if (is_first_half_ready) {
			per_bytes_read = pbuff_idx*2;
			HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x84, (uint8_t*)(&(periodic_signal[0])), per_bytes_read);
			pbuff_idx = 1024*4;
		} else {
			per_bytes_read = (pbuff_idx - 1024*2) * 2;
			HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0x84, (uint8_t*)(&(periodic_signal[1024*2])), per_bytes_read);
			pbuff_idx = 0;
		}
		dummy_periodic2 = per_bytes_read;
//
//
//
		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0, (uint8_t*)&per_bytes_read, 2);

//		HAL_PCD_EP_Transmit(&hpcd_USB_OTG_HS, 0, 0, 0);
	}
}

void HAL_PCD_DataOutStageCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum) {
	printf("Data OUT stage, ep %i\n", epnum);
	if (epnum == 0) {
		printf("Data OUT stage, ep %i\n", epnum);
//		HAL_PCD_EP_Transmit(hpcd, 0, 0, 0);
	}
	if (epnum == 2) {
		HAL_PCD_EP_Receive(hpcd, 2, 0, 0);
		BaseType_t xHigherPriorityTaskWoken = pdFALSE;
		xTaskNotifyFromISR(task_retr_main, 1 << REQUESTED, eSetBits, &xHigherPriorityTaskWoken);
		portYIELD_FROM_ISR(xHigherPriorityTaskWoken);
//		// Activate sound transmission
//		// If previous transmission has finished.
//		if (is_transmitting_half == 4) {
//			HAL_GPIO_WritePin(LED2_GPIO_Port, LED2_Pin, RESET);
//
//
//			  __HAL_TIM_DISABLE(&htim1);
//			  __HAL_TIM_SET_COUNTER(&htim1, 0);
//			  __HAL_TIM_CLEAR_FLAG(&htim1, TIM_FLAG_CC1 | TIM_FLAG_UPDATE);
//			  __HAL_TIM_ENABLE(&htim1);
//
//
//			HAL_TIM_IC_Start_DMA(&htim1, TIM_CHANNEL_1, (uint32_t*)sound, SOUND_ITEMS*2);
//			ncaptures = 0;
//	//	    HAL_TIM_Base_Start_IT(&htim2);
//			HAL_SPI_TransmitReceive_IT(&hspi1, 0, 0, SOUND_ITEMS*2);
//			hspi1.Instance->DR = 25;
//			is_transmitting_half = 0;
//			SEGGER_SYSVIEW_OnTaskStartReady(81);
//		}
	}
}

uint32_t n_trans = 0;
extern int is_periodic_transmitting;
void HAL_PCD_DataInStageCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum) {
//	printf("Data IN stage, ep %i\n", epnum);
	if (epnum == 0) 	HAL_PCD_EP_Receive(hpcd, 0x00, 0, 0);
	if (epnum == 1) 	{
//		if (is_transmitting_half == 1) is_half1_available = 0;
//		if (is_transmitting_half == 2) is_half2_available = 0;
//		if (is_transmitting_half == 1 && is_reads_started) SEGGER_SYSVIEW_SampleData(&sample_grab_1);
//		if (is_transmitting_half == 2 && is_reads_started) SEGGER_SYSVIEW_SampleData(&sample_grab_2);

//		is_transmitting_half = 4;  // Do not initiate transmit until interrupt request arrives
//		SEGGER_SYSVIEW_OnTaskStopExec();
		BaseType_t xHigherPriorityTaskWoken = pdFALSE;
		xTaskNotifyFromISR(task_retr_main, 1 << SENT, eSetBits, &xHigherPriorityTaskWoken);
		portYIELD_FROM_ISR(xHigherPriorityTaskWoken);
	}
	if (epnum == 3)		{
		is_reads_started = 1;
		n_trans++;
		is_segger_tx = 0;

//		BaseType_t xHigherPriorityTaskWoken = pdFALSE;
//		xTaskNotifyFromISR(task_send_segger, 1 << SEGGER_SENT, eSetBits, &xHigherPriorityTaskWoken);
//		portYIELD_FROM_ISR(xHigherPriorityTaskWoken);
	}
	if (epnum == 4)		{
		is_periodic_transmitting = 0;
//		BaseType_t xHigherPriorityTaskWoken = pdFALSE;
//		xTaskNotifyFromISR(task_retr_periodic, 1 << PERIODIC_SENT, eSetBits, &xHigherPriorityTaskWoken);
//		portYIELD_FROM_ISR(xHigherPriorityTaskWoken);
	}
}


void USB_Start_M3() {
//  HAL_PCDEx_PMAConfig(&hpcd_USB_FS , 0x00 , PCD_SNG_BUF, 0x18);
//  HAL_PCDEx_PMAConfig(&hpcd_USB_FS , 0x80 , PCD_SNG_BUF, 0x58);
//
//  // IN Bulk endpoint (1)
//  uint32_t bulk_buff_1 = 0x58 + 64;
//  uint32_t bulk_buff_2 = bulk_buff_1 + 64;
//  HAL_PCDEx_PMAConfig(&hpcd_USB_FS , 0x81 , PCD_DBL_BUF, (bulk_buff_2 << 16) + bulk_buff_1);
//  uint32_t int_buff = bulk_buff_2 + 64;
//  HAL_PCDEx_PMAConfig(&hpcd_USB_FS , 0x82 , PCD_SNG_BUF, int_buff);
//
//  HAL_PCD_Start(&hpcd_USB_FS);
}

void USB_Start_M4(PCD_HandleTypeDef* hpcd) {
  // Set FIFO number to activate,
  // along with its size in 4-byte WORDS, e.g.
  // 0x20 = 32 words = 128 bytes

  // FIFOs MUST be allocated in order:
  // Rx -> Tx0 -> Tx1 -> Tx2 etc.
  // Allocating Tx0 FIFO before Rx FIFO will result in wrong configuration
  HAL_PCDEx_SetRxFiFo(hpcd, 0x40);

  HAL_PCDEx_SetTxFiFo(hpcd, 0, 0x40);
  HAL_PCDEx_SetTxFiFo(hpcd, 1, 128);
  HAL_PCDEx_SetTxFiFo(hpcd, 3, 128);
  HAL_PCDEx_SetTxFiFo(hpcd, 2, 64);
  HAL_PCDEx_SetTxFiFo(hpcd, 4, 128);
//  HAL_PCDEx_SetTxFiFo(hpcd, 3, 0x100);
  HAL_PCD_Start(hpcd);
}
