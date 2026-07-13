/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  *                   This file contains the common defines of the application.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2025 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32f4xx_hal.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
//#include "tasks.h"
#include "FreeRTOS.h"
#include "semphr.h"
/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */


typedef enum SRetrieval {
	SLEEPING = 0,
    READY,
	REQUESTED,
	CAPTURED,
	SENT
} SRetrieval;

typedef enum SeggerStatus {
	SEGGER_SLEEPING = 0,
	SEGGER_STARTED,
	SEGGER_REQUESTED,
	SEGGER_FAIL,
	SEGGER_ENDED,
	SEGGER_SENT
} SeggerStatus;

typedef enum PeriodicStatus {
	PERIODIC_SLEEPING = 0,
	PERIODIC_STARTED,
	PERIODIC_REQUESTED,
	PERIODIC_FAIL,
	PERIODIC_ENDED,
	PERIODIC_SENT
} PeriodicStatus;
/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

/* Exported functions prototypes ---------------------------------------------*/
void Error_Handler(void);

/* USER CODE BEGIN EFP */

/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/
#define LED2_Pin GPIO_PIN_2
#define LED2_GPIO_Port GPIOE
#define USB_RST_Pin GPIO_PIN_1
#define USB_RST_GPIO_Port GPIOC
#define ADC_FDATA_2_Pin GPIO_PIN_4
#define ADC_FDATA_2_GPIO_Port GPIOC
#define ADC_FDATA_1_Pin GPIO_PIN_5
#define ADC_FDATA_1_GPIO_Port GPIOC
#define ADC_AUX_2_Pin GPIO_PIN_6
#define ADC_AUX_2_GPIO_Port GPIOC
#define ADC_AUX_1_Pin GPIO_PIN_7
#define ADC_AUX_1_GPIO_Port GPIOC
#define ADC_RDY_Pin GPIO_PIN_8
#define ADC_RDY_GPIO_Port GPIOC
#define ADC_CS_2_Pin GPIO_PIN_9
#define ADC_CS_2_GPIO_Port GPIOA
#define LED_R_Pin GPIO_PIN_9
#define LED_R_GPIO_Port GPIOB
#define LED_G_Pin GPIO_PIN_0
#define LED_G_GPIO_Port GPIOE
#define LED_Pin GPIO_PIN_1
#define LED_GPIO_Port GPIOE

/* USER CODE BEGIN Private defines */

//#define SOUND_ITEMS (4*512*16)
#define SOUND_ITEMS (4*1024*4)
/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
