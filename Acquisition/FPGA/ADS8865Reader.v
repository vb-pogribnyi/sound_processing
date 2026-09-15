`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date:    22:23:27 11/26/2025 
// Design Name: 
// Module Name:    ADS8865Reader 
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
module ADS8865Reader(
    input o_SCLK,
    input i_EN,
    output [15:0] o_OUT,
	 output o_RDY,
    input i_MISO,
    input i_CLK,
	 input i_IS_ADS,
	 
	 
	 // Debug fields
	 output o_STATE,
	 output o_RST,
	 output o_RESET,
	 output [7:0] o_C
    );
	 localparam	IDLE		= 1'h0,
					CONV		= 1'h1;
	 reg state;
	 reg next_state;
	 reg rdy;
	 reg is_done;
	 reg is_rst;
	 reg [15:0] out;
	 reg [7:0] c;
	 initial begin
		 state <= IDLE;
		 next_state <= IDLE;
		 
		 rdy = 1'b1;
		 out = 16'h0;
		 c = 8'h1;
		 is_rst = 0;
		 is_done = 0;
		 rr_d1 = 0;
		 rr_d2 = 0;
	 end
	 assign o_OUT = i_IS_ADS ? out : out + 16'h8000;  // For single-ended ADC, simulate signed output.
	 assign o_RDY = rdy;
	 assign o_STATE = state;
	 assign o_RST = is_rst;
	 assign o_RESET = is_reset;
	 assign o_C = c;
	 
	 
	 always @(negedge i_CLK) begin
		case(state)
			IDLE: begin
				if (i_EN) begin
					if (~i_MISO || ~i_IS_ADS) begin
						is_rst <= 1'b1;
					end
					if (is_rst && ~rdy) begin
						state <= CONV;
					end
				end
			end
			CONV: begin
				if (rr_d2) begin
					is_rst <= 1'b0;
				end
				if (rdy) begin
					state <= IDLE;
				end
			end
		endcase
	   rr_d1 <= is_rst;
	 end
	 
	 reg rr_d1, rr_d2;
	 always @(posedge o_SCLK) begin
		rr_d2 <= rr_d1;
		if (is_reset) begin
			rdy <= 1'b0;
			out <= 16'h0;
			if (i_IS_ADS) begin
				c <= 8'h0;
			end
			else begin
				out[15] <= i_MISO;
				c <= 8'h1;
			end
		end
		case(state)
			IDLE: begin
				is_done <= 0;
			end
			CONV: begin
				if (c >= 0) begin
					out[15 - c] <= i_MISO;
					if (c >= 15) begin
						rdy <= 1'b1;
						is_done <= 1;
					end
				end
				c <= c + 1;
			end
		endcase
	 end
	 wire is_reset = rr_d1 & ~rr_d2;


endmodule
