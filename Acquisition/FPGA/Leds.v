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
    output reg o_LED1P,
    output reg o_LED2P,
    output reg o_LED1N,
    output reg o_LED2N,
    output reg o_LED3N,
    output reg o_LED4N
    );
	 
	 reg [15:0] counter_intensity;
	 
	 always @(posedge i_CLK) begin
		counter_intensity <= counter_intensity + 1;
		if (counter_intensity < 16'hE000) begin
			 o_LED1P <= 1;
			 o_LED2P <= 0;
			if (counter_intensity < i_VAR1) begin
			  o_LED1N <= 1'b0;
			  //o_DBG <= 1'b1;
			end else begin
			  o_LED1N <= 1'b1;
			  //o_DBG <= 1'b0;
			end
			if (counter_intensity < i_VAR2) begin
			  o_LED2N <= 1'b0;
			  //o_DBG <= 1'b1;
			end else begin
			  o_LED2N <= 1'b1;
			  //o_DBG <= 1'b0;
			end
			if (counter_intensity < i_VAR3) begin
			  o_LED3N <= 1'b0;
			  //o_DBG <= 1'b1;
			end else begin
			  o_LED3N <= 1'b1;
			  //o_DBG <= 1'b0;
			end
			if (counter_intensity < i_VAR4) begin
			  o_LED4N <= 1'b0;
			  //o_DBG <= 1'b1;
			end else begin
			  o_LED4N <= 1'b1;
			  //o_DBG <= 1'b0;
			end
		end
		else begin
		
		// Configuration leds
			 o_LED1P <= 0;
			 o_LED2P <= 1;
			 if (i_SW1) begin
				o_LED1N <= 0;
			 end else begin
				o_LED1N <= 1;
			 end 
			 if (i_SW2) begin
				o_LED2N <= 0;
			 end else begin
				o_LED2N <= 1;
			 end 
			 if (i_SW3) begin
				o_LED3N <= 0;
			 end else begin
				o_LED3N <= 1;
			 end 
			 if (i_SW4) begin
				o_LED4N <= 0;
			 end else begin
				o_LED4N <= 1;
			 end
		
		end
	end

endmodule
