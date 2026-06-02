`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date:    23:07:05 12/17/2025 
// Design Name: 
// Module Name:    outputter 
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
module Outputter(
    input [15:0] i_OUT1,
    input [15:0] i_OUT2,
    input [15:0] i_OUT3,
    input [15:0] i_OUT4,
    input i_OCLK,
    input i_CLK,
    input i_RDY,
    input i_DBG,
    output reg [7:0] o_OUTPUT,
    output reg [7:0] o_OUTPUT2,
    output wire o_RDY
    );
	 reg [7:0] out_cycle = 0;
	 reg is_reading = 0;
	 reg is_available = 0;
	 reg was_rdy_reset = 1;
	 wire [15:0] OUT_1;
	 wire [15:0] OUT_2;
	 wire [15:0] OUT_3;
	 wire [15:0] OUT_4;
	 /*
	 if (i_DBG) begin
		OUT_LAST = 16'hACDC;
	 end 
	 else begin
		OUT_LAST = i_OUT4;
	 end
	 */
	 /*
	 assign OUT_1 = (i_DBG) ? 16'hACDC : i_OUT1;
	 assign OUT_2 = (i_DBG) ? 16'hACDC : i_OUT2;
	 assign OUT_3 = (i_DBG) ? 16'hACDC : i_OUT3;
	 assign OUT_4 = (i_DBG) ? 16'hACDC : i_OUT4;
	 */
	 assign OUT_1 = (i_DBG) ? 16'hFeFF : i_OUT1;
	 assign OUT_2 = (i_DBG) ? 16'hFeFF : i_OUT2;
	 assign OUT_3 = (i_DBG) ? 16'hFeFF : i_OUT3;
	 assign OUT_4 = (i_DBG) ? 16'hFeFF : i_OUT4;
	 //assign OUT_LAST = i_OUT4;
	 
	 
	 assign o_RDY = out_cycle < 3 || is_available;
	 always @(negedge i_CLK) begin
	   if (is_reading) begin
		  is_available <= 0;
	   end
		if (i_RDY && was_rdy_reset) begin
		  is_available <= 1;
		  was_rdy_reset <= 0;
		end
		if (~i_RDY) begin
		  was_rdy_reset <= 1;
		end
	 end
	 
	 always @(posedge i_OCLK) begin
		out_cycle <= out_cycle + 1;
		if (is_available) begin
			out_cycle <= 1;
			is_reading <= 1;
			o_OUTPUT <= OUT_1[7:0];
			o_OUTPUT2 <= OUT_1[15:8];
		end
		else begin
			is_reading <= 0;
			case (out_cycle)
				0: begin
					//o_OUTPUT <= OUT_1[7:0];
				end
				1: begin
					//o_OUTPUT <= OUT_1[15:8];
				end
				2: begin
					//o_OUTPUT <= OUT_2[7:0];
				end
				3: begin
					//o_OUTPUT <= OUT_2[15:8];
				end
				4: begin
					//o_OUTPUT <= OUT_3[7:0];
				end
				5: begin
					//o_OUTPUT <= OUT_3[15:8];
				end
				6: begin
					//o_OUTPUT <= OUT_4[7:0];
				end
				7: begin
					o_OUTPUT <= OUT_4[15:8];
					o_OUTPUT2 <= OUT_4[7:0];
				end
			endcase
		end
	 end

endmodule
