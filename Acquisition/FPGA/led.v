`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date:    07:21:52 11/16/2025 
// Design Name: 
// Module Name:    led 
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
module led(
	 input wire i_BTN,
	 input wire i_RST,
    input wire i_CLK,
    output reg o_LED0,
    output reg o_LED1,
    output reg o_LED2,
    output reg o_LED3,
    output wire o_CONVST,
    output wire o_SCLK,
    input wire i_MISO1,
    input wire i_MISO2,
    input wire i_MISO3,
    input wire i_MISO4,
	 
	 // Parallel output
	 input wire i_OCLK,
	 output wire [7:0] o_OUTPUT,
	 output wire o_RDY,
	 
	 // Debugs
    output reg o_DBG,
    output wire o_MOSI,
    output wire o_GND
    );
	 parameter CLK_FREQ = 50000000;
	 localparam COUNT_MAX = CLK_FREQ / 100;
	 reg [31:0] counter;
	 wire [15:0] out1;
	 wire [15:0] out2;
	 wire [15:0] out3;
	 wire [15:0] out4;
	 wire rdy;
	 reg [31:0] counter_rst;
	 reg [2:0] counter_presses;
	 reg [15:0] counter_intensity;
	 reg is_on;
	 wire [31:0] mean;
	 wire [16:0] o_CNT;
	 
	 reg clk_slow;
	 reg [15:0] clk_cnt;
	 
	 
	 ADS8865Master adc_master (
		.i_CLK(clk_slow), 
		.o_CONVST(o_CONVST), 
		.o_SCLK(o_SCLK),
		.o_RDY(rdy), 
		.i_MISO1(i_MISO1), 
		.i_MISO2(i_MISO2), 
		.i_MISO3(i_MISO3), 
		.i_MISO4(i_MISO4), 
		.o_OUT1(out1), 
		.o_OUT2(out2),
		.o_OUT3(out3),
		.o_OUT4(out4),
		
		.o_CNT(o_CNT)
	);
	 wire [31:0] var1;
	 wire [31:0] mean1;
	 wire [31:0] var2;
	 wire [31:0] mean2;
	 wire [31:0] var3;
	 wire [31:0] mean3;
	 wire [31:0] var4;
	 wire [31:0] mean4;
	RunningMean running_mean1 (
		.i_SIGNAL(out1), 
		.o_VARIANCE(var1), 
		.i_RDY(rdy), 
		.o_MEAN(mean1)
	);
	RunningMean running_mean2 (
		.i_SIGNAL(out2), 
		.o_VARIANCE(var2), 
		.i_RDY(rdy), 
		.o_MEAN(mean2)
	);
	RunningMean running_mean3 (
		.i_SIGNAL(out3), 
		.o_VARIANCE(var3), 
		.i_RDY(rdy), 
		.o_MEAN(mean3)
	);
	RunningMean running_mean4 (
		.i_SIGNAL(out4), 
		.o_VARIANCE(var4), 
		.i_RDY(rdy), 
		.o_MEAN(mean4)
	);
	
	 reg [15:0] out_tst = 16'hACDC;
	Outputter out (
		.i_OUT1(out_tst), 
		.i_OUT2(out2), 
		.i_OUT3(out3), 
		.i_OUT4(out4), 
		.i_OCLK(i_OCLK), 
		.i_CLK(i_CLK), 
		.i_RDY(rdy), 
		.o_OUTPUT(o_OUTPUT), 
		.o_RDY(o_RDY)
	);
	
	assign o_MOSI = 1;
	assign o_GND = 0;
	 
	 
	 always @(posedge i_CLK) begin
	   // o_DBG <= i_RST;
	   o_DBG <= clk_slow;
		counter_intensity <= counter_intensity + 1;
		
		
		if (clk_cnt == 0) begin
			clk_slow <= ~clk_slow;
		end
		clk_cnt <= clk_cnt + 1;
		if (clk_cnt == 3) begin
			clk_cnt <= 0;
		end
		/*
		// PWM led indication
		if (counter_intensity < var1) begin
		  o_LED <= 1'b1;
		  o_DBG <= 1'b1;
		end else begin
		  o_LED <= 1'b0;
		  o_DBG <= 1'b0;
		end
		*/
		
		if (counter_intensity < var1) begin
		  o_LED0 <= 1'b1;
		  //o_DBG <= 1'b1;
		end else begin
		  o_LED0 <= 1'b0;
		  //o_DBG <= 1'b0;
		end
		if (counter_intensity < var2) begin
		  o_LED1 <= 1'b1;
		  //o_DBG <= 1'b1;
		end else begin
		  o_LED1 <= 1'b0;
		  //o_DBG <= 1'b0;
		end
		if (counter_intensity < var3) begin
		  o_LED2 <= 1'b1;
		  //o_DBG <= 1'b1;
		end else begin
		  o_LED2 <= 1'b0;
		  //o_DBG <= 1'b0;
		end
		if (counter_intensity < var4) begin
		  o_LED3 <= 1'b1;
		  //o_DBG <= 1'b1;
		end else begin
		  o_LED3 <= 1'b0;
		  //o_DBG <= 1'b0;
		end
		
		
		/*
		if (o_CNT < 5) begin
		  o_LED <= 1'b0;
		end else begin
		  o_LED <= 1'b1;
		end
		*/
		
		
		
		
		
		
		
		
		
		
		
		
		
		
		// Detect clock button press
		// if is_on was not set and button remains pressed for 10 ms
		// then set is_on.
	   if (!is_on) begin
			if (!i_BTN) begin
				counter <= counter + 1;
				if (counter >= COUNT_MAX) begin
					is_on <= 1'b1;
					counter <= 0;
					counter_presses <= counter_presses + 1;
				end
			end else begin
				counter <= 0;
			end
		// if is_on was set then wait until the button is not pressed
		// for at least 10 ms
		end else begin
			if (i_BTN) begin
				counter <= counter + 1;
				if (counter >= COUNT_MAX) begin
					is_on <= 1'b0;
					counter <= 0;
				end
			end else begin
				counter <= 0;
			end
		end
		
		
		// Detect reset button press in the same way
		if (!i_RST) begin // it turns out to be active low...
			counter_rst <= counter_rst + 1;
			if (counter_rst >= COUNT_MAX) begin
				counter_rst <= 0;
				counter_presses <= 0;
			end
		end else begin
			counter_rst <= 0;
		end
		
	 end
	 
		assign mean = mean1 + 10000 < 30000 ? mean1 + 10000 : 0;
 endmodule
