`timescale 1ns / 1ps

`include "src/ADS8865Master.v"
`include "src/ADS8865Reader.v"
////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer:
//
// Create Date:   23:25:06 12/02/2025
// Design Name:   ADS8865Master
// Module Name:   C:/Users/ise_user/Documents/ISE_Projects/test2/ADS8865MasterTester.v
// Project Name:  test2
// Target Device:  
// Tool versions:  
// Description: 
//
// Verilog Test Fixture created by ISE for module: ADS8865Master
//
// Dependencies:
// 
// Revision:
// Revision 0.01 - File Created
// Additional Comments:
// 
////////////////////////////////////////////////////////////////////////////////

module ADS8865MasterTester;

	// Inputs
	reg i_CLK;
	reg i_MISO1;
	reg i_MISO2;

	// Outputs
	wire o_CONVST;
	wire o_SCLK;
	wire o_RDY;
	
	wire [15:0] o_OUT1;
	wire [15:0] o_OUT2;
	
	reg [15:0] value1 = 16'hACDC;
	reg [15:0] value2 = 16'hBBDF;
	
	
	 wire [7:0] o_C;
	 wire [16:0] o_CNT;
	 wire [1:0] o_STATE;
	 wire i_IS_ADS = 1;
	
	integer i;
	integer j;
	always #5 i_CLK = ~i_CLK;

	// Instantiate the Unit Under Test (UUT)
	ADS8865Master #( .IS_ADS(0) ) uut (
		.i_CLK(i_CLK), 
		.o_CONVST(o_CONVST), 
		.o_SCLK(o_SCLK),
		.o_RDY(o_RDY), 
		.i_MISO1(i_MISO1), 
		.i_MISO2(i_MISO2), 
		.i_MISO3(i_MISO1), 
		.i_MISO4(i_MISO2),
		.i_IS_ADS(i_IS_ADS), 
		.o_OUT1(o_OUT1), 
		.o_OUT2(o_OUT2),
		
		.o_C(o_C),
		.o_CNT(o_CNT),
		.o_STATE(o_STATE)
	);

	initial begin
		// Initialize Inputs
		i_CLK = 0;
		i_MISO1 = 0;
		i_MISO2 = 0;

		// Wait 100 ns for global reset to finish
		//#100;
        
		// Add stimulus here
		for (j = 15; j >= 0; j = j - 1)
		begin
			@(posedge o_CONVST);
			i_MISO1 <= 1;
			i_MISO2 <= 1;
			#20 i_MISO1 <= 0;
			#20 i_MISO2 <= 0;
			//@(negedge o_SCLK);
			//i_MISO <= 0;
			//@(negedge o_SCLK);
			//i_MISO <= 1;
			for (i = 15; i >= 0; i = i - 1)
			begin
				@(negedge o_SCLK);
				if (i <= 15) begin
					i_MISO1 <= value1[i];
					i_MISO2 <= value2[i];
				end
			end
		end

	end
      
endmodule

