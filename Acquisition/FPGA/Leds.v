`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date:    23:25:04 03/23/2026 
// Design Name: 
// Module Name:    Leds 
// Project Name: 
// Target Devices: 
// Tool versions: 
// Description: 
//
// Dependencies: 
//
// Revision: 
// Revision 0.01 - File Created
// Additional Comments: 
//
//////////////////////////////////////////////////////////////////////////////////
module Leds(
    input i_CLK,
    input i_SW1,
    input i_SW2,
    input i_SW3,
    input i_SW4,
    input [31:0] i_VAR1,
    input [31:0] i_VAR2,
    input [31:0] i_VAR3,
    input [31:0] i_VAR4,
    input [3:0] i_STATE,
    output reg o_LED1P,
    output reg o_LED2P,
    output reg o_LED1N,
    output reg o_LED2N,
    output reg o_LED3N,
    output reg o_LED4N
    );
     
     reg [15:0] counter_intensity;
     reg [15:0] adc_brightness;
     reg [15:0] adc_invalid_countdown;
     reg [15:0] adc_div_cnt;
     localparam counter_half = 16'h0000;
     //localparam counter_half = 16'hC000;
	  
	  // A valid ADC sample has to appear at least once per this period 
	  // to keep the ADC glowing.
     localparam [15:0] ADC_INVALID_COUNT = 16'd3200;    // 50 Mhz / 3200 = ~16khz
     localparam [15:0] ADC_BRIGHT_DIV = 16'd6103;
     localparam [15:0] ADC_BRIGHT_MAX = 16'hFFFF - counter_half;
     
     always @(posedge i_CLK) begin
        counter_intensity <= counter_intensity + 1;
		  if (i_STATE[1] == 1) begin
		      adc_invalid_countdown <= ADC_INVALID_COUNT;
		  end
		  else begin
		      if (adc_invalid_countdown > 0) begin
				    adc_invalid_countdown <= adc_invalid_countdown - 1;
				end
		  end
		  if (adc_invalid_countdown > 0) begin
		     if (adc_brightness < ADC_BRIGHT_MAX) begin
				  if (adc_div_cnt < ADC_BRIGHT_DIV) begin
						adc_div_cnt <= adc_div_cnt + 1;
				  end
				  else begin
						adc_div_cnt <= 0;
						adc_brightness <= adc_brightness + 1;
				  end
			  end
		  end 
		  else begin
		      adc_brightness <= 0;
				adc_div_cnt <= 0;
		  end
        if (counter_intensity < counter_half) begin
             o_LED1P <= 1;
             o_LED2P <= 0;
            if (counter_intensity < i_VAR1) begin
              //o_LED1N <= 1'b0;
            end else begin
              //o_LED1N <= 1'b1;
            end
            if (counter_intensity < i_VAR2) begin
              //o_LED2N <= 1'b0;
            end else begin
              //o_LED2N <= 1'b1;
            end
            if (counter_intensity < i_VAR3) begin
              //o_LED3N <= 1'b0;
            end else begin
              //o_LED3N <= 1'b1;
            end
            if (counter_intensity < i_VAR4) begin
              //o_LED4N <= 1'b0;
            end else begin
              //o_LED4N <= 1'b1;
            end
        end
        else begin
        
        // Configuration leds
            o_LED1P <= 0;
            o_LED2P <= 1;
            // if (i_SW1) begin
            //     o_LED1N <= 0;
            // end else begin
            //     o_LED1N <= 1;
            // end 
            // if (i_SW2) begin
            //     o_LED2N <= 0;
            // end else begin
            //     o_LED2N <= 1;
            // end 
            // if (i_SW3) begin
            //     o_LED3N <= 0;
            // end else begin
            //     o_LED3N <= 1;
            // end 
            // if (i_SW4) begin
            //     o_LED4N <= 0;
            // end else begin
            //     o_LED4N <= 1;
            // end


            if (i_STATE[0] == 1) begin  // PSRAM status
                o_LED1N <= 0;
            end else begin
                o_LED1N <= 1;
            end 

            if (counter_intensity < (counter_half + adc_brightness)) begin
            //if (i_STATE[1] == 1) begin  // ADC status
                o_LED2N <= 0;
            end else begin
                o_LED2N <= 1;
            end

            if (i_STATE[2] == 1) begin
                o_LED3N <= 0;
            end else begin
                o_LED3N <= 1;
            end 
            if (i_STATE[3] == 1) begin
                o_LED4N <= 0;
            end else begin
                o_LED4N <= 1;
            end
        
        end
    end

endmodule
