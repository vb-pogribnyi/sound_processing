`timescale 1ns / 1ps
`include "src/ADS8865Reader.v"
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date:    23:24:33 12/02/2025 
// Design Name: 
// Module Name:    ADS8865Master 
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
module ADS8865Master
	(
    input i_CLK,
    output reg o_CONVST,
    output wire o_SCLK,
    output reg o_RDY,
    input i_MISO1,
    input i_MISO2,
    input i_MISO3,
    input i_MISO4,
    input i_IS_ADS,
    output wire [15:0] o_OUT1,
    output wire [15:0] o_OUT2,
    output wire [15:0] o_OUT3,
    output wire [15:0] o_OUT4,
	 
	 
	 // Debug wires
	 output wire [7:0] o_C,
    output wire [16:0] o_CNT,
	 output wire [1:0] o_STATE
    );
	 localparam	IDLE		= 2'h0,
					PRE_CONV	= 2'h1,
					CONV		= 2'h2,
					READ		= 2'h3;
	 reg [1:0] state = IDLE;
	 reg en = 1'b0;
	 reg [1:0] next_state = IDLE;
	 wire rdy1;
	 wire rdy2;
	 wire rdy3;
	 wire rdy4;
	 reg [7:0] c = 8'h0;
	 
	 assign o_C = c;
	 assign o_STATE = state;
	 assign o_CNT = conv_cnt;
	 
	ADS8865Reader reader1 (
		.o_SCLK(o_SCLK), 
		.o_OUT(o_OUT1), 
		.i_EN(en),  
		.o_RDY(rdy1), 
		.i_MISO(i_MISO1), 
		.i_CLK(i_CLK),
		.i_IS_ADS(i_IS_ADS)
	);
	ADS8865Reader reader2 (
		.o_SCLK(o_SCLK), 
		.o_OUT(o_OUT2), 
		.i_EN(en), 
		.o_RDY(rdy2), 
		.i_MISO(i_MISO2), 
		.i_CLK(i_CLK),
		.i_IS_ADS(i_IS_ADS)
	);
	ADS8865Reader reader3 (
		.o_SCLK(o_SCLK), 
		.o_OUT(o_OUT3), 
		.i_EN(en), 
		.o_RDY(rdy3), 
		.i_MISO(i_MISO3), 
		.i_CLK(i_CLK),
		.i_IS_ADS(i_IS_ADS)
	);
	ADS8865Reader reader4 (
		.o_SCLK(o_SCLK), 
		.o_OUT(o_OUT4), 
		.i_EN(en), 
		.o_RDY(rdy4), 
		.i_MISO(i_MISO4), 
		.i_CLK(i_CLK),
		.i_IS_ADS(i_IS_ADS)
	);
	
	reg [3:0] conv_cnt = 0; // This module is driven by slow clock 50/4 MHz = 12.5MHz. 5 bit overflows about 200k times per  second
	 always @(posedge i_CLK) begin
		state <= next_state;
		conv_cnt <= conv_cnt - 1;
	 end
	 
	 assign o_SCLK = state == CONV ? i_CLK : 1'b0;
	 always @(posedge i_CLK) begin
		case(state)
			IDLE: begin
				o_RDY <= 1'b1;
				c <= 8'h0;
				if (conv_cnt == 0) begin
					o_CONVST <= 1'b1;
					en <= 1;
					next_state <= PRE_CONV;
				end
			end
			PRE_CONV: begin
				// Wait for minimal time required for convst to register
				if ((i_IS_ADS && conv_cnt < 15) || (~i_IS_ADS && conv_cnt < 10)) begin
					o_CONVST <= 1'b0;
					
					// For the MCP, start transfer right away
					if (i_IS_ADS) begin
						if (~i_MISO1 || ~i_MISO2 || ~i_MISO3 || ~i_MISO4) begin
							o_RDY <= 1'b0;
						end
						if (~i_MISO1 && ~i_MISO2 && ~i_MISO3 && ~i_MISO4) begin
							next_state <= CONV;
						end
					end
					else begin
						o_RDY <= 1'b0;
						next_state <= CONV;
					end
				end
			end
			CONV: begin
				c <= c+1;
				if ((i_IS_ADS && c >= 15) || (~i_IS_ADS && c >= 14)) begin
				  en <= 0;
				  next_state <= IDLE;
				end
			end
		endcase
	 end
	 

endmodule
